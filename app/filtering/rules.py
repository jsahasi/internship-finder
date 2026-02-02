"""Filtering rules for internship postings."""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.config import ExclusionsConfig, FunctionsConfig, KeywordsConfig
from app.extract.dates import is_within_days
from app.extract.normalize import OTHER_FUNCTION, NearMiss, Posting
from app.filtering.taxonomy import TaxonomyClassifier, classify_function, is_target_function


@dataclass
class FilterResult:
    """Result of filtering a posting."""
    included: bool
    reason: str
    evidence: str = ""


@dataclass
class FilterStats:
    """Statistics from filtering run."""
    total_processed: int = 0
    included: int = 0
    excluded_year: int = 0
    excluded_upperclass: int = 0
    excluded_no_underclass: int = 0
    excluded_wrong_function: int = 0
    excluded_no_date: int = 0
    excluded_too_old: int = 0


class PostingFilter:
    """Filter for internship postings based on configurable rules."""

    def __init__(
        self,
        keywords_config: KeywordsConfig,
        exclusions_config: ExclusionsConfig,
        recency_days: int = 7,
        functions_config: Optional[FunctionsConfig] = None
    ):
        self.keywords = keywords_config
        self.exclusions = exclusions_config
        self.recency_days = recency_days
        self.stats = FilterStats()
        self.near_misses: list[NearMiss] = []

        # Initialize taxonomy classifier
        if functions_config is None:
            functions_config = FunctionsConfig()
        self.taxonomy = TaxonomyClassifier(functions_config)

        # Compile patterns for efficiency
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Compile regex patterns."""
        # Year exclusion pattern
        years = '|'.join(str(y) for y in self.exclusions.graduation_years)
        self.year_pattern = re.compile(rf'\b({years})\b')

        # Upperclass exclusion patterns (word boundaries)
        upper_terms = '|'.join(
            re.escape(term) for term in self.exclusions.upperclass_terms
        )
        self.upperclass_pattern = re.compile(rf'\b({upper_terms})\b', re.IGNORECASE)

        # Underclass inclusion patterns
        under_terms = '|'.join(
            re.escape(term) for term in self.keywords.underclass
        )
        self.underclass_pattern = re.compile(rf'\b({under_terms})\b', re.IGNORECASE)

    def filter_posting(self, posting: Posting) -> FilterResult:
        """Apply all filter rules to a posting.

        Args:
            posting: Posting to filter.

        Returns:
            FilterResult with decision and reason.
        """
        self.stats.total_processed += 1
        text = f"{posting.title} {posting.text}".lower()

        # Rule 1: Check for excluded graduation years
        year_match = self.year_pattern.search(text)
        if year_match:
            self.stats.excluded_year += 1
            return FilterResult(
                included=False,
                reason=f"Contains excluded graduation year: {year_match.group(1)}",
                evidence=self._extract_context(text, year_match)
            )

        # Rule 2: Check for upperclass terms
        upper_match = self.upperclass_pattern.search(text)
        if upper_match:
            self.stats.excluded_upperclass += 1
            return FilterResult(
                included=False,
                reason=f"Contains upperclass term: {upper_match.group(1)}",
                evidence=self._extract_context(text, upper_match)
            )

        # Rule 3: Check post date
        if posting.posted_at is None:
            self.stats.excluded_no_date += 1
            return FilterResult(
                included=False,
                reason="No reliable post date available",
                evidence=""
            )

        if not is_within_days(posting.posted_at, self.recency_days):
            self.stats.excluded_too_old += 1
            return FilterResult(
                included=False,
                reason=f"Posted more than {self.recency_days} days ago",
                evidence=f"Posted: {posting.posted_at.strftime('%Y-%m-%d')}"
            )

        # Rule 4: Must have underclass signal
        under_match = self.underclass_pattern.search(text)
        if not under_match:
            self.stats.excluded_no_underclass += 1
            return FilterResult(
                included=False,
                reason="No underclass-specific terms found",
                evidence=""
            )

        # Rule 5: Check function family
        if posting.function_family == OTHER_FUNCTION:
            # Try to classify
            family, confidence = self.taxonomy.classify(posting.title, posting.text)
            posting.function_family = family
            posting.confidence = confidence

        if not self.taxonomy.is_target_function(posting.function_family):
            self.stats.excluded_wrong_function += 1
            return FilterResult(
                included=False,
                reason=f"Function family not in target list: {posting.function_family}",
                evidence=""
            )

        # Passed all rules
        self.stats.included += 1
        return FilterResult(
            included=True,
            reason="Passed all filters",
            evidence=under_match.group(1)
        )

    def _extract_context(self, text: str, match: re.Match, context_chars: int = 50) -> str:
        """Extract context around a regex match.

        Args:
            text: Full text.
            match: Regex match object.
            context_chars: Characters of context on each side.

        Returns:
            Context string with match highlighted.
        """
        start = max(0, match.start() - context_chars)
        end = min(len(text), match.end() + context_chars)

        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(text) else ""

        return f"{prefix}{text[start:end]}{suffix}"

    def filter_batch(self, postings: list[Posting]) -> tuple[list[Posting], list[NearMiss]]:
        """Filter a batch of postings.

        Args:
            postings: List of postings to filter.

        Returns:
            Tuple of (included postings, near misses).
        """
        included = []
        near_misses = []

        for posting in postings:
            result = self.filter_posting(posting)

            if result.included:
                posting.underclass_evidence = result.evidence
                included.append(posting)
            else:
                near_miss = NearMiss(
                    posting=posting,
                    exclusion_reason=result.reason,
                    evidence_snippet=result.evidence
                )
                near_misses.append(near_miss)

        # Keep only top 10 near misses (most recent first)
        near_misses.sort(
            key=lambda nm: nm.posting.posted_at or datetime.min,
            reverse=True
        )
        self.near_misses = near_misses[:10]

        return included, self.near_misses

    def get_stats_summary(self) -> str:
        """Get human-readable stats summary."""
        s = self.stats
        return (
            f"Processed: {s.total_processed} | "
            f"Included: {s.included} | "
            f"Excluded - Year: {s.excluded_year}, "
            f"Upperclass: {s.excluded_upperclass}, "
            f"No underclass: {s.excluded_no_underclass}, "
            f"Wrong function: {s.excluded_wrong_function}, "
            f"No date: {s.excluded_no_date}, "
            f"Too old: {s.excluded_too_old}"
        )


def quick_exclude_check(text: str, exclusions: ExclusionsConfig) -> Optional[str]:
    """Quick check for hard exclusion criteria.

    Useful for pre-filtering before full processing.

    Args:
        text: Text to check.
        exclusions: Exclusion configuration.

    Returns:
        Exclusion reason if excluded, None if passes.
    """
    text_lower = text.lower()

    # Check graduation years
    for year in exclusions.graduation_years:
        if str(year) in text:
            return f"Contains excluded year: {year}"

    # Check upperclass terms
    for term in exclusions.upperclass_terms:
        if term.lower() in text_lower:
            return f"Contains upperclass term: {term}"

    return None
