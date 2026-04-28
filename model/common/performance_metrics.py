import time
import logging
import threading
from urllib.parse import urlparse
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("anomaly-detection")


class MetricsTracker:
    """
    Tracks cumulative realtime batch performance metrics.

    Assumptions:
    - df["startTime"] and df["duration"] are in epoch nanoseconds
    """

    def __init__(self):
        self.total_ml_processed_time = 0
        self.total_service_processed_time = 0
        self.total_spans_processed = 0
        self.total_traces_processed = 0
        self.total_batches = 0

        self._lock = threading.Lock()
        log.info("Initialized MetricsTracker with empty metrics")

    def calculate_performance_metrics(self, write_buffer: list[pd.DataFrame]):
        if not write_buffer:
            return

        # Merge all DataFrames in batch
        df = pd.concat(write_buffer, ignore_index=True)

        if df.empty:
            return

        batch_size = len(df)
        end_time = time.time_ns()

        df["startTime"] = df["startTime"].astype("int64")
        df["duration"] = df["duration"].astype("int64")

        service_times = end_time - (df["startTime"] + df["duration"])
        ml_batch_processed_time = df["ml_batch_processed_time"].sum()

        with self._lock:
            self.total_spans_processed += batch_size
            self.total_ml_processed_time += ml_batch_processed_time
            self.total_service_processed_time += service_times.sum()
            self.total_batches += 1

            log.info(
                "ML total time: %.2f ns | Service total time: %.2f ns | Total processed spans: %d spans | Current batch processed: %d spans",
                self.total_ml_processed_time,
                self.total_service_processed_time,
                self.total_spans_processed,
                batch_size
            )