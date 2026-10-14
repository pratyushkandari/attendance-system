# Production Operations & Incident Runbook

**Service:** VisionAttend Core Attendance & Identity Gateway  
**Audience:** Site Reliability Engineers (SRE), DevOps, On-Call Engineers  
**Classification:** Tier-1 Institutional Infrastructure  

---

## 1. Service Level Objectives (SLOs) & Targets

| Metric | Target | Measurement Window | Alert Threshold |
| :--- | :--- | :--- | :--- |
| **API Availability** | $\ge 99.9\%$ successful HTTP requests (non-5xx) | Rolling 30 Days | $< 99.5\%$ over 5 minutes |
| **P95 Recognition Latency** | $< 45\text{ ms}$ per video frame | Rolling 1 Hour | $> 75\text{ ms}$ sustained for 3m |
| **P99 QR Verification Latency** | $< 10\text{ ms}$ | Rolling 1 Hour | $> 25\text{ ms}$ sustained for 3m |
| **Ledger Data Integrity** | Zero duplicate check-ins per student per day | Real-time | Any duplicate write event |

---

## 2. Telemetry & Alerting Definitions

Prometheus scrapes metrics from `/metrics` every 5 seconds. Configure the following alerting rules:

```yaml
groups:
  - name: attendance_gateway_alerts
    rules:
      - alert: HighFrameRecognitionLatency
        expr: histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{endpoint="attendance.recognize_with_box"}[2m])) by (le)) > 0.075
        for: 3m
        labels:
          severity: warning
        annotations:
          summary: "Biometric inference P95 latency exceeded 75ms"
          description: "Frame processing pipeline is bottlenecked. Check container CPU throttling or concurrent active camera clients."

      - alert: ElevatedHttpServerErrorRate
        expr: sum(rate(http_requests_total{status=~"5.."}[2m])) / sum(rate(http_requests_total[2m])) > 0.02
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "5xx server error rate exceeds 2%"
          description: "Database connection exhaustion or unhandled runtime exceptions detected."

      - alert: RedisDistributedCacheDown
        expr: rate(redis_connected_clients[1m]) == 0
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Redis distributed cache unreachable"
          description: "Application has engaged in-memory TTL cache fallback. Sliding brute-force lockout counters are localized to pods."
```

---

## 3. Incident Response Playbooks

### Playbook A: High P95 Latency on Biometric Terminal

**Symptoms:** Bounding boxes lag on kiosk video feed; Prometheus `http_request_duration_seconds` spikes above 100ms.

1. **Verify Active Camera Concurrency:**
   Check gauge `active_camera_clients_total`. If a single pod is handling $> 4$ high-resolution streams simultaneously, trigger horizontal pod scale-out:
   ```bash
   kubectl scale deployment attendance-api-deployment --replicas=5
   ```
2. **Inspect CPU Throttling:**
   Verify if the pod has reached Kubernetes CPU limit (1000m):
   ```bash
   kubectl top pods -l app=attendance-system
   ```
3. **Check PyTorch Thread Contention:**
   Ensure environment variables limit BLAS/OpenMP thread thrashing:
   `OMP_NUM_THREADS=1`, `OPENBLAS_NUM_THREADS=1`, `MKL_NUM_THREADS=1`.
4. **Emergency Mitigation (Degraded Mode):**
   Advise operators at the affected kiosk to click **"Switch to QR Session"**. Dynamic QR attendance uses zero CPU inference and executes in $< 1\text{ ms}$.

---

### Playbook B: Database Connection Starvation (`pool_timeout: 20`)

**Symptoms:** HTTP 500 responses with `TimeoutError: QueuePool limit of size 5 overflow 10 reached, connection timed out, timeout 20.00`.

1. **Inspect Active PostgreSQL Connection Count:**
   ```sql
   SELECT count(*), state FROM pg_stat_activity GROUP BY state;
   ```
2. **Identify Orphaned Queries:**
   ```sql
   SELECT pid, now() - query_start AS duration, query 
   FROM pg_stat_activity 
   WHERE state != 'idle' 
   ORDER BY duration DESC;
   ```
3. **Terminate Hanging Connections:**
   ```sql
   SELECT pg_terminate_backend(pid) 
   FROM pg_stat_activity 
   WHERE state = 'idle in transaction' 
     AND now() - state_change > interval '2 minutes';
   ```
4. **Adjust Connection Pool Configuration:**
   If institutional scale exceeds 10 pods, deploy PgBouncer or raise `pool_size` and `max_overflow` in `app/config.py`.

---

### Playbook C: Redis Node Outage

**Symptoms:** `SafeCacheStore` log outputs: `[CACHE] Redis offline (...), operating with in-memory TTL store.`

1. **Impact Assessment:**
   * **Severity: LOW (Non-Breaking).**
   * The platform's two-tier cache automatically diverts all key-value operations to localized in-memory stores with timestamp expiration.
   * Student check-ins and attendance marking continue operating normally.
2. **Recovery Procedure:**
   Check Redis pod status:
   ```bash
   kubectl describe pod -l app=attendance-redis
   kubectl logs -l app=attendance-redis --tail=100
   ```
   Restart Redis deployment:
   ```bash
   kubectl rollout restart deployment attendance-redis
   ```
   Once Redis is back online, the application seamlessly auto-reconnects on the subsequent read/write cycle.

---

### Playbook D: Zero-Downtime Rolling Update & Rollback

1. **Deploy New Build to Kubernetes:**
   ```bash
   kubectl set image deployment/attendance-api-deployment attendance-api=ghcr.io/pratyushkandari/attendance-system:v2.4.3 --record
   ```
2. **Monitor Rolling Rollout:**
   ```bash
   kubectl rollout status deployment/attendance-api-deployment
   ```
   * Readiness probe tests `GET /` with initial delay 15s.
   * Liveness probe tests `GET /metrics` with period 15s.
3. **Instant Rollback (if errors observed):**
   ```bash
   kubectl rollout undo deployment/attendance-api-deployment
   ```

---

## 4. Hardware Sizing & Capacity Guidelines

| Daily Active Students | Pod Count | CPU Request / Limit | RAM Request / Limit | Database Sizing |
| :--- | :---: | :---: | :---: | :--- |
| **$< 1,000$** | 1–2 | $250\text{m} / 1000\text{m}$ | $256\text{Mi} / 512\text{Mi}$ | 1 Core, 1GB RAM (PostgreSQL 16) |
| **$1,000 - 10,000$** | 2–4 | $500\text{m} / 1500\text{m}$ | $512\text{Mi} / 1024\text{Mi}$ | 2 Cores, 2GB RAM |
| **$> 10,000$** | 4–10 (HPA) | $1000\text{m} / 2000\text{m}$ | $1024\text{Mi} / 2048\text{Mi}$ | 4 Cores, 8GB RAM + PgBouncer |

*Note: In multi-worker deployments, 1 worker with 4 threads per container is optimal on CPU nodes to eliminate OpenMP thread contention.*
