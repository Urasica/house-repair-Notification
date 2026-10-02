import json
from pathlib import Path

from app.schemas.catalog import CatalogDefinition

destination = Path(__file__).resolve().parents[2] / "schemas" / "catalog.schema.json"
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(
    json.dumps(CatalogDefinition.model_json_schema(by_alias=True), ensure_ascii=False, indent=2)
    + "\n",
    encoding="utf-8",
)
print("Exported schemas/catalog.schema.json")
