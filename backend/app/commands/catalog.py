"""One-shot catalog validation/publication; never starts API recovery or inserts sample data."""

import argparse
import asyncio
import json
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import text

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.session import MIGRATION_HEAD, Database
from app.schemas.catalog import CatalogDefinition
from app.services.catalog import publication_allowed, publish_catalog

MAX_FILE_BYTES = 5 * 1024 * 1024


def read_definition(path: Path) -> CatalogDefinition:
    # Bound reads even if a file grows between stat/read. UTF-8 BOM is accepted.
    with path.open("rb") as handle:
        raw = handle.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("Catalog file exceeds 5 MiB")
    return CatalogDefinition.model_validate_json(raw.decode("utf-8-sig"))


async def publish(definition: CatalogDefinition):
    settings = get_settings()
    publication_allowed(definition, settings)
    database = Database(settings)
    try:
        async with database.transaction() as session:
            if (
                await session.scalar(text("SELECT version_num FROM alembic_version"))
                != MIGRATION_HEAD
            ):
                raise Database.unavailable()
            result = await publish_catalog(session, definition, settings)
        return result
    finally:
        await database.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate or publish a reviewed catalog JSON file")
    parser.add_argument("action", choices=["validate", "publish"])
    parser.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    try:
        definition = read_definition(args.path)
        output = {
            "version": definition.version,
            "reviewState": definition.review.state,
            "counts": {
                wire_name: len(getattr(definition, name))
                for wire_name, name in (
                    ("housingTypes", "housing_types"),
                    ("rooms", "rooms"),
                    ("facilities", "facilities"),
                    ("symptoms", "symptoms"),
                    ("questions", "questions"),
                )
            },
        }
        if args.action == "publish":
            result = asyncio.run(publish(definition))
            output["publishedAt"] = result.model_dump(mode="json", by_alias=True)["publishedAt"]
        else:
            output["reviewComplete"] = definition.review.state == "COMPLETE_VERIFIED"
        print(json.dumps(output, ensure_ascii=False))
        return 0
    except ValidationError as error:
        # Never print Pydantic's raw input or SQL/credentials in command errors.
        print(
            json.dumps(
                {
                    "error": "VALIDATION_ERROR",
                    "fields": [
                        ".".join(map(str, item["loc"])) or "catalog" for item in error.errors()
                    ],
                },
                ensure_ascii=False,
            )
        )
    except AppError as error:
        print(json.dumps({"error": error.code, "message": error.message}, ensure_ascii=False))
    except (OSError, ValueError):
        print(
            json.dumps(
                {"error": "VALIDATION_ERROR", "message": "목록 파일을 읽거나 검증할 수 없어요."},
                ensure_ascii=False,
            )
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
