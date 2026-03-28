"""
Step 5: Model Deploy (DAG 2 only)
─────────────────────────────────
Reads metadata.json from S3 for the given version_id, patches the
anomaly-detection-service ConfigMap with new threshold and model path,
and triggers a rolling restart of the deployment.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone

import boto3
from kubernetes import client, config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("model-deploy")

NAMESPACE = "anomaly-detection"
CONFIGMAP_NAME = "anomaly-detection-service-config"
DEPLOYMENT_NAME = "anomaly-detection-service"


def run():
    version_id = os.getenv("VERSION_ID")
    if not version_id:
        log.error("VERSION_ID not set")
        sys.exit(1)

    log.info("Model deploy starting, version_id=%s", version_id)

    # Download metadata from S3
    s3_client = boto3.client("s3", region_name=os.getenv("S3_REGION", "ap-southeast-1"))
    bucket = os.getenv("S3_BUCKET", "kltn-anomaly-dateset-1")

    local_dir = "/tmp/mlops_deploy"
    os.makedirs(local_dir, exist_ok=True)
    metadata_local = os.path.join(local_dir, "metadata.json")

    try:
        s3_client.download_file(bucket, f"mlops/models/{version_id}/metadata.json", metadata_local)
    except Exception as e:
        log.error("Failed to download metadata for version %s: %s", version_id, e)
        sys.exit(1)

    with open(metadata_local) as f:
        metadata = json.load(f)

    threshold = str(metadata["threshold"])
    model_s3_path = metadata["model_s3_path"]

    log.info("Deploying model: version=%s, threshold=%s, path=%s", version_id, threshold, model_s3_path)

    # Load in-cluster Kubernetes config
    config.load_incluster_config()
    v1 = client.CoreV1Api()
    apps_v1 = client.AppsV1Api()

    # Patch ConfigMap
    cm_patch = {
        "data": {
            "ANOMALY_THRESHOLD": threshold,
            "MODEL_S3_PATH": model_s3_path,
            "MODEL_VERSION": version_id,
        }
    }
    v1.patch_namespaced_config_map(CONFIGMAP_NAME, NAMESPACE, cm_patch)
    log.info("ConfigMap %s patched", CONFIGMAP_NAME)

    # Trigger rolling restart by patching deployment annotation
    restart_patch = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "kubectl.kubernetes.io/restartedAt": datetime.now(timezone.utc).isoformat()
                    }
                }
            }
        }
    }
    apps_v1.patch_namespaced_deployment(DEPLOYMENT_NAME, NAMESPACE, restart_patch)
    log.info("Deployment %s rolling restart triggered", DEPLOYMENT_NAME)

    # Transition model to Production in MLflow (optional, best-effort)
    try:
        import mlflow
        mlflow_uri = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow.mlflow.svc.cluster.local:5000")
        mlflow.set_tracking_uri(mlflow_uri)
        mlflow_client = mlflow.tracking.MlflowClient()

        # Find latest version of the model
        versions = mlflow_client.search_model_versions(f"name='transformer-ae'")
        for v in versions:
            if v.run_id and version_id in (v.tags.get("version_id", "") if v.tags else ""):
                mlflow_client.transition_model_version_stage(
                    name="transformer-ae",
                    version=v.version,
                    stage="Production",
                )
                log.info("MLflow model version %s transitioned to Production", v.version)
                break
    except Exception as e:
        log.warning("Could not update MLflow model stage: %s", e)

    log.info("Model deploy complete for version %s", version_id)


if __name__ == "__main__":
    run()
