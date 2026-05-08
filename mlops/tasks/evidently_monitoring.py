"""
Evidently Monitoring Module for Span Data
─────────────────────────────────────────
Context class using Strategy Pattern + Workspace integration.
Provides SpanMonitoring for drift detection and WorkspaceManager for UI.
"""

import os
import logging
from typing import Optional

import pandas as pd
from evidently import ColumnMapping
from evidently.ui.workspace import Workspace

from tasks.evidently_strategies import (
    ReportStrategy,
    DataDriftStrategy,
    DataQualityStrategy,
    DriftTestSuiteStrategy,
)

log = logging.getLogger("evidently-monitoring")

MIN_SAMPLE_SIZE = int(os.getenv("EVIDENTLY_MIN_SAMPLES", "100"))
DRIFT_COLUMN_THRESHOLD = int(os.getenv("EVIDENTLY_DRIFT_THRESHOLD", "2"))


class SpanMonitoring:
    """Context class for Evidently monitoring using Strategy Pattern."""

    def __init__(
        self,
        strategy: ReportStrategy = None,
        numeric_features: list[str] = None,
        categorical_features: list[str] = None,
    ):
        self._strategy = strategy or DriftTestSuiteStrategy(DRIFT_COLUMN_THRESHOLD)
        self.numeric_features = numeric_features or ["duration_ns", "duration"]
        self.categorical_features = categorical_features or ["service", "operation"]
        self.column_mapping = None

    @property
    def strategy(self) -> ReportStrategy:
        return self._strategy

    @strategy.setter
    def strategy(self, strategy: ReportStrategy):
        self._strategy = strategy

    def validate_and_filter_columns(
        self, reference: pd.DataFrame, current: pd.DataFrame
    ) -> tuple[list[str], list[str]]:
        """Validate columns exist in both dataframes with compatible dtypes."""
        valid_numeric = [
            col for col in self.numeric_features
            if col in reference.columns and col in current.columns
            and pd.api.types.is_numeric_dtype(reference[col])
        ]
        valid_categorical = [
            col for col in self.categorical_features
            if col in reference.columns and col in current.columns
        ]

        if not valid_numeric and not valid_categorical:
            raise ValueError("No valid columns for drift detection")

        log.info("Validated: numeric=%s, categorical=%s", valid_numeric, valid_categorical)
        return valid_numeric, valid_categorical

    def check_sample_size(self, reference: pd.DataFrame, current: pd.DataFrame) -> bool:
        """Check minimum sample sizes for statistical tests."""
        return len(reference) >= MIN_SAMPLE_SIZE and len(current) >= MIN_SAMPLE_SIZE

    def prepare_column_mapping(
        self, reference: pd.DataFrame, current: pd.DataFrame
    ) -> ColumnMapping:
        """Create ColumnMapping with validated columns."""
        numeric, categorical = self.validate_and_filter_columns(reference, current)
        self.column_mapping = ColumnMapping(
            numerical_features=numeric or None,
            categorical_features=categorical or None,
        )
        return self.column_mapping

    def execute(
        self,
        reference: pd.DataFrame,
        current: pd.DataFrame,
        workspace=None,
        project_id: Optional[str] = None,
    ):
        """Execute current strategy to generate report."""
        if self.column_mapping is None:
            self.prepare_column_mapping(reference, current)

        return self._strategy.create_report(
            reference, current, self.column_mapping, workspace, project_id
        )

    def create_test_suite(
        self, reference: pd.DataFrame, current: pd.DataFrame
    ):
        """Create test suite using DriftTestSuiteStrategy."""
        original_strategy = self._strategy
        self._strategy = DriftTestSuiteStrategy(DRIFT_COLUMN_THRESHOLD)
        try:
            return self.execute(reference, current)
        finally:
            self._strategy = original_strategy

    def create_drift_report(
        self, reference: pd.DataFrame, current: pd.DataFrame
    ):
        """Create drift report using DataDriftStrategy."""
        original_strategy = self._strategy
        self._strategy = DataDriftStrategy()
        try:
            return self.execute(reference, current)
        finally:
            self._strategy = original_strategy

    def get_drift_summary(self, test_suite) -> dict:
        """Extract drift summary for XCom. Defensive parsing with fallback."""
        try:
            result = test_suite.as_dict()
            tests = result.get("tests", [])

            if not tests:
                return self._fallback_summary()

            drift_detected = any(t.get("status") == "FAIL" for t in tests)
            failed_tests = [t.get("name") for t in tests if t.get("status") == "FAIL"]

            return {
                "drift_detected": drift_detected,
                "failed_tests": failed_tests,
                "total_tests": len(tests),
                "passed_tests": sum(1 for t in tests if t.get("status") == "SUCCESS"),
            }
        except Exception as e:
            log.error("Failed to parse Evidently result: %s", e)
            return self._fallback_summary()

    def _fallback_summary(self) -> dict:
        """Fallback summary when parsing fails."""
        return {"drift_detected": None, "failed_tests": [], "error": "parse_failed"}


class WorkspaceManager:
    """Manages Evidently UI Workspace and per-app projects."""

    def __init__(self, workspace_path: str = "monitoring_workspace"):
        self.workspace_path = workspace_path
        self._workspace = None

    def get_workspace(self) -> Workspace:
        """Get or create workspace."""
        if self._workspace is None:
            self._workspace = Workspace.create(self.workspace_path)
        return self._workspace

    def get_or_create_project(self, app_id: str) -> str:
        """Get or create project for app_id. Returns project_id."""
        ws = self.get_workspace()
        projects = ws.search_project(project_name=app_id)

        if projects:
            return projects[0].id

        project = ws.create_project(app_id)
        log.info("Created Evidently project: %s", app_id)
        return project.id

    def add_report(self, app_id: str, report):
        """Add report to app's project."""
        ws = self.get_workspace()
        project_id = self.get_or_create_project(app_id)
        ws.add_report(project_id=project_id, report=report)

    def add_test_suite(self, app_id: str, test_suite):
        """Add test suite to app's project."""
        ws = self.get_workspace()
        project_id = self.get_or_create_project(app_id)
        ws.add_test_suite(project_id=project_id, test_suite=test_suite)
