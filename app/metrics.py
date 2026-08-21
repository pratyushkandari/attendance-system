import time
from flask import request, Response
from prometheus_client import (
    Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
)

# ---------------- PROMETHEUS METRIC DEFINITIONS ----------------

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total count of HTTP requests processed by endpoint and status",
    ["method", "endpoint", "status"]
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds with p50, p95, p99 distribution",
    ["method", "endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

ATTENDANCE_MARKED_TOTAL = Counter(
    "attendance_marked_total",
    "Total attendance instances successfully logged",
    ["method"]
)

ACTIVE_CAMERA_CLIENTS = Gauge(
    "active_camera_clients_total",
    "Current count of active real-time webcam client sessions"
)

LIVENESS_DETECTION_TOTAL = Counter(
    "liveness_detection_total",
    "Total biometric liveness / blink checks processed",
    ["status"]
)


def init_metrics(app):
    """
    Hooks metrics middleware into Flask request lifecycle.
    """
    @app.before_request
    def start_timer():
        request._start_time = time.time()

    @app.after_request
    def record_metrics(response):
        if hasattr(request, "_start_time"):
            duration = time.time() - request._start_time
            endpoint = request.endpoint or "unknown"
            REQUEST_LATENCY.labels(method=request.method, endpoint=endpoint).observe(duration)
            REQUEST_COUNT.labels(
                method=request.method,
                endpoint=endpoint,
                status=response.status_code
            ).inc()
        return response

    @app.route("/metrics")
    def metrics_endpoint():
        """Prometheus scrape endpoint."""
        return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)
