"""URL canonicalization utilities."""

import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


# Tracking parameters to strip
TRACKING_PARAMS = {
    'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
    'ref', 'source', 'fbclid', 'gclid', 'msclkid', 'mc_cid', 'mc_eid',
    'gh_src', 'lever_source', 'lever_origin', 'ashby_jid',
    '_ga', '_gl', '_hsenc', '_hsmi', 'trk', 'trkInfo'
}


def canonicalize_url(url: str) -> str:
    """Canonicalize a URL by removing tracking parameters.

    Args:
        url: URL to canonicalize.

    Returns:
        Cleaned URL.
    """
    if not url:
        return url

    try:
        parsed = urlparse(url)

        # Parse query parameters
        params = parse_qs(parsed.query, keep_blank_values=False)

        # Remove tracking parameters
        cleaned_params = {
            k: v for k, v in params.items()
            if k.lower() not in TRACKING_PARAMS
        }

        # Rebuild query string
        new_query = urlencode(cleaned_params, doseq=True)

        # Rebuild URL
        canonical = urlunparse((
            parsed.scheme,
            parsed.netloc.lower(),
            parsed.path.rstrip('/'),
            parsed.params,
            new_query,
            ''  # Remove fragment
        ))

        return canonical
    except Exception:
        return url


def detect_ats_type(url: str) -> str | None:
    """Detect the ATS type from URL.

    Args:
        url: URL to analyze.

    Returns:
        ATS type string or None.
    """
    url_lower = url.lower()

    if 'greenhouse.io' in url_lower or 'boards-api.greenhouse.io' in url_lower:
        return 'greenhouse'
    elif 'lever.co' in url_lower or 'jobs.lever.co' in url_lower:
        return 'lever'
    elif 'ashbyhq.com' in url_lower or 'jobs.ashbyhq.com' in url_lower:
        return 'ashby'
    elif 'myworkdayjobs.com' in url_lower or 'workday.com' in url_lower:
        return 'workday'

    return None


def extract_company_from_ats_url(url: str) -> str | None:
    """Extract company slug from ATS URL.

    Args:
        url: ATS URL.

    Returns:
        Company slug or None.
    """
    patterns = [
        # Greenhouse: boards.greenhouse.io/company or boards-api.greenhouse.io/v1/boards/company
        r'greenhouse\.io/(?:v1/boards/)?([a-zA-Z0-9_-]+)',
        # Lever: jobs.lever.co/company
        r'lever\.co/([a-zA-Z0-9_-]+)',
        # Ashby: jobs.ashbyhq.com/company
        r'ashbyhq\.com/([a-zA-Z0-9_-]+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, url, re.IGNORECASE)
        if match:
            return match.group(1)

    return None


def build_greenhouse_api_url(company: str) -> str:
    """Build Greenhouse API URL for a company."""
    return f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true"


def build_lever_api_url(company: str) -> str:
    """Build Lever API URL for a company."""
    return f"https://api.lever.co/v0/postings/{company}?mode=json"


def build_ashby_url(company: str) -> str:
    """Build Ashby jobs page URL for a company."""
    return f"https://jobs.ashbyhq.com/{company}"
