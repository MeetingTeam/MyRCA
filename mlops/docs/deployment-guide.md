# MLOps Deployment Guide

## Airflow Deployment (3.0.6)

### Docker Image

The Airflow scheduler/webserver runs on Apache Airflow 3.0.6 (Python 3.12).

**Build:**
```bash
docker build -t asdads6495/my-airflow:3.0.6 -f Dockerfile.airflow .
```

**Image details:**
- Base: `apache/airflow:3.0.6-python3.12`
- Python: 3.12
- Providers: 
  - `apache-airflow-providers-cncf-kubernetes>=10.0.0` (KubernetesExecutor)
  - `apache-airflow-providers-amazon>=9.0.0` (BatchOperator)
- Additional packages: `kubernetes`, `mlflow-skinny`, `pendulum`

### Airflow 3.0.6 Upgrade Notes

Migrated from Airflow 2.10.4 → 3.0.6. Key changes:

| Aspect | 2.10.4 | 3.0.6 |
|--------|--------|-------|
| DAG schedule param | `schedule_interval` | `schedule` |
| Import paths | `airflow.utils.dates` | N/A (use `datetime` + `pendulum`) |
| Operator | `BashOperator` | `BashOperator` (unchanged) |
| Datetime | `days_ago()` | `pendulum` or `datetime` |

**DAG Configuration Example (3.0.6):**
```python
from datetime import datetime
from airflow import DAG
from airflow.operators.empty import EmptyOperator

with DAG(
    dag_id="my_dag",
    schedule=None,  # Changed from schedule_interval=None
    start_date=datetime(2024, 1, 1),
    catchup=False,
) as dag:
    task = EmptyOperator(task_id="dummy")
```

### Helm Deployment

Deploy via Helm (v1.15.0):

```bash
helm install airflow apache-airflow/airflow \
  --namespace airflow \
  --create-namespace \
  -f airflow-values.yaml
```

Configure:
- Executor: `KubernetesExecutor`
- Replicas: 1 scheduler, 1 webserver
- Image: `asdads6495/my-airflow:3.0.6`

## DAG Management

### Training Pipeline (DAG 1)

**DAG ID:** `training_pipeline`  
**Schedule:** Manual trigger (`schedule=None`)  
**Task flow:**
```
drift_detection → preprocess → train (Batch) → evaluate (Batch)
```

**Trigger via Airflow UI:**
1. Navigate to `http://<airflow>:30380`
2. Select "training_pipeline" DAG
3. Click "Trigger DAG"

**Trigger via CLI:**
```bash
airflow dags trigger training_pipeline
```

### Model Deploy (DAG 2)

**DAG ID:** `model_deploy`  
**Schedule:** Manual trigger with config  
**Task flow:**
```
deploy_model (with version_id parameter)
```

**Trigger with version:**
```bash
airflow dags trigger model_deploy \
  --conf '{"version_id": "v20240315-120000"}'
```

## Storage & Dependencies

| Component | Version | Purpose |
|-----------|---------|---------|
| MLflow | 2.12.2 | Model registry, tracking |
| AWS S3 | - | Training data, models, reports |
| DuckDB | latest | Data processing |
| PyTorch | latest | Model training |
| Kubernetes | - | Container orchestration |

## Troubleshooting

**DAG parsing errors with Airflow 3.0.6:**
- Ensure `schedule_interval` is replaced with `schedule` in all DAG files
- Use `pendulum` for datetime handling when needed
- Import `EmptyOperator` from `airflow.operators.empty` (not `airflow.operators.dummy`)

**Provider compatibility:**
- Verify `apache-airflow-providers-cncf-kubernetes>=10.0.0` for Airflow 3.0
- Verify `apache-airflow-providers-amazon>=9.0.0` for AWS Batch support
