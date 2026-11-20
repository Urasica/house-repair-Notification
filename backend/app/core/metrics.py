"""Aggregate metrics for a single API worker, with bounded metric labels."""

from prometheus_client import CollectorRegistry, Counter, Histogram

from app.domain.constants import GuidanceStatus

METRICS_PATH = "/internal/metrics"
REGISTRY = CollectorRegistry()
HTTP_REQUESTS = Counter(
    "repair_http_requests_total",
    "HTTP requests by route template and status.",
    ("route", "method", "status"),
    registry=REGISTRY,
)
HTTP_DURATION = Histogram(
    "repair_http_request_duration_seconds",
    "HTTP request handling time.",
    ("route", "method"),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 8, 10, 15, 20, 25, 30),
    registry=REGISTRY,
)
GUIDANCE_RESULTS = Counter(
    "repair_guidance_results_total",
    "Newly committed guidance results by status.",
    ("flow", "status"),
    registry=REGISTRY,
)
GUIDANCE_FALLBACKS = Counter(
    "repair_guidance_fallbacks_total",
    "Guidance fallback decisions by cause.",
    ("flow", "reason"),
    registry=REGISTRY,
)
DELETION_EXPORT = Counter(
    "repair_deletion_exports_total",
    "Immediate deletion export attempts.",
    ("outcome",),
    registry=REGISTRY,
)

for flow in ("chat", "survey"):
    for status in GuidanceStatus:
        GUIDANCE_RESULTS.labels(flow, status)
    for reason in ("provider_failure", "provider_disabled", "source_unavailable"):
        GUIDANCE_FALLBACKS.labels(flow, reason)
for outcome in ("success", "failure"):
    DELETION_EXPORT.labels(outcome)
