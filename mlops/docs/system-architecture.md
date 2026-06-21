# MLOps System Architecture

## High-Level Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         Kubernetes Cluster                               │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │  Airflow Namespace (airflow)                                       │ │
│  │  ┌──────────────┐        ┌──────────────┐                          │ │
│  │  │  Scheduler   │◄─────►│  Webserver   │                          │ │
│  │  │  (1 pod)     │        │  (1 pod)     │                          │ │
│  │  │  3.0.6       │        │  Port 30380  │                          │ │
│  │  └──────────────┘        └──────────────┘                          │ │
│  │         │                                                           │ │
│  │         ├──► training_pipeline_dag                                 │ │
│  │         └──► model_deploy_dag                                      │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │  Execution Layer (Dynamic Pods)                                    │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐             │ │
│  │  │ Drift Detect │  │ Preprocess   │  │  Model Dep   │             │ │
│  │  │ (KubernetesPodOperator)              │  (KubernetesPodOperator) │ │
│  │  │ Image: mlops-pipeline-light          │                          │ │
│  │  └──────────────┘  └──────────────┘  └──────────────┘             │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                              │                                           │
└──────────────────────────────┼───────────────────────────────────────────┘
                               │
                   ┌───────────┴──────────────┐
                   ▼                          ▼
            ┌─────────────┐         ┌──────────────────┐
            │  AWS Batch  │         │   S3 Storage     │
            │             │         │ (kltn-anomaly...)│
            │ Training    │         │                  │
            │ Evaluation  │         │ Inference Data   │
            │ (GPU Spot)  │         │ Models           │
            │ (p3.2xlarge)│         │ Reports          │
            └─────────────┘         └──────────────────┘
                   │                        │
                   └────────────┬───────────┘
                                ▼
                        ┌──────────────┐
                        │  MLflow      │
                        │  Tracking    │
                        │  :5000       │
                        └──────────────┘
```

## Component Architecture

### 1. Airflow Orchestration (3.0.6)

**Role:** DAG scheduling, task execution coordination, XCom passing

**Configuration:**
- **Executor:** `KubernetesExecutor` (one pod per task)
- **Namespace:** `airflow`
- **Scheduler:** 1 pod (3.0.6-python3.12)
- **Webserver:** 1 pod (3.0.6-python3.12, port 30380)
- **Database:** Postgres (metadata, DAG definitions, task logs)

**DAGs:**
1. **training_pipeline_dag** (main orchestration)
   - Drift detection → decision branch → preprocessing → training (Batch) → evaluation (Batch)
   - Manual trigger (`schedule=None`)
   - Hybrid K8s + AWS Batch execution

2. **model_deploy_dag** (deployment)
   - Accept version_id as config
   - Patch ConfigMap, trigger rolling restart
   - Manual trigger with config input

**Airflow 3.0.6 Features:**
- ✅ `schedule` parameter (replaces `schedule_interval`)
- ✅ `EmptyOperator` (replaces `DummyOperator`)
- ✅ `pendulum` for datetime (replaces `days_ago()`)
- ✅ KubernetesExecutor stable (no patches needed)

### 2. Kubernetes Execution Layer

**Lightweight Tasks (KubernetesPodOperator):**

| Task | Image | Resources | Purpose |
|------|-------|-----------|---------|
| drift_detection | mlops-pipeline-light:dev | CPU 500m–1, Mem 512Mi–2Gi | PSI calculation, new API detection |
| preprocessing | mlops-pipeline-light:dev | CPU 500m–1, Mem 1–4Gi | Encoding, scaling, splitting |
| model_deploy | mlops-pipeline-light:dev | CPU 100m–500m, Mem 256–512Mi | ConfigMap patch, rollout |

**Pod Configuration:**
- **Restart policy:** Never (Airflow handles retries)
- **Service account:** `airflow` (default)
- **Storage:** EmptyDir for /tmp (cleaned up after pod termination)
- **Image pull:** Always (fresh image per run)

### 3. AWS Batch Execution Layer

**GPU-Intensive Tasks (BatchOperator):**

| Job | Image | Instance | Resources | Duration |
|-----|-------|----------|-----------|----------|
| training | mlops-pipeline-gpu (ECR) | p3.2xlarge | 1 GPU (V100), 8 vCPU, 61 Gi RAM | 2–4 hours |
| evaluation | mlops-pipeline-gpu (ECR) | p3.2xlarge | 1 GPU (V100), 8 vCPU, 61 Gi RAM | 30–60 min |

**Batch Setup:**
- **Compute Environment:** Spot instances (cost savings)
- **Job Queue:** `mlops-job-queue`
- **IAM Role:** `ecsTaskExecutionRolePolicy` + S3 access
- **Docker Registry:** ECR (`asdads6495/mlops-pipeline-gpu`)

**Data Flow (Batch → S3 XCom Replacement):**
```
Batch Job completes
    ↓
Writes output JSON → S3: mlops/batch-outputs/{version_id}/{task}_output.json
    ↓
Airflow reads from S3 via `read_batch_output()` (with retries)
    ↓
Parses JSON, pushes to XCom for downstream tasks
```

### 4. Data Storage (S3)

**Bucket:** `kltn-anomaly-dateset-1` (region: ap-southeast-1)

**Partitioning by version_id:** `v{YYYYMMDD-HHMMSS}` (e.g., `v20240315-120000`)

**Data Organization:**

```
s3://kltn-anomaly-dateset-1/
│
├── anomalies/data.parquet/                     # Inference dataset (input)
│   └── date_part=YYYY-MM-DD/
│       ├── part-0.parquet (multiple files)
│       └── ...
│
├── mlops/
│   ├── drift-reports/{version_id}/              # Drift analysis results
│   │   ├── drift_report.json
│   │   └── drift_metrics.json
│   │
│   ├── training-data/{version_id}/              # Preprocessed data
│   │   ├── train.parquet (70% samples)
│   │   ├── test.parquet (30% samples)
│   │   ├── encoders.pkl (label encoders)
│   │   ├── scalers.pkl (feature scalers)
│   │   └── metadata.json (schema, counts)
│   │
│   ├── models/{version_id}/                     # Model artifacts
│   │   ├── model.pth (PyTorch state_dict)
│   │   ├── encoders.pkl (inference encoders)
│   │   ├── scalers.pkl (inference scalers)
│   │   ├── metadata.json (threshold, metrics)
│   │   └── training_config.json (hyperparams)
│   │
│   └── batch-outputs/{version_id}/              # Batch job results
│       ├── train_output.json
│       └── evaluate_output.json
```

### 5. Model Registry (MLflow)

**Tracking Server:** `http://mlflow-tracking.mlflow.svc.cluster.local:5000`

**Model:**
- **Name:** `transformer-ae`
- **Registered versions:** One per training run (v1, v2, ...)
- **Metrics tracked:** train_loss, val_loss, p99_threshold, f1_score
- **Parameters:** d_model, nhead, latent_dim, learning_rate, epochs
- **Artifacts:** model.pth, metadata.json, encoders.pkl

**Stage Transitions (best-effort in model_deploy):**
- `None` → `Staging` (after evaluation)
- `Staging` → `Production` (on successful deploy)

### 6. Monitoring & Observability

**Evidently (v0.4.33, Kubernetes service in mlops namespace):**
- **Dashboard URL:** `http://evidently-ui.mlops.svc.cluster.local:8000`
- **Monitors:**
  - Data drift (distribution comparison)
  - Model quality (test set metrics)
  - Feature statistics (mean, variance)
  - Categorical feature correlation

**CloudWatch (AWS Batch logs):**
- Batch job stdout/stderr → CloudWatch `/aws/batch/job`
- Filtered logs for training metrics (loss, learning rate)

**Airflow UI (http://localhost:30380):**
- Task logs, DAG execution history
- Task success/failure rates
- XCom variables passed between tasks

### 7. External Services

**ClickHouse (optional, ap-southeast-1):**
- **Namespace:** clickhouse
- **Service:** `clickhouse-cluster-client.clickhouse.svc.cluster.local:9000`
- **Purpose:** Trace data warehouse, partitioned by date
- **Data flow:** S3 → ClickHouse (tiered storage for cost)

**DNS & Networking:**
- **Intra-cluster:** Use Kubernetes DNS (`{service}.{namespace}.svc.cluster.local`)
- **Inter-region:** Use AWS PrivateLink or VPN (S3 in ap-southeast-1 from us-east-1 Batch)

## Data Flow Diagram

### Training Pipeline Execution

```
Manual Trigger (Airflow UI / CLI)
    │
    ▼
┌─────────────────────────────────────┐
│  task: drift_detection (K8s Pod)    │
│  Input: S3 anomalies/data.parquet/  │
│  Algorithm: PSI, new API detection  │
│  Output: drift_report.json → S3     │
│          XCom: {version_id, drift}  │
└─────────────────────────────────────┘
    │
    ▼ (XCom decision)
    ├─→ [drift_detected=False] → SKIP rest (ShortCircuitOperator)
    │
    └─→ [drift_detected=True]
        │
        ▼
    ┌─────────────────────────────────────┐
    │  task: preprocess (K8s Pod)         │
    │  Input: S3 raw spans + encoders     │
    │  Algorithm: label encode, scale     │
    │  Output: train.parquet, test.parquet│
    │          → S3 mlops/training-data/  │
    └─────────────────────────────────────┘
        │
        ▼
    ┌─────────────────────────────────────┐
    │  task: train (AWS Batch, GPU)       │
    │  Input: train.parquet + config      │
    │  Algorithm: Transformer AE training │
    │  Output: model.pth → S3             │
    │          training_metrics → MLflow  │
    │  Read: train_output.json from S3    │
    └─────────────────────────────────────┘
        │
        ▼
    ┌─────────────────────────────────────┐
    │  task: evaluate (AWS Batch, GPU)    │
    │  Input: test.parquet + model.pth    │
    │  Algorithm: p99 threshold calc      │
    │  Output: metadata.json → S3         │
    │          eval_metrics → MLflow      │
    │  Read: evaluate_output.json from S3 │
    └─────────────────────────────────────┘
        │
        ▼ (Pipeline complete, ready for deploy)
    [Manual trigger: model_deploy DAG]
```

### Model Deployment Flow

```
Manual Trigger with {version_id}
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  task: model_deploy (K8s Pod)                       │
│  1. Download metadata.json from S3                  │
│  2. Extract p99_threshold, MODEL_S3_PATH            │
│  3. Patch ConfigMap in anomaly-detection namespace │
│     - anomaly-detection-service-config             │
│     - ANOMALY_THRESHOLD = p99_threshold            │
│     - MODEL_S3_PATH = mlops/models/{version_id}/   │
│     - MODEL_VERSION = version_id                   │
│  4. Patch Deployment to trigger rolling restart    │
│     - Annotation: restartedAt = timestamp          │
│  5. (Best-effort) Transition MLflow stage          │
│     - Staging → Production                          │
└─────────────────────────────────────────────────────┘
    │
    ▼
Anomaly Detection Service (rolling restart)
    │
    ├── Terminate old pods with previous model
    │
    └── Start new pods with updated ConfigMap
        (reads threshold, model path at startup)
        │
        ▼
    Service inference with new model + threshold
```

## Failure Modes & Resilience

### Airflow Failures
- **Scheduler crash:** Kubernetes replicaset auto-restarts pod
- **DAG parse error:** Visible in Airflow UI, prevents DAG scheduling
- **Task timeout:** Configurable per operator; default 24 hours
- **Retry logic:** 1 retry per task with 5-min backoff

### Batch Job Failures
- **GPU unavailable:** Spot instance interruption → job fails → Airflow retries
- **Out-of-memory:** Training crash → S3 output not written → `read_batch_output()` raises error
- **S3 write failure:** Batch logs error, Airflow detects missing output

### Data Issues
- **Empty inference data:** Drift detection skips, preprocessing fails
- **Schema mismatch:** Label encoder expects same categorical values → encoding fails
- **S3 access denied:** All tasks fail (likely IAM role misconfiguration)

### Mitigation Strategies
- **Monitoring:** Evidently dashboards alert on schema drift
- **Retries:** Batch jobs retry up to 1 time; Airflow retries once
- **Fallback:** Manual model_deploy with known-good version_id
- **Alerts:** CloudWatch alarms on Batch failures, Airflow task SLA breaches

## Scaling Considerations

### Horizontal Scaling

**Kubernetes:**
- Add nodes to cluster as pods scale
- Airflow scheduler auto-discovers new node resources
- Consider: network I/O to S3 becomes bottleneck

**AWS Batch:**
- Spot fleet auto-scales up to max vCPU limit
- Configure on-demand fallback if spot unavailable
- Cost: ~$1/hour per p3.2xlarge GPU instance

**S3:**
- Throughput: ~3,500 PUT, 5,500 GET requests/sec per prefix
- Use multi-part upload for >100 MB files
- Consider: S3 Transfer Acceleration for cross-region

### Vertical Scaling

**Training memory:** Increase batch size → faster training, higher OOM risk
**Model size:** Increase d_model, nhead → better accuracy, slower inference
**Sequence length:** Longer sequences → detect complex patterns, higher compute

## Security & Compliance

### Authentication & Authorization
- **Airflow UI:** Basic auth (default), or OAuth2 (configurable)
- **Kubernetes:** RBAC via ServiceAccount `airflow` (default)
- **AWS:** IAM roles for Batch execution, no long-lived keys in code

### Data Protection
- **S3 encryption:** SSE-S3 (default) or SSE-KMS (configurable)
- **In-transit:** TLS for S3, Batch, MLflow APIs
- **Access logs:** S3 CloudTrail, Batch CloudWatch logs

### Secret Management
- **AWS credentials:** EC2 instance role (for on-premises) or STS (for K8s)
- **MLflow token:** Stored in Kubernetes Secret (if authentication required)
- **Database password:** Airflow Secret Backend (Kubernetes Secret provider)

## Deployment Instructions

See `deployment-guide.md` for Helm chart setup, image builds, and DAG registration steps.
