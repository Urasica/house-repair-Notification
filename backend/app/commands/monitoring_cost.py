"""Read a project's reported OpenAI spend and publish only monthly totals."""

import json
import math
import os
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx

from app.core.monitoring_push import push_metrics

COSTS_URL = "https://api.openai.com/v1/organization/costs"
KEY_FILE = Path("/run/secrets/openai_cost_admin_key")


def monthly_spend(client: httpx.Client, project_id: str, start: int, end: int) -> Decimal:
    params = {
        "start_time": str(start),
        "end_time": str(max(end, start + 1)),
        "bucket_width": "1d",
        "limit": "31",
        "project_ids[]": project_id,
        "group_by[]": "project_id",
    }
    total = Decimal(0)
    seen = set()
    for _ in range(32):
        response = client.get(COSTS_URL, params=params)
        response.raise_for_status()
        page = response.json(parse_float=Decimal)
        if not isinstance(page["data"], list) or type(page["has_more"]) is not bool:
            raise ValueError("Invalid cost page")
        for bucket in page["data"]:
            if not isinstance(bucket["results"], list):
                raise ValueError("Invalid cost bucket")
            for item in bucket["results"]:
                amount = item["amount"]
                if item["project_id"] != project_id or amount["currency"] != "usd":
                    raise ValueError("Unexpected project or currency in costs")
                value = amount["value"]
                if type(value) not in (Decimal, int) or not math.isfinite(float(value)):
                    raise ValueError("Invalid cost amount")
                total += value
        if not page["has_more"]:
            if not math.isfinite(float(total)):
                raise ValueError("Invalid cost total")
            return total
        cursor = page["next_page"]
        if not isinstance(cursor, str) or not cursor or cursor in seen:
            raise ValueError("Invalid cost cursor")
        seen.add(cursor)
        params["page"] = cursor
    raise ValueError("Cost page limit exceeded")


def main() -> int:
    try:
        project_id = os.environ["MONITORING_COST_PROJECT_ID"]
        budget = Decimal(os.environ["MONITORING_COST_MONTHLY_BUDGET_USD"])
        if not re.fullmatch(r"proj_[A-Za-z0-9_-]{1,100}", project_id):
            raise ValueError("Invalid OpenAI project ID")
        if not math.isfinite(float(budget)) or float(budget) <= 0:
            raise ValueError("Invalid budget")
        if not os.environ.get("MONITORING_PUSHGATEWAY"):
            raise ValueError("Pushgateway is required")
        key = KEY_FILE.read_text(encoding="utf-8").strip()
        if not key:
            raise ValueError("OpenAI cost key is empty")
        now = datetime.now(UTC)
        start = int(now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp())
        with httpx.Client(
            headers={"Authorization": "Bearer " + key},
            timeout=10,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            total = monthly_spend(client, project_id, start, int(now.timestamp()))
        if not push_metrics(
            "repair_openai_cost",
            "# TYPE repair_openai_month_spend_usd gauge\n"
            f"repair_openai_month_spend_usd {float(total):.17g}\n"
            "# TYPE repair_openai_month_budget_usd gauge\n"
            f"repair_openai_month_budget_usd {float(budget):.17g}\n"
            "# TYPE repair_openai_month_start_timestamp_seconds gauge\n"
            f"repair_openai_month_start_timestamp_seconds {start}\n",
        ):
            raise OSError("Cost metric push failed")
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        OverflowError,
        InvalidOperation,
        httpx.HTTPError,
    ) as error:
        print(json.dumps({"error": "COST_COLLECTION_FAILED", "type": type(error).__name__}))
        return 1
    print(json.dumps({"status": "COST_COLLECTED"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
