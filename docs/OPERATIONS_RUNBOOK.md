# Operations

Deploying, monitoring and troubleshooting VisionAttend.

## Deploying

Every deployment needs `SECRET_KEY` and `DATABASE_URL`. The app refuses to start without a proper `SECRET_KEY` (see [Troubleshooting](#app-exits-at-startup-with-secret_key-is-missing)).

### Render

1. In the service's **Environment** settings, set `SECRET_KEY` (Render's **Generate** button works) and `DATABASE_URL`. Render's `postgres://` URLs are rewritten to `postgresql://` automatically.
2. Optionally set `REDIS_URL`, and `ALLOW_PUBLIC_ADMIN_SIGNUP=true` if visitors should be able to create admin accounts.
3. Deploy with `python run.py` as the start command (the Docker image already uses it). It runs Gunicorn on `$PORT`.

On the free plan the instance sleeps when idle, and the first request after that takes a while. The FaceNet weights are downloaded again on the first face request after each restart.

### Docker Compose

```bash
cp .env.example .env      # set SECRET_KEY
docker compose up -d --build
```

Runs the app, PostgreSQL 16 (seeded from `seed.sql`), Redis 7, Prometheus and Grafana.

### Kubernetes

The manifests in `k8s/` define a ConfigMap, a Deployment (2 replicas, 250m/256Mi requests, 1 CPU/512Mi limits), a LoadBalancer Service and an HPA (2 to 10 replicas on CPU and memory).

1. Build and push the image referenced in `k8s/deployment.yaml`. CI doesn't publish images.
2. Create the secret:
   ```bash
   kubectl create secret generic attendance-secrets \
     --from-literal=database-url=postgresql://... \
     --from-literal=secret-key=$(python -c "import secrets; print(secrets.token_hex(32))")
   ```
3. Provide Redis as a Service named `redis-service`, or each pod keeps its own lockout counters.
4. `make k8s-apply`

Kiosk trackers are kept in each pod's memory. Enable session affinity on the Service or ingress so a kiosk's frames reach the same pod; without it, trackers are rebuilt on the next keyframe.

Rolling update and rollback:

```bash
kubectl set image deployment/attendance-api-deployment attendance-api=ghcr.io/pratyushkandari/attendance-system:<tag>
kubectl rollout status deployment/attendance-api-deployment
kubectl rollout undo deployment/attendance-api-deployment
```

The readiness probe requests `GET /` (after 15 s) and the liveness probe `GET /metrics` (every 15 s).

## Monitoring

Prometheus scrapes `/metrics` (every 5 s in the bundled `prometheus.yml`). Metric names are listed in the [API reference](API_SPECIFICATION.md#get-metrics).

Example alert rules:

```yaml
groups:
  - name: visionattend
    rules:
      - alert: SlowRecognition
        expr: histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{endpoint="attendance.recognize_with_box"}[2m])) by (le)) > 0.5
        for: 3m
        labels:
          severity: warning
        annotations:
          summary: "p95 kiosk frame latency above 500 ms"

      - alert: HighErrorRate
        expr: sum(rate(http_requests_total{status=~"5.."}[2m])) / sum(rate(http_requests_total[2m])) > 0.02
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "More than 2% of requests are failing with 5xx"

      # Needs a Redis exporter such as oliver006/redis_exporter;
      # the app doesn't export Redis metrics itself.
      - alert: RedisDown
        expr: redis_up == 0
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Redis unreachable; lockout counters are per process until it's back"
```

Adjust the latency threshold once you have a baseline for your hardware.

## Troubleshooting

### App exits at startup with `SECRET_KEY is missing`

`SECRET_KEY` is unset, empty, or a value that was committed to this repository (an old config default, `.env.example` or `docker-compose.yml`). The app won't sign anything with a key that other people can see.

1. Generate a key: `python -c "import secrets; print(secrets.token_hex(32))"`
2. Set it in `.env` (local and Compose), in the `attendance-secrets` Secret under `secret-key` (Kubernetes) or in the service's environment variables (Render).
3. Restart. Existing sessions, JWTs and QR codes stop working, since they were signed with the old key.

### Kiosk finds no faces; logs show `unexpected EOF ... The file might be corrupted`

The VGGFace2 weights (`20180402-114759-vggface2.pt`, 111,898,327 bytes) are downloaded into the PyTorch cache on the first face request. If that download is cut off, the partial file stays in the cache and facenet-pytorch never downloads it again, so every embedding fails.

```bash
docker exec attendance_app ls -l /root/.cache/torch/checkpoints/
```

If the file isn't 111,898,327 bytes, delete it and the next face request downloads it again:

```bash
docker exec attendance_app rm /root/.cache/torch/checkpoints/20180402-114759-vggface2.pt
```

A recreated container starts with an empty cache and downloads the weights again on first use.

### Kiosk is slow or boxes lag

1. Check `active_camera_clients_total`. Each pod handles every kiosk sending frames to it, so several high-resolution kiosks on one pod will queue up. Add replicas:
   ```bash
   kubectl scale deployment attendance-api-deployment --replicas=4
   ```
2. Check for CPU throttling against the 1-CPU limit: `kubectl top pods -l app=attendance-system`
3. Make sure `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS` and `MKL_NUM_THREADS` are `1`, as in the Docker image. More threads per request means contention between Gunicorn's threads.
4. As a stopgap, use the **Switch to QR Session** button on the kiosk. QR check-in doesn't run any model.

### `QueuePool limit of size 5 overflow 10 reached, connection timed out`

All database connections are in use (pool of 5, overflow 10, 20-second timeout).

1. See what's connected:
   ```sql
   SELECT count(*), state FROM pg_stat_activity GROUP BY state;
   ```
2. Find long-running queries:
   ```sql
   SELECT pid, now() - query_start AS duration, query
   FROM pg_stat_activity
   WHERE state != 'idle'
   ORDER BY duration DESC;
   ```
3. Kill sessions stuck in a transaction:
   ```sql
   SELECT pg_terminate_backend(pid)
   FROM pg_stat_activity
   WHERE state = 'idle in transaction'
     AND now() - state_change > interval '2 minutes';
   ```
4. If you're running many pods, put PgBouncer in front of PostgreSQL or raise `pool_size` and `max_overflow` in `SQLALCHEMY_ENGINE_OPTIONS` (`app/config.py`).

### Redis is down

The logs show `[CACHE] Redis offline (...), operating with in-memory TTL store.` Logins and attendance keep working; lockout counters are tracked per process until Redis is back.

- Compose: `docker compose logs redis`, then `docker compose restart redis`.
- Kubernetes: Redis isn't part of `k8s/`. Check whatever backs `redis-service` with `kubectl get endpoints redis-service`.

`SafeCacheStore` re-checks Redis every 30 seconds and logs `[CACHE] Redis connection restored.` when it reconnects. Counters recorded in memory during the outage aren't copied to Redis.
