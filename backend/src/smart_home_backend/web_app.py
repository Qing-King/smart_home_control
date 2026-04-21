from __future__ import annotations

from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import MQTTSettings, WebSettings
from .controller import MqttDeviceController, StatusPacket
from .cycle_control import CycleAlreadyRunningError, CycleRequest, LightCycleManager

ALLOWED_COMMANDS = {"on", "off", "toggle", "status"}
PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = PROJECT_ROOT.parent / "frontend"
CYCLE_MANAGER = LightCycleManager()


def serialize_status(packet: StatusPacket | None) -> dict[str, Any] | None:
    if packet is None:
        return None

    return {
        "topic": packet.topic,
        "payload": packet.payload,
        "parsed": packet.parsed,
        "retain": packet.retain,
    }


def parse_positive_number(payload: dict[str, Any], key: str, label: str) -> float:
    raw_value = payload.get(key)
    if raw_value in {None, ""}:
        raise ValueError(f"缺少 {label}。")

    try:
        value = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} 必须是数字。") from exc

    if value <= 0:
        raise ValueError(f"{label} 必须大于 0。")

    return value


def create_app() -> Flask:
    app = Flask(__name__, static_folder=None)
    web_settings = WebSettings.from_env()

    if web_settings.proxy_fix:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

    @app.get("/api/health")
    def health() -> tuple[dict[str, Any], int]:
        settings = MQTTSettings.from_env()
        return (
            {
                "ok": True,
                "service": "smart-home-control",
                "mqtt_topic_root": settings.topic_root,
                "web_root": "/",
                "proxy_fix": web_settings.proxy_fix,
                "cycle_active": CYCLE_MANAGER.get_status().get("active", False),
            },
            200,
        )

    @app.get("/api/device/status")
    def get_device_status() -> tuple[dict[str, Any], int]:
        try:
            settings = MQTTSettings.from_env()
            controller = MqttDeviceController(settings)
            status = controller.send_command("status", wait_for_status=True)
            return jsonify({"ok": True, "command": "status", "status": serialize_status(status)}), 200
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500

    @app.post("/api/device/command")
    def send_device_command() -> tuple[dict[str, Any], int]:
        payload = request.get_json(silent=True) or {}
        command = str(payload.get("command", "")).strip().lower()
        wait_for_status = bool(payload.get("wait_for_status", True))

        if command not in ALLOWED_COMMANDS:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "不支持的命令。",
                        "allowed_commands": sorted(ALLOWED_COMMANDS),
                    }
                ),
                400,
            )

        try:
            cycle_stop_requested = False
            if command in {"on", "off", "toggle"}:
                cycle_stop_requested = CYCLE_MANAGER.request_stop(skip_final_off=True)

            settings = MQTTSettings.from_env()
            controller = MqttDeviceController(settings)
            status = controller.send_command(command, wait_for_status=wait_for_status)
            return (
                jsonify(
                    {
                        "ok": True,
                        "command": command,
                        "status": serialize_status(status),
                        "cycle_stop_requested": cycle_stop_requested,
                        "cycle": CYCLE_MANAGER.get_status(),
                    }
                ),
                200,
            )
        except Exception as exc:
            return jsonify({"ok": False, "command": command, "error": str(exc)}), 500

    @app.get("/api/cycle")
    def get_cycle_status() -> tuple[dict[str, Any], int]:
        return jsonify({"ok": True, "cycle": CYCLE_MANAGER.get_status()}), 200

    @app.post("/api/cycle/start")
    def start_cycle() -> tuple[dict[str, Any], int]:
        payload = request.get_json(silent=True) or {}

        try:
            cycle_request = CycleRequest(
                total_hours=parse_positive_number(payload, "total_hours", "控制总时长"),
                on_minutes=parse_positive_number(payload, "on_minutes", "亮灯时长"),
                off_minutes=parse_positive_number(payload, "off_minutes", "灭灯时长"),
            )
            cycle = CYCLE_MANAGER.start(cycle_request, MQTTSettings.from_env())
            return jsonify({"ok": True, "cycle": cycle}), 200
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except CycleAlreadyRunningError as exc:
            return jsonify({"ok": False, "error": str(exc), "cycle": CYCLE_MANAGER.get_status()}), 409
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500

    @app.post("/api/cycle/stop")
    def stop_cycle() -> tuple[dict[str, Any], int]:
        stop_requested = CYCLE_MANAGER.request_stop()
        return (
            jsonify(
                {
                    "ok": True,
                    "stop_requested": stop_requested,
                    "cycle": CYCLE_MANAGER.get_status(),
                }
            ),
            200,
        )

    @app.get("/")
    def index() -> Any:
        return send_from_directory(FRONTEND_ROOT, "index.html")

    @app.get("/assets/<path:filename>")
    def frontend_assets(filename: str) -> Any:
        return send_from_directory(FRONTEND_ROOT / "assets", filename)

    return app
