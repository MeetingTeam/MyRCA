from airflow import DAG
from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
import os
import pendulum
from datetime import datetime
from kubernetes.client import models as k8s

KB_BUILDER_IMAGE="hungtran679/kb_builder"

# --- DAG Definition ---
with DAG(
    'kb_building_dag',
    schedule='@weekly',
    start_date=pendulum.today('UTC').add(days=-1),
    catchup=False,
    tags=['mlops', 'kb_building']
) as dag:

    # Run the Training/Building Pod
    run_kb_k8s = KubernetesPodOperator(
        task_id='run_kb_building_pod',
        namespace='airflow',
        name='kb-builder-pod',
        image=KB_BUILDER_IMAGE,
        image_pull_policy="Always",
        env_from=[
            k8s.V1EnvFromSource(secret_ref=k8s.V1SecretEnvSource(name="airflow-aws-secret")),
            k8s.V1EnvFromSource(secret_ref=k8s.V1SecretEnvSource(name="airflow-clickhouse-secret")),
            k8s.V1EnvFromSource(config_map_ref=k8s.V1ConfigMapEnvSource(name="airflow-kb-builder-configmap"))
        ],
        env_vars=[
            k8s.V1EnvVar(
                name="AIRFLOW_RUN_ID",
                value="{{ run_id }}"
            )
        ],
        container_resources=k8s.V1ResourceRequirements(
            requests={"cpu": "200m", "memory": "512Mi"},
            limits={"cpu": "500m", "memory": "1Gi"}
        ),
        get_logs=True,
        on_finish_action="keep_pod",
        in_cluster=True,
        startup_timeout_seconds=900
    )