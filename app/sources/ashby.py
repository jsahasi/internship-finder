"""Ashby ATS adapter."""

import json
import re
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from app.extract.canonical import canonicalize_url
from app.extract.dates import parse_date
from app.extract.normalize import ATSSource, Posting
from app.filtering.taxonomy import classify_function
from app.logging_config import get_logger


logger = get_logger()


class AshbyAdapter:
    """Adapter for Ashby ATS (HTML + embedded JSON)."""

    BASE_URL = "https://jobs.ashbyhq.com"

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'text/html,application/xhtml+xml',
            'User-Agent': 'InternshipScanner/1.0'
        })

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def fetch_jobs(self, company: str) -> list[Posting]:
        """Fetch all jobs from an Ashby board.

        Args:
            company: Company board slug.

        Returns:
            List of normalized Posting objects.
        """
        url = f"{self.BASE_URL}/{company}"
        logger.debug(f"Fetching Ashby jobs: {url}")

        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            html = response.text
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch Ashby board '{company}': {e}")
            return []

        # Extract embedded JSON data
        jobs_data = self._extract_jobs_json(html)
        if not jobs_data:
            logger.warning(f"No job data found in Ashby page for '{company}'")
            return []

        postings = []
        for job in jobs_data:
            posting = self._parse_job(job, company)
            if posting:
                postings.append(posting)

        logger.info(f"Ashby '{company}': {len(postings)} jobs fetched")
        return postings

    def _extract_jobs_json(self, html: str) -> list[dict]:
        """Extract job data from embedded JSON in Ashby page.

        Args:
            html: Page HTML.

        Returns:
            List of job dicts.
        """
        # Ashby embeds job data in a script tag with __NEXT_DATA__
        soup = BeautifulSoup(html, 'lxml')

        # Try __NEXT_DATA__ script
        script = soup.find('script', {'id': '__NEXT_DATA__'})
        if script and script.string:
            try:
                data = json.loads(script.string)
                # Navigate to jobs list - structure varies
                props = data.get('props', {})
                page_props = props.get('pageProps', {})

                # Try different possible paths
                jobs = page_props.get('jobs', [])
                if not jobs:
                    jobs = page_props.get('jobPostings', [])
                if not jobs:
                    # Check for nested structure
                    initial_data = page_props.get('initialData', {})
                    jobs = initial_data.get('jobs', [])

                return jobs if isinstance(jobs, list) else []
            except json.JSONDecodeError:
                pass

        # Fallback: look for JSON-LD
        ld_scripts = soup.find_all('script', {'type': 'application/ld+json'})
        for script in ld_scripts:
            if script.string:
                try:
                    data = json.loads(script.string)
                    if isinstance(data, list):
                        return [d for d in data if d.get('@type') == 'JobPosting']
                    elif data.get('@type') == 'JobPosting':
                        return [data]
                except json.JSONDecodeError:
                    continue

        # Last resort: parse HTML directly
        return self._parse_html_jobs(soup)

    def _parse_html_jobs(self, soup: BeautifulSoup) -> list[dict]:
        """Parse jobs from HTML structure.

        Args:
            soup: BeautifulSoup object.

        Returns:
            List of job dicts.
        """
        jobs = []
        # Look for common job listing patterns
        job_links = soup.find_all('a', href=re.compile(r'/[^/]+/[a-f0-9-]+'))

        seen_urls = set()
        for link in job_links:
            href = link.get('href', '')
            if href in seen_urls:
                continue
            seen_urls.add(href)

            title = link.get_text(strip=True)
            if title and len(title) > 5:
                jobs.append({
                    'title': title,
                    'url': href,
                    'id': href.split('/')[-1]
                })

        return jobs

    def _parse_job(self, job: dict, company: str) -> Optional[Posting]:
        """Parse a single job from Ashby data.

        Args:
            job: Job dict.
            company: Company slug.

        Returns:
            Posting or None if parsing fails.
        """
        try:
            # Handle different data formats
            title = job.get('title') or job.get('name', '')
            job_id = job.get('id') or job.get('jobId', '')

            # Get description
            description = job.get('descriptionHtml') or job.get('description', '')
            if description and '<' in description:
                soup = BeautifulSoup(description, 'lxml')
                description = soup.get_text(separator=' ', strip=True)

            # Get location
            location = job.get('location') or job.get('locationName', 'Not specified')
            if isinstance(location, dict):
                location = location.get('name', 'Not specified')

            # Parse date
            published_at = job.get('publishedAt') or job.get('createdAt')
            posted_at = parse_date(str(published_at)) if published_at else None

            # Build URL
            job_url = job.get('url') or job.get('jobUrl', '')
            if not job_url and job_id:
                job_url = f"{self.BASE_URL}/{company}/{job_id}"
            url = canonicalize_url(job_url)

            # Classify function
            family, confidence = classify_function(title, description)

            return Posting(
                company=company.replace('-', ' ').title(),
                title=title,
                function_family=family,
                location=location,
                url=url,
                source=ATSSource.ASHBY,
                posted_at=posted_at,
                text=description,
                raw_snippet=description[:500] if description else '',
                confidence=confidence
            )
        except Exception as e:
            logger.warning(f"Failed to parse Ashby job: {e}")
            return None

    def fetch_single_job(self, company: str, job_id: str) -> Optional[Posting]:
        """Fetch a single job page.

        Args:
            company: Company slug.
            job_id: Job ID.

        Returns:
            Posting or None.
        """
        url = f"{self.BASE_URL}/{company}/{job_id}"
        logger.debug(f"Fetching single Ashby job: {url}")

        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            html = response.text

            soup = BeautifulSoup(html, 'lxml')

            # Extract title
            title_tag = soup.find('h1')
            title = title_tag.get_text(strip=True) if title_tag else ''

            # Extract description
            desc_div = soup.find('div', class_=re.compile(r'description|content'))
            description = desc_div.get_text(separator=' ', strip=True) if desc_div else ''

            family, confidence = classify_function(title, description)

            return Posting(
                company=company.replace('-', ' ').title(),
                title=title,
                function_family=family,
                location='Not specified',
                url=canonicalize_url(url),
                source=ATSSource.ASHBY,
                posted_at=None,
                text=description,
                raw_snippet=description[:500],
                confidence=confidence
            )
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch Ashby job {job_id}: {e}")
            return None
