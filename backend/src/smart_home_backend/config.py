from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import uuid

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"


def load_env_file(path: Path = DEFAULT_ENV_FILE) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("export "):
            line = line[7:].lstrip()

        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if value and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        os.environ.setdefault(key, value)


def read_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class MQTTSettings:
    host: str
    port: int
    username: str
    password: str
    topic_root: str
    client_id_prefix: str
    keepalive: int
    command_timeout: float
    use_tls: bool
    tls_insecure: bool

    @property
    def command_topic(self) -> str:
        return f"{self.topic_root}/cmd"

    @property
    def status_topic(self) -> str:
        return f"{self.topic_root}/status"

    def build_client_id(self) -> str:
        return f"{self.client_id_prefix}-{uuid.uuid4().hex[:8]}"

    @classmethod
    def from_env(cls) -> "MQTTSettings":
        load_env_file()

        host = os.getenv("MQTT_HOST", "").strip()
        username = os.getenv("MQTT_USERNAME", "").strip()
        password = os.getenv("MQTT_PASSWORD", "")
        topic_root = os.getenv("MQTT_TOPIC_ROOT", "nodemcu").strip()

        if not host:
            raise ValueError("缺少 MQTT_HOST，请先配置 smart_home_control/backend/.env。")

        if not username:
            raise ValueError("缺少 MQTT_USERNAME，请先配置 smart_home_control/backend/.env。")

        return cls(
            host=host,
            port=int(os.getenv("MQTT_PORT", "8883")),
            username=username,
            password=password,
            topic_root=topic_root,
            client_id_prefix=(
                os.getenv("MQTT_CLIENT_ID_PREFIX", "smart-home-backend").strip()
                or "smart-home-backend"
            ),
            keepalive=int(os.getenv("MQTT_KEEPALIVE", "60")),
            command_timeout=float(os.getenv("MQTT_COMMAND_TIMEOUT", "5")),
            use_tls=read_bool_env("MQTT_USE_TLS", True),
            tls_insecure=read_bool_env("MQTT_TLS_INSECURE", False),
        )


@dataclass(slots=True)
class WebSettings:
    host: str
    port: int
    debug: bool
    proxy_fix: bool

    @classmethod
    def from_env(cls) -> "WebSettings":
        load_env_file()
        return cls(
            host=os.getenv("WEB_HOST", "0.0.0.0").strip() or "0.0.0.0",
            port=int(os.getenv("WEB_PORT", "28681")),
            debug=read_bool_env("WEB_DEBUG", False),
            proxy_fix=read_bool_env("WEB_PROXY_FIX", True),
        )
