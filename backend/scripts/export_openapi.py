import argparse
import json
from pathlib import Path

from app.core.config import Settings
from app.main import create_app


def contract_json() -> str:
    app = create_app(Settings(_env_file=None, app_env="test", openai_enabled=False))
    return json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = Path(__file__).resolve().parents[2] / "schemas" / "openapi.json"
    content = contract_json()
    if args.check:
        if not target.exists() or target.read_text(encoding="utf-8") != content:
            raise SystemExit("OpenAPI snapshot is stale; run python -m scripts.export_openapi")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
