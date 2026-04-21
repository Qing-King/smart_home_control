from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from typing import Any

from .config import MQTTSettings
from .controller import MqttDeviceController

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = PROJECT_ROOT / ".runtime"
STATE_FILE = RUNTIME_DIR / "light_cycle_state.json"
SIGNAL_FILE = RUNTIME_DIR / "light_cycle_signal.json"
LOCK_FILE = RUNTIME_DIR / "light_cycle.lock"
STATE_STALE_SECONDS = 15.0


class CycleAlreadyRunningError(RuntimeError):
    """Raised when the light cycle is already active."""


@dataclass(slots=True, frozen=True)
class CycleRequest:
    total_hours: float
    on_minutes: float
    off_minutes: float

    @property
    def total_seconds(self) -> float:
        return self.total_hours * 3600

    @property
    def on_seconds(self) -> float:
        return self.on_minutes * 60

    @property
    def off_seconds(self) -> float:
        return self.off_minutes * 60


def utc_now_epoch() -> float:
    return time.time()


def ensure_runtime_dir() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    ensure_runtime_dir()

    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(path.parent),
        delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
        temp_path = Path(handle.name)

    last_error: OSError | None = None
    for _ in range(20):
        try:
            temp_path.replace(path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.05)

    try:
        temp_path.unlink()
    except FileNotFoundError:
        pass

    if last_error is not None:
        raise last_error


def read_json_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


class FileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: Any | None = None

    def acquire_nonblocking(self) -> None:
        ensure_runtime_dir()
        self.handle = self.path.open("a+b")
        self.handle.seek(0)
        self.handle.write(b"0")
        self.handle.flush()
        self.handle.seek(0)

        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            self.handle = None
            raise CycleAlreadyRunningError("当前已有循环任务正在运行。") from exc

    def release(self) -> None:
        if self.handle is None:
            return

        try:
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None


class LightCycleManager:
    def __init__(self) -> None:
        self._thread_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def get_status(self) -> dict[str, Any]:
        state = self._load_state()
        now = utc_now_epoch()
        heartbeat = float(state.get("heartbeat_at") or 0)

        if state.get("active") and heartbeat and now - heartbeat > STATE_STALE_SECONDS:
            state["active"] = False
            state["status"] = "failed"
            state["current_phase"] = "off"
            state["next_switch_at"] = None
            state["ended_at"] = now
            state["last_error"] = "循环任务状态已过期，可能是服务重启或进程退出。"
            self._write_state(state)

        ends_at = state.get("ends_at")
        if state.get("active") and isinstance(ends_at, (int, float)):
            state["remaining_seconds"] = max(0.0, round(float(ends_at) - now, 1))
        else:
            state["remaining_seconds"] = 0.0

        return state

    def start(self, request: CycleRequest, settings: MQTTSettings) -> dict[str, Any]:
        self._validate_request(request)

        with self._thread_lock:
            if self._thread is not None and self._thread.is_alive():
                raise CycleAlreadyRunningError("当前已有循环任务正在运行。")

        lock = FileLock(LOCK_FILE)
        lock.acquire_nonblocking()

        try:
            self._send_cycle_start(settings, request)

            with self._thread_lock:
                self._stop_event = threading.Event()
                self._clear_signal_file()

                now = utc_now_epoch()
                state = self._build_state(
                    request=request,
                    active=True,
                    status="running",
                    current_phase="on",
                    started_at=now,
                    phase_started_at=now,
                    next_switch_at=min(now + request.on_seconds, now + request.total_seconds),
                    ends_at=now + request.total_seconds,
                    heartbeat_at=now,
                    ended_at=None,
                    stop_requested=False,
                    stop_skip_final_off=False,
                    last_command="cycle:start",
                    last_error=None,
                )
                self._write_state(state)

                thread = threading.Thread(
                    target=self._run_cycle,
                    args=(request, lock),
                    name="light-cycle-runner",
                    daemon=True,
                )
                self._thread = thread
                thread.start()
        except Exception:
            lock.release()
            raise

        return self.get_status()

    def request_stop(
        self,
        *,
        skip_final_off: bool = False,
        settings: MQTTSettings | None = None,
    ) -> bool:
        state = self.get_status()
        if not state.get("active"):
            return False

        if settings is not None:
            if skip_final_off:
                self._send_cycle_cancel(settings)
            else:
                self._send_cycle_stop(settings)

        payload = {
            "action": "stop",
            "skip_final_off": bool(skip_final_off),
            "requested_at": utc_now_epoch(),
        }
        atomic_write_json(SIGNAL_FILE, payload)
        self._stop_event.set()

        state["stop_requested"] = True
        state["stop_skip_final_off"] = bool(skip_final_off)
        state["heartbeat_at"] = utc_now_epoch()
        self._write_state(state)
        return True

    def _run_cycle(self, request: CycleRequest, lock: FileLock) -> None:
        current_phase = "on"
        status = "completed"
        last_error: str | None = None
        ended_at = utc_now_epoch()
        skip_final_off = False

        try:
            started_at = utc_now_epoch()
            ends_at = started_at + request.total_seconds
            phase_started_at = started_at
            next_switch_at = min(phase_started_at + request.on_seconds, ends_at)
            self._write_state(
                self._build_state(
                    request=request,
                    active=True,
                    status="running",
                    current_phase=current_phase,
                    started_at=started_at,
                    phase_started_at=phase_started_at,
                    next_switch_at=next_switch_at,
                    ends_at=ends_at,
                    heartbeat_at=started_at,
                    ended_at=None,
                    stop_requested=False,
                    stop_skip_final_off=False,
                    last_command="cycle:start",
                    last_error=None,
                )
            )

            while True:
                now = utc_now_epoch()
                if now >= ends_at:
                    break

                phase_duration = request.on_seconds if current_phase == "on" else request.off_seconds
                phase_deadline = min(phase_started_at + phase_duration, ends_at)
                stop_signal = self._wait_for_signal(phase_deadline)
                ended_at = utc_now_epoch()

                if stop_signal is not None:
                    status = "stopped"
                    skip_final_off = bool(stop_signal.get("skip_final_off", False))
                    break

                if ended_at >= ends_at:
                    break

                current_phase = "off" if current_phase == "on" else "on"
                phase_started_at = ended_at
                next_switch_at = min(
                    phase_started_at
                    + (request.on_seconds if current_phase == "on" else request.off_seconds),
                    ends_at,
                )
                self._write_state(
                    self._build_state(
                        request=request,
                        active=True,
                        status="running",
                        current_phase=current_phase,
                        started_at=started_at,
                        phase_started_at=phase_started_at,
                        next_switch_at=next_switch_at,
                        ends_at=ends_at,
                        heartbeat_at=phase_started_at,
                        ended_at=None,
                        stop_requested=False,
                        stop_skip_final_off=False,
                        last_command=f"cycle:{current_phase}",
                        last_error=None,
                    )
                )
        except Exception as exc:
            status = "failed"
            last_error = str(exc)
            ended_at = utc_now_epoch()
        finally:
            final_state = self.get_status()
            final_state.update(
                {
                    "active": False,
                    "status": status,
                    "current_phase": "off",
                    "next_switch_at": None,
                    "heartbeat_at": utc_now_epoch(),
                    "ended_at": ended_at,
                    "stop_requested": status == "stopped",
                    "stop_skip_final_off": skip_final_off,
                    "last_command": "cycle:cancel" if skip_final_off else "cycle:stop",
                }
            )
            if last_error is not None:
                final_state["last_error"] = last_error
            self._write_state(final_state)
            self._clear_signal_file()
            lock.release()

    def _wait_for_signal(self, deadline: float) -> dict[str, Any] | None:
        while True:
            signal = read_json_file(SIGNAL_FILE)
            if signal is not None and signal.get("action") == "stop":
                return signal

            if self._stop_event.is_set():
                signal = read_json_file(SIGNAL_FILE)
                if signal is not None:
                    return signal
                return {"action": "stop", "skip_final_off": False}

            now = utc_now_epoch()
            state = self._load_state()
            state["heartbeat_at"] = now
            self._write_state(state)

            if now >= deadline:
                return None

            time.sleep(min(1.0, max(0.1, deadline - now)))

    def _send_cycle_start(self, settings: MQTTSettings, request: CycleRequest) -> None:
        controller = MqttDeviceController(settings)
        controller.send_cycle_start(
            total_seconds=request.total_seconds,
            on_seconds=request.on_seconds,
            off_seconds=request.off_seconds,
        )

    def _send_cycle_stop(self, settings: MQTTSettings) -> None:
        controller = MqttDeviceController(settings)
        controller.send_cycle_stop()

    def _send_cycle_cancel(self, settings: MQTTSettings) -> None:
        controller = MqttDeviceController(settings)
        controller.send_cycle_cancel()

    def _load_state(self) -> dict[str, Any]:
        state = read_json_file(STATE_FILE)
        if state is not None:
            return state
        return self._build_idle_state()

    def _write_state(self, state: dict[str, Any]) -> None:
        atomic_write_json(STATE_FILE, state)

    def _clear_signal_file(self) -> None:
        try:
            SIGNAL_FILE.unlink()
        except FileNotFoundError:
            return

    def _validate_request(self, request: CycleRequest) -> None:
        if request.total_hours <= 0:
            raise ValueError("控制总时长必须大于 0 小时。")
        if request.on_minutes <= 0:
            raise ValueError("亮灯时长必须大于 0 分钟。")
        if request.off_minutes <= 0:
            raise ValueError("灭灯时长必须大于 0 分钟。")

    def _build_idle_state(self) -> dict[str, Any]:
        return {
            "active": False,
            "status": "idle",
            "started_at": None,
            "ends_at": None,
            "ended_at": None,
            "heartbeat_at": None,
            "current_phase": "off",
            "phase_started_at": None,
            "next_switch_at": None,
            "total_hours": None,
            "on_minutes": None,
            "off_minutes": None,
            "total_seconds": None,
            "on_seconds": None,
            "off_seconds": None,
            "stop_requested": False,
            "stop_skip_final_off": False,
            "last_command": None,
            "last_error": None,
        }

    def _build_state(
        self,
        *,
        request: CycleRequest,
        active: bool,
        status: str,
        current_phase: str,
        started_at: float | None,
        phase_started_at: float | None,
        next_switch_at: float | None,
        ends_at: float | None,
        heartbeat_at: float | None,
        ended_at: float | None,
        stop_requested: bool,
        stop_skip_final_off: bool,
        last_command: str | None,
        last_error: str | None,
    ) -> dict[str, Any]:
        return {
            "active": active,
            "status": status,
            "started_at": started_at,
            "ends_at": ends_at,
            "ended_at": ended_at,
            "heartbeat_at": heartbeat_at,
            "current_phase": current_phase,
            "phase_started_at": phase_started_at,
            "next_switch_at": next_switch_at,
            "total_hours": request.total_hours,
            "on_minutes": request.on_minutes,
            "off_minutes": request.off_minutes,
            "total_seconds": request.total_seconds,
            "on_seconds": request.on_seconds,
            "off_seconds": request.off_seconds,
            "stop_requested": stop_requested,
            "stop_skip_final_off": stop_skip_final_off,
            "last_command": last_command,
            "last_error": last_error,
        }
