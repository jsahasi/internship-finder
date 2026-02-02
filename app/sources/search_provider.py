"""Search provider implementations for job discovery."""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from app.extract.canonical import detect_ats_type, extract_company_from_ats_url
from app.logging_config import get_logger


logger = get_logger()


@dataclass
class SearchResult:
    """A single search result."""
    title: str
    url: str
    snippet: str
    ats_type: Optional[str] = None
    company_slug: Optional[str] = None


class SearchProvider(ABC):
    """Abstract base class for search providers."""

    @abstractmethod
    def search(
        self,
        query: str,
        recency_days: int = 7,
        max_results: int = 50
    ) -> list[SearchResult]:
        """Execute a search query.

        Args:
            query: Search query string.
            recency_days: Only return results from last N days.
            max_results: Maximum results to return.

        Returns:
            List of SearchResult objects.
        """
        pass


class GoogleCSEProvider(SearchProvider):
    """Google Custom Search Engine provider."""

    API_URL = "https://www.googleapis.com/customsearch/v1"

    def __init__(self, api_key: str, cx: str, timeout: int = 30):
        """Initialize Google CSE provider.

        Args:
            api_key: Google API key.
            cx: Custom Search Engine ID.
            timeout: Request timeout in seconds.
        """
        self.api_key = api_key
        self.cx = cx
        self.timeout = timeout
        self.session = requests.Session()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def search(
        self,
        query: str,
        recency_days: int = 7,
        max_results: int = 50
    ) -> list[SearchResult]:
        """Execute a Google Custom Search.

        Args:
            query: Search query string.
            recency_days: Only return results from last N days.
            max_results: Maximum results to return.

        Returns:
            List of SearchResult objects.
        """
        results = []
        start_index = 1

        # Calculate date range for recency filter
        date_restrict = f"d{recency_days}"

        while len(results) < max_results:
            params = {
                'key': self.api_key,
                'cx': self.cx,
                'q': query,
                'dateRestrict': date_restrict,
                'start': start_index,
                'num': min(10, max_results - len(results))  # Max 10 per request
            }

            try:
                response = self.session.get(
                    self.API_URL,
                    params=params,
                    timeout=self.timeout
                )
                response.raise_for_status()
                data = response.json()
            except requests.RequestException as e:
                logger.warning(f"Google CSE request failed: {e}")
                break

            items = data.get('items', [])
            if not items:
                break

            for item in items:
                url = item.get('link', '')
                result = SearchResult(
                    title=item.get('title', ''),
                    url=url,
                    snippet=item.get('snippet', ''),
                    ats_type=detect_ats_type(url),
                    company_slug=extract_company_from_ats_url(url)
                )
                results.append(result)

            # Check if there are more results
            next_page = data.get('queries', {}).get('nextPage')
            if not next_page:
                break

            start_index += 10

        logger.info(f"Google CSE returned {len(results)} results for query")
        return results[:max_results]


class BingSearchProvider(SearchProvider):
    """Bing Web Search API provider."""

    API_URL = "https://api.bing.microsoft.com/v7.0/search"

    def __init__(self, api_key: str, timeout: int = 30):
        """Initialize Bing provider.

        Args:
            api_key: Bing API key.
            timeout: Request timeout in seconds.
        """
        self.api_key = api_key
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'Ocp-Apim-Subscription-Key': api_key
        })

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def search(
        self,
        query: str,
        recency_days: int = 7,
        max_results: int = 50
    ) -> list[SearchResult]:
        """Execute a Bing Web Search.

        Args:
            query: Search query string.
            recency_days: Only return results from last N days.
            max_results: Maximum results to return.

        Returns:
            List of SearchResult objects.
        """
        results = []
        offset = 0

        # Bing freshness parameter
        if recency_days <= 1:
            freshness = "Day"
        elif recency_days <= 7:
            freshness = "Week"
        else:
            freshness = "Month"

        while len(results) < max_results:
            params = {
                'q': query,
                'count': min(50, max_results - len(results)),
                'offset': offset,
                'freshness': freshness,
                'responseFilter': 'Webpages'
            }

            try:
                response = self.session.get(
                    self.API_URL,
                    params=params,
                    timeout=self.timeout
                )
                response.raise_for_status()
                data = response.json()
            except requests.RequestException as e:
                logger.warning(f"Bing search request failed: {e}")
                break

            web_pages = data.get('webPages', {}).get('value', [])
            if not web_pages:
                break

            for page in web_pages:
                url = page.get('url', '')
                result = SearchResult(
                    title=page.get('name', ''),
                    url=url,
                    snippet=page.get('snippet', ''),
                    ats_type=detect_ats_type(url),
                    company_slug=extract_company_from_ats_url(url)
                )
                results.append(result)

            # Check for more results
            total_estimated = data.get('webPages', {}).get('totalEstimatedMatches', 0)
            if offset + len(web_pages) >= total_estimated:
                break

            offset += len(web_pages)

        logger.info(f"Bing returned {len(results)} results for query")
        return results[:max_results]


class SerpAPIProvider(SearchProvider):
    """SerpAPI provider (supports multiple search engines)."""

    API_URL = "https://serpapi.com/search"

    def __init__(self, api_key: str, timeout: int = 30):
        """Initialize SerpAPI provider.

        Args:
            api_key: SerpAPI key.
            timeout: Request timeout in seconds.
        """
        self.api_key = api_key
        self.timeout = timeout
        self.session = requests.Session()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def search(
        self,
        query: str,
        recency_days: int = 7,
        max_results: int = 50
    ) -> list[SearchResult]:
        """Execute a SerpAPI search.

        Args:
            query: Search query string.
            recency_days: Only return results from last N days.
            max_results: Maximum results to return.

        Returns:
            List of SearchResult objects.
        """
        results = []
        start = 0

        # SerpAPI time-based query modifier
        tbs = f"qdr:d{recency_days}" if recency_days <= 30 else "qdr:m"

        while len(results) < max_results:
            params = {
                'api_key': self.api_key,
                'engine': 'google',
                'q': query,
                'tbs': tbs,
                'start': start,
                'num': min(100, max_results - len(results))
            }

            try:
                response = self.session.get(
                    self.API_URL,
                    params=params,
                    timeout=self.timeout
                )
                response.raise_for_status()
                data = response.json()
            except requests.RequestException as e:
                logger.warning(f"SerpAPI request failed: {e}")
                break

            organic = data.get('organic_results', [])
            if not organic:
                break

            for item in organic:
                url = item.get('link', '')
                result = SearchResult(
                    title=item.get('title', ''),
                    url=url,
                    snippet=item.get('snippet', ''),
                    ats_type=detect_ats_type(url),
                    company_slug=extract_company_from_ats_url(url)
                )
                results.append(result)

            # Check pagination
            if not data.get('serpapi_pagination', {}).get('next'):
                break

            start += len(organic)

        logger.info(f"SerpAPI returned {len(results)} results for query")
        return results[:max_results]


def create_search_provider(
    provider_type: str,
    api_key: str,
    cx: Optional[str] = None
) -> SearchProvider:
    """Factory function to create search provider.

    Args:
        provider_type: One of 'google_cse', 'bing', 'serpapi'.
        api_key: API key for the provider.
        cx: Custom Search Engine ID (for Google CSE only).

    Returns:
        Configured SearchProvider instance.

    Raises:
        ValueError: If provider type is unknown.
    """
    if provider_type == 'google_cse':
        if not cx:
            raise ValueError("Google CSE requires 'cx' parameter")
        return GoogleCSEProvider(api_key, cx)
    elif provider_type == 'bing':
        return BingSearchProvider(api_key)
    elif provider_type == 'serpapi':
        return SerpAPIProvider(api_key)
    else:
        raise ValueError(f"Unknown search provider: {provider_type}")


def build_internship_query(
    underclass_terms: list[str],
    role_terms: list[str],
    site_filter: bool = True
) -> str:
    """Build an optimized search query for underclass internships.

    Args:
        underclass_terms: List of underclass keywords.
        role_terms: List of role keywords.
        site_filter: Whether to add site restrictions for ATS platforms.

    Returns:
        Search query string.
    """
    # Core query parts
    underclass = ' OR '.join(f'"{term}"' for term in underclass_terms[:5])
    roles = ' OR '.join(f'"{term}"' for term in role_terms[:5])

    query_parts = [
        f"({underclass})",
        "internship",
        f"({roles})"
    ]

    if site_filter:
        sites = (
            "site:greenhouse.io OR site:lever.co OR "
            "site:ashbyhq.com OR site:myworkdayjobs.com"
        )
        query_parts.append(f"({sites})")

    return ' '.join(query_parts)
