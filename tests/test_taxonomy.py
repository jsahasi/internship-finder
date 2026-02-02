"""Tests for taxonomy classification."""

import pytest

from app.extract.normalize import FunctionFamily
from app.filtering.taxonomy import (
    classify_function,
    is_target_function,
    get_function_display_name
)


class TestClassifyFunction:
    """Tests for function family classification."""

    def test_swe_from_title(self):
        """Should classify SWE from title."""
        family, confidence = classify_function("Software Engineering Intern")
        assert family == FunctionFamily.SWE
        assert confidence > 0.5

    def test_swe_developer(self):
        """Should classify developer roles as SWE."""
        family, _ = classify_function("Backend Developer Intern")
        assert family == FunctionFamily.SWE

    def test_swe_from_description(self):
        """Should boost SWE from description keywords."""
        family, confidence = classify_function(
            "Technical Intern",
            "Work with Python, JavaScript, and AWS"
        )
        assert family == FunctionFamily.SWE

    def test_pm_from_title(self):
        """Should classify PM from title."""
        family, confidence = classify_function("Product Manager Intern")
        assert family == FunctionFamily.PM
        assert confidence > 0.5

    def test_pm_apm(self):
        """Should classify APM as PM."""
        family, _ = classify_function("APM Intern")
        assert family == FunctionFamily.PM

    def test_pm_program_manager(self):
        """Should classify program manager as PM."""
        family, _ = classify_function("Technical Program Manager Intern")
        assert family == FunctionFamily.PM

    def test_consulting_from_title(self):
        """Should classify consulting from title."""
        family, confidence = classify_function("Management Consulting Intern")
        assert family == FunctionFamily.CONSULTING
        assert confidence > 0.5

    def test_consulting_strategy(self):
        """Should classify strategy analyst as consulting."""
        family, _ = classify_function("Strategy Analyst Intern")
        assert family == FunctionFamily.CONSULTING

    def test_consulting_from_description(self):
        """Should boost consulting from description."""
        family, _ = classify_function(
            "Business Intern",
            "Work with clients on McKinsey engagements"
        )
        assert family == FunctionFamily.CONSULTING

    def test_ib_from_title(self):
        """Should classify IB from title."""
        family, confidence = classify_function("Investment Banking Analyst Intern")
        assert family == FunctionFamily.IB
        assert confidence > 0.5

    def test_ib_ma(self):
        """Should classify M&A as IB."""
        family, _ = classify_function("M&A Analyst Intern")
        assert family == FunctionFamily.IB

    def test_ib_from_description(self):
        """Should boost IB from description."""
        family, _ = classify_function(
            "Finance Intern",
            "Work on valuations, DCF models, and pitch books at Goldman Sachs"
        )
        assert family == FunctionFamily.IB

    def test_other_marketing(self):
        """Should classify marketing as OTHER."""
        family, _ = classify_function("Marketing Intern")
        assert family == FunctionFamily.OTHER

    def test_other_hr(self):
        """Should classify HR as OTHER."""
        family, _ = classify_function("Human Resources Intern")
        assert family == FunctionFamily.OTHER

    def test_ambiguous_defaults_to_other(self):
        """Ambiguous titles should be OTHER."""
        family, confidence = classify_function("Summer Intern")
        assert family == FunctionFamily.OTHER
        assert confidence == 0.0


class TestIsTargetFunction:
    """Tests for target function check."""

    def test_swe_is_target(self):
        """SWE should be a target function."""
        assert is_target_function(FunctionFamily.SWE)

    def test_pm_is_target(self):
        """PM should be a target function."""
        assert is_target_function(FunctionFamily.PM)

    def test_consulting_is_target(self):
        """Consulting should be a target function."""
        assert is_target_function(FunctionFamily.CONSULTING)

    def test_ib_is_target(self):
        """IB should be a target function."""
        assert is_target_function(FunctionFamily.IB)

    def test_other_not_target(self):
        """OTHER should not be a target function."""
        assert not is_target_function(FunctionFamily.OTHER)


class TestGetFunctionDisplayName:
    """Tests for display name function."""

    def test_swe_display(self):
        """SWE should have full display name."""
        assert get_function_display_name(FunctionFamily.SWE) == "Software Engineering"

    def test_pm_display(self):
        """PM should have full display name."""
        assert get_function_display_name(FunctionFamily.PM) == "Product Management"

    def test_consulting_display(self):
        """Consulting should have display name."""
        assert get_function_display_name(FunctionFamily.CONSULTING) == "Consulting"

    def test_ib_display(self):
        """IB should have full display name."""
        assert get_function_display_name(FunctionFamily.IB) == "Investment Banking"

    def test_other_display(self):
        """OTHER should have display name."""
        assert get_function_display_name(FunctionFamily.OTHER) == "Other"


class TestRealWorldTitles:
    """Tests with real-world job titles."""

    @pytest.mark.parametrize("title,expected", [
        ("Software Engineer Intern - Summer 2026", FunctionFamily.SWE),
        ("SWE Intern, Infrastructure", FunctionFamily.SWE),
        ("Full Stack Developer Intern", FunctionFamily.SWE),
        ("iOS Engineer Intern", FunctionFamily.SWE),
        ("Machine Learning Engineer Intern", FunctionFamily.SWE),
        ("Product Manager Intern, Growth", FunctionFamily.PM),
        ("Associate Product Manager (APM) Intern", FunctionFamily.PM),
        ("Technical Program Manager Intern", FunctionFamily.PM),
        ("Business Analyst Intern - Consulting", FunctionFamily.CONSULTING),
        ("Strategy Consulting Summer Analyst", FunctionFamily.CONSULTING),
        ("Management Consultant Intern", FunctionFamily.CONSULTING),
        ("Investment Banking Summer Analyst", FunctionFamily.IB),
        ("IB Analyst - M&A Group", FunctionFamily.IB),
        ("Capital Markets Intern", FunctionFamily.IB),
        ("Private Equity Summer Analyst", FunctionFamily.IB),
    ])
    def test_real_titles(self, title, expected):
        """Test classification of real-world titles."""
        family, _ = classify_function(title)
        assert family == expected, f"'{title}' classified as {family}, expected {expected}"
