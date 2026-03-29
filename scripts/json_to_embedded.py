#!/usr/bin/env python3
"""从 plants.json 生成 plants.embedded.js（本地改 JSON 后执行本脚本即可）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JSON_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "plants.json"
JS_PATH = JSON_PATH.with_name("plants.embedded.js")


def main() -> int:
    payload = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    JS_PATH.write_text(
        "/* Synced from plants.json — python3 flower/scripts/json_to_embedded.py */\n"
        "window.__PLANTS_PAYLOAD__ = "
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )
    print("Wrote", JS_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
