# MLOps Pipeline — Cách hoạt động

## Tổng quan

MLOps pipeline tự động hóa quy trình **phát hiện drift → tiền xử lý → huấn luyện → đánh giá → triển khai** cho mô hình Transformer Autoencoder phục vụ phát hiện bất thường (anomaly detection) trên distributed traces.

Pipeline được điều phối bởi **Apache Airflow** với **KubernetesExecutor** — mỗi bước chạy trong một Pod riêng biệt trên Kubernetes sử dụng chung image `asdads6495/mlops-pipeline:dev`.

## Kiến trúc

```
┌─────────────────────────────────────────────────────────────────┐
│                    DAG 1: training_pipeline                      │
│                                                                  │
│  compact ──► drift_detection ──► check_drift ──► preprocess     │
│                                      │              │            │
│                                  (no drift)         ▼            │
│                                    STOP          train           │
│                                                    │            │
│                                                    ▼            │
│                                                 evaluate        │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│              DAG 2: model_deploy (manual trigger)               │
│                                                                  │
│          Input: version_id ──► deploy_model                     │
└─────────────────────────────────────────────────────────────────┘
```

## Luồng dữ liệu trên S3

```
s3://kltn-anomaly-dateset-1/
├── anomalies/data.parquet/          ← Dữ liệu inference (input cho pipeline)
│   └── date_part=YYYY-MM-DD/
├── mlops/
│   ├── drift-reports/{version_id}/  ← Báo cáo drift (JSON)
│   ├── training-data/{version_id}/  ← Dữ liệu đã xử lý
│   │   ├── train.parquet
│   │   ├── test.parquet
│   │   ├── encoders.pkl
│   │   └── scalers.pkl
│   └── models/{version_id}/         ← Model artifacts
│       ├── model.pth
│       ├── encoders.pkl
│       ├── scalers.pkl
│       └── metadata.json
```

Version ID có format: `v{YYYYMMDD-HHMMSS}` (ví dụ: `v20240315-120000`).

## Chi tiết từng bước

### Step 0: Compaction (`tasks/compaction.py`)

**Mục đích:** Gộp các file Parquet nhỏ trong mỗi date partition thành 1 file duy nhất, giảm số lượng file mà DuckDB phải mở khi đọc.

**Hoạt động:**
1. Quét tất cả date partition trong `anomalies/data.parquet/`
2. Với mỗi partition có > 1 file: đọc tất cả → ghi lại thành 1 file `compacted.parquet`
3. Xóa các file cũ (DuckDB hoặc fallback sang boto3)

### Step 1: Drift Detection (`tasks/drift_detection.py`)

**Mục đích:** So sánh phân phối dữ liệu inference hiện tại với dữ liệu training trước đó để quyết định có cần retrain hay không.

**Thuật toán:**
- **PSI (Population Stability Index)** trên `duration_ns`: chia reference distribution thành 10 bin theo quantile, tính PSI giữa reference và current. Ngưỡng mặc định: `0.2`
- **New API detection**: phát hiện các cặp `(service, operation)` mới chưa xuất hiện trong dữ liệu training trước

**Drift được kích hoạt khi:**
- Lần chạy đầu tiên (không có dữ liệu training trước)
- PSI > 0.2 (phân phối duration thay đổi đáng kể)
- Xuất hiện API endpoint mới

**Output:** Drift report (JSON lên S3) + XCom `{version_id, drift_detected}` cho Airflow.

**Short-circuit:** Nếu `drift_detected = False`, `ShortCircuitOperator` sẽ skip toàn bộ các bước sau.

### Step 2: Preprocessing (`tasks/preprocessing.py`)

**Mục đích:** Encode và scale dữ liệu thô thành format phù hợp cho training.

**Hoạt động:**
1. Đọc dữ liệu span từ `anomalies/data.parquet/`
2. Map `http_status` thành status group (1xx→1, 2xx→2, ..., 5xx→5)
3. **Label encode** các cột `service`, `operation` bằng `SafeLabelEncoder`
4. **StandardScaler** trên cột `duration`
5. Tính `parent_op` và `parent_service` từ `parentSpanId`
6. Shuffle và split 70/30 → `train.parquet` + `test.parquet`
7. Upload encoders/scalers (pickle) lên S3

### Step 3: Training (`tasks/training.py`)

**Mục đích:** Huấn luyện Transformer Autoencoder trên dữ liệu đã tiền xử lý.

**Cấu hình:**
| Tham số | Giá trị |
|---------|---------|
| Sequence length | 20 spans |
| Stride | 2 |
| Epochs | 50 |
| Batch size | 64 |
| Learning rate | 5e-4 |
| d_model | 64 |
| Latent dim | 32 |

**Hoạt động:**
1. Đọc `train.parquet` và encoders từ S3
2. Nhóm span theo `(service, parent_service, operation, parent_op, http_status)` → tạo sequence dài 20 với stride 2
3. Train Transformer Autoencoder (MSE loss, Adam optimizer, ReduceLROnPlateau scheduler, gradient clipping 1.0)
4. Upload `model.pth`, `encoders.pkl`, `scalers.pkl` lên `mlops/models/{version_id}/`
5. Log tất cả metrics và register model vào **MLflow** (`transformer-ae`)

**Resource:** CPU 500m–2, Memory 1Gi–4Gi

### Step 4: Evaluation (`tasks/evaluation.py`)

**Mục đích:** Đánh giá model trên test set và tính ngưỡng anomaly (p99 threshold).

**Hoạt động:**
1. Download model artifacts + test data từ S3
2. Build sequence từ test data → inference với model
3. Tính anomaly score = reconstruction error (MSE)
4. Boost score +1000 cho span có `span_status=2` (error) hoặc `http_status=5` (5xx)
5. Tính **p99 threshold** từ các span bình thường (non-error)
6. Log metrics lên MLflow, save `metadata.json` lên S3

**`metadata.json` chứa:** version, threshold, model_s3_path, mean_score, test_samples — được dùng bởi bước deploy.

### Step 5: Model Deploy (`tasks/model_deploy.py`) — DAG 2

**Mục đích:** Triển khai model version cụ thể lên Anomaly Detection Service đang chạy.

**Hoạt động:**
1. Download `metadata.json` từ `mlops/models/{version_id}/`
2. Patch ConfigMap `anomaly-detection-service-config` trong namespace `anomaly-detection`:
   - `ANOMALY_THRESHOLD` = p99 threshold
   - `MODEL_S3_PATH` = đường dẫn S3 tới model
   - `MODEL_VERSION` = version_id
3. Trigger **rolling restart** deployment bằng cách patch annotation `restartedAt`
4. (Best-effort) Transition model version sang stage `Production` trong MLflow

**Yêu cầu:** Pod chạy với `airflow-deploy-sa` ServiceAccount có quyền patch ConfigMap và Deployment trong namespace `anomaly-detection`.

## Cách trigger pipeline

### Training Pipeline (DAG 1)
```bash
# Qua Airflow UI
# Truy cập http://<airflow>:30380 → DAGs → training_pipeline → Trigger

# Qua CLI
airflow dags trigger training_pipeline
```
Schedule: Manual trigger (`schedule_interval=None`), có thể đổi sang `@weekly`.

### Model Deploy (DAG 2)
```bash
# Qua Airflow UI với parameter version_id
# DAGs → model_deploy → Trigger w/ config → {"version_id": "v20240315-120000"}

# Qua CLI
airflow dags trigger model_deploy --conf '{"version_id": "v20240315-120000"}'
```

## Công nghệ sử dụng

| Thành phần | Công nghệ |
|-----------|-----------|
| Orchestrator | Apache Airflow (Helm chart v1.15.0, KubernetesExecutor) |
| Model Registry | MLflow v2.12.2 |
| Storage | AWS S3 (DuckDB httpfs + boto3) |
| Training Framework | PyTorch |
| Data Processing | pandas, scikit-learn, DuckDB |
| Container Runtime | Kubernetes Pods (via KubernetesPodOperator) |

## Docker Image

```dockerfile
# Build từ root repo
docker build -t asdads6495/mlops-pipeline:dev -f mlops/Dockerfile.mlops .
```

Image chứa:
- `tasks/` — code các bước pipeline
- `common/` — shared utilities (SafeLabelEncoder, util)
- `transformer_ae/` — model definition + evaluate logic
- `configs/` — cấu hình model
