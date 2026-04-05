import requests
import logging
from datetime import datetime

log = logging.getLogger("trace-rca-service")

# Failure indicator patterns to search for in log messages
FAILURE_PATTERNS = [
    "outofmemory", "oom", "java.lang.OutOfMemoryError",
    "timeout", "timed out", "deadline exceeded",
    "connection refused", "connection reset",
    "nullpointer", "NullPointerException",
    "circuit breaker", "circuit open",
    "too many requests", "rate limit",
    "503", "502", "500",
]


class LokiLogExtractor:
    """Queries Loki for log evidence to support RCA analysis."""

    def __init__(self, loki_url: str = "http://loki.loki.svc.cluster.local:3100"):
        self.loki_url = loki_url.rstrip("/")

    def query_logs(
        self, service: str, start_ns: int, end_ns: int, limit: int = 15
    ) -> list[dict]:
        """Query ERROR/WARN logs by service name within a time window.

        Args:
            service: Service name (OTel Java Agent label: service_name).
            start_ns: Start time in nanoseconds since epoch.
            end_ns: End time in nanoseconds since epoch.
            limit: Max log lines to return.
        """
        query = f'{{service_name="{service}"}} |~ "(?i)(error|warn|fatal|exception)"'
        return self._query(query, start_ns, end_ns, limit)

    def query_logs_by_trace(self, trace_id: str, limit: int = 50) -> list[dict]:
        """Query logs correlated to a specific trace via trace_id injected by OTel Java Agent."""
        query = f'{{}} |= "{trace_id}"'
        return self._query(query, limit=limit)

    def query_logs_for_services(
        self, services: list[str], start_dt: datetime, end_dt: datetime, limit_per_svc: int = 15
    ) -> dict[str, list[dict]]:
        """Query logs for multiple services, returning {service: [logs]}."""
        start_ns = int(start_dt.timestamp() * 1e9)
        end_ns = int(end_dt.timestamp() * 1e9)

        result: dict[str, list[dict]] = {}
        for svc in services:
            try:
                result[svc] = self.query_logs(svc, start_ns, end_ns, limit_per_svc)
            except Exception as e:
                log.warning(f"Failed to query logs for {svc}: {e}")
                result[svc] = []
        return result

    def extract_indicators(self, logs: list[dict]) -> dict:
        """Extract failure indicators from log messages."""
        if not logs:
            return {
                "has_oom": False,
                "has_timeout": False,
                "has_connection_refused": False,
                "has_null_pointer": False,
                "error_count": 0,
                "warning_count": 0,
                "patterns_found": [],
            }

        text = " ".join(l.get("message", "").lower() for l in logs)
        patterns_found = [p for p in FAILURE_PATTERNS if p.lower() in text]

        return {
            "has_oom": any(k in text for k in ["outofmemory", "oom"]),
            "has_timeout": any(k in text for k in ["timeout", "timed out", "deadline exceeded"]),
            "has_connection_refused": "connection refused" in text,
            "has_null_pointer": "nullpointer" in text,
            "error_count": sum(1 for l in logs if "error" in l.get("level", "").lower()),
            "warning_count": sum(1 for l in logs if "warn" in l.get("level", "").lower()),
            "patterns_found": patterns_found,
        }

    # ── Private helpers ───────────────────────────────────────────────

    def _query(
        self, query: str, start_ns: int | None = None, end_ns: int | None = None, limit: int = 50
    ) -> list[dict]:
        """Execute a LogQL query_range against Loki HTTP API."""
        params: dict = {"query": query, "limit": limit}
        if start_ns is not None:
            params["start"] = start_ns
        if end_ns is not None:
            params["end"] = end_ns

        try:
            resp = requests.get(
                f"{self.loki_url}/loki/api/v1/query_range",
                params=params,
                timeout=10,
            )
            resp.raise_for_status()
            return self._parse(resp.json())
        except requests.RequestException as e:
            log.error(f"Loki query failed: {e}")
            return []

    @staticmethod
    def _parse(response_json: dict) -> list[dict]:
        """Parse Loki query_range response into flat list of log entries."""
        results = []
        data = response_json.get("data", {})
        for stream in data.get("result", []):
            labels = stream.get("stream", {})
            for ts, line in stream.get("values", []):
                results.append({
                    "timestamp": ts,
                    "message": line,
                    "service": labels.get("service_name", "unknown"),
                    "level": labels.get("severity", labels.get("level", "unknown")),
                })
        return results
