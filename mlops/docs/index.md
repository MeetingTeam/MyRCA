# MLOps Documentation Index

Welcome to the MLOps documentation. This project is an automated ML Operations pipeline for distributed trace anomaly detection, orchestrated by Apache Airflow 3.0.6 and deployed on Kubernetes with GPU-accelerated training on AWS Batch.

## Quick Links

### Getting Started
- **[Deployment Guide](./deployment-guide.md)** — How to deploy Airflow, build images, and trigger pipelines
- **[Codebase Summary](./codebase-summary.md)** — Project structure, components, and data flow
- **[PIPELINE.md](../PIPELINE.md)** — Detailed pipeline documentation (in Vietnamese)

### Design & Architecture
- **[System Architecture](./system-architecture.md)** — Kubernetes, Airflow 3.0.6, AWS Batch, S3, MLflow
- **[Project Overview & PDR](./project-overview-pdr.md)** — Requirements, success metrics, phases

### Development
- **[Code Standards](./code-standards.md)** — Python, Airflow 3.0.6, PyTorch conventions

---

## What Changed: Airflow 2.10.4 → 3.0.6

This project was upgraded from Airflow 2.10.4 to 3.0.6. Key updates:

### DAG Syntax Changes
| Feature | 2.10.4 | 3.0.6 |
|---------|--------|-------|
| Schedule parameter | `schedule_interval=None` | `schedule=None` |
| Dummy task | `DummyOperator` | `EmptyOperator` |
| Date utilities | `from airflow.utils.dates import days_ago` | `from datetime import datetime` + `pendulum` |

### Docker Image
- **Old:** `apache/airflow:2.10.4-python3.11`
- **New:** `apache/airflow:3.0.6-python3.12`
- Built as: `asdads6495/my-airflow:3.0.6`

### Kubernetes Providers
- **Old:** `apache-airflow-providers-cncf-kubernetes==9.x`
- **New:** `apache-airflow-providers-cncf-kubernetes>=10.0.0`
- **Benefit:** Fixes KubernetesExecutor bugs (#41436, #42991)

### Custom Patches
- **Removed:** No longer needed for Airflow 3.0.6
- Airflow 3.0.6 stabilizes KubernetesExecutor out-of-the-box

---

## Documentation Structure

```
docs/
├── index.md                    # This file (overview + navigation)
├── deployment-guide.md         # How to deploy & configure
├── codebase-summary.md         # Project structure & components
├── system-architecture.md      # Detailed system design
├── project-overview-pdr.md     # Requirements & PDR
└── code-standards.md           # Development conventions
```

---

## Key Components

### Airflow Orchestration (3.0.6)
- **Scheduler + Webserver:** Kubernetes pods in `airflow` namespace
- **Executor:** KubernetesExecutor (one pod per task)
- **DAGs:**
  - `training_pipeline_dag` — Drift → Preprocess → Train (Batch) → Evaluate (Batch)
  - `model_deploy_dag` — Patch ConfigMap, trigger rolling restart

### Execution Model
- **Lightweight tasks (K8s):** Drift detection, preprocessing, model deploy
- **GPU-intensive tasks (AWS Batch):** Training, evaluation on p3.2xlarge Spot instances

### Data & Storage
- **S3 Bucket:** `kltn-anomaly-dateset-1` (ap-southeast-1)
  - Inference data: `anomalies/data.parquet/`
  - Models: `mlops/models/{version_id}/`
  - Reports: `mlops/drift-reports/{version_id}/`
- **Model Registry:** MLflow Tracking Server (5000)
- **Monitoring:** Evidently dashboards + CloudWatch logs

---

## Common Tasks

### Deploy Airflow
```bash
# Build Airflow image
docker build -t asdads6495/my-airflow:3.0.6 -f Dockerfile.airflow .

# Deploy via Helm
helm install airflow apache-airflow/airflow \
  --namespace airflow --create-namespace \
  -f airflow-values.yaml
```

### Trigger Training Pipeline
```bash
# Via Airflow UI: http://localhost:30380 → training_pipeline → Trigger

# Via CLI
airflow dags trigger training_pipeline
```

### Deploy a Model
```bash
# Via Airflow UI with config
# DAGs → model_deploy → Trigger w/ config → {"version_id": "v20240315-120000"}

# Via CLI
airflow dags trigger model_deploy --conf '{"version_id": "v20240315-120000"}'
```

### Check Airflow Status
```bash
# List all DAGs
airflow dags list

# View DAG details
airflow dags show training_pipeline

# Check task logs
kubectl logs -n airflow pod-name
```

### Monitor Training
```bash
# MLflow tracking
# Open http://mlflow-tracking.mlflow.svc.cluster.local:5000

# Evidently dashboards
# Open http://evidently-ui.mlops.svc.cluster.local:8000

# AWS Batch logs
# CloudWatch → /aws/batch/job
```

---

## File Organization

```
mlops/
├── dags/                       # Airflow DAGs (Airflow 3.0.6)
│   ├── training_pipeline_dag.py
│   ├── model_deploy_dag.py
│   └── ...
├── tasks/                      # Task implementations
│   ├── drift_detection.py      # PSI, new API detection
│   ├── preprocessing.py        # Encoding, scaling, splitting
│   ├── training.py             # Transformer AE training
│   ├── evaluation.py           # p99 threshold calculation
│   ├── model_deploy.py         # ConfigMap patching
│   └── ...
├── common/                     # Shared utilities
│   ├── util.py
│   └── encoders.py
├── transformer_ae/             # Model architecture
│   ├── model.py
│   ├── evaluate.py
│   └── config.yaml
├── tests/                      # Unit & integration tests
├── docs/                       # Documentation (you are here)
├── Dockerfile.airflow          # Airflow 3.0.6 image
├── Dockerfile.mlops            # Full GPU pipeline
├── Dockerfile.mlops-light      # CPU-only lightweight
├── airflow-requirements.txt    # Airflow dependencies
├── requirements-mlops.txt      # Full pipeline dependencies
└── PIPELINE.md                 # Detailed pipeline docs (Vietnamese)
```

---

## Development Workflow

1. **Read:** Start with [Codebase Summary](./codebase-summary.md) to understand structure
2. **Design:** Review [System Architecture](./system-architecture.md) for component interactions
3. **Code:** Follow [Code Standards](./code-standards.md) for Python, Airflow, PyTorch conventions
4. **Deploy:** Use [Deployment Guide](./deployment-guide.md) for setup & configuration
5. **Monitor:** Check MLflow, Evidently, Airflow UI for metrics & logs

---

## Troubleshooting

### Airflow DAG Not Showing Up
```bash
# Check DAG syntax
airflow dags list
airflow dags show training_pipeline

# Verify airflow_home and dags_folder in airflow.cfg
# Restart scheduler
kubectl rollout restart deployment/airflow-scheduler -n airflow
```

### Training Job Fails
```bash
# Check Batch logs
aws batch describe-jobs --jobs {job_id} --region us-east-1

# Check Airflow task logs
kubectl logs -n airflow {pod_name}

# Common issues:
# - GPU quota exceeded → Request AWS quota increase
# - S3 access denied → Check IAM role, AWS credentials
# - Out of memory → Reduce batch_size or sequence_length
```

### Model Deploy ConfigMap Patch Fails
```bash
# Check anomaly-detection namespace
kubectl get configmap -n anomaly-detection

# Verify ServiceAccount permissions
kubectl get rolebindings -n anomaly-detection

# Manual patch (fallback)
kubectl patch configmap anomaly-detection-service-config -n anomaly-detection \
  -p '{"data": {"ANOMALY_THRESHOLD": "0.95", "MODEL_S3_PATH": "s3://..."}}'
```

### S3 Data Not Found
```bash
# List S3 bucket contents
aws s3 ls s3://kltn-anomaly-dateset-1/mlops/ --recursive

# Check IAM bucket policy
aws s3api get-bucket-policy --bucket kltn-anomaly-dateset-1

# Verify region (ap-southeast-1)
aws s3api head-bucket --bucket kltn-anomaly-dateset-1 --region ap-southeast-1
```

---

## Performance Tuning

### Faster Training
- **Increase batch_size** (64 → 128) — faster per-epoch, higher GPU memory usage
- **Reduce sequence_length** (20 → 10) — faster, less pattern capture
- **Use lower d_model** (64 → 32) — smaller model, faster training
- **Enable mixed precision** — PyTorch AMP for 2x speedup (requires code change)

### Lower Costs
- **Use Spot instances** (default in Batch) — 70% savings vs on-demand
- **Reduce training frequency** — Trigger only on significant drift (PSI > 0.3)
- **Archive old models** — Clean up S3 after 30 days retention
- **Use CPU-only images** for lightweight tasks (preprocessing)

### Better Accuracy
- **Longer sequences** (20 → 50) — capture longer-range dependencies
- **More encoder layers** (2 → 3) — deeper attention mechanism
- **Larger latent dimension** (32 → 64) — richer bottleneck representation
- **Data augmentation** — Add noise, time-shift to training data

---

## References

- [Apache Airflow 3.0.6 Documentation](https://airflow.apache.org/docs/apache-airflow/3.0.6/)
- [Kubernetes Executor Guide](https://airflow.apache.org/docs/apache-airflow/3.0.6/executor/kubernetes.html)
- [PyTorch Transformer Documentation](https://pytorch.org/docs/stable/generated/torch.nn.Transformer.html)
- [MLflow Tracking](https://mlflow.org/docs/latest/tracking.html)
- [AWS Batch User Guide](https://docs.aws.amazon.com/batch/latest/userguide/)
- [Evidently Documentation](https://docs.evidentlyai.com/)

---

## Support & Contact

- **Issues:** Check troubleshooting section above
- **DAG Questions:** Review PIPELINE.md and system-architecture.md
- **Deployment:** Refer to deployment-guide.md
- **Code Review:** Follow code-standards.md conventions

---

**Last Updated:** June 6, 2024  
**Airflow Version:** 3.0.6  
**Python Version:** 3.12
