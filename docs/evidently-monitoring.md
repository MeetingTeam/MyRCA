# Evidently Monitoring

Data drift detection and monitoring for ML pipeline using Evidently AI.

## Overview

Evidently monitors span data drift between baseline (training) and current (inference) data. Integrated into Airflow `training_pipeline` DAG to trigger retraining when drift is detected.

## Deployment

| Property | Value |
|----------|-------|
| Namespace | `mlops` |
| Version | `0.4.33` |
| Image | `evidently/evidently-service:0.4.33` |
| Service | `evidently-ui:8000` (NodePort 30800) |
| Storage | 5Gi PVC (ebs-sc) |
| Workspace | `/workspace` (via `--workspace` CLI arg) |

**Note:** The container must be started with `evidently ui --workspace /workspace` to use the PVC for persistence. The `EVIDENTLY_WORKSPACE` env var alone is not sufficient.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Airflow training_pipeline DAG                     │
├─────────────────────────────────────────────────────────────────────┤
│  compact → drift_detection → check_drift → [retrain / no_retrain]  │
└─────────────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      drift_detection task                            │
│  ┌─────────────┐    ┌─────────────────┐    ┌───────────────┐       │
│  │ Load Data   │───▶│ SpanMonitoring  │───▶│ WorkspaceManager │    │
│  │ from S3     │    │ (Strategy Pattern)│   │ (RemoteWorkspace)│    │
│  └─────────────┘    └─────────────────┘    └───────────────┘       │
└─────────────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Evidently UI Service                              │
│  - Dashboard panels (Summary + Detailed)                             │
│  - Test suite storage                                                │
│  - Per-app projects (microservices-demo, k8s-repo-application)       │
└─────────────────────────────────────────────────────────────────────┘
```

## Key Components

### 1. SpanMonitoring (`mlops/tasks/evidently_monitoring.py`)

Context class using Strategy Pattern for drift detection.

**Features:**
- Numeric features: `duration_ns`, `duration`
- Categorical features: `service`, `operation`
- Column validation and dtype checking
- Sample size verification (min 100 samples)

**Strategies:**
| Strategy | Purpose |
|----------|---------|
| `DriftTestSuiteStrategy` | Test suite with drift tests (default) |
| `DataDriftStrategy` | Detailed drift report |
| `DataQualityStrategy` | Data quality metrics |

### 2. WorkspaceManager

Manages Evidently UI workspace and projects.

**Features:**
- Auto-create projects per app_id
- Dashboard panel configuration (Summary + Detailed)
- Remote workspace support (`http://evidently-ui.mlops.svc.cluster.local:8000`)

### 3. Dashboard Panels

| Panel | Type | Description |
|-------|------|-------------|
| Data Drift Tests: Summary | TestSuite (Aggregate) | Overall drift status per day |
| Data Drift Tests: Detailed | TestSuite (Detailed) | Per-column drift breakdown |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `USE_EVIDENTLY` | `true` | Enable Evidently drift detection |
| `EVIDENTLY_WORKSPACE` | - | Workspace URL (set in DAG) |
| `EVIDENTLY_MIN_SAMPLES` | `100` | Min samples for drift detection |
| `EVIDENTLY_DRIFT_THRESHOLD` | `2` | Max drifted columns before alert |
| `MIN_DRIFT_SAMPLES` | `10` | Lower threshold for testing |

## Test Results Interpretation

| Status | Meaning |
|--------|---------|
| SUCCESS (green) | No drift detected, data stable |
| FAIL (red) | Drift detected, data distribution changed |
| WARNING (yellow) | Partial drift or edge case |
| SKIPPED (purple) | Insufficient data or column not found |

## Access

```bash
# Port forward
kubectl port-forward svc/evidently-ui 8000:8000 -n mlops

# NodePort
http://<node-ip>:30800
```

## Files

| File | Purpose |
|------|---------|
| `mlops/tasks/evidently_monitoring.py` | SpanMonitoring + WorkspaceManager |
| `mlops/tasks/evidently_strategies.py` | Strategy Pattern implementations |
| `mlops/tasks/drift_detection.py` | Main drift detection logic |
| `opensource/evidently-ui/` | Helm chart for UI deployment |
