from airflow import DAG
from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from kubernetes.client import models as k8s
import os
from airflow.utils.dates import days_ago
from airflow.operators.python import PythonOperator
from airflow.operators.bash import BashOperator
from airflow.operators.empty import EmptyOperator
import mlflow
from kubernetes import client, config
from datetime import datetime
from kubernetes.client import models as k8s

S3_ENDPOINT = os.getenv("S3_ENDPOINT", "s3.amazonaws.com")
S3_REGION = os.getenv("S3_REGION", "ap-southeast-7")
S3_BUCKET = os.getenv("S3_BUCKET", "kltn-anomaly-dateset")
S3_USE_SSL = os.getenv("S3_USE_SSL", "true").lower() == "true"

KB_BUILDER_IMAGE = os.getenv("KB_BUILDER_IMAGE", "hungtran679/kb_builder:latest")
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow.mlflow.svc.cluster.local:5000")
MLFLOW_KB_MODEL = os.getenv("MLFLOW_KB_MODEL", "rca-knowledge-base")

RCA_SERVICE_DEPLOYMENT = os.getenv("RCA_SERVICE_DEPLOYMENT", "trace-rca-service")
RCA_SERVICE_NAMESPACE = os.getenv("RCA_SERVICE_NAMESPACE", "rca")

def promote_model_to_production(**context):
    """
    Fetches the latest version registered by the K8s pod and updates alias.
    """
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    client = mlflow.MlflowClient()

    # In a real scenario, your K8s pod would write its version to XCom.
    # For now, we fetch the latest version of the model to promote it.
    versions = client.get_latest_versions(MLFLOW_KB_MODEL, stages=["None"])
    if not versions:
        raise Exception(f"No versions found for model {MLFLOW_KB_MODEL}")
    
    latest_version = versions[0].version
    
    client.set_registered_model_alias(
        name=MLFLOW_KB_MODEL,
        alias="production",
        version=latest_version
    )
    print(f"Promoted version {latest_version} of {MLFLOW_KB_MODEL} to @production")

def restart_deployment(**context):
    """
    Equivalent to:
    kubectl rollout restart deployment/<name> -n <namespace>
    """

    # Load config (choose one depending on environment)
    try:
        config.load_incluster_config()   # if running inside K8s
    except:
        raise Exception("Failed to load in-cluster config. Ensure this is running inside the cluster.")

    apps_v1 = client.AppsV1Api()
    now = datetime.utcnow().isoformat()

    patch = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "kubectl.kubernetes.io/restartedAt": now
                    }
                }
            }
        }
    }

    # Apply patch
    response = apps_v1.patch_namespaced_deployment(
        name=RCA_SERVICE_DEPLOYMENT,
        namespace=RCA_SERVICE_NAMESPACE,
        body=patch
    )

    return response

# --- DAG Definition ---
with DAG(
    'kb_building_dag',
    schedule_interval='@weekly',
    start_date=days_ago(1),
    catchup=False,
    tags=['kltn', 'mlops']
) as dag:

    # Step 1: Run the Training/Building Pod
    # AWS credentials from secret
    run_kb_k8s = KubernetesPodOperator(
        task_id='run_kb_building_pod',
        namespace='airflow',
        name='kb-builder-pod',
        image=KB_BUILDER_IMAGE,
        env_vars={
            'MLFLOW_TRACKING_URI': MLFLOW_TRACKING_URI,
            'S3_REGION': S3_REGION,
            'S3_BUCKET': S3_BUCKET,
            'AIRFLOW_RUN_ID': '{{ run_id }}'
        },
        env_from=[
            k8s.V1EnvFromSource(secret_ref=k8s.V1SecretEnvSource(name="airflow-aws-secret")),
        ],
        container_resources=k8s.V1ResourceRequirements(
            requests={"cpu": "200m", "memory": "256Mi"},
            limits={"cpu": "500m", "memory": "512Mi"}
        ),
        get_logs=True,
        on_finish_action="keep_pod",
        in_cluster=True,
    )

    # Step 2: Manual Approval Gate
    await_approval = EmptyOperator(
        task_id='manual_ui_approval',
    )

    # Step 3: Update MLflow Alias
    promote_to_prod = PythonOperator(
        task_id='update_mlflow_alias',
        python_callable=promote_model_to_production,
    )

    # Step 4: Refresh K8s Deployment (Trigger new Pods to pull new KB)
    refresh_deployment = PythonOperator(
        task_id='refresh_serving_pods',
        python_callable=restart_deployment
    )

    # Dependency Flow
    run_kb_k8s >> await_approval >> promote_to_prod >> refresh_deployment