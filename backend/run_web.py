from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from smart_home_backend.config import WebSettings
from smart_home_backend.web_app import create_app


def main() -> int:
    settings = WebSettings.from_env()
    app = create_app()
    app.run(host=settings.host, port=settings.port, debug=settings.debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
