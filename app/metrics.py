import time

from flask import Flask, Response, request
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

# ---------------- PROMETHEUS METRIC DEFINITIONS ----------------

REQUEST_COUNT: Counter = Counter(
    "http_requests_total",
    "Total count of HTTP requests processed by endpoint and status",
    ["method", "endpoint", "status"],
)

REQUEST_LATENCY: Histogram = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds with p50, p95, p99 distribution",
    ["method", "endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

ATTENDANCE_MARKED_TOTAL: Counter = Counter(
    "attendance_marked_total",
    "Total attendance instances successfully logged",
    ["method"],
)

# Number of kiosk tracking sessions seen in the last 120 s by *this* process.
# Updated by /recognize_with_box; each Gunicorn worker/pod reports its own value.
ACTIVE_CAMERA_CLIENTS: Gauge = Gauge(
    "active_camera_clients_total",
    "Current count of active real-time webcam client sessions",
)


def init_metrics(app: Flask) -> None:
    """
    Hooks Prometheus telemetry collection into the Flask request lifecycle.

    Tracks incoming HTTP requests, status code distribution, and execution duration
    histograms. Exposes raw metric output at `/metrics` compliant with Prometheus format.
    """

    @app.before_request
    def start_timer() -> None:
        request._start_time = time.time()  # type: ignore[attr-defined]

    @app.after_request
    def record_metrics(response: Response) -> Response:
        if hasattr(request, "_start_time"):
            duration = time.time() - request._start_time  # type: ignore[attr-defined]
            endpoint = request.endpoint or "unknown"
            REQUEST_LATENCY.labels(method=request.method, endpoint=endpoint).observe(duration)
            REQUEST_COUNT.labels(
                method=request.method,
                endpoint=endpoint,
                status=response.status_code,
            ).inc()
        return response

    @app.route("/metrics")
    def metrics_endpoint() -> Response:
        """Prometheus scrape endpoint."""
        return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

