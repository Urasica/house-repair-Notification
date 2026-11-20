"""Publish aggregate metrics from optional one-shot operations commands."""

import logging
import os

import httpx

logger = logging.getLogger(__name__)


def push_metrics(job: str, payload: str, grouping: str = "") -> bool:
    gateway = os.environ.get("MONITORING_PUSHGATEWAY")
    if not gateway:
        return False
    try:
        response = httpx.put(
            f"{gateway.rstrip('/')}/metrics/job/{job}{grouping}",
            content=payload.encode(),
            headers={"Content-Type": "text/plain; version=0.0.4; charset=utf-8"},
            timeout=3,
            trust_env=False,
        )
        response.raise_for_status()
    except (httpx.HTTPError, httpx.InvalidURL) as error:
        logger.warning("Monitoring metric push failed: job=%s type=%s", job, type(error).__name__)
        return False
    return True


def report_maintenance(action: str, *, success: bool) -> None:
    if action in {"backup", "cleanup", "export-deletions"}:
        result = "success" if success else "failure"
        push_metrics(
            "repair_maintenance",
            "# TYPE repair_maintenance_result gauge\nrepair_maintenance_result 1\n",
            f"/task/{action}/result/{result}",
        )
