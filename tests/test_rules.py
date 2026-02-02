"""Tests for filtering rules."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.config import ExclusionsConfig, KeywordsConfig
from app.extract.normalize import OTHER_FUNCTION, Posting
from app.filtering.rules import PostingFilter, quick_exclude_check


@pytest.fixture
def keywords_config():
    """Default keywords configuration."""
    return KeywordsConfig()


@pytest.fixture
def exclusions_config():
    """Default exclusions configuration."""
    return ExclusionsConfig()


@pytest.fixture
def posting_filter(keywords_config, exclusions_config):
    """Configured posting filter."""
    return PostingFilter(keywords_config, exclusions_config, recency_days=7)


@pytest.fixture
def sample_postings():
    """Load sample postings from fixtures."""
    fixtures_path = Path(__file__).parent / "fixtures" / "postings.json"
    with open(fixtures_path) as f:
        return json.load(f)


def make_posting(
    title: str = "Test Intern",
    company: str = "Test Corp",
    text: str = "",
    posted_at: datetime = None,
    function_family: str = "SWE"
) -> Posting:
    """Create a test posting."""
    if posted_at is None:
        posted_at = datetime.utcnow() - timedelta(days=1)

    return Posting(
        company=company,
        title=title,
        function_family=function_family,
        location="Test City",
        url="https://example.com/job/123",
        posted_at=posted_at,
        text=text
    )


class TestYearExclusion:
    """Tests for graduation year exclusion."""

    def test_exclude_2027(self, posting_filter):
        """Should exclude postings mentioning 2027."""
        posting = make_posting(
            text="Looking for Class of 2027 students"
        )
        result = posting_filter.filter_posting(posting)
        assert not result.included
        assert "2027" in result.reason

    def test_exclude_2028(self, posting_filter):
        """Should exclude postings mentioning 2028."""
        posting = make_posting(
            text="Graduating in 2028 preferred"
        )
        result = posting_filter.filter_posting(posting)
        assert not result.included
        assert "2028" in result.reason

    def test_allow_2029(self, posting_filter):
        """Should not exclude 2029 (current freshmen)."""
        posting = make_posting(
            text="For freshman students graduating in 2029"
        )
        result = posting_filter.filter_posting(posting)
        # Should pass year filter, might fail on other criteria
        assert "graduation year" not in result.reason.lower()


class TestUpperclassExclusion:
    """Tests for upperclass term exclusion."""

    def test_exclude_junior(self, posting_filter):
        """Should exclude postings for juniors."""
        posting = make_posting(text="Looking for junior students")
        result = posting_filter.filter_posting(posting)
        assert not result.included
        assert "junior" in result.reason.lower()

    def test_exclude_senior(self, posting_filter):
        """Should exclude postings for seniors."""
        posting = make_posting(text="Senior year students only")
        result = posting_filter.filter_posting(posting)
        assert not result.included
        assert "senior" in result.reason.lower()

    def test_exclude_penultimate(self, posting_filter):
        """Should exclude penultimate year postings."""
        posting = make_posting(text="Penultimate year students")
        result = posting_filter.filter_posting(posting)
        assert not result.included
        assert "penultimate" in result.reason.lower()

    def test_exclude_rising_senior(self, posting_filter):
        """Should exclude rising senior postings."""
        posting = make_posting(text="For rising senior students")
        result = posting_filter.filter_posting(posting)
        assert not result.included
        assert "rising senior" in result.reason.lower()

    def test_exclude_final_year(self, posting_filter):
        """Should exclude final year postings."""
        posting = make_posting(text="Final-year students wanted")
        result = posting_filter.filter_posting(posting)
        assert not result.included
        assert "final" in result.reason.lower()


class TestUnderclassInclusion:
    """Tests for underclass term inclusion."""

    def test_require_freshman(self, posting_filter):
        """Should include freshman-targeted postings."""
        posting = make_posting(text="Freshman students welcome to apply")
        result = posting_filter.filter_posting(posting)
        assert result.included
        assert "freshman" in result.evidence.lower()

    def test_require_sophomore(self, posting_filter):
        """Should include sophomore-targeted postings."""
        posting = make_posting(text="For sophomore students interested in tech")
        result = posting_filter.filter_posting(posting)
        assert result.included
        assert "sophomore" in result.evidence.lower()

    def test_require_first_year(self, posting_filter):
        """Should include first-year targeted postings."""
        posting = make_posting(text="First-year and second-year students")
        result = posting_filter.filter_posting(posting)
        assert result.included

    def test_require_underclassmen(self, posting_filter):
        """Should include underclassmen-targeted postings."""
        posting = make_posting(text="Open to underclassmen only")
        result = posting_filter.filter_posting(posting)
        assert result.included
        assert "underclassmen" in result.evidence.lower()

    def test_require_discovery(self, posting_filter):
        """Should include discovery program postings."""
        posting = make_posting(text="Our Discovery Program for early talent")
        result = posting_filter.filter_posting(posting)
        assert result.included

    def test_exclude_no_signal(self, posting_filter):
        """Should exclude postings without underclass signals."""
        posting = make_posting(text="Looking for interns to join our team")
        result = posting_filter.filter_posting(posting)
        assert not result.included
        assert "underclass" in result.reason.lower()


class TestDateFilter:
    """Tests for posting date filtering."""

    def test_include_recent(self, posting_filter):
        """Should include postings from last 7 days."""
        posting = make_posting(
            text="Freshman internship program",
            posted_at=datetime.utcnow() - timedelta(days=3)
        )
        result = posting_filter.filter_posting(posting)
        assert result.included

    def test_exclude_old(self, posting_filter):
        """Should exclude postings older than 7 days."""
        posting = make_posting(
            text="Freshman internship program",
            posted_at=datetime.utcnow() - timedelta(days=10)
        )
        result = posting_filter.filter_posting(posting)
        assert not result.included
        assert "7 days" in result.reason

    def test_exclude_no_date(self, posting_filter):
        """Should exclude postings without date."""
        posting = Posting(
            company="Test",
            title="Test",
            url="https://example.com",
            text="Freshman program",
            posted_at=None
        )
        result = posting_filter.filter_posting(posting)
        assert not result.included
        assert "date" in result.reason.lower()


class TestQuickExcludeCheck:
    """Tests for quick exclusion check."""

    def test_quick_exclude_year(self, exclusions_config):
        """Quick check should catch year exclusion."""
        result = quick_exclude_check("Class of 2027", exclusions_config)
        assert result is not None
        assert "2027" in result

    def test_quick_exclude_term(self, exclusions_config):
        """Quick check should catch upperclass terms."""
        result = quick_exclude_check("for junior students", exclusions_config)
        assert result is not None
        assert "junior" in result.lower()

    def test_quick_pass(self, exclusions_config):
        """Quick check should pass valid text."""
        result = quick_exclude_check("freshman internship", exclusions_config)
        assert result is None


class TestFixturePostings:
    """Tests using fixture postings."""

    def test_all_fixtures(self, posting_filter, sample_postings):
        """Test all fixture postings match expected decisions."""
        for fixture in sample_postings:
            posted_at = None
            if fixture.get("posted_at"):
                posted_at = datetime.fromisoformat(
                    fixture["posted_at"].replace("Z", "+00:00")
                ).replace(tzinfo=None)

            # Determine function family
            family = "SWE"
            if fixture.get("expected_family"):
                family = fixture["expected_family"]
            elif "pm" in fixture["title"].lower() or "product" in fixture["title"].lower():
                family = "PM"
            elif "consult" in fixture["title"].lower():
                family = "Consulting"
            elif "banking" in fixture["title"].lower() or "ib" in fixture["title"].lower():
                family = "IB"

            posting = Posting(
                company=fixture["company"],
                title=fixture["title"],
                function_family=family,
                location=fixture["location"],
                url=fixture["url"],
                posted_at=posted_at,
                text=fixture["text"]
            )

            result = posting_filter.filter_posting(posting)
            expected_include = fixture["expected_decision"] == "include"

            assert result.included == expected_include, (
                f"Fixture {fixture['id']}: expected {fixture['expected_decision']}, "
                f"got {'include' if result.included else 'exclude'} ({result.reason})"
            )
