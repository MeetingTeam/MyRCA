# MLOps Training Pipeline - Bugfix Summary (2026-03-28)

The training pipeline (`training_pipeline` DAG) was failing at multiple stages. Six bugs were identified and fixed through iterative debugging directly on the Kubernetes cluster.

## Pipeline Flow

```
compact >> drift_detection >> check_drift >> preprocess >> train >> evaluate
```

## Fixes

### 1. S3 Bucket Name Mismatch

- **Root Cause:** `s3_utils.py` (used by DuckDB operations) defaulted to `kltn-anomaly-dateset-1`, but four task files using boto3 directly defaulted to `kltn-anomaly-dateset` (missing `-1`). This caused boto3 upload/download operations to target a nonexistent bucket.
- **Fix:** Corrected all four boto3 defaults to `kltn-anomaly-dateset-1`.
- **Files:** `mlops/tasks/training.py`, `mlops/tasks/evaluation.py`, `mlops/tasks/preprocessing.py`, `mlops/tasks/model_deploy.py`

### 2. Missing `__init__.py` Files

- **Root Cause:** `model/common/` and `model/transformer_ae/` were copied into the Docker image but lacked `__init__.py`, making them unimportable as Python packages. Any task importing from these modules would fail with `ImportError`.
- **Fix:** Added empty `__init__.py` files to both directories.
- **Files:** `model/common/__init__.py`, `model/transformer_ae/__init__.py`

### 3. Stale Docker Image (No `imagePullPolicy`)

- **Root Cause:** KubernetesPodOperator tasks did not set `imagePullPolicy: Always`. Kubernetes nodes cached the old `:dev` image and never pulled the updated version, so code fixes were not reflected in running pods.
- **Fix:** Added `image_pull_policy="Always"` to all six KubernetesPodOperator definitions across both DAGs.
- **Files:** `mlops/dags/training_pipeline_dag.py`, `mlops/dags/model_deploy_dag.py`

### 4. Compaction Timeout (2312-File Partition)

- **Root Cause:** The compaction step built an inline SQL string with 2312 individual S3 file paths for DuckDB `read_parquet()`. DuckDB httpfs opening each file individually was extremely slow, causing the pod to hang until the 600s `startup_timeout_seconds` was exceeded.
- **Fix:** Replaced inline file list with DuckDB S3 glob pattern (`*.parquet`), and increased compact timeout from 600s to 1800s with explicit resource limits (2Gi memory).
- **Files:** `mlops/tasks/compaction.py`, `mlops/dags/training_pipeline_dag.py`

### 5. Missing `startTime` Column

- **Root Cause:** The S3 parquet data uses `timestamp` as the column name, but `preprocessing.py` only mapped `start_time` to `startTime`. The column rename map was incomplete, causing a `Missing columns: ['startTime']` error.
- **Fix:** Added `"timestamp": "startTime"` to the rename map.
- **Files:** `mlops/tasks/preprocessing.py`

### 6. MLflow SDK/Server Version Mismatch

- **Root Cause:** The `mlflow.pytorch.log_model()` call in the training step uses an API endpoint (`/api/2.0/mlflow/logged-models`) not supported by the deployed MLflow server version. Training completed successfully (model saved to S3), but the MLflow registration at the end crashed the task.
- **Fix:** Wrapped the `mlflow.pytorch.log_model()` call in a try/except block, matching the best-effort pattern already used in `model_deploy.py`.
- **Files:** `mlops/tasks/training.py`

## Result

All six pipeline stages now complete successfully:

| Task | Duration |
|------|----------|
| compact | ~12s |
| drift_detection | ~20s |
| check_drift | <1s |
| preprocess | ~18s |
| train | ~91s |
| evaluate | ~24s |

## Lessons Learned

- Always set `imagePullPolicy: Always` when using mutable tags like `:dev` in Kubernetes.
- Hardcoded defaults across multiple files drift apart. Consider a single config source (env var with one fallback location).
- DuckDB httpfs glob is significantly faster than inline file lists for large S3 partitions.
- MLflow SDK calls to the server should be best-effort when the server version is not tightly controlled.
