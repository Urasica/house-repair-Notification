"""Allowlisted request metadata: never log raw paths, query strings or identities."""

import json
import logging
from datetime import UTC, datetime

from starlette.requests import Request

from app.core.metrics import HTTP_DURATION, HTTP_REQUESTS

logger = logging.getLogger("repair.http")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False


def log_http(request: Request, status: int, elapsed: float, *, collect_metrics: bool) -> None:
    route = getattr(request.scope.get("route"), "path", "unmatched")
    method = request.method
    if method not in {"GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"}:
        method = "OTHER"
    if collect_metrics:
        metric_route = (
            "unmatched_api"
            if route == "unmatched" and request.url.path.startswith("/api/v1/")
            else route
        )
        HTTP_REQUESTS.labels(metric_route, method, str(status)).inc()
        HTTP_DURATION.labels(metric_route, method).observe(elapsed)
    logger.info(
        json.dumps(
            {
                "event": "http",
                "time": datetime.now(UTC).isoformat(),
                "route": route,
                "method": method,
                "status": status,
                "durationMs": round(elapsed * 1000, 2),
                "traceId": str(request.state.trace_id),
            }
        )
    )
