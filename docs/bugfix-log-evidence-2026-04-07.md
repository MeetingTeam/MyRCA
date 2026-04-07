# Bugfix: Empty Log Evidence in RCA Dashboard (2026-04-07)

## Overview

The RCA dashboard's incident detail view showed empty log evidence (`"log_evidence": {"service-name": []}`) for all incidents despite Loki having ERROR/WARN logs available for the services.

## Root Cause

The `trace-rca-service` queried Loki with the **exact 1-minute anomaly window** (e.g., `03:59:51 → 04:00:51`). ERROR/WARN logs don't always fire at the exact same second as the anomaly — they may occur seconds or minutes before/after. A 1-minute window is too narrow to capture relevant log evidence.

### Evidence

| Query Window | Result |
|---|---|
| Exact incident window (1 min) | 0 log entries |
| ±5 min around incident | 3+ entries (WARN, ERROR) |
| Last 10 min (broad) | 15 streams with WARN/ERROR |

Loki data was confirmed available for all services (`chat-service`, `team-service`, `meeting-service`, `websocket-service`) with 24h retention. The issue was purely the query time range.

## Affected Components

| Component | File | Role |
|---|---|---|
| `trace-rca-service` | `trace_rca_algo/trace_rca_service/main.py` | Queries Loki for log evidence during Stage 2 RCA |
| `LokiLogExtractor` | `trace_rca_algo/trace_rca_service/log_extractor.py` | Executes LogQL queries against Loki HTTP API |
| `rca-dashboard` | `trace_rca_algo/rca-dashboard/src/components/log-evidence.jsx` | Renders log evidence (component was correct, no changes needed) |

## Fix

**File:** `trace_rca_algo/trace_rca_service/main.py` (Stage 2 log query, ~line 258)

**Before:**
```python
top_k_services = [svc for svc, _ in ranking[:5]]
logs = log_extractor.query_logs_for_services(
    top_k_services, start_dt, end_dt
)
```

**After:**
```python
top_k_services = [svc for svc, _ in ranking[:5]]
from datetime import timedelta
log_start = start_dt - timedelta(minutes=5)
log_end = end_dt + timedelta(minutes=5)
logs = log_extractor.query_logs_for_services(
    top_k_services, log_start, log_end
)
```

The log query window is widened by ±5 minutes around the anomaly detection window. This captures logs that are temporally related to the anomaly but don't fall within the exact 1-minute detection window.

## How the Log Evidence Pipeline Works

```
system-failure-checker (1-min interval)
  │
  ├─ Queries S3 parquet for anomalous spans in [T, T+1min]
  ├─ If anomalies found → publishes RCA task to Kafka topic `rca-task-data`
  │
  ▼
trace-rca-service (Kafka consumer)
  │
  ├─ Stage 1: Reads spans from S3, builds trace DAGs, ranks root causes
  │
  ├─ Stage 2: For top-5 ranked services:
  │     ├─ Queries Loki: {service_name="X"} | severity_text =~ `ERROR|WARN|FATAL`
  │     │   Time range: [start_dt - 5min, end_dt + 5min]  ← THE FIX
  │     ├─ Passes logs + ranking to LLM (Claude) for analysis
  │     └─ LLM produces root cause classification, propagation chain
  │
  ├─ Sends Discord notification
  └─ Saves incident JSON to S3 (rca-results/{incident_id}.json)
        └─ Includes `log_evidence` field: {service: [{timestamp, message, level}]}
```

## Debugging Checklist (if log evidence is empty again)

1. **Verify Loki is running:**
   ```bash
   kubectl exec deployment/trace-rca-service -n rca -- \
     python3 -c "import requests; print(requests.get('http://loki.loki.svc.cluster.local:3100/ready').text)"
   ```

2. **Check Loki has data for the service:**
   ```bash
   kubectl exec deployment/trace-rca-service -n rca -- \
     python3 -c "import requests; r=requests.get('http://loki.loki.svc.cluster.local:3100/loki/api/v1/label/service_name/values'); print(r.json().get('data',[]))"
   ```

3. **Test the LogQL query manually:**
   ```bash
   kubectl exec deployment/trace-rca-service -n rca -- python3 -c "
   import requests, time
   loki = 'http://loki.loki.svc.cluster.local:3100'
   now = int(time.time() * 1e9)
   start = now - int(10 * 60 * 1e9)
   q = '{service_name=\"team-service\"} | severity_text =~ \`ERROR|WARN|FATAL\`'
   r = requests.get(f'{loki}/loki/api/v1/query_range', params={'query': q, 'start': start, 'end': now, 'limit': 5})
   results = r.json().get('data',{}).get('result',[])
   print(f'Found {sum(len(s.get(\"values\",[])) for s in results)} entries')
   "
   ```

4. **Check trace-rca-service logs for Loki errors:**
   ```bash
   kubectl logs deployment/trace-rca-service -n rca | grep -i "loki\|log.*fail"
   ```

5. **Verify the ±5min window is in the deployed code:**
   ```bash
   kubectl exec deployment/trace-rca-service -n rca -- \
     grep -A2 "timedelta" /app/main.py
   ```

## Deployment

```bash
cd trace_rca_algo/trace_rca_service
docker build -t asdads6495/trace_rca_service:dev .
docker push asdads6495/trace_rca_service:dev
kubectl rollout restart deployment/trace-rca-service -n rca
```

## Related Issues

- [bugfix-rca-services-2026-04-06.md](./bugfix-rca-services-2026-04-06.md) — S3 credentials, UTF-8 race condition, Kafka reconnect issues
- The UTF-8/S3 write fix (same session) changed `anomaly-detection-service` to use DuckDB `APPEND` mode with fresh connections per write, producing unique parquet files per flush
