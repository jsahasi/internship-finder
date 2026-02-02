"""Job function taxonomy classification."""

import re
from typing import Optional

from app.config import FunctionsConfig
from app.extract.normalize import OTHER_FUNCTION


class TaxonomyClassifier:
    """Configurable taxonomy classifier for job functions."""

    def __init__(self, functions_config: FunctionsConfig):
        """Initialize classifier with configuration.

        Args:
            functions_config: Function families configuration.
        """
        self.config = functions_config
        self._compiled_patterns: dict[str, list[re.Pattern]] = {}
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Compile regex patterns for each function family."""
        for family_key, family_config in self.config.families.items():
            patterns = []
            for pattern_str in family_config.title_patterns:
                try:
                    patterns.append(re.compile(pattern_str, re.IGNORECASE))
                except re.error:
                    pass  # Skip invalid patterns
            for pattern_str in family_config.description_patterns:
                try:
                    patterns.append(re.compile(pattern_str, re.IGNORECASE))
                except re.error:
                    pass
            self._compiled_patterns[family_key] = patterns

    def classify(self, title: str, description: str = "") -> tuple[str, float]:
        """Classify a job posting into a function family.

        Args:
            title: Job title.
            description: Job description text.

        Returns:
            Tuple of (function family key, confidence score 0-1).
        """
        combined_text = f"{title} {description}".lower()
        scores: dict[str, float] = {key: 0.0 for key in self.config.families}

        # Score based on patterns
        for family_key, patterns in self._compiled_patterns.items():
            for pattern in patterns:
                if pattern.search(title):
                    scores[family_key] += 3.0  # Title match is strong signal
                if pattern.search(description):
                    scores[family_key] += 0.5  # Description match is weaker

        # Boost based on keywords
        for family_key, family_config in self.config.families.items():
            for keyword in family_config.boost_keywords:
                if keyword.lower() in combined_text:
                    scores[family_key] += 0.3

        # Find best match
        if not scores:
            return OTHER_FUNCTION, 0.0

        best_family = max(scores, key=scores.get)
        best_score = scores[best_family]

        # Normalize confidence (cap at 1.0)
        confidence = min(best_score / 5.0, 1.0)

        # If no strong signal, return OTHER
        if best_score < 1.0:
            return OTHER_FUNCTION, 0.0

        return best_family, confidence

    def is_target_function(self, family: str) -> bool:
        """Check if function family is a target type.

        Args:
            family: Function family key.

        Returns:
            True if this family is marked as a target.
        """
        if family == OTHER_FUNCTION:
            return False
        family_config = self.config.families.get(family)
        if family_config is None:
            return False
        return family_config.target

    def get_display_name(self, family: str) -> str:
        """Get human-readable name for function family.

        Args:
            family: Function family key.

        Returns:
            Display name string.
        """
        if family == OTHER_FUNCTION:
            return "Other"
        family_config = self.config.families.get(family)
        if family_config is None:
            return family
        return family_config.display_name

    def get_target_families(self) -> list[str]:
        """Get list of target function family keys.

        Returns:
            List of family keys where target=True.
        """
        return [
            key for key, config in self.config.families.items()
            if config.target
        ]


# Module-level functions for backward compatibility
_default_classifier: Optional[TaxonomyClassifier] = None


def get_default_classifier() -> TaxonomyClassifier:
    """Get or create default classifier with default config."""
    global _default_classifier
    if _default_classifier is None:
        _default_classifier = TaxonomyClassifier(FunctionsConfig())
    return _default_classifier


def classify_function(title: str, description: str = "") -> tuple[str, float]:
    """Classify a job posting into a function family.

    Uses default configuration. For custom config, use TaxonomyClassifier directly.

    Args:
        title: Job title.
        description: Job description text.

    Returns:
        Tuple of (function family key, confidence score 0-1).
    """
    return get_default_classifier().classify(title, description)


def is_target_function(family: str) -> bool:
    """Check if function family is a target type.

    Uses default configuration. For custom config, use TaxonomyClassifier directly.

    Args:
        family: Function family key.

    Returns:
        True if this family is marked as a target.
    """
    return get_default_classifier().is_target_function(family)


def get_function_display_name(family: str) -> str:
    """Get human-readable name for function family.

    Uses default configuration. For custom config, use TaxonomyClassifier directly.

    Args:
        family: Function family key.

    Returns:
        Display name string.
    """
    return get_default_classifier().get_display_name(family)
