# MLOps Pipeline — Cách hoạt động

## Tổng quan

MLOps pipeline tự động hóa **phát hiện drift → tiền xử lý → huấn luyện → đánh giá → so sánh model → triển khai** cho Transformer Autoencoder dùng cho anomaly detection trên distributed traces, kèm hai DAG phụ build/deploy RCA Knowledge Base.

Pipeline điều phối bằng **Apache Airflow (Helm 1.15.0, KubernetesExecutor)**, kiến trúc **hybrid**:
- Task nhẹ (drift, preprocess, model_comparison, deploy) chạy bằng `KubernetesPodOperator` với image `asdads6495/mlops-pipeline-light:dev`.
- Task nặng GPU (train, evaluate) chạy trên **AWS Batch Spot** (`us-east-1`, queue `gpu-spot-queue`) với image `mlops-pipeline-gpu` lưu trên ECR.

Data source chính là **ClickHouse** (`clickhouse-cluster-client.clickhouse.svc.cluster.local:9000`), không còn dùng DuckDB đọc S3. ClickHouse tiered storage tự xử lý lifecycle (EBS hot → S3 cold), nên task `compact` cũ đã bị bỏ.

## Kiến trúc

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  DAG 1: training_pipeline                                                    │
│                                                                              │
│  drift_detection ─► check_drift ─┬─► no_retrain (STOP)                       │
│       (K8s)                       │                                          │
│                                   └─► trigger_retrain ─► preprocess          │
│                                                            (K8s)             │
│                                                              │               │
│                                                              ▼               │
│                                                            train  ──► Batch  │
│                                                              │               │
│                                                              ▼               │
│                                                     fetch_train_output (K8s) │
│                                                              │               │
│                                                              ▼               │
│                                                          evaluate ──► Batch  │
│                                                              │               │
│                                                              ▼               │
│                                                   fetch_evaluate_output (K8s)│
│                                                              │               │
│                                                              ▼               │
│                                                     model_comparison (K8s)   │
│                                                     → khuyến nghị admin      │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│  DAG 2: model_deploy (manual trigger, param: version_id)                     │
│     deploy_model (K8s) → patch ConfigMap + rolling restart                   │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│  DAG 3: kb_building_dag (@weekly)         │ DAG 4: kb_deploy_dag (manual)     │
│     hungtran679/kb_builder → MLflow       │     hungtran679/kb_deploy:latest  │
│     model `rca-knowledge-base`            │     → cập nhật trace-rca-service  │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Layout S3

Bucket: `kltn-anomaly-dateset-1` (region `ap-southeast-1`).

```
s3://kltn-anomaly-dateset-1/mlops/
├── drift-reports/{version_id}/
│   ├── drift_report.json                 ← per_app_results có cả quality_summary
│   └── {app_id}/drift_report.html        ← HTML Evidently per-app
├── quality-reports/{version_id}/
│   └── {app_id}/quality_report.html      ← Data quality (missing, dup, cardinality)
├── training-data/{version_id}/
│   ├── train.parquet                     ← có cột app_id
│   ├── test.parquet
│   ├── encoders.pkl                      ← service, operation, app_id
│   └── scalers.pkl
├── models/{version_id}/
│   ├── model.pth
│   ├── encoders.pkl
│   ├── scalers.pkl
│   └── metadata.json                     ← threshold, mean_score, model_s3_path…
├── batch-outputs/{version_id}/           ← XCom thay thế cho Batch jobs
│   ├── train_output.json
│   └── evaluate_output.json
└── model-comparisons/{version_id}/
    └── comparison.json                   ← gate results + recommendation
```

`version_id` format: `v{YYYYMMDD-HHMMSS}` (UTC). Sinh tại bước `drift_detection`.

## Chi tiết từng bước

### Step 1: Drift Detection (`tasks/drift_detection.py`)

**Mục đích:** Quyết định có cần retrain hay không, theo từng app (`app_id`).

**Data source:** ClickHouse, đọc cửa sổ `DRIFT_WINDOW_MINUTES` phút gần nhất (fallback 60 phút nếu rỗng).

**Multi-app:** chỉ xử lý các app trong `KNOWN_APPS = ["microservices-demo", "k8s-repo-application"]`, group dữ liệu hiện tại theo `app_id` và so từng app với baseline tương ứng.

**Baseline lookup (theo thứ tự):**
1. MLflow alias `champion` trên model `transformer-ae` (khuyến nghị, MLflow ≥ 2.9)
2. MLflow alias `production`
3. MLflow stage `Production` (deprecated, backwards-compat)
4. Fallback: version mới nhất trong `mlops/training-data/`

**Thuật toán:**
- **Evidently** (`USE_EVIDENTLY=true`) — `DriftTestSuiteStrategy` trên numeric `[duration_ns, duration]` + categorical `[service, operation]`. Mỗi app sinh 1 HTML report đẩy lên S3 và (nếu có `EVIDENTLY_WORKSPACE`) thêm vào workspace UI.
- **PSI fallback** trên `duration_ns` — 10 bin quantile, ngưỡng `PSI_THRESHOLD=0.2`. Dùng khi `USE_EVIDENTLY=false` hoặc Evidently lỗi.
- **New API detection** — luôn chạy, set `(service, operation)` mới so với baseline ⇒ drift.
- **`FORCE_DRIFT=true`** — bypass mọi check, ép drift (dùng để test).
- **Data quality (observability)** — `RUN_DATA_QUALITY=true` (mặc định) chạy thêm `DataQualityStrategy` per-app: missing values, duplicates, cardinality. **Non-blocking** — không ảnh hưởng `drift_detected`, chỉ ghi HTML lên `quality-reports/{version_id}/{app_id}/` và push Evidently UI. Summary nhúng vào `per_app_results[app_id].quality_summary` của `drift_report.json`.

**Điều kiện drift:**
- Lần chạy đầu (không có baseline).
- Bất kỳ app nào vượt ngưỡng Evidently hoặc PSI.
- Xuất hiện API mới.

**Output:**
- `drift-reports/{version_id}/drift_report.json` (per_app_results, drifted_apps, psi_duration, new_apis, mlflow_run_id…).
- XCom `{version_id, drift_detected, mlflow_run_id}`.
- Nếu drift: **mở MLflow parent pipeline run** (`start_pipeline_run`) — các bước sau log dưới dạng nested run.

**Sample-size guard:** `MIN_DRIFT_SAMPLES` (env, default 100; DAG override `10`). Dưới ngưỡng → bỏ qua, không retrain.

**Branching:** `check_drift` (`BranchPythonOperator`) đọc XCom rồi rẽ sang `trigger_retrain` (EmptyOperator → tiếp tục) hoặc `no_retrain` (EmptyOperator → STOP).

### Step 2: Preprocessing (`tasks/preprocessing.py`)

Pod K8s, image light.

1. Đọc dữ liệu từ ClickHouse cho cửa sổ `TRAINING_WINDOW_DAYS` (env, default `3`).
2. `http_status` → status group (1–5) qua `common.util.map_status_group`.
3. `SafeLabelEncoder` cho `service`, `operation`, **`app_id`**.
4. `StandardScaler` cho `duration`.
5. Suy ra `parent_op`, `parent_service` từ `parentSpanId` (fallback `unknown_index`).
6. Shuffle, split 70/30 → `train.parquet` + `test.parquet`.
7. Upload encoders/scalers (`joblib`) lên `mlops/training-data/{version_id}/`.

### Step 3: Training (`tasks/training.py`) — AWS Batch

Job definition `mlops-train-job`, queue `gpu-spot-queue`, region `us-east-1`, image GPU trên ECR.

**Cấu hình:**

| Tham số | Giá trị |
|---|---|
| Sequence length | 20 spans |
| Stride | 2 |
| Epochs | 50 |
| Batch size | 64 |
| Learning rate | 5e-4 |
| Weight decay | 1e-5 |
| Checkpoint interval | 10 epoch |
| d_model | 64 |
| Latent dim | 32 |

**Hoạt động:**
1. Tải `train.parquet` + encoders từ S3.
2. Group span theo `(app_id, service, parent_service, operation, parent_op, http_status)` ⇒ sliding window len 20, stride 2.
3. Train `TransformerAutoencoder` (MSE, Adam, ReduceLROnPlateau, gradient clipping 1.0).
4. **Checkpointing** mỗi 10 epoch để recover khi Spot bị interrupt.
5. Upload `model.pth`, `encoders.pkl`, `scalers.pkl` lên `mlops/models/{version_id}/`.
6. Log metrics + register model `transformer-ae` trong MLflow dưới nested run của parent pipeline run.
7. Ghi `mlops/batch-outputs/{version_id}/train_output.json` → thay thế Airflow XCom (Batch không xài XCom được).

**fetch_train_output (K8s):** PythonOperator, retry exponential backoff đọc S3 (NoSuchKey ⇒ retry, tối đa 5 lần), push XCom cho task sau.

### Step 4: Evaluation (`tasks/evaluation.py`) — AWS Batch

Job definition `mlops-evaluate-job`, cùng queue GPU Spot.

1. Tải model + encoders + `test.parquet`.
2. Build sequence, inference, anomaly score = reconstruction MSE.
3. **Boost +1000** cho span `span_status=2` (error) hoặc `http_status=5` (5xx).
4. Tính **p99 threshold** từ span non-error.
5. Tính **F1 / precision / recall** dùng cột `is_anomaly` làm ground truth (qua `precision_recall_curve`).
6. Ghi `metadata.json` (version, threshold, model_s3_path, mean_score, test_samples) lên S3.
7. Log metrics MLflow ⇒ **kết thúc parent pipeline run** (`end_pipeline_run`).
8. Ghi `mlops/batch-outputs/{version_id}/evaluate_output.json`.

`fetch_evaluate_output` tương tự fetch_train.

### Step 5: Model Comparison (`tasks/model_comparison.py`) — K8s

**Chỉ xuất khuyến nghị, không tự deploy.**

1. Lấy champion hiện tại qua alias `champion` (model `transformer-ae`).
2. Lấy challenger theo `version_id` (search model versions, lọc theo tag `version_id`).
3. So sánh qua **3 gate**:

| Gate | Quy tắc | Tolerance |
|---|---|---|
| F1 | `challenger ≥ champion × 0.99` | 1% (fixed) |
| Precision | `challenger ≥ champion × (1 − T)` | `COMPARISON_PRECISION_TOLERANCE=0.05` |
| Recall | `challenger ≥ champion × (1 − T)` | `COMPARISON_RECALL_TOLERANCE=0.05` |

4. Output `comparison.json` lên `mlops/model-comparisons/{version_id}/`:
   - `recommendation`: `PROMOTE` (first model hoặc all gates pass), `KEEP_CURRENT` (gate fail), `ERROR` (không tìm thấy challenger).
   - Kèm `action` là command Airflow CLI để admin chạy `model_deploy` nếu muốn promote.

5. Admin review report rồi quyết định trigger DAG 2.

### Step 6: Model Deploy (`tasks/model_deploy.py`) — DAG 2

Pod chạy với `service_account_name=airflow-deploy-sa` (cần quyền patch ConfigMap + Deployment trong namespace `anomaly-detection`).

1. Tải `mlops/models/{version_id}/metadata.json`.
2. Patch ConfigMap `anomaly-detection-service-config`:
   - `ANOMALY_THRESHOLD` = p99 threshold
   - `MODEL_S3_PATH` = đường dẫn S3 tới model
   - `MODEL_VERSION` = `version_id`
3. Patch annotation `kubectl.kubernetes.io/restartedAt` trên deployment `anomaly-detection-service` ⇒ rolling restart.
4. (Best-effort) `mlflow_client.set_registered_model_alias("transformer-ae", "champion", v.version)` cho version có tag `version_id` khớp.

## DAG phụ — RCA Knowledge Base

### DAG 3: `kb_building_dag` (`dags/kb_building_dag.py`)

- Schedule: `@weekly`.
- Pod image `hungtran679/kb_builder`, namespace `airflow`.
- Env từ secret `airflow-aws-secret`, `airflow-clickhouse-secret`, configmap `airflow-kb-builder-configmap`.
- Resource: 200m/512Mi → 500m/1Gi.
- Output: đăng ký MLflow model `rca-knowledge-base`.

### DAG 4: `kb_deploy_dag` (`dags/kb_deploy_dag.py`)

- Manual trigger, param `version_id`.
- Pod image `hungtran679/kb_deploy:latest`, ServiceAccount `mlops-deployer-sa`.
- Pull KB version từ MLflow rồi cập nhật deployment `trace-rca-service` trong namespace `rca`.

## Trigger pipeline

### Training Pipeline (DAG 1)
```bash
airflow dags trigger training_pipeline
# Force drift (debug):
airflow dags trigger training_pipeline --conf '{"FORCE_DRIFT": "true"}'
```
Schedule mặc định `None` (manual). `FORCE_DRIFT` truyền qua env vars của pod.

### Model Deploy (DAG 2)
```bash
airflow dags trigger model_deploy --conf '{"version_id": "v20240315-120000"}'
```

### KB Building (DAG 3)
Tự động @weekly, hoặc trigger tay qua UI.

### KB Deploy (DAG 4)
```bash
airflow dags trigger kb_deploy_dag --conf '{"version_id": "<mlflow_kb_version>"}'
```

## Biến môi trường chính (DAG 1)

| Env | Mặc định | Ý nghĩa |
|---|---|---|
| `MLFLOW_TRACKING_URI` | `http://mlflow-tracking.mlflow.svc:5000` | MLflow server |
| `S3_BUCKET` | `kltn-anomaly-dateset-1` | Bucket data |
| `S3_REGION` | `ap-southeast-1` | Region bucket |
| `CLICKHOUSE_HOST` | `clickhouse-cluster-client.clickhouse.svc` | DNS ClickHouse |
| `CLICKHOUSE_PORT` | `9000` | Native protocol |
| `USE_EVIDENTLY` | `true` | Bật Evidently (tắt → PSI fallback) |
| `RUN_DATA_QUALITY` | `true` | Bật DataQuality report per-app (observability, non-blocking) |
| `EVIDENTLY_WORKSPACE` | `http://evidently-ui.mlops.svc:8000` | UI workspace (optional) |
| `PSI_THRESHOLD` | `0.2` | Ngưỡng PSI |
| `MIN_DRIFT_SAMPLES` | `100` (DAG ép `10`) | Min sample để chạy drift |
| `FORCE_DRIFT` | `false` | Bypass drift check |
| `TRAINING_WINDOW_DAYS` | `3` | Cửa sổ data cho preprocess |
| `COMPARISON_PRECISION_TOLERANCE` | `0.05` | Tolerance gate precision |
| `COMPARISON_RECALL_TOLERANCE` | `0.05` | Tolerance gate recall |

Secret `airflow-aws-secret` (env_from) cung cấp `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` cho S3 + Batch.

## Công nghệ sử dụng

| Lớp | Công nghệ |
|---|---|
| Orchestrator | Apache Airflow Helm v1.15.0, KubernetesExecutor |
| Compute nhẹ | K8s Pods (namespace `airflow`), image `asdads6495/mlops-pipeline-light:dev` |
| Compute nặng | AWS Batch GPU Spot (`us-east-1`), image `mlops-pipeline-gpu` (ECR) |
| Data source | ClickHouse cluster (namespace `clickhouse`) + tiered storage S3 |
| Drift | Evidently v0.4.x (namespace `mlops`) + PSI custom (fallback) |
| Model registry | MLflow v2.12.2 (namespace `mlflow`) — alias `champion`/`production` |
| Object storage | AWS S3 (boto3) |
| Training framework | PyTorch |
| Data processing | pandas, scikit-learn, `clickhouse-driver` |
| Container runtime | Kubernetes Pods (`KubernetesPodOperator`) + `BatchOperator` |
| Deploy target | `anomaly-detection-service` (ns `anomaly-detection`), `trace-rca-service` (ns `rca`) |

## Docker Images

```bash
# Light image — K8s tasks (drift, preprocess, comparison, deploy, KB)
docker build -t asdads6495/mlops-pipeline-light:dev -f mlops/Dockerfile.mlops-light .

# GPU image — AWS Batch (train, evaluate)
docker build -t mlops-pipeline-gpu -f mlops/Dockerfile.mlops-gpu .
# Tag + push lên ECR us-east-1, dùng làm job definition image cho Batch.

# Airflow image (custom, gồm provider AWS + ClickHouse driver)
docker build -t <airflow-image>:<tag> -f mlops/Dockerfile.airflow .
```

Mỗi image chứa: `tasks/`, `common/`, `transformer_ae/`, `configs/`. Image light bỏ CUDA stack để giảm size.

## Câu hỏi chưa rõ

- `kb_building_dag` deploy KB version nào (có pin version vào MLflow alias hay phải truyền tay)? Code không thấy alias setting.
- `model_comparison` chỉ in log/action — chưa có cơ chế tự động trigger DAG `model_deploy`, có phải mặc ý chờ admin?
- Có integration nào giữa drift signal (`drifted_apps`) và KB pipeline không, hay 2 pipeline hoàn toàn độc lập?
