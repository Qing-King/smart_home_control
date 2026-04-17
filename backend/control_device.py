from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from smart_home_backend.config import MQTTSettings
from smart_home_backend.controller import MqttDeviceController, StatusPacket


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="通过 Python 后端向家庭设备发送 MQTT 控制命令。"
    )
    parser.add_argument(
        "command",
        choices=["on", "off", "toggle", "status"],
        help="要发送到 nodemcu/cmd 的命令。",
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="只发布命令，不等待设备回 status。",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="连接和等待状态回包的超时时间，单位秒。",
    )
    return parser


def format_status(packet: StatusPacket) -> str:
    if packet.parsed is not None:
        return json.dumps(packet.parsed, ensure_ascii=False, indent=2)
    return packet.payload


def main() -> int:
    args = build_parser().parse_args()

    try:
        settings = MQTTSettings.from_env()
        controller = MqttDeviceController(settings)

        status = controller.send_command(
            args.command,
            wait_for_status=not args.no_wait,
            timeout=args.timeout,
        )

        print(f"已发送命令: {args.command}")
        if status is not None:
            print("设备回包:")
            print(format_status(status))
        return 0
    except Exception as exc:  # pragma: no cover - CLI exception guard
        print(f"执行失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
