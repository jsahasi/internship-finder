"""Tests for taxonomy classification."""

import pytest

from app.extract.normalize import OTHER_FUNCTION
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
        assert family == "SWE"
        assert confidence > 0.5

    def test_swe_developer(self):
        """Should classify developer roles as SWE."""
        family, _ = classify_function("Backend Developer Intern")
        assert family == "SWE"

    def test_swe_from_description(self):
        """Should boost SWE from description keywords."""
        family, confidence = classify_function(
            "Technical Intern",
            "Work with Python, JavaScript, and AWS"
        )
        assert family == "SWE"

    def test_pm_from_title(self):
        """Should classify PM from title."""
        family, confidence = classify_function("Product Manager Intern")
        assert family == "PM"
        assert confidence > 0.5

    def test_pm_apm(self):
        """Should classify APM as PM."""
        family, _ = classify_function("APM Intern")
        assert family == "PM"

    def test_pm_program_manager(self):
        """Should classify program manager as PM."""
        family, _ = classify_function("Technical Program Manager Intern")
        assert family == "PM"

    def test_consulting_from_title(self):
        """Should classify consulting from title."""
        family, confidence = classify_function("Management Consulting Intern")
        assert family == "Consulting"
        assert confidence > 0.5

    def test_consulting_strategy(self):
        """Should classify strategy analyst as consulting."""
        family, _ = classify_function("Strategy Analyst Intern")
        assert family == "Consulting"

    def test_consulting_from_description(self):
        """Should boost consulting from description."""
        family, _ = classify_function(
            "Business Intern",
            "Work with clients on McKinsey engagements"
        )
        assert family == "Consulting"

    def test_ib_from_title(self):
        """Should classify IB from title."""
        family, confidence = classify_function("Investment Banking Analyst Intern")
        assert family == "IB"
        assert confidence > 0.5

    def test_ib_ma(self):
        """Should classify M&A as IB."""
        family, _ = classify_function("M&A Analyst Intern")
        assert family == "IB"

    def test_ib_from_description(self):
        """Should boost IB from description."""
        family, _ = classify_function(
            "Finance Intern",
            "Work on valuations, DCF models, and pitch books at Goldman Sachs"
        )
        assert family == "IB"

    def test_other_marketing(self):
        """Should classify marketing as OTHER."""
        family, _ = classify_function("Marketing Intern")
        assert family == OTHER_FUNCTION

    def test_other_hr(self):
        """Should classify HR as OTHER."""
        family, _ = classify_function("Human Resources Intern")
        assert family == OTHER_FUNCTION

    def test_ambiguous_defaults_to_other(self):
        """Ambiguous titles should be OTHER."""
        family, confidence = classify_function("Summer Intern")
        assert family == OTHER_FUNCTION
        assert confidence == 0.0


class TestIsTargetFunction:
    """Tests for target function check."""

    def test_swe_is_target(self):
        """SWE should be a target function."""
        assert is_target_function("SWE")

    def test_pm_is_target(self):
        """PM should be a target function."""
        assert is_target_function("PM")

    def test_consulting_is_target(self):
        """Consulting should be a target function."""
        assert is_target_function("Consulting")

    def test_ib_is_target(self):
        """IB should be a target function."""
        assert is_target_function("IB")

    def test_other_not_target(self):
        """OTHER should not be a target function."""
        assert not is_target_function(OTHER_FUNCTION)


class TestGetFunctionDisplayName:
    """Tests for display name function."""

    def test_swe_display(self):
        """SWE should have full display name."""
        assert get_function_display_name("SWE") == "Software Engineering"

    def test_pm_display(self):
        """PM should have full display name."""
        assert get_function_display_name("PM") == "Product Management"

    def test_consulting_display(self):
        """Consulting should have display name."""
        assert get_function_display_name("Consulting") == "Consulting"

    def test_ib_display(self):
        """IB should have full display name."""
        assert get_function_display_name("IB") == "Investment Banking"

    def test_other_display(self):
        """OTHER should have display name."""
        assert get_function_display_name(OTHER_FUNCTION) == "Other"


class TestRealWorldTitles:
    """Tests with real-world job titles."""

    @pytest.mark.parametrize("title,expected", [
        ("Software Engineer Intern - Summer 2026", "SWE"),
        ("SWE Intern, Infrastructure", "SWE"),
        ("Full Stack Developer Intern", "SWE"),
        ("iOS Engineer Intern", "SWE"),
        ("Machine Learning Engineer Intern", "SWE"),
        ("Product Manager Intern, Growth", "PM"),
        ("Associate Product Manager (APM) Intern", "PM"),
        ("Technical Program Manager Intern", "PM"),
        ("Business Analyst Intern - Consulting", "Consulting"),
        ("Strategy Consulting Summer Analyst", "Consulting"),
        ("Management Consultant Intern", "Consulting"),
        ("Investment Banking Summer Analyst", "IB"),
        ("IB Analyst - M&A Group", "IB"),
        ("Capital Markets Intern", "IB"),
        ("Private Equity Summer Analyst", "IB"),
    ])
    def test_real_titles(self, title, expected):
        """Test classification of real-world titles."""
        family, _ = classify_function(title)
        assert family == expected, f"'{title}' classified as {family}, expected {expected}"
