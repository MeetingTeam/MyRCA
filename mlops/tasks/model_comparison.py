"""
Step 5: Model Comparison
------------------------
Compares evaluation metrics between newly trained model and current champion.
Outputs a RECOMMENDATION for admin review. Does NOT auto-promote.

Admin uses model_deploy DAG to manually set champion after review.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("model-comparison")

PRECISION_TOLERANCE = float(os.getenv("COMPARISON_PRECISION_TOLERANCE", "0.05"))
RECALL_TOLERANCE = float(os.getenv("COMPARISON_RECALL_TOLERANCE", "0.05"))
MODEL_NAME = "transformer-ae"


def get_run_metrics(client, run_id: str) -> dict:
    """Fetch metrics from MLflow run."""
    run = client.get_run(run_id)
    return run.data.metrics


def get_champion_info(client) -> tuple[Optional[str], Optional[str], dict]:
    """Get current champion model version, run_id, and metrics."""
    try:
        champion = client.get_model_version_by_alias(MODEL_NAME, "champion")
        metrics = get_run_metrics(client, champion.run_id)
        return champion.version, champion.run_id, metrics
    except Exception as e:
        log.info("No champion model found: %s", e)
        return None, None, {}


def get_challenger_info(client, version_id: str) -> tuple[Optional[str], Optional[str], dict]:
    """Get challenger model version, run_id, and metrics by version_id tag."""
    try:
        versions = client.search_model_versions(
            f"name='{MODEL_NAME}'", max_results=50, order_by=["creation_timestamp DESC"]
        )
        for v in versions:
            run = client.get_run(v.run_id)
            if run.data.tags.get("version_id") == version_id:
                return v.version, v.run_id, run.data.metrics
        log.warning("No model version found for version_id: %s", version_id)
        return None, None, {}
    except Exception as e:
        log.error("Failed to get challenger info: %s", e)
        return None, None, {}


def evaluate_comparison_gates(champion_metrics: dict, challenger_metrics: dict) -> tuple[bool, list]:
    """Evaluate metrics comparison gates."""
    gates = []

    # Gate 1: F1 score - no regression (1% noise tolerance)
    champ_f1 = champion_metrics.get("f1_score", 0)
    chal_f1 = challenger_metrics.get("f1_score", 0)
    f1_passed = chal_f1 >= champ_f1 * 0.99
    gates.append({
        "metric": "f1_score",
        "champion": round(champ_f1, 4),
        "challenger": round(chal_f1, 4),
        "passed": f1_passed,
        "rule": "challenger >= champion * 0.99"
    })

    # Gate 2: Precision - 5% tolerance
    champ_prec = champion_metrics.get("precision", 0)
    chal_prec = challenger_metrics.get("precision", 0)
    prec_passed = chal_prec >= champ_prec * (1 - PRECISION_TOLERANCE)
    gates.append({
        "metric": "precision",
        "champion": round(champ_prec, 4),
        "challenger": round(chal_prec, 4),
        "passed": prec_passed,
        "rule": f"challenger >= champion * {1 - PRECISION_TOLERANCE}"
    })

    # Gate 3: Recall - 5% tolerance
    champ_rec = champion_metrics.get("recall", 0)
    chal_rec = challenger_metrics.get("recall", 0)
    rec_passed = chal_rec >= champ_rec * (1 - RECALL_TOLERANCE)
    gates.append({
        "metric": "recall",
        "champion": round(champ_rec, 4),
        "challenger": round(chal_rec, 4),
        "passed": rec_passed,
        "rule": f"challenger >= champion * {1 - RECALL_TOLERANCE}"
    })

    return all(g["passed"] for g in gates), gates


def save_comparison_report(s3_client, bucket: str, version_id: str, report: dict):
    """Save comparison report to S3 for admin review."""
    s3_client.put_object(
        Bucket=bucket,
        Key=f"mlops/model-comparisons/{version_id}/comparison.json",
        Body=json.dumps(report, indent=2),
        ContentType="application/json",
    )
    log.info("Comparison report saved to s3://%s/mlops/model-comparisons/%s/", bucket, version_id)


def run():
    version_id = os.getenv("VERSION_ID")
    if not version_id:
        log.error("VERSION_ID not set")
        sys.exit(1)

    log.info("Model comparison starting, version_id=%s", version_id)

    import boto3
    from mlflow.tracking import MlflowClient
    from tasks.mlflow_utils import setup_mlflow
    setup_mlflow()
    client = MlflowClient()

    s3_client = boto3.client("s3", region_name=os.getenv("S3_REGION", "ap-southeast-1"))
    bucket = os.getenv("S3_BUCKET", "kltn-anomaly-dateset-1")

    champion_ver, champion_run, champion_metrics = get_champion_info(client)
    challenger_ver, challenger_run, challenger_metrics = get_challenger_info(client, version_id)

    report = {
        "version_id": version_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "champion": {
            "model_version": champion_ver,
            "run_id": champion_run,
            "metrics": {k: round(v, 4) for k, v in champion_metrics.items()} if champion_metrics else None,
        },
        "challenger": {
            "model_version": challenger_ver,
            "run_id": challenger_run,
            "metrics": {k: round(v, 4) for k, v in challenger_metrics.items()} if challenger_metrics else None,
        },
    }

    if champion_ver is None:
        log.info("No existing champion - this is the first model")
        report["recommendation"] = "PROMOTE"
        report["reason"] = "first_model"
        report["gate_results"] = []
        report["action"] = f"Run: airflow dags trigger model_deploy --conf '{{\"version_id\": \"{version_id}\"}}'"
    elif not challenger_ver:
        log.warning("Could not find challenger model for version_id: %s", version_id)
        report["recommendation"] = "ERROR"
        report["reason"] = "challenger_not_found"
        report["gate_results"] = []
    else:
        log.info("Comparing: champion v%s vs challenger v%s", champion_ver, challenger_ver)
        passed, gate_results = evaluate_comparison_gates(champion_metrics, challenger_metrics)

        for gate in gate_results:
            status = "PASS" if gate["passed"] else "FAIL"
            log.info("Gate %s: %s (champion=%.4f, challenger=%.4f)",
                     gate["metric"], status, gate["champion"], gate["challenger"])

        report["gate_results"] = gate_results
        report["all_gates_passed"] = passed

        if passed:
            report["recommendation"] = "PROMOTE"
            report["reason"] = "all_gates_passed"
            report["action"] = f"Run: airflow dags trigger model_deploy --conf '{{\"version_id\": \"{version_id}\"}}'"
        else:
            report["recommendation"] = "KEEP_CURRENT"
            report["reason"] = "gates_failed"
            report["failed_gates"] = [g["metric"] for g in gate_results if not g["passed"]]

    save_comparison_report(s3_client, bucket, version_id, report)

    xcom_dir = "/airflow/xcom"
    if os.path.exists(os.path.dirname(xcom_dir)) or os.path.exists("/airflow"):
        os.makedirs(xcom_dir, exist_ok=True)
        with open(os.path.join(xcom_dir, "return.json"), "w") as f:
            json.dump(report, f)

    log.info("Model comparison complete: recommendation=%s", report.get("recommendation"))

    if report.get("recommendation") == "PROMOTE":
        log.info("=" * 60)
        log.info("RECOMMENDATION: PROMOTE challenger to champion")
        log.info("ACTION: %s", report.get("action", ""))
        log.info("=" * 60)


if __name__ == "__main__":
    run()
