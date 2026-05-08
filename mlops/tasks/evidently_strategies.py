"""
Evidently Report Strategies
───────────────────────────
Abstract base class + concrete strategies for different report types.
Uses Strategy Pattern for flexible, swappable drift detection approaches.
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

import pandas as pd
from evidently import ColumnMapping
from evidently.report import Report
from evidently.metric_preset import DataDriftPreset, DataQualityPreset
from evidently.test_suite import TestSuite
from evidently.test_preset import DataDriftTestPreset
from evidently.tests import TestNumberOfDriftedColumns

log = logging.getLogger("evidently-strategies")


class ReportStrategy(ABC):
    """Abstract strategy for Evidently report generation."""

    @abstractmethod
    def create_report(
        self,
        reference: pd.DataFrame,
        current: pd.DataFrame,
        column_mapping: ColumnMapping,
        workspace=None,
        project_id: Optional[str] = None,
    ):
        """Generate report and optionally add to workspace."""
        pass


class DataDriftStrategy(ReportStrategy):
    """Strategy for DataDriftPreset report (visual drift metrics)."""

    def create_report(self, reference, current, column_mapping, workspace=None, project_id=None):
        report = Report(
            metrics=[DataDriftPreset()],
            timestamp=datetime.now(),
            tags=["drift_report"],
        )
        report.run(reference_data=reference, current_data=current, column_mapping=column_mapping)

        if workspace and project_id:
            workspace.add_report(project_id=project_id, report=report)

        return report


class DataQualityStrategy(ReportStrategy):
    """Strategy for DataQualityPreset report (missing values, duplicates, etc.)."""

    def create_report(self, reference, current, column_mapping, workspace=None, project_id=None):
        report = Report(
            metrics=[DataQualityPreset()],
            timestamp=datetime.now(),
            tags=["quality_report"],
        )
        report.run(reference_data=reference, current_data=current, column_mapping=column_mapping)

        if workspace and project_id:
            workspace.add_report(project_id=project_id, report=report)

        return report


class DriftTestSuiteStrategy(ReportStrategy):
    """Strategy for TestSuite with pass/fail drift tests."""

    def __init__(self, drift_threshold: int = 2):
        """
        Args:
            drift_threshold: Max number of drifted columns before test fails.
        """
        self.drift_threshold = drift_threshold

    def create_report(self, reference, current, column_mapping, workspace=None, project_id=None):
        suite = TestSuite(
            tests=[
                DataDriftTestPreset(),
                TestNumberOfDriftedColumns(lt=self.drift_threshold),
            ]
        )
        suite.run(reference_data=reference, current_data=current, column_mapping=column_mapping)

        if workspace and project_id:
            workspace.add_test_suite(project_id=project_id, test_suite=suite)

        return suite
