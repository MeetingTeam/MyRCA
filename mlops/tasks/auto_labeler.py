"""Auto-label test_df với `is_anomaly` dựa latency + error rule.

Adapted from user-provided latency-based labeling function for post-preprocessing
DataFrames (service/operation already int-encoded, http_status grouped 1-5,
duration_ns preserved raw).
"""
import logging

import pandas as pd

from configs.constants import DELIMITER

log = logging.getLogger(__name__)


def _build_group_operation(df: pd.DataFrame) -> pd.Series:
    """group_operation key = service//operation//parent_op//http_status."""
    op = df["service"].astype(str) + DELIMITER + df["operation"].astype(str)
    span_to_op = dict(zip(df["spanId"], op))
    parent_op = df["parentSpanId"].map(span_to_op).fillna("None")
    return op + DELIMITER + parent_op + DELIMITER + df["http_status"].astype(str)


def _get_latency_upper_bound(normal_df: pd.DataFrame, duration_col: str) -> dict:
    """Per-group_operation upper bound = quantile(0.98) * 5."""
    return {
        op: group[duration_col].quantile(0.98) * 5
        for op, group in normal_df.groupby("group_operation")
    }


def auto_label_test_df(
    normal_df: pd.DataFrame,
    test_df: pd.DataFrame,
    duration_col: str = "duration_ns",
    chunk_size: int = 20,
    chunk_stride: int = 2,
    anomaly_ratio: float = 0.5,
) -> pd.DataFrame:
    """Label test_df with `is_anomaly` (bool). Returns a labeled copy.

    Rules (preserved from source function):
      1. is_span_anomaly = duration > 5x quantile(0.98) per group_operation.
      2. is_anomaly per chunk: chunk of `chunk_size` spans (stride `chunk_stride`)
         marks all spans in chunk anomaly when >= `anomaly_ratio` span-anomalies.
      3. Force is_anomaly=True for span_status==2 OR http_status==5.
    """
    normal_df = normal_df.copy()
    test_df = test_df.copy()

    normal_df["group_operation"] = _build_group_operation(normal_df)
    test_df["group_operation"] = _build_group_operation(test_df)

    upper_bounds = _get_latency_upper_bound(normal_df, duration_col)
    test_df["upper_bound"] = test_df["group_operation"].map(upper_bounds)

    test_df["is_span_anomaly"] = (
        (~test_df["upper_bound"].isna())
        & (test_df[duration_col] > test_df["upper_bound"])
    )

    test_df["is_anomaly"] = False
    for _, group in test_df.groupby("group_operation", sort=False):
        group = group.sort_values("startTime")
        for start_idx in range(0, len(group), chunk_stride):
            chunk = group.iloc[start_idx:start_idx + chunk_size]
            if chunk["is_span_anomaly"].mean() >= anomaly_ratio:
                test_df.loc[chunk.index, "is_anomaly"] = True

    test_df.loc[test_df["span_status"] == 2, "is_anomaly"] = True
    test_df.loc[test_df["http_status"] == 5, "is_anomaly"] = True

    n_anomaly = int(test_df["is_anomaly"].sum())
    log.info(
        "Auto-labeled %d/%d spans as anomaly (%.2f%%)",
        n_anomaly, len(test_df), 100 * n_anomaly / max(len(test_df), 1),
    )

    return test_df.drop(columns=["group_operation", "upper_bound", "is_span_anomaly"])
