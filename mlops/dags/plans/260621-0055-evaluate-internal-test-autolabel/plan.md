# Plan: Evaluate trên test.parquet của version vừa train + auto-label

## Context

Hiện `evaluation.py:123-125` luôn dùng **external fixed dataset** `mlops/external-datasets/mt-test-data.parquet` để đo F1/precision/recall. Hệ quả:

1. Test set không phản ánh distribution data hiện tại của ClickHouse → drift detection thấy shift mà evaluate không thấy.
2. So sánh model qua version dùng cùng baseline, nhưng không validate model trên data tươi vừa train với.
3. test.parquet của version vừa train (đã được preprocessing.py sinh ra) bị bỏ không.

Cần: dùng `test.parquet` của version vừa train làm test set chính, external dataset chỉ làm **fallback** khi internal missing/S3 fail. Vì test.parquet không có `is_anomaly` label đáng tin (ClickHouse column `is_anomaly` thường rỗng/sai trong demo workload), cần auto-label dùng function user cung cấp (latency-based + error rule).

## Decisions (đã chốt qua AskUserQuestion)

| Quyết định | Giá trị |
|---|---|
| Normal data source | `train.parquet` cùng version (autoencoder's "normal" definition, tự động có sẵn) |
| Duration column | `duration_ns` (raw nanoseconds, preserved tại `preprocessing.py:117`) |
| Fallback trigger | Chỉ khi internal test.parquet missing/S3 read fail |
| DELIMITER | Import `from configs.constants import DELIMITER` (`model/configs/constants.py:2`, value `"//"`); GPU image đã COPY `model/configs/` |

## Adaptations từ function gốc

User cung cấp function operate trên **raw** CSV (service/operation strings, http_status 200/404/500). Test.parquet đã preprocess: service/operation là **int encoded**, http_status đã **grouped 1-5** via `map_status_group`. Adapt:

| Thay đổi | Original | Adapted |
|---|---|---|
| Input/output | CSV file paths | In-memory DataFrames |
| Latency column | `duration` (scaled in preprocess) | `duration_ns` (raw, preserved) |
| Error check 5xx | `(http_status // 100) == 5` | `http_status == 5` (vì đã grouped 1-5) |
| group_operation build | string concat of raw labels | string concat of encoded ints (vẫn unique per-version) |
| Logic chunk/threshold | giữ nguyên | giữ nguyên (chunk=20, stride=2, ratio≥0.5) |
| Force error | giữ nguyên (`span_status==2`) | giữ nguyên |

Hệ quả: labeler chỉ work trên data **post-preprocessing**. Group_operation key là string của int (vd `"5//12//3//5"`) — deterministic per-version, không cần ý nghĩa cross-version.

## Files modified/created

### Create — `mlops/tasks/auto_labeler.py` (new, ~60 LoC)

```python
"""
Auto-label test.parquet với `is_anomaly` dựa trên latency + error rule.
Adapted from user-provided function for post-preprocessing DataFrames.
"""
import logging
import numpy as np
import pandas as pd

from configs.constants import DELIMITER

log = logging.getLogger(__name__)


def _build_group_operation(df: pd.DataFrame) -> pd.Series:
    """Build group_operation key: service//operation//parent_op//http_status."""
    op = df["service"].astype(str) + DELIMITER + df["operation"].astype(str)
    span_to_op = dict(zip(df["spanId"], op))
    parent_op = df["parentSpanId"].map(span_to_op).fillna("None")
    return op + DELIMITER + parent_op + DELIMITER + df["http_status"].astype(str)


def _get_latency_upper_bound(normal_df: pd.DataFrame, duration_col: str) -> dict:
    """Per-group_operation upper bound = quantile(0.98) × 5."""
    return {
        op: group[duration_col].quantile(0.98) * 5
        for op, group in normal_df.groupby("group_operation")
    }


def auto_label_test_df(
    normal_df: pd.DataFrame,
    test_df: pd.DataFrame,
    duration_col: str = "duration_ns",
    chunk_size: int = 20,
    chunk_stride: int = 2,
    anomaly_ratio: float = 0.5,
) -> pd.DataFrame:
    """Label test_df with `is_anomaly` column (bool). Returns mutated copy.

    Rules (preserved from source function):
      1. is_span_anomaly = duration > 5x quantile(0.98) per group_operation
      2. is_anomaly = chunk of 20 spans (stride 2) has >=50% span_anomaly
      3. Force is_anomaly=True for span_status==2 OR http_status==5
    """
    normal_df = normal_df.copy()
    test_df = test_df.copy()

    normal_df["group_operation"] = _build_group_operation(normal_df)
    test_df["group_operation"] = _build_group_operation(test_df)

    upper_bounds = _get_latency_upper_bound(normal_df, duration_col)
    test_df["upper_bound"] = test_df["group_operation"].map(upper_bounds)

    test_df["is_span_anomaly"] = (
        (~test_df["upper_bound"].isna())
        & (test_df[duration_col] > test_df["upper_bound"])
    )

    test_df["is_anomaly"] = False
    for _, group in test_df.groupby("group_operation", sort=False):
        group = group.sort_values("startTime")
        for start_idx in range(0, len(group), chunk_stride):
            chunk = group.iloc[start_idx:start_idx + chunk_size]
            if chunk["is_span_anomaly"].mean() >= anomaly_ratio:
                test_df.loc[chunk.index, "is_anomaly"] = True

    test_df.loc[test_df["span_status"] == 2, "is_anomaly"] = True
    test_df.loc[test_df["http_status"] == 5, "is_anomaly"] = True

    n_anomaly = int(test_df["is_anomaly"].sum())
    log.info("Auto-labeled %d/%d spans as anomaly (%.2f%%)",
             n_anomaly, len(test_df), 100 * n_anomaly / max(len(test_df), 1))

    return test_df.drop(columns=["group_operation", "upper_bound", "is_span_anomaly"])
```

### Edit — `mlops/tasks/evaluation.py:123-162`

Trước (load external + preprocess):
```python
external_test_path = "mlops/external-datasets/mt-test-data.parquet"
test_df = read_parquet_from_s3(s3_path(external_test_path))
log.info("Using external test dataset: %s (%d rows)", external_test_path, len(test_df))

# Compute eval dataset stats for MLflow tracking
eval_dataset_stats = {
    "eval_data_path": s3_path(external_test_path),
    ...
    "eval_data_source": "external_fixed",
    ...
}
...
test_df = preprocess_test_df(test_df, encoders, scalers)
```

Sau:
```python
from botocore.exceptions import ClientError
from tasks.auto_labeler import auto_label_test_df

internal_test_key = f"mlops/training-data/{version_id}/test.parquet"
internal_train_key = f"mlops/training-data/{version_id}/train.parquet"
external_test_key = "mlops/external-datasets/mt-test-data.parquet"

use_internal = False
try:
    test_df = read_parquet_from_s3(s3_path(internal_test_key))
    train_df = read_parquet_from_s3(s3_path(internal_train_key))
    log.info("Loaded internal test set: %s (%d rows)", internal_test_key, len(test_df))
    log.info("Loaded internal train set (normal baseline): %d rows", len(train_df))
    test_df = auto_label_test_df(train_df, test_df)
    use_internal = True
    eval_dataset_stats = {
        "eval_data_path": s3_path(internal_test_key),
        "eval_data_rows": len(test_df),
        "eval_data_source": "version_test_parquet_autolabeled",
        "eval_data_version": version_id,
    }
except (ClientError, FileNotFoundError, KeyError) as e:
    log.warning("Internal test.parquet not available (%s) — falling back to external", e)
    test_df = read_parquet_from_s3(s3_path(external_test_key))
    log.info("Loaded external fallback: %s (%d rows)", external_test_key, len(test_df))
    eval_dataset_stats = {
        "eval_data_path": s3_path(external_test_key),
        "eval_data_rows": len(test_df),
        "eval_data_source": "external_fixed_fallback",
        "eval_data_version": "mt-test-data-v1",
    }

if "app_id" in test_df.columns:
    app_counts = test_df["app_id"].value_counts().head(10).to_dict()
    eval_dataset_stats["app_distribution"] = {str(k): int(v) for k, v in app_counts.items()}
    eval_dataset_stats["num_apps"] = int(test_df["app_id"].nunique())

for col in ["startTime", "timestamp", "start_time"]:
    if col in test_df.columns:
        try:
            eval_dataset_stats["data_start_time"] = str(pd.to_datetime(test_df[col].min()))
            eval_dataset_stats["data_end_time"] = str(pd.to_datetime(test_df[col].max()))
        except Exception:
            pass
        break

log.info("Eval dataset stats: %d rows, source=%s",
         eval_dataset_stats["eval_data_rows"], eval_dataset_stats["eval_data_source"])

# Rename map only needed for external (internal already has canonical names from preprocessing)
if not use_internal:
    rename_map = {
        "trace_id": "traceId", "span_id": "spanId", "parent_span_id": "parentSpanId",
    }
    for old, new in rename_map.items():
        if old in test_df.columns and new not in test_df.columns:
            test_df[new] = test_df[old]
    if "duration_ns" in test_df.columns and "duration" not in test_df.columns:
        test_df["duration"] = test_df["duration_ns"]
    # External needs preprocessing (encode, scale)
    test_df = preprocess_test_df(test_df, encoders, scalers)
# else: internal test.parquet đã preprocessed by preprocessing.py — skip preprocess_test_df
```

**Lý do skip `preprocess_test_df` cho internal**: test.parquet đã encoded + scaled (`preprocessing.py:120-126`). Chạy lại sẽ double-encode (label encoder áp lên int → tất cả thành `unknown_index`).

## Build + deploy

### Step 1 — Rebuild GPU image + push lên ECR

GPU image baked `mlops/tasks/` (Dockerfile.mlops-gpu:9) và `model/configs/` (line 7). Image này pull bởi Batch job `mlops-evaluate-job` từ ECR us-east-1.

```bash
cd D:/KLTN/MyRCA

# ECR login
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com

# Build + tag
docker build -t mlops-pipeline-gpu:latest -f mlops/Dockerfile.mlops-gpu .
docker tag mlops-pipeline-gpu:latest \
  <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/mlops-pipeline-gpu:latest

# Push
docker push <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/mlops-pipeline-gpu:latest
```

Batch job definition `mlops-evaluate-job` dùng `:latest` → next job auto-pulls.

### Step 2 — Trigger pipeline

```bash
MSYS_NO_PATHCONV=1 kubectl exec -n airflow -c scheduler airflow-scheduler-... -- \
  airflow dags trigger training_pipeline --conf '{"FORCE_DRIFT": "true"}'
```

`FORCE_DRIFT=true` để ép retrain → đảm bảo evaluate chạy với code mới (không bị skip do no drift).

## Verification

### Check 1 — Auto-label log từ Batch CloudWatch

Vào AWS CloudWatch log group `/aws/batch/job` → stream của job `mlops-evaluate-...{version_id}`.

Expect log:
- `Loaded internal test set: mlops/training-data/{version_id}/test.parquet (NNNN rows)`
- `Loaded internal train set (normal baseline): MMMM rows`
- `Auto-labeled X/N spans as anomaly (YY%)`

### Check 2 — MLflow eval_data_source

UI MLflow → run `eval-{version_id}` (nested dưới parent pipeline run):
- Tag `eval_data_source` = `version_test_parquet_autolabeled` (không phải `external_fixed_fallback`).
- Param `eval_data_s3_path` = `s3://kltn-anomaly-dateset-1/mlops/training-data/{version_id}/test.parquet`.

### Check 3 — Classification metrics có giá trị

Trên MLflow metrics tab:
- `f1_score`, `precision`, `recall`, `best_threshold` > 0 (trước đây có thể bằng 0 hoặc NaN nếu external dataset không có `is_anomaly`).
- `test_samples` > 0.

### Check 4 — S3 evaluate_output.json

```bash
aws s3 cp s3://kltn-anomaly-dateset-1/mlops/batch-outputs/{version_id}/evaluate_output.json - | \
  jq '.f1_score, .precision, .recall, .p99_threshold'
```

### Check 5 — Fallback path (negative test, optional)

Tạm xóa quyền S3 read của Batch role tới `training-data/` → trigger lại → log expect `Internal test.parquet not available — falling back to external` và `eval_data_source=external_fixed_fallback`.

## Risks

| Risk | Mitigation |
|---|---|
| `preprocess_test_df` skip cho internal → cột thiếu nếu preprocessing.py thay đổi schema | Document rõ; chỉ skip nếu use_internal=True |
| Auto-label F1 inflate (toàn lệch theo rule `span_status==2`) | Log tỉ lệ anomaly%; nếu >20% → cờ đỏ data quality |
| Train.parquet load fail trong fallback flow | Cả 2 file (train + test) phải có; nếu chỉ thiếu train → fallback external (cùng except branch) |
| ECR auth fail | Confirm `aws sts get-caller-identity` trước build |
| Group_operation từ encoded int trong test khác trong train | Cùng version → cùng encoder → cùng int → group key match |

## Unresolved

- Có cần expose `chunk_size`/`anomaly_ratio` qua env var không? Hiện hardcode trong function (KISS, có thể đổi sau).
- Tỉ lệ anomaly% từ auto-label có khớp với `is_anomaly` từ ClickHouse (nếu có) không? Đáng so sánh trong report đầu tiên để validate logic.
- Cần update `MyRCA/mlops/PIPELINE.md` section "Step 4: Evaluation" reflect source mới sau khi verify thành công.
