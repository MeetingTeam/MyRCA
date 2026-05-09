# MLOps Training Pipeline Troubleshooting Guide

This document covers common issues, bugs, and fixes for the Airflow `training_pipeline` DAG that orchestrates model training via AWS Batch.

## Pipeline Architecture

```
[Airflow Scheduler] → [KubernetesPodOperator: preprocess] 
                    → [BatchOperator: train] (AWS Batch GPU)
                    → [BatchOperator: evaluate] (AWS Batch GPU)
                    → [KubernetesPodOperator: register/deploy]
```

## Bug Fixes (Session 2026-05-07/08)

### 1. AWS Batch Job Not Starting (RUNNABLE stuck)

**Symptom:** Jobs remained in `RUNNABLE` status with reason "CE(s) associated with the job queue are disabled."

**Root Cause:** Compute environments were disabled and job queue was misconfigured.

**Fix:**
```bash
# Enable Spot compute environment
aws batch update-compute-environment \
  --compute-environment gpu-spot-ce \
  --state ENABLED \
  --compute-resources "maxvCpus=4,instanceTypes=g4dn.xlarge" \
  --region us-east-1

# Enable On-Demand compute environment (fallback)
aws batch update-compute-environment \
  --compute-environment gpu-ondemand-ce \
  --state ENABLED \
  --region us-east-1

# Configure job queue with Spot → On-Demand fallback
aws batch update-job-queue \
  --job-queue gpu-spot-queue \
  --compute-environment-order \
    "order=1,computeEnvironment=gpu-spot-ce" \
    "order=2,computeEnvironment=gpu-ondemand-ce" \
  --region us-east-1
```

**Key Config (respecting 4 vCPU quota):**
- `gpu-spot-ce`: maxvCpus=4, g4dn.xlarge only
- `gpu-ondemand-ce`: maxvCpus=4, g4dn.xlarge only
- Job queue priority: Spot first, On-Demand fallback

---

### 2. Preprocessing DuckDB Hive Partition Error

**Symptom:** `BinderException: Hive partition mismatch`

**Root Cause:** S3 parquet files didn't follow strict Hive partitioning.

**Fix** (`mlops/tasks/preprocessing.py`):
```python
# Before (incorrect)
df = con.execute(f"""
    SELECT * FROM read_parquet('s3://{S3_BUCKET}/anomalies/data.parquet/**/*.parquet')
    WHERE epoch(startTime) >= {cutoff_epoch}
""").fetchdf()

# After (fixed)
df = con.execute(f"""
    SELECT * FROM read_parquet(
        's3://{S3_BUCKET}/anomalies/data.parquet/**/*.parquet',
        hive_partitioning=0, union_by_name=1
    )
    WHERE epoch(timestamp) >= {cutoff_epoch}
""").fetchdf()
```

**Changes:**
- `hive_partitioning=0` - Disable strict Hive partitioning
- `union_by_name=1` - Allow schema variations across files
- `startTime` → `timestamp` - Use correct column name

---

### 3. Evaluation ValueError: Too Many Values to Unpack

**Symptom:** `ValueError: too many values to unpack (expected 7)`

**Root Cause:** `build_sequences()` function was updated to return 8 values (added `apps` for app_id support), but `evaluation.py` only unpacked 7.

**Fix** (`mlops/tasks/evaluation.py`):
```python
# Before (incorrect - 7 values)
services, parent_services, operations, parent_ops, statuses, metrics_x, row_idx = build_sequences(...)

# After (fixed - 8 values)
apps, services, parent_services, operations, parent_ops, statuses, metrics_x, row_idx = build_sequences(...)

# Also update model initialization to include app_vocab
model = TransformerAutoencoder(
    service_vocab=encoders["service"].get_unknown_index() + 1,
    op_vocab=encoders["operation"].get_unknown_index() + 1,
    status_vocab=6,
    app_vocab=encoders["app_id"].get_unknown_index() + 1,  # Added
    metrics_feature_num=len(metric_cols),
).to(device)

# Update TensorDataset to include apps tensor
dataset = TensorDataset(
    torch.LongTensor(apps),  # Added
    torch.LongTensor(services),
    ...
)

# Update model forward call
recon = model(s, ps, op, pop, h, a, x)  # Added 'a' for apps
```

---

### 4. Missing Classification Metrics (F1, Precision, Recall)

**Symptom:** Evaluation only computed `p99_threshold` and `mean_score`, no classification metrics.

**Root Cause:** Original evaluation didn't compute metrics against ground truth labels.

**Fix** (`mlops/tasks/evaluation.py`):
```python
from sklearn.metrics import precision_recall_curve

def compute_classification_metrics(scored_df: pd.DataFrame) -> dict:
    """Compute F1, precision, recall using is_anomaly as ground truth."""
    if "is_anomaly" not in scored_df.columns:
        log.warning("No 'is_anomaly' column found, skipping classification metrics")
        return {}

    y_true = scored_df["is_anomaly"].astype(bool).values
    y_score = scored_df["anomaly_score"].values

    prec, rec, thresholds = precision_recall_curve(y_true, y_score)
    f1 = 2 * (prec * rec) / (prec + rec + 1e-9)
    best_idx = np.argmax(f1)

    best_threshold = float(thresholds[best_idx]) if best_idx < len(thresholds) else float(thresholds[-1])
    
    log.info("Classification metrics: threshold=%.6f, F1=%.4f, precision=%.4f, recall=%.4f",
             best_threshold, f1[best_idx], prec[best_idx], rec[best_idx])

    return {
        "best_threshold": best_threshold,
        "f1_score": float(f1[best_idx]),
        "precision": float(prec[best_idx]),
        "recall": float(rec[best_idx]),
    }
```

**Requires:** Test dataset must have `is_anomaly` column as ground truth labels.

---

### 5. Missing Common Module in Docker Image

**Symptom:** `ModuleNotFoundError: No module named 'common'`

**Root Cause:** Dockerfile didn't copy the common module.

**Fix** (`mlops/Dockerfile.mlops-light`):
```dockerfile
# Before
COPY mlops/tasks/ tasks/

# After
COPY mlops/tasks/ tasks/
COPY model/common/ common/
```

---

## External Dataset Evaluation

To evaluate on a specific external dataset instead of auto-generated test.parquet:

### Step 1: Prepare Dataset
```python
import pandas as pd
df = pd.read_csv("mt-test-data.csv")
df.insert(0, "app_id", "k8s-repo-application")  # Add app_id column
df.to_parquet("mt-test-data.parquet", index=False)
```

### Step 2: Upload to S3
```bash
aws s3 cp mt-test-data.parquet \
  s3://kltn-anomaly-dateset-1/mlops/external-datasets/mt-test-data.parquet \
  --region ap-southeast-1
```

### Step 3: Modify Evaluation (hardcoded path)
```python
# In mlops/tasks/evaluation.py line 77
external_test_path = "mlops/external-datasets/mt-test-data.parquet"
test_df = read_parquet_from_s3(s3_path(external_test_path))
```

### Step 4: Rebuild & Push Docker Image
```bash
docker build -f mlops/Dockerfile.mlops-gpu -t mlops-pipeline-gpu:latest .
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 791992545850.dkr.ecr.us-east-1.amazonaws.com
docker tag mlops-pipeline-gpu:latest 791992545850.dkr.ecr.us-east-1.amazonaws.com/mlops-pipeline-gpu:latest
docker push 791992545850.dkr.ecr.us-east-1.amazonaws.com/mlops-pipeline-gpu:latest
```

---

## Required Dataset Columns

| Column | Type | Required | Notes |
|--------|------|----------|-------|
| `app_id` | str | Optional | Defaults to "UNKNOWN" if missing |
| `service` | str | Yes | Service name |
| `operation` | str | Yes | Operation/endpoint name |
| `duration` | numeric | Yes | Span duration (ns or ms) |
| `http_status` | int | Yes | HTTP status code |
| `span_status` | int | Yes | OTel span status (0=OK, 2=ERROR) |
| `traceId` | str | Yes | Trace ID |
| `spanId` | str | Yes | Span ID |
| `parentSpanId` | str | Yes | Parent span ID |
| `startTime` | numeric | Yes | Start timestamp |
| `is_anomaly` | bool | Optional | Ground truth for F1/precision/recall |

---

## Monitoring AWS Batch Jobs

### Check Job Status
```bash
aws batch describe-jobs --jobs <job-id> --region us-east-1 \
  --query 'jobs[0].{name:jobName,status:status,reason:statusReason}'
```

### View CloudWatch Logs
```bash
# Get log stream name
aws batch describe-jobs --jobs <job-id> --region us-east-1 \
  --query 'jobs[0].container.logStreamName'

# Get logs
export MSYS_NO_PATHCONV=1  # Windows Git Bash only
aws logs get-log-events \
  --log-group-name '/aws/batch/mlops-training' \
  --log-stream-name '<log-stream-name>' \
  --region us-east-1
```

### Check Compute Environment
```bash
aws batch describe-compute-environments \
  --compute-environments gpu-spot-ce gpu-ondemand-ce \
  --region us-east-1 \
  --query 'computeEnvironments[*].{name:computeEnvironmentName,state:state,status:status}'
```

---

## Files Reference

| File | Purpose |
|------|---------|
| `mlops/tasks/preprocessing.py` | Data preprocessing (DuckDB S3 queries) |
| `mlops/tasks/training.py` | Model training on AWS Batch GPU |
| `mlops/tasks/evaluation.py` | Model evaluation + metrics |
| `mlops/Dockerfile.mlops-gpu` | GPU container for Batch jobs |
| `mlops/Dockerfile.mlops-light` | CPU container for K8s tasks |
| `model/transformer_ae/evaluate.py` | build_sequences, preprocess_test_df |
| `opensource/airflow/values.dev.yaml` | Airflow Helm chart values |
