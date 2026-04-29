import time
import logging
import threading
from urllib.parse import urlparse
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("trace_rca_service")


class MetricsTracker:
    """
    Tracks cumulative realtime batch performance metrics.
    """

    def __init__(self):
        self.total_rca_processed_time = 0
        self.total_service_processed_time = 0
        self.total_spans_processed = 0
        self.total_run = 0

        self._lock = threading.Lock()
        log.info("Initialized MetricsTracker with empty metrics")

    def calculate_performance_metrics(self, df, record_timestamp, rca_processed_time):
        if df.empty:
            return

        batch_size = len(df)
        end_time = time.time_ns()

        with self._lock:
            self.total_run += 1
            self.total_spans_processed += batch_size
            self.total_rca_processed_time += rca_processed_time
            self.total_service_processed_time += (end_time - int(record_timestamp))

            log.info(
                "RCA total time: %.2f ns | Service total time: %.2f ns | Total run: %d | Total processed spans: %d spans",
                self.total_rca_processed_time,
                self.total_service_processed_time,
                self.total_run,
                self.total_spans_processed
            )