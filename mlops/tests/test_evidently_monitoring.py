"""
Unit tests for Evidently monitoring module.
Tests drift detection, no-drift scenarios, and XCom format validation.
"""

import pytest
import pandas as pd
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tasks.evidently_monitoring import SpanMonitoring
from tasks.evidently_strategies import DataDriftStrategy, DriftTestSuiteStrategy


@pytest.fixture
def sample_reference():
    """Reference data with stable distribution."""
    return pd.DataFrame({
        "duration_ns": [100, 200, 150, 180, 220, 190, 210, 170, 160, 140] * 10,
        "duration": [0.1, 0.2, 0.15, 0.18, 0.22, 0.19, 0.21, 0.17, 0.16, 0.14] * 10,
        "service": ["svc-a", "svc-b"] * 50,
        "operation": ["op1", "op2"] * 50,
    })


@pytest.fixture
def sample_current_no_drift(sample_reference):
    """Current data with similar distribution (no drift)."""
    return sample_reference.copy()


@pytest.fixture
def sample_current_with_drift():
    """Current data with significant drift (10x duration)."""
    return pd.DataFrame({
        "duration_ns": [1000, 2000, 1500, 1800, 2200, 1900, 2100, 1700, 1600, 1400] * 10,
        "duration": [1.0, 2.0, 1.5, 1.8, 2.2, 1.9, 2.1, 1.7, 1.6, 1.4] * 10,
        "service": ["svc-a", "svc-b", "svc-c"] * 33 + ["svc-d"],
        "operation": ["op1", "op2", "op3"] * 33 + ["op4"],
    })


class TestSpanMonitoring:
    """Test cases for SpanMonitoring class."""

    def test_validate_columns_success(self, sample_reference, sample_current_no_drift):
        """Test column validation with valid columns."""
        monitor = SpanMonitoring(
            numeric_features=["duration_ns"],
            categorical_features=["service", "operation"],
        )
        numeric, categorical = monitor.validate_and_filter_columns(
            sample_reference, sample_current_no_drift
        )
        assert "duration_ns" in numeric
        assert "service" in categorical
        assert "operation" in categorical

    def test_validate_columns_missing(self, sample_reference):
        """Test column validation with missing columns."""
        monitor = SpanMonitoring(
            numeric_features=["nonexistent_col"],
            categorical_features=[],
        )
        with pytest.raises(ValueError, match="No valid columns"):
            monitor.validate_and_filter_columns(sample_reference, sample_reference)

    def test_check_sample_size_pass(self, sample_reference, sample_current_no_drift):
        """Test sample size check with sufficient data."""
        monitor = SpanMonitoring()
        assert monitor.check_sample_size(sample_reference, sample_current_no_drift) is True

    def test_check_sample_size_fail(self):
        """Test sample size check with insufficient data."""
        small_df = pd.DataFrame({"duration_ns": [1, 2, 3]})
        monitor = SpanMonitoring()
        assert monitor.check_sample_size(small_df, small_df) is False

    def test_create_drift_report(self, sample_reference, sample_current_no_drift):
        """Test drift report generation."""
        monitor = SpanMonitoring(
            numeric_features=["duration_ns"],
            categorical_features=["service", "operation"],
        )
        report = monitor.create_drift_report(sample_reference, sample_current_no_drift)
        assert report is not None

    def test_create_test_suite(self, sample_reference, sample_current_no_drift):
        """Test suite generation."""
        monitor = SpanMonitoring(
            numeric_features=["duration_ns"],
            categorical_features=["service", "operation"],
        )
        suite = monitor.create_test_suite(sample_reference, sample_current_no_drift)
        assert suite is not None

    def test_no_drift_detected(self, sample_reference, sample_current_no_drift):
        """Test that similar distributions show no drift."""
        monitor = SpanMonitoring(
            numeric_features=["duration_ns"],
            categorical_features=["service", "operation"],
        )
        suite = monitor.create_test_suite(sample_reference, sample_current_no_drift)
        summary = monitor.get_drift_summary(suite)
        assert summary["drift_detected"] is False

    def test_drift_detected(self, sample_reference, sample_current_with_drift):
        """Test that significantly different distributions show drift."""
        monitor = SpanMonitoring(
            numeric_features=["duration_ns"],
            categorical_features=["service", "operation"],
        )
        suite = monitor.create_test_suite(sample_reference, sample_current_with_drift)
        summary = monitor.get_drift_summary(suite)
        assert summary["drift_detected"] is True
        assert len(summary["failed_tests"]) > 0

    def test_summary_format_xcom_compatible(self, sample_reference, sample_current_with_drift):
        """Test that summary format is XCom-compatible."""
        monitor = SpanMonitoring()
        suite = monitor.create_test_suite(sample_reference, sample_current_with_drift)
        summary = monitor.get_drift_summary(suite)

        # Verify XCom-compatible format
        assert "drift_detected" in summary
        assert isinstance(summary["drift_detected"], bool)
        assert "failed_tests" in summary
        assert isinstance(summary["failed_tests"], list)
        assert "total_tests" in summary
        assert "passed_tests" in summary

    def test_strategy_switching(self, sample_reference, sample_current_no_drift):
        """Test runtime strategy switching."""
        monitor = SpanMonitoring()

        # Default strategy is DriftTestSuite
        assert isinstance(monitor.strategy, DriftTestSuiteStrategy)

        # Switch to DataDrift strategy
        monitor.strategy = DataDriftStrategy()
        assert isinstance(monitor.strategy, DataDriftStrategy)

        # Execute with new strategy
        report = monitor.execute(sample_reference, sample_current_no_drift)
        assert report is not None


class TestDriftStrategies:
    """Test cases for individual strategies."""

    def test_data_drift_strategy(self, sample_reference, sample_current_no_drift):
        """Test DataDriftStrategy produces report."""
        from evidently import ColumnMapping
        strategy = DataDriftStrategy()
        mapping = ColumnMapping(numerical_features=["duration_ns"])
        report = strategy.create_report(sample_reference, sample_current_no_drift, mapping)
        assert report is not None

    def test_drift_test_suite_strategy(self, sample_reference, sample_current_no_drift):
        """Test DriftTestSuiteStrategy produces suite."""
        from evidently import ColumnMapping
        strategy = DriftTestSuiteStrategy(drift_threshold=2)
        mapping = ColumnMapping(numerical_features=["duration_ns"])
        suite = strategy.create_report(sample_reference, sample_current_no_drift, mapping)
        assert suite is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
