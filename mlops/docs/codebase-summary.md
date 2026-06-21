# MLOps Codebase Summary

## Project Overview

An automated ML Operations pipeline for distributed trace anomaly detection using Transformer Autoencoders. Orchestrated by Apache Airflow 3.0.6, deployed on Kubernetes with GPU-accelerated training on AWS Batch.

## Directory Structure

```
mlops/
├── dags/                          # Airflow DAG definitions
│   ├── training_pipeline_dag.py   # Main training orchestration
│   ├── model_deploy_dag.py        # Model deployment DAG
│   ├── kb_building_dag.py         # Knowledge base building
│   └── kb_deploy_dag.py           # Knowledge base deployment
├── tasks/                         # Pipeline task implementations
│   ├── drift_detection.py         # Data drift monitoring (PSI, new API detection)
│   ├── preprocessing.py           # Data encoding, scaling, splitting
│   ├── training.py                # Transformer Autoencoder training
│   ├── evaluation.py              # Model evaluation, threshold calculation
│   ├── model_deploy.py            # ConfigMap patching, rolling restart
│   ├── compaction.py              # Parquet file consolidation (legacy)
│   ├── evidently_strategies.py    # Evidently monitoring integration
│   └── s3_utils.py                # S3 operations, boto3 helpers
├── tests/                         # Unit and integration tests
├── common/                        # Shared utilities
│   ├── util.py                    # Common helpers
│   └── encoders.py                # SafeLabelEncoder for categorical features
├── transformer_ae/                # Model architecture
│   ├── model.py                   # Transformer Autoencoder definition
│   ├── evaluate.py                # Evaluation logic
│   └── config.yaml                # Hyperparameters
├── configs/                       # Pipeline configuration
├── Dockerfile.airflow             # Airflow 3.0.6 base image
├── Dockerfile.mlops               # GPU-enabled training image
├── Dockerfile.mlops-light         # CPU-only lightweight image
├── airflow-requirements.txt       # Airflow dependencies
├── requirements-mlops*.txt        # Task dependencies
├── PIPELINE.md                    # Detailed pipeline documentation
└── repomix-output.xml             # Full codebase snapshot
```

## Key Components

### 1. DAGs (Airflow 3.0.6)

**training_pipeline_dag.py:**
- Orchestrates drift detection → preprocessing → training (AWS Batch) → evaluation
- Uses `KubernetesPodOperator` for lightweight tasks
- Uses `BatchOperator` for GPU-intensive training/evaluation
- Manual trigger only (`schedule=None`)
- Hybrid K8s + AWS Batch execution model

**model_deploy_dag.py:**
- Triggers model deployment to production
- Accepts `version_id` as DAG run config
- Patches ConfigMap and rolls out Deployment in anomaly-detection namespace

**kb_building_dag.py, kb_deploy_dag.py:**
- Knowledge base building and deployment workflows

### 2. Tasks

**drift_detection.py (4,050 tokens)**
- Population Stability Index (PSI) on `duration_ns` column
- New API endpoint detection
- Threshold: PSI > 0.2 triggers retraining
- Outputs: drift report (JSON→S3) + XCom for Airflow

**preprocessing.py**
- Label encoding for categorical features (`service`, `operation`)
- StandardScaler for `duration`
- Parent operation resolution via `parentSpanId`
- 70/30 train/test split, Parquet output

**training.py (3,227 tokens)**
- Transformer Autoencoder with:
  - Sequence length: 20 spans
  - d_model: 64, latent_dim: 32
  - 50 epochs, batch size 64
  - MSE loss + Adam optimizer
  - ReduceLROnPlateau scheduler
- MLflow model registration
- Resource: 500m–2 CPU, 1–4 Gi memory

**evaluation.py**
- p99 threshold calculation from test set
- Anomaly score = reconstruction error (MSE)
- Boost score +1000 for error/5xx spans
- Metadata JSON upload (threshold, version, S3 paths)

**model_deploy.py**
- ConfigMap patching (anomaly-detection-service-config)
- Deployment rolling restart via annotation
- MLflow stage transition (best-effort)

**evidently_strategies.py**
- Evidently v0.4.33 integration
- Monitoring dashboards for drift, model quality

### 3. Model Architecture

**transformer_ae/model.py:**
- Transformer Autoencoder
- Encoder: 2 layers, 8 heads, feedforward dim 256
- Latent bottleneck: 32-dim
- Decoder: symmetric to encoder

**Config parameters (transformer_ae/config.yaml):**
```yaml
sequence_length: 20
d_model: 64
nhead: 8
num_encoder_layers: 2
dim_feedforward: 256
latent_dim: 32
epochs: 50
batch_size: 64
learning_rate: 5e-4
```

### 4. Docker Images

| Image | Base | Use Case |
|-------|------|----------|
| `asdads6495/my-airflow:3.0.6` | `apache/airflow:3.0.6-python3.12` | Scheduler/webserver |
| `asdads6495/mlops-pipeline:dev` | Python 3.12 + PyTorch | Full training pipeline |
| `asdads6495/mlops-pipeline-light:dev` | Python 3.12 (no GPU) | Lightweight K8s tasks |
| `asdads6495/mlops-pipeline-gpu` (ECR) | NVIDIA CUDA + PyTorch | AWS Batch GPU training |

### 5. Dependencies

**Airflow 3.0.6 Providers:**
- `apache-airflow-providers-cncf-kubernetes>=10.0.0`
- `apache-airflow-providers-amazon>=9.0.0`

**Core packages:**
- `apache-airflow==3.0.6`
- `kubernetes` (K8s API)
- `boto3` (AWS S3, Batch)
- `mlflow-skinny==2.12.2`
- `pytorch`, `pandas`, `scikit-learn`
- `duckdb` (data processing)
- `evidently==0.4.33` (monitoring)
- `pendulum` (datetime handling in Airflow 3.0)

## Data Flow

```
S3 Inference Data (anomalies/data.parquet/)
          ↓
    Drift Detection (PSI, new API)
          ↓
     [BRANCH: drift_detected?]
          ├─→ No Drift: Stop
          └─→ Drift: Continue
          ↓
    Preprocessing (encode, scale, split)
          ↓
    AWS Batch Training (GPU)
          ↓
    AWS Batch Evaluation (calculate threshold)
          ↓
    Upload Model + Metadata to S3 (mlops/models/{version_id}/)
          ↓
    Model Deploy (manual trigger)
          ↓
    Patch ConfigMap + Roll Deployment
          ↓
    Anomaly Detection Service (updated)
```

## Environment Variables

Key env vars (set via K8s Secret `airflow-aws-secret`):
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`
- `AWS_DEFAULT_REGION=us-east-1` (training)
- `S3_BUCKET=kltn-anomaly-dateset-1`
- `S3_REGION=ap-southeast-1`
- `MLFLOW_TRACKING_URI=http://mlflow-tracking.mlflow.svc.cluster.local:5000`
- `CLICKHOUSE_HOST`, `CLICKHOUSE_PORT` (data warehouse)

## Airflow 3.0.6 Changes from 2.10.4

| Feature | 2.10.4 | 3.0.6 | Notes |
|---------|--------|-------|-------|
| Schedule param | `schedule_interval` | `schedule` | All DAGs updated |
| Datetime utils | `airflow.utils.dates.days_ago()` | `datetime` + `pendulum` | airflow-requirements.txt includes pendulum |
| Dummy operator | `DummyOperator` | `EmptyOperator` | Imported from `airflow.operators.empty` |
| Kubernetes provider | 9.x | 10.x+ | KubernetesExecutor works with 3.0.6 |

No custom patches required for Airflow 3.0.6 — fixes KubernetesExecutor bugs #41436, #42991 that existed in 2.10.4.

## Testing

**Test files (tests/):**
- `test_model_comparison.py` — Model performance validation
- Unit tests for task functions (preprocessing, drift detection)
- Integration tests for S3 operations

**Run tests:**
```bash
pytest tests/ -v
```

## Monitoring & Observability

- **MLflow:** Model registry, metrics tracking
- **Evidently:** Data/model drift dashboards
- **Airflow UI:** Task logs, DAG execution history
- **CloudWatch** (AWS): Batch job logs
- **ClickHouse:** Trace data warehouse, archival

## Next Steps

1. Verify all DAGs parse correctly in Airflow 3.0.6 UI
2. Test training_pipeline with sample data
3. Validate model_deploy against production anomaly-detection ConfigMap
4. Monitor Evidently dashboards post-deployment
