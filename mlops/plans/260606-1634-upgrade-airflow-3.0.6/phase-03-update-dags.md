---
phase: 3
title: "Update DAGs"
status: completed
priority: P1
effort: "20m"
dependencies: [2]
---

# Phase 3: Update DAGs

## Overview

Update DAG files for Airflow 3.0 compatibility. Most imports remain the same, but verify deprecated features.

**Status**: COMPLETED - All 4 DAGs updated:
- Replaced `days_ago` with `pendulum.today('UTC').add(days=-N)`
- Replaced `schedule_interval` with `schedule` parameter
- No deprecated context variable usage found
- DAGs verified to parse in 3.0.6 image

## Related Code Files

- Review: `mlops/dags/training_pipeline_dag.py`
- Review: `mlops/dags/model_deploy_dag.py`
- Review: `mlops/dags/kb_building_dag.py`
- Review: `mlops/dags/kb_deploy_dag.py`

## Breaking Changes to Check

| Deprecated (2.x) | Replacement (3.0) |
|------------------|-------------------|
| `execution_date` | `logical_date` |
| `next_execution_date` | `data_interval_end` |
| `prev_execution_date` | `data_interval_start` |
| `airflow.utils.dates.days_ago` | `pendulum.today('UTC').add(days=-N)` |
| `schedule_interval` | `schedule` |
| `SubDAG` | `TaskGroup` |

<!-- Updated: Validation Session 1 - Added days_ago deprecation per user decision -->

## Implementation Steps

1. **Replace `days_ago` with pendulum** (REQUIRED - validation decision):
   ```python
   # Old (deprecated)
   from airflow.utils.dates import days_ago
   start_date=days_ago(1)
   
   # New (Airflow 3.0)
   import pendulum
   start_date=pendulum.today('UTC').add(days=-1)
   ```

2. **Replace `schedule_interval` with `schedule`** (REQUIRED - discovered during cook):
   ```python
   # Old (deprecated)
   with DAG('dag_id', schedule_interval='@weekly', ...):
   
   # New (Airflow 3.0)
   with DAG('dag_id', schedule='@weekly', ...):
   ```

2. **Check for deprecated context variables**:
   ```bash
   grep -rn "execution_date\|prev_execution_date\|next_execution_date" mlops/dags/
   ```

3. **Verify imports are compatible**:
   ```python
   # These should still work in 3.0:
   from airflow import DAG
   from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
   from airflow.providers.amazon.aws.operators.batch import BatchOperator
   from airflow.operators.python import BranchPythonOperator, PythonOperator
   from airflow.operators.empty import EmptyOperator
   ```

3. **Test DAG parsing in new image**:
   ```bash
   docker run --rm asdads6495/my-airflow:3.0.6-test \
     airflow dags list
   ```

4. **Check for import errors**:
   ```bash
   docker run --rm asdads6495/my-airflow:3.0.6-test \
     python -c "import sys; sys.path.insert(0, '/opt/airflow/dags'); import training_pipeline_dag"
   ```

## Current DAG Analysis

Based on `training_pipeline_dag.py`:
- Uses `KubernetesPodOperator` ✓ (provider, compatible)
- Uses `BatchOperator` ✓ (provider, compatible)
- Uses `BranchPythonOperator` ✓ (compatible)
- Uses `EmptyOperator` ✓ (compatible)
- No `execution_date` usage found ✓
- No SubDAGs ✓

**Likely no changes needed** - DAGs use provider operators that are 3.0 compatible.

## Success Criteria

- [ ] No deprecated context variables found
- [ ] All DAGs parse without errors in 3.0 image
- [ ] Import validation passes
