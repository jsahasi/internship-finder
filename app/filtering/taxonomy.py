"""Job function taxonomy classification."""

import re
from typing import Optional

from app.extract.normalize import FunctionFamily


# Title patterns for each function family
TAXONOMY_PATTERNS: dict[FunctionFamily, list[re.Pattern]] = {
    FunctionFamily.SWE: [
        re.compile(r'\b(?:software|swe|developer|engineer(?:ing)?|programming|coding)\b', re.I),
        re.compile(r'\b(?:backend|frontend|full[- ]?stack|devops|sre|platform)\b', re.I),
        re.compile(r'\b(?:data\s+engineer|ml\s+engineer|machine\s+learning)\b', re.I),
        re.compile(r'\b(?:ios|android|mobile)\s+(?:developer|engineer)\b', re.I),
        re.compile(r'\b(?:web\s+developer|application\s+developer)\b', re.I),
    ],
    FunctionFamily.PM: [
        re.compile(r'\b(?:product\s+manag|pm\b|product\s+lead)', re.I),
        re.compile(r'\b(?:program\s+manag|technical\s+program)\b', re.I),
        re.compile(r'\b(?:product\s+owner|product\s+strateg)\b', re.I),
        re.compile(r'\bapm\b', re.I),  # Associate Product Manager
    ],
    FunctionFamily.CONSULTING: [
        re.compile(r'\b(?:consult(?:ant|ing)?)\b', re.I),
        re.compile(r'\b(?:strategy|strateg(?:ic|y)\s+(?:analyst|associate))\b', re.I),
        re.compile(r'\b(?:management\s+consult|business\s+analyst)\b', re.I),
        re.compile(r'\b(?:advisory|transformation)\b', re.I),
    ],
    FunctionFamily.IB: [
        re.compile(r'\b(?:investment\s+bank(?:ing)?|ib\s+analyst)\b', re.I),
        re.compile(r'\b(?:m&a|mergers?\s+(?:and|&)\s+acquisitions?)\b', re.I),
        re.compile(r'\b(?:capital\s+markets|equity\s+research)\b', re.I),
        re.compile(r'\b(?:corporate\s+finance|financial\s+analyst)\b', re.I),
        re.compile(r'\b(?:private\s+equity|venture\s+capital|pe/vc)\b', re.I),
        re.compile(r'\b(?:trading|sales\s+(?:and|&)\s+trading)\b', re.I),
        re.compile(r'\bsummer\s+analyst\b', re.I),  # Common IB title
    ],
}

# Keywords that boost classification confidence
BOOST_KEYWORDS: dict[FunctionFamily, list[str]] = {
    FunctionFamily.SWE: [
        'python', 'java', 'javascript', 'typescript', 'react', 'node',
        'sql', 'database', 'api', 'cloud', 'aws', 'azure', 'gcp',
        'git', 'agile', 'scrum', 'ci/cd', 'kubernetes', 'docker'
    ],
    FunctionFamily.PM: [
        'roadmap', 'stakeholder', 'user research', 'sprint', 'backlog',
        'prioritization', 'metrics', 'kpi', 'a/b test', 'user story',
        'product vision', 'go-to-market', 'feature'
    ],
    FunctionFamily.CONSULTING: [
        'client', 'engagement', 'deliverable', 'workstream', 'framework',
        'recommendation', 'presentation', 'deck', 'case study', 'bain',
        'mckinsey', 'bcg', 'deloitte', 'accenture', 'pwc', 'ey', 'kpmg'
    ],
    FunctionFamily.IB: [
        'deal', 'transaction', 'valuation', 'dcf', 'lbo', 'pitch book',
        'financial model', 'due diligence', 'goldman', 'morgan stanley',
        'jpmorgan', 'citi', 'barclays', 'bofa', 'ubs', 'credit suisse'
    ],
}


def classify_function(title: str, description: str = "") -> tuple[FunctionFamily, float]:
    """Classify a job posting into a function family.

    Args:
        title: Job title.
        description: Job description text.

    Returns:
        Tuple of (FunctionFamily, confidence score 0-1).
    """
    combined_text = f"{title} {description}".lower()
    scores: dict[FunctionFamily, float] = {f: 0.0 for f in FunctionFamily}

    # Score based on title patterns (weighted heavily)
    for family, patterns in TAXONOMY_PATTERNS.items():
        for pattern in patterns:
            if pattern.search(title):
                scores[family] += 3.0  # Title match is strong signal
            if pattern.search(description):
                scores[family] += 0.5  # Description match is weaker

    # Boost based on keywords in description
    for family, keywords in BOOST_KEYWORDS.items():
        for keyword in keywords:
            if keyword.lower() in combined_text:
                scores[family] += 0.3

    # Find best match
    best_family = max(scores, key=scores.get)
    best_score = scores[best_family]

    # Normalize confidence (cap at 1.0)
    confidence = min(best_score / 5.0, 1.0)

    # If no strong signal, return OTHER
    if best_score < 1.0:
        return FunctionFamily.OTHER, 0.0

    return best_family, confidence


def is_target_function(family: FunctionFamily) -> bool:
    """Check if function family is one of the target types.

    Args:
        family: Function family to check.

    Returns:
        True if SWE, PM, Consulting, or IB.
    """
    return family in {
        FunctionFamily.SWE,
        FunctionFamily.PM,
        FunctionFamily.CONSULTING,
        FunctionFamily.IB
    }


def get_function_display_name(family: FunctionFamily) -> str:
    """Get human-readable name for function family."""
    names = {
        FunctionFamily.SWE: "Software Engineering",
        FunctionFamily.PM: "Product Management",
        FunctionFamily.CONSULTING: "Consulting",
        FunctionFamily.IB: "Investment Banking",
        FunctionFamily.OTHER: "Other"
    }
    return names.get(family, "Unknown")
