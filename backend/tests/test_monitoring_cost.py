from decimal import Decimal

import httpx
import pytest

from app.commands import monitoring_cost


def cost_page(value, *, project="proj_test", next_page=None):
    return {
        "data": [
            {"results": [{"project_id": project, "amount": {"value": value, "currency": "usd"}}]}
        ],
        "has_more": next_page is not None,
        "next_page": next_page,
    }


def test_costs_sum_all_pages_for_one_project():
    requests = []

    def mock(request):
        assert request.method == "GET"
        assert request.url.host == "api.openai.com"
        assert request.url.path == "/v1/organization/costs"
        assert request.url.params["project_ids[]"] == "proj_test"
        assert request.url.params["group_by[]"] == "project_id"
        assert request.url.params["start_time"] == "1000"
        assert request.url.params["end_time"] == "1100"
        requests.append(request)
        if request.url.params.get("page") == "next":
            return httpx.Response(200, json=cost_page(0.2))
        return httpx.Response(200, json=cost_page(0.1, next_page="next"))

    with httpx.Client(transport=httpx.MockTransport(mock)) as client:
        assert monitoring_cost.monthly_spend(client, "proj_test", 1000, 1100) == Decimal("0.3")
    assert len(requests) == 2


def test_costs_reject_unexpected_projects_and_repeated_cursors():
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=cost_page(0.1, project="proj_other"))
        )
    ) as client:
        with pytest.raises(ValueError, match="Unexpected project"):
            monitoring_cost.monthly_spend(client, "proj_test", 1000, 1100)

    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=cost_page(0.1, next_page="same"))
        )
    ) as client:
        with pytest.raises(ValueError, match="Invalid cost cursor"):
            monitoring_cost.monthly_spend(client, "proj_test", 1000, 1100)


def test_collector_exports_only_aggregates_and_keeps_last_snapshot_on_failure(
    monkeypatch, tmp_path, capsys
):
    key = tmp_path / "key"
    key.write_text("synthetic-admin-key", encoding="utf-8")
    monkeypatch.setattr(monitoring_cost, "KEY_FILE", key)
    monkeypatch.setenv("MONITORING_COST_PROJECT_ID", "proj_test")
    monkeypatch.setenv("MONITORING_COST_MONTHLY_BUDGET_USD", "10")
    monkeypatch.setenv("MONITORING_PUSHGATEWAY", "http://pushgateway:9091")
    pushes = []
    monkeypatch.setattr(monitoring_cost, "monthly_spend", lambda *args: Decimal("8.25"))
    monkeypatch.setattr(
        monitoring_cost, "push_metrics", lambda job, payload: pushes.append((job, payload)) or True
    )
    assert monitoring_cost.main() == 0
    job, payload = pushes[0]
    assert job == "repair_openai_cost"
    assert "repair_openai_month_spend_usd 8.25" in payload
    assert "repair_openai_month_budget_usd 10" in payload
    assert "proj_test" not in payload

    def fail(*args):
        raise ValueError("private provider response")

    monkeypatch.setattr(monitoring_cost, "monthly_spend", fail)
    assert monitoring_cost.main() == 1
    assert len(pushes) == 1
    output = capsys.readouterr().out
    assert "COST_COLLECTION_FAILED" in output
    assert "synthetic-admin-key" not in output + payload
    assert "private provider response" not in output
