"""Generic HTML job page parser."""

import re
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from app.extract.canonical import canonicalize_url
from app.extract.dates import extract_date_from_text, parse_date
from app.extract.normalize import ATSSource, Posting
from app.filtering.taxonomy import classify_function
from app.logging_config import get_logger


logger = get_logger()


class GenericHTMLParser:
    """Generic parser for job pages without a specific ATS adapter."""

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'text/html,application/xhtml+xml',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def parse_url(self, url: str) -> Optional[Posting]:
        """Parse a job posting from a generic URL.

        Args:
            url: Job posting URL.

        Returns:
            Posting or None if parsing fails.
        """
        logger.debug(f"Fetching generic URL: {url}")

        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            html = response.text
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch URL '{url}': {e}")
            return None

        soup = BeautifulSoup(html, 'lxml')

        # Extract company name
        company = self._extract_company(soup, url)

        # Extract title
        title = self._extract_title(soup)

        # Extract description
        description = self._extract_description(soup)

        # Extract location
        location = self._extract_location(soup)

        # Extract date
        posted_at = self._extract_date(soup, description)

        if not title:
            logger.warning(f"Could not extract title from {url}")
            return None

        # Classify function
        family, confidence = classify_function(title, description)

        return Posting(
            company=company,
            title=title,
            function_family=family,
            location=location,
            url=canonicalize_url(url),
            source=ATSSource.GENERIC,
            posted_at=posted_at,
            text=description,
            raw_snippet=description[:500] if description else '',
            confidence=confidence
        )

    def _extract_company(self, soup: BeautifulSoup, url: str) -> str:
        """Extract company name from page.

        Args:
            soup: BeautifulSoup object.
            url: Page URL (fallback).

        Returns:
            Company name.
        """
        # Try common meta tags
        og_site = soup.find('meta', property='og:site_name')
        if og_site:
            return og_site.get('content', '')

        # Try schema.org
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                import json
                data = json.loads(script.string)
                if isinstance(data, dict):
                    hiring_org = data.get('hiringOrganization', {})
                    if isinstance(hiring_org, dict):
                        name = hiring_org.get('name')
                        if name:
                            return name
            except:
                continue

        # Fallback to domain
        parsed = urlparse(url)
        domain = parsed.netloc.replace('www.', '').split('.')[0]
        return domain.title()

    def _extract_title(self, soup: BeautifulSoup) -> str:
        """Extract job title from page.

        Args:
            soup: BeautifulSoup object.

        Returns:
            Job title.
        """
        # Try og:title
        og_title = soup.find('meta', property='og:title')
        if og_title:
            title = og_title.get('content', '')
            # Clean common suffixes
            title = re.sub(r'\s*[-|]\s*.*$', '', title)
            if title:
                return title

        # Try h1
        h1 = soup.find('h1')
        if h1:
            return h1.get_text(strip=True)

        # Try title tag
        title_tag = soup.find('title')
        if title_tag:
            title = title_tag.get_text(strip=True)
            title = re.sub(r'\s*[-|]\s*.*$', '', title)
            return title

        return "Unknown Position"

    def _extract_description(self, soup: BeautifulSoup) -> str:
        """Extract job description from page.

        Args:
            soup: BeautifulSoup object.

        Returns:
            Description text.
        """
        # Try common description containers
        selectors = [
            {'class_': re.compile(r'job[-_]?description', re.I)},
            {'class_': re.compile(r'posting[-_]?description', re.I)},
            {'class_': re.compile(r'description', re.I)},
            {'id': re.compile(r'job[-_]?description', re.I)},
            {'itemprop': 'description'},
        ]

        for selector in selectors:
            container = soup.find(['div', 'section', 'article'], **selector)
            if container:
                text = container.get_text(separator=' ', strip=True)
                if len(text) > 100:
                    return text

        # Fallback: main content
        main = soup.find('main') or soup.find('article')
        if main:
            return main.get_text(separator=' ', strip=True)

        # Last resort: body text
        body = soup.find('body')
        if body:
            # Remove script/style
            for tag in body.find_all(['script', 'style', 'nav', 'footer', 'header']):
                tag.decompose()
            return body.get_text(separator=' ', strip=True)[:5000]

        return ""

    def _extract_location(self, soup: BeautifulSoup) -> str:
        """Extract job location from page.

        Args:
            soup: BeautifulSoup object.

        Returns:
            Location string.
        """
        # Try schema.org
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                import json
                data = json.loads(script.string)
                if isinstance(data, dict):
                    location = data.get('jobLocation', {})
                    if isinstance(location, dict):
                        address = location.get('address', {})
                        if isinstance(address, dict):
                            parts = [
                                address.get('addressLocality', ''),
                                address.get('addressRegion', ''),
                                address.get('addressCountry', '')
                            ]
                            loc_str = ', '.join(filter(None, parts))
                            if loc_str:
                                return loc_str
            except:
                continue

        # Try common location patterns
        location_patterns = [
            re.compile(r'(?:location|office):\s*([^<\n]+)', re.I),
            re.compile(r'(?:based in|located in)\s+([^<\n.]+)', re.I),
        ]

        text = soup.get_text()
        for pattern in location_patterns:
            match = pattern.search(text)
            if match:
                return match.group(1).strip()[:100]

        return "Not specified"

    def _extract_date(self, soup: BeautifulSoup, description: str) -> Optional[datetime]:
        """Extract posting date from page.

        Args:
            soup: BeautifulSoup object.
            description: Description text.

        Returns:
            Posted datetime or None.
        """
        # Try schema.org datePosted
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                import json
                data = json.loads(script.string)
                if isinstance(data, dict):
                    date_posted = data.get('datePosted')
                    if date_posted:
                        parsed = parse_date(date_posted)
                        if parsed:
                            return parsed
            except:
                continue

        # Try meta tag
        date_meta = soup.find('meta', property='article:published_time')
        if date_meta:
            parsed = parse_date(date_meta.get('content'))
            if parsed:
                return parsed

        # Try to extract from description
        return extract_date_from_text(description)
