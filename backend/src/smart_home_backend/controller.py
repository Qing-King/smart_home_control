from __future__ import annotations

from dataclasses import dataclass
import json
import queue
import ssl
import threading
import time
from typing import Any

import paho.mqtt.client as mqtt

from .config import MQTTSettings

COMMAND_REASON_MAP = {
    "on": "cmd_on",
    "off": "cmd_off",
    "toggle": "cmd_toggle",
    "status": "cmd_status",
}


def reason_code_value(code: Any) -> int:
    value = getattr(code, "value", code)
    return int(value)


@dataclass(slots=True)
class StatusPacket:
    topic: str
    payload: str
    parsed: dict[str, Any] | None
    retain: bool


class MqttDeviceController:
    def __init__(self, settings: MQTTSettings) -> None:
        self.settings = settings
        self._message_queue: queue.Queue[StatusPacket] = queue.Queue()
        self._connected = threading.Event()
        self._subscribed = threading.Event()
        self._connect_error: str | None = None
        self._subscribe_error: str | None = None
        self._subscribe_mid: int | None = None

        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.settings.build_client_id(),
            protocol=mqtt.MQTTv311,
        )
        self._client.username_pw_set(self.settings.username, self.settings.password)

        if self.settings.use_tls:
            context = ssl.create_default_context()
            if self.settings.tls_insecure:
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
            self._client.tls_set_context(context)

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.on_subscribe = self._on_subscribe

    def connect(self, timeout: float | None = None) -> None:
        effective_timeout = timeout or self.settings.command_timeout
        self._connected.clear()
        self._connect_error = None

        try:
            self._client.connect(self.settings.host, self.settings.port, self.settings.keepalive)
        except OSError as exc:
            raise ConnectionError(f"无法连接 MQTT Broker: {exc}") from exc

        self._client.loop_start()

        if not self._connected.wait(effective_timeout):
            self.disconnect()
            raise TimeoutError("等待 MQTT 连接超时。")

        if self._connect_error is not None:
            self.disconnect()
            raise ConnectionError(self._connect_error)

    def disconnect(self) -> None:
        try:
            self._client.disconnect()
        finally:
            self._client.loop_stop()

    def send_command(
        self,
        command: str,
        *,
        wait_for_status: bool = True,
        timeout: float | None = None,
    ) -> StatusPacket | None:
        effective_timeout = timeout or self.settings.command_timeout

        self.connect(timeout=effective_timeout)
        try:
            if wait_for_status:
                self._subscribe_status(timeout=effective_timeout)

                # 订阅后先等一小段时间，让 broker 已保留的旧状态先到达并清空，
                # 避免把旧 retained 消息误认为这次命令的回包。
                time.sleep(0.5)
                self._drain_messages()

            message_info = self._client.publish(
                self.settings.command_topic,
                payload=command,
                qos=1,
                retain=False,
            )
            message_info.wait_for_publish(timeout=effective_timeout)

            if message_info.rc != mqtt.MQTT_ERR_SUCCESS:
                raise RuntimeError(f"MQTT 发布失败，错误码: {message_info.rc}")

            if not wait_for_status:
                return None

            return self._wait_for_status(command, timeout=effective_timeout)
        finally:
            self.disconnect()

    def publish_command_payload(
        self,
        payload: str,
        *,
        timeout: float | None = None,
    ) -> None:
        effective_timeout = timeout or self.settings.command_timeout

        self.connect(timeout=effective_timeout)
        try:
            message_info = self._client.publish(
                self.settings.command_topic,
                payload=payload,
                qos=1,
                retain=False,
            )
            message_info.wait_for_publish(timeout=effective_timeout)

            if message_info.rc != mqtt.MQTT_ERR_SUCCESS:
                raise RuntimeError(f"MQTT 发布失败，错误码: {message_info.rc}")
        finally:
            self.disconnect()

    def send_cycle_start(
        self,
        *,
        total_seconds: float,
        on_seconds: float,
        off_seconds: float,
        timeout: float | None = None,
    ) -> None:
        payload = "cycle:start:{total_ms}:{on_ms}:{off_ms}".format(
            total_ms=max(1, round(total_seconds * 1000)),
            on_ms=max(1, round(on_seconds * 1000)),
            off_ms=max(1, round(off_seconds * 1000)),
        )
        self.publish_command_payload(payload, timeout=timeout)

    def send_cycle_stop(self, *, timeout: float | None = None) -> None:
        self.publish_command_payload("cycle:stop", timeout=timeout)

    def send_cycle_cancel(self, *, timeout: float | None = None) -> None:
        self.publish_command_payload("cycle:cancel", timeout=timeout)

    def _subscribe_status(self, timeout: float) -> None:
        self._subscribed.clear()
        self._subscribe_error = None

        result, mid = self._client.subscribe(self.settings.status_topic, qos=1)
        if result != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"订阅状态主题失败，错误码: {result}")

        self._subscribe_mid = mid

        if not self._subscribed.wait(timeout):
            raise TimeoutError("等待 MQTT 订阅确认超时。")

        if self._subscribe_error is not None:
            raise RuntimeError(self._subscribe_error)

    def _wait_for_status(self, command: str, timeout: float) -> StatusPacket:
        expected_reason = COMMAND_REASON_MAP.get(command)
        deadline = time.monotonic() + timeout
        last_packet: StatusPacket | None = None

        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            try:
                packet = self._message_queue.get(timeout=max(0.1, remaining))
            except queue.Empty:
                continue

            last_packet = packet
            if packet.parsed is None:
                continue

            reason = str(packet.parsed.get("reason", ""))
            if expected_reason and reason == expected_reason:
                return packet

            led = str(packet.parsed.get("led", "")).lower()
            if command in {"on", "off"} and led == command:
                return packet

        details = last_packet.payload if last_packet is not None else "没有收到任何状态消息"
        raise TimeoutError(f"等待设备状态回包超时。最后一条消息: {details}")

    def _drain_messages(self) -> None:
        while True:
            try:
                self._message_queue.get_nowait()
            except queue.Empty:
                return

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        del client, userdata, flags, properties

        if not getattr(reason_code, "is_failure", False):
            self._connected.set()
            return

        self._connect_error = f"MQTT 连接被 broker 拒绝: {reason_code}"
        self._connected.set()

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        disconnect_flags: mqtt.DisconnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        del client, userdata, disconnect_flags, reason_code, properties

    def _on_subscribe(
        self,
        client: mqtt.Client,
        userdata: Any,
        mid: int,
        reason_codes: list[mqtt.ReasonCode],
        properties: mqtt.Properties | None,
    ) -> None:
        del client, userdata, properties

        if mid != self._subscribe_mid:
            return

        if any(reason_code_value(code) >= 128 for code in reason_codes):
            joined = ", ".join(str(code) for code in reason_codes)
            self._subscribe_error = f"订阅被 broker 拒绝: {joined}"

        self._subscribed.set()

    def _on_message(
        self,
        client: mqtt.Client,
        userdata: Any,
        message: mqtt.MQTTMessage,
    ) -> None:
        del client, userdata

        payload = message.payload.decode("utf-8", errors="replace")
        parsed: dict[str, Any] | None

        try:
            loaded = json.loads(payload)
            parsed = loaded if isinstance(loaded, dict) else None
        except json.JSONDecodeError:
            parsed = None

        self._message_queue.put(
            StatusPacket(
                topic=message.topic,
                payload=payload,
                parsed=parsed,
                retain=bool(message.retain),
            )
        )
