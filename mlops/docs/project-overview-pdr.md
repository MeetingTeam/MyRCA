# MLOps Project Overview & PDR

## Project Vision

Automated ML Operations pipeline for distributed trace anomaly detection. Detects performance degradation and service anomalies by training Transformer Autoencoders on trace span data, deployed on Kubernetes with cloud-scale training on AWS Batch.

## Functional Requirements

### FR1: Drift Detection
- **Detect data distribution shifts** using Population Stability Index (PSI)
- **Monitor new API endpoints** in inference data
- **Threshold:** PSI > 0.2 triggers retraining
- **Output:** Drift report (JSON) + Airflow XCom signal

### FR2: Data Preprocessing
- **Encode categorical features** (service, operation) using SafeLabelEncoder
- **Scale continuous features** (duration) with StandardScaler
- **Resolve parent operations** via parentSpanId relationships
- **Split data:** 70% train, 30% test
- **Output:** train.parquet, test.parquet, encoders.pkl, scalers.pkl → S3

### FR3: Model Training
- **Architecture:** Transformer Autoencoder (2-layer encoder, 64 d_model, 32-dim latent)
- **Input:** 20-span sequences with stride 2
- **Loss:** MSE reconstruction error
- **Optimizer:** Adam (lr=5e-4) + ReduceLROnPlateau scheduler
- **Output:** model.pth, training metrics → MLflow + S3

### FR4: Model Evaluation
- **Calculate p99 anomaly threshold** from test set reconstruction errors
- **Boost anomaly scores** +1000 for error/5xx spans
- **Validate model quality** before deployment
- **Output:** metadata.json (threshold, version, S3 paths) → S3

### FR5: Model Deployment
- **Patch production ConfigMap** (anomaly-detection-service-config)
- **Update ANOMALY_THRESHOLD** and MODEL_S3_PATH
- **Trigger rolling restart** of Anomaly Detection Service
- **Register model version** in MLflow (best-effort)

### FR6: Orchestration
- **Manual trigger** via Airflow UI or CLI
- **Hybrid execution:** KubernetesPodOperator (K8s) + BatchOperator (AWS Batch)
- **Conditional branching:** Skip training if no drift detected
- **XCom passing** for data between tasks

## Non-Functional Requirements

### NFR1: Scalability
- **Training data:** Handle >100M spans per run
- **GPU acceleration:** AWS Batch Spot instances (p3.2xlarge)
- **Kubernetes:** Multi-node clusters (default: 1 scheduler, 1 webserver)

### NFR2: Reliability
- **Retry policy:** Up to 1 retry per task, 5-min backoff
- **Data durability:** S3 versioning for model artifacts
- **Monitoring:** Evidently dashboards + MLflow tracking

### NFR3: Performance
- **Training time:** 50 epochs on 60K sequences ≈ 2-4 hours (GPU)
- **Preprocessing:** <30 min for drift detection + data prep
- **Deployment:** <5 min for ConfigMap patch + rollout

### NFR4: Maintainability
- **Code organization:** Tasks modularized in `tasks/`, shared utilities in `common/`
- **Documentation:** PIPELINE.md, deployment-guide.md, inline comments
- **Testing:** Unit tests in `tests/`, CI via GitHub Actions
- **Version tracking:** Docker image tags, Git commit hashes in metadata

## Architecture

### Execution Model

```
┌─────────────────────────────────────────────────────────────┐
│              Airflow 3.0.6 (KubernetesExecutor)            │
│  Namespace: airflow  (scheduler, webserver)                │
└─────────────────────────────────────────────────────────────┘
                          │
         ┌────────────────┼────────────────┐
         ▼                ▼                ▼
    ┌────────────┐  ┌──────────────┐  ┌────────────┐
    │  Drift     │  │ Preprocess   │  │  K8s Pod   │
    │ Detection  │  │ (KubernetesPodOperator)  │
    │ (K8s Pod)  │  │              │  │ Tasks      │
    └────────────┘  └──────────────┘  └────────────┘
                            │
                    ┌───────┴────────┐
                    ▼                ▼
              ┌──────────────┐  ┌──────────────┐
              │    Train     │  │   Evaluate   │
              │  (AWS Batch) │  │  (AWS Batch) │
              │ (GPU p3.2xl) │  │ (GPU p3.2xl) │
              └──────────────┘  └──────────────┘
                    │                │
                    └────────┬────────┘
                             ▼
                    ┌────────────────┐
                    │  Model Deploy  │
                    │  (K8s Pod)     │
                    │ Patch ConfigMap│
                    └────────────────┘
```

### Data Pipeline

```
S3: anomalies/data.parquet/
          │
          ▼
    Drift Detection (PSI)
          │
    ┌─────┴─────┐
    ▼           ▼
 [Drift]    [No Drift]
    │           │
    ▼           ▼
Preprocess    STOP
    │
    ▼
S3: mlops/training-data/{version_id}/
    (train.parquet, test.parquet, encoders, scalers)
    │
    ▼
Train (AWS Batch)
    │
    ▼
S3: mlops/models/{version_id}/
    (model.pth, metadata.json, encoders, scalers)
    │
    ▼
Evaluate (AWS Batch)
    │
    ▼
Anomaly Detection Service
    (ConfigMap updated with p99 threshold)
```

### Storage Schema

**S3 Bucket:** `kltn-anomaly-dateset-1`

```
s3://kltn-anomaly-dateset-1/
├── anomalies/data.parquet/         # Inference data (partitioned by date)
│   └── date_part=YYYY-MM-DD/
├── mlops/
│   ├── drift-reports/{version_id}/
│   │   └── drift_report.json
│   ├── training-data/{version_id}/
│   │   ├── train.parquet
│   │   ├── test.parquet
│   │   ├── encoders.pkl
│   │   └── scalers.pkl
│   ├── models/{version_id}/
│   │   ├── model.pth
│   │   ├── metadata.json
│   │   ├── encoders.pkl
│   │   └── scalers.pkl
│   └── batch-outputs/{version_id}/
│       ├── train_output.json
│       └── evaluate_output.json
```

## Success Metrics

| Metric | Target | Validation |
|--------|--------|-----------|
| **Training accuracy** | >95% normal span reconstruction | MSE on test set |
| **Drift detection precision** | >90% | Confusion matrix on labeled data |
| **Model deployment time** | <5 min | CloudWatch logs |
| **Pipeline uptime** | >95% | Airflow task success rate |
| **Cost per training run** | <$20 | AWS Cost Explorer (Batch Spot) |

## Dependencies & Constraints

### External Dependencies
- **Kubernetes cluster** (1+ nodes, 2+ CPU, 4 Gi memory minimum)
- **AWS Account** (S3, Batch, ECR in us-east-1)
- **MLflow tracking server** (http://mlflow-tracking.mlflow.svc.cluster.local:5000)
- **ClickHouse** (trace data warehouse, optional)

### Constraints
- **Python version:** 3.12 (Airflow 3.0.6 requirement)
- **Pytorch:** Requires CUDA 12.1+ for GPU training
- **Docker registry:** asdads6495 on DockerHub (or ECR for GPU image)
- **Kubernetes RBAC:** `airflow-deploy-sa` ServiceAccount needs patch permissions on anomaly-detection ConfigMap

## Implementation Phases

### Phase 1: Setup (Complete)
- ✅ Airflow deployment with KubernetesExecutor
- ✅ Docker image builds (Airflow, mlops, mlops-light)
- ✅ S3 bucket configuration
- ✅ AWS Batch compute environment setup

### Phase 2: Pipeline Core (Complete)
- ✅ Drift detection task
- ✅ Preprocessing task
- ✅ Training task (Batch)
- ✅ Evaluation task (Batch)
- ✅ Model deploy task
- ✅ DAG orchestration (training_pipeline, model_deploy)

### Phase 3: Monitoring (Complete)
- ✅ MLflow integration
- ✅ Evidently dashboards
- ✅ S3 data tracking

### Phase 4: Airflow 3.0.6 Upgrade (Complete)
- ✅ Update base image to apache/airflow:3.0.6-python3.12
- ✅ Migrate DAG syntax: `schedule_interval` → `schedule`
- ✅ Remove deprecated imports
- ✅ Update Kubernetes provider to 10.0.0+
- ✅ Test training_pipeline and model_deploy DAGs

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|-----------|
| **GPU quota exhaustion** | Training blocked | Monitor AWS Batch job queue, request quota increase |
| **S3 data corruption** | Data loss | S3 versioning enabled, snapshot before cleaning |
| **Airflow DAG parse errors** | Pipeline stuck | Validate DAGs with `airflow dags list` after upgrades |
| **ModelDeploy fails** | Old model in prod | Manual rollback via kubectl ConfigMap edit |
| **ClickHouse unavailable** | Data pipeline blocked | Fallback to S3 parquet queries (slower) |

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | Feb 2024 | Initial Airflow 2.10.4 pipeline |
| 1.1 | Mar 2024 | AWS Batch integration for GPU training |
| 1.2 | May 2024 | Evidently monitoring integration |
| 2.0 | Jun 2024 | **Airflow 3.0.6 upgrade**, KubernetesExecutor stabilization |

## Next Steps

1. **Validation:** Run training_pipeline with sample data, verify p99 threshold calculation
2. **Integration:** Test model_deploy with staging anomaly-detection-service ConfigMap
3. **Monitoring:** Enable Evidently dashboards, set up CloudWatch alarms
4. **Documentation:** Maintain runbook for troubleshooting common issues
5. **Optimization:** Profile GPU training, explore model distillation for inference
