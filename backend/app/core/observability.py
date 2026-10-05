"""Allowlisted request metadata: never log raw paths, query strings or identities."""

import json
import logging
from datetime import UTC, datetime

from starlette.requests import Request

logger = logging.getLogger("repair.http")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False


def log_http(request: Request, status: int, elapsed: float) -> None:
    route = request.scope.get("route")
    logger.info(
        json.dumps(
            {
                "event": "http",
                "time": datetime.now(UTC).isoformat(),
                "route": getattr(route, "path", "unmatched"),
                "method": request.method
                if request.method in {"GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"}
                else "OTHER",
                "status": status,
                "durationMs": round(elapsed * 1000, 2),
                "traceId": str(request.state.trace_id),
            }
        )
    )
