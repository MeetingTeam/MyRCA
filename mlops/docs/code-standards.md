# MLOps Code Standards

## File Organization

### Directory Structure

```
mlops/
├── dags/                    # Airflow DAG definitions (Airflow 3.0.6 syntax)
├── tasks/                   # Task implementations (operators, functions)
├── common/                  # Shared utilities and base classes
├── transformer_ae/          # Model architecture and inference
├── configs/                 # Configuration files (YAML, JSON)
├── tests/                   # Unit and integration tests
├── Dockerfile.*             # Multi-image build for deployment
├── *-requirements.txt       # Python dependencies by context
└── docs/                    # Documentation (markdown)
```

### File Naming Conventions

- **Python files:** `kebab-case.py` (e.g., `drift_detection.py`, `safe_label_encoder.py`)
- **DAGs:** `{name}_dag.py` (e.g., `training_pipeline_dag.py`)
- **Tests:** `test_{feature}.py` (e.g., `test_drift_detection.py`)
- **Config files:** `config.yaml`, `config.json`
- **Dockerfiles:** `Dockerfile.{context}` (e.g., `Dockerfile.airflow`, `Dockerfile.mlops-light`)

## Python Code Standards

### Imports

**Order:**
1. Standard library (`datetime`, `json`, `os`)
2. Third-party (`airflow`, `boto3`, `torch`, `pandas`)
3. Local imports (`from tasks import`, `from common import`)

**Example:**
```python
from datetime import datetime, timedelta
import json
import logging

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
import boto3
import pandas as pd

from common.util import load_s3_json
from common.encoders import SafeLabelEncoder
```

### Function & Variable Naming

- **Functions:** `snake_case()` (e.g., `calculate_psi()`, `read_batch_output()`)
- **Classes:** `PascalCase` (e.g., `SafeLabelEncoder`, `TransformerAutoencoder`)
- **Constants:** `UPPER_SNAKE_CASE` (e.g., `S3_BUCKET`, `BATCH_REGION`)
- **Private methods:** `_snake_case()` (e.g., `_validate_data()`)

### Docstrings

Use **Google-style docstrings** for functions:

```python
def calculate_psi(reference_dist: np.ndarray, current_dist: np.ndarray, 
                  bins: int = 10, threshold: float = 0.2) -> float:
    """Calculate Population Stability Index between two distributions.
    
    Args:
        reference_dist: Baseline distribution values (array-like).
        current_dist: Current period distribution values (array-like).
        bins: Number of quantile bins (default: 10).
        threshold: PSI alert threshold (default: 0.2).
    
    Returns:
        PSI value (float). Values > threshold indicate significant drift.
    
    Raises:
        ValueError: If distributions are empty or have mismatched shapes.
    
    Example:
        >>> reference = np.array([1, 2, 3, 4, 5])
        >>> current = np.array([1, 2, 3, 4, 6])
        >>> psi = calculate_psi(reference, current)
        >>> assert psi < 0.2  # No significant drift
    """
    # Implementation...
```

### Error Handling

Always use try-except with specific exception types:

```python
def read_batch_output(version_id: str, task_name: str, max_retries: int = 5) -> dict:
    """Read AWS Batch job output from S3."""
    s3 = boto3.client("s3", region_name=S3_REGION)
    
    for attempt in range(max_retries):
        try:
            response = s3.get_object(
                Bucket=S3_BUCKET,
                Key=f"mlops/batch-outputs/{version_id}/{task_name}_output.json",
            )
            return json.loads(response["Body"].read().decode("utf-8"))
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                if attempt == max_retries - 1:
                    raise ValueError(f"S3 output not found after {max_retries} retries")
                time.sleep(2 ** attempt)
            else:
                raise
```

### Type Hints

Use type hints for all functions:

```python
def preprocess_spans(df: pd.DataFrame, 
                     encoders: dict[str, SafeLabelEncoder],
                     scalers: dict[str, StandardScaler]) -> tuple[pd.DataFrame, dict]:
    """Preprocess spans with encoding and scaling."""
    # Implementation...
    return processed_df, metadata
```

### Logging

Use Python's `logging` module, not `print()`:

```python
import logging

logger = logging.getLogger(__name__)

def drift_detection_task(**context):
    logger.info(f"Starting drift detection for version {version_id}")
    try:
        psi_value = calculate_psi(ref_dist, curr_dist)
        logger.info(f"PSI calculated: {psi_value}")
    except Exception as e:
        logger.error(f"Drift detection failed: {str(e)}", exc_info=True)
        raise
```

## Airflow 3.0.6 DAG Standards

### DAG Definition

Use the Airflow 3.0.6 syntax:

```python
from datetime import datetime
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.empty import EmptyOperator  # Not DummyOperator

default_args = {
    "owner": "mlops",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
    "catchup": False,
}

with DAG(
    dag_id="training_pipeline",
    default_args=default_args,
    description="MLOps training pipeline",
    schedule=None,  # Changed from schedule_interval=None
    start_date=datetime(2024, 1, 1),
    tags=["mlops", "training"],
) as dag:
    task1 = PythonOperator(task_id="task1", python_callable=func1)
    task2 = PythonOperator(task_id="task2", python_callable=func2)
    
    task1 >> task2
```

### Deprecated Patterns (Airflow 2.10.4) → Removed

| Pattern | Status | Reason |
|---------|--------|--------|
| `schedule_interval=None` | Replaced with `schedule=None` | Airflow 3.0 syntax |
| `from airflow.utils.dates import days_ago()` | Use `datetime` or `pendulum` | Removed in 3.0 |
| `DummyOperator` | Use `EmptyOperator` | Renamed in 3.0 |
| Custom patches for KubernetesExecutor | Removed | Fixed in Airflow 3.0.6 |

### Task Conventions

1. **Task IDs:** `snake_case`, descriptive (e.g., `drift_detection`, `train_model`, `deploy_model`)
2. **Operators:** Choose correct operator type:
   - `KubernetesPodOperator` — lightweight, ephemeral tasks (drift detection, preprocessing)
   - `BatchOperator` — GPU-intensive tasks (training, evaluation)
   - `PythonOperator` — simple control logic (branching, aggregation)
   - `BranchPythonOperator` — conditional branching (drift decision)

3. **Sensor usage:** Avoid for tasks without external state checks; use `aws_batch_job_done()` waiter instead

## PyTorch Model Standards

### Model Definition

Place architecture in `transformer_ae/model.py`:

```python
import torch
import torch.nn as nn

class TransformerAutoencoder(nn.Module):
    """Transformer-based Autoencoder for sequence anomaly detection."""
    
    def __init__(self, input_dim: int, d_model: int, nhead: int, 
                 num_layers: int, dim_feedforward: int, latent_dim: int):
        super().__init__()
        self.input_projection = nn.Linear(input_dim, d_model)
        
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=dim_feedforward,
            dropout=0.1,
            batch_first=True,
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
        
        # Bottleneck
        self.latent_projection = nn.Linear(d_model, latent_dim)
        self.latent_expansion = nn.Linear(latent_dim, d_model)
        
        # Decoder (symmetric)
        decoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=dim_feedforward,
            batch_first=True,
        )
        self.decoder = nn.TransformerEncoder(decoder_layer, num_layers=num_layers)
        
        self.output_projection = nn.Linear(d_model, input_dim)
    
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Forward pass with shape (batch_size, seq_len, input_dim)."""
        # Implementation...
        return output
```

### Training Loop

```python
def train_epoch(model, train_loader, optimizer, criterion, device):
    model.train()
    total_loss = 0.0
    
    for batch_idx, (sequences, _) in enumerate(train_loader):
        sequences = sequences.to(device)
        optimizer.zero_grad()
        
        outputs = model(sequences)
        loss = criterion(outputs, sequences)
        
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
        optimizer.step()
        
        total_loss += loss.item()
    
    return total_loss / len(train_loader)
```

## Testing Standards

### Unit Tests

Place tests in `tests/test_{feature}.py`:

```python
import pytest
import numpy as np
from tasks.drift_detection import calculate_psi

def test_calculate_psi_no_drift():
    """Test PSI calculation with identical distributions."""
    dist = np.array([1, 2, 3, 4, 5] * 10)
    psi = calculate_psi(dist, dist)
    assert psi < 0.01  # Virtually zero for identical distributions

def test_calculate_psi_significant_drift():
    """Test PSI calculation with shifted distribution."""
    ref = np.array([1, 2, 3] * 10)
    current = np.array([5, 6, 7] * 10)
    psi = calculate_psi(ref, current)
    assert psi > 0.2  # Significant drift
```

### Integration Tests

Test full pipeline workflows:

```python
def test_training_pipeline_with_sample_data(airflow_home):
    """Test full training pipeline with mocked S3."""
    from dags.training_pipeline_dag import dag
    
    # Mock S3 data
    # Run DAG
    # Assert outputs in S3
```

### Test Fixtures

Use pytest fixtures for common setup:

```python
@pytest.fixture
def sample_spans_df():
    """Fixture for sample span data."""
    return pd.DataFrame({
        "spanId": ["a", "b", "c"],
        "service": ["api", "db", "cache"],
        "operation": ["GET", "query", "get"],
        "duration_ns": [100, 200, 150],
    })
```

## Documentation Standards

### Markdown Files

- Use ATX headings (`#`, `##`, `###`)
- Max line length: 120 chars
- Code blocks with syntax highlighting: `` ```python ``
- Tables for structured data

**Example structure:**
```markdown
# Title

## Overview
Brief description.

## Usage
How to use.

## Implementation Details
Deep dive.

## Examples
Code samples.

## Troubleshooting
Common issues.
```

### Inline Code Comments

Comment **why**, not **what**:

```python
# Bad
x = y * 2  # multiply by 2

# Good
# Apply learning rate schedule decay to prevent overfitting
lr = initial_lr * decay_factor
```

## CI/CD Standards

### Pre-commit Checks

1. **Linting:** `pylint` or `flake8` (code quality)
2. **Type checking:** `mypy` (type safety)
3. **Formatting:** `black` (code style)
4. **Testing:** `pytest` (unit + integration tests)

### Deployment Validation

Before pushing to main:
1. All tests pass
2. DAGs parse without syntax errors: `airflow dags list`
3. Docker images build successfully
4. No hardcoded credentials in code

## Security Standards

### Credentials & Secrets

- **Never commit** credentials, API keys, or secrets
- Use **environment variables** or **Kubernetes Secrets**
- Reference secrets via `k8s.V1EnvFromSource(secret_ref=...)`
- Use **IAM roles** for AWS access (no long-lived keys in code)

### Data Handling

- **Validate input** from S3 (schema validation, null checks)
- **Sanitize logs** to avoid leaking PII or sensitive data
- **Encrypt S3 objects** in transit (SSL) and at rest (S3-SSE)
- **Mask sensitive data** in Airflow logs (model paths, thresholds)

## Deprecation & Migration

### From Airflow 2.10.4

All new code must use Airflow 3.0.6 syntax:
- ✅ Use `schedule=None` (not `schedule_interval`)
- ✅ Use `EmptyOperator` (not `DummyOperator`)
- ✅ Use `datetime` or `pendulum` (not `days_ago()`)
- ❌ Remove custom KubernetesExecutor patches

### From Python 3.11 → 3.12

Ensure all dependencies support Python 3.12:
- Run `pip list --outdated` before upgrades
- Test with `python --version == 3.12.x`
