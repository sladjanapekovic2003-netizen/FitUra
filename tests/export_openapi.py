"""Save the live specifications beside each implementation."""
import json
from pathlib import Path
from test_api import BASE, call

root = Path(__file__).resolve().parents[1]
for service in BASE:
    path = root / "storitve" / service / "openapi.json"
    path.write_text(json.dumps(call(service, "GET", "/openapi.json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(path.relative_to(root))
