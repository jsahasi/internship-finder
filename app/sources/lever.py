"""Lever ATS adapter."""

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


class LeverAdapter:
    """Adapter for Lever ATS API."""

    API_BASE = "https://api.lever.co/v0/postings"

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'application/json',
            'User-Agent': 'InternshipScanner/1.0'
        })

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def fetch_jobs(self, company: str) -> list[Posting]:
        """Fetch all jobs from a Lever board.

        Args:
            company: Company board slug.

        Returns:
            List of normalized Posting objects.
        """
        url = f"{self.API_BASE}/{company}?mode=json"
        logger.debug(f"Fetching Lever jobs: {url}")

        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            jobs = response.json()
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch Lever board '{company}': {e}")
            return []

        if not isinstance(jobs, list):
            logger.warning(f"Unexpected Lever response format for '{company}'")
            return []

        postings = []
        for job in jobs:
            posting = self._parse_job(job, company)
            if posting:
                postings.append(posting)

        logger.info(f"Lever '{company}': {len(postings)} jobs fetched")
        return postings

    def _parse_job(self, job: dict, company: str) -> Optional[Posting]:
        """Parse a single job from Lever API response.

        Args:
            job: Job dict from API.
            company: Company slug.

        Returns:
            Posting or None if parsing fails.
        """
        try:
            title = job.get('text', '')

            # Get description - Lever uses 'descriptionPlain' or nested lists
            description = job.get('descriptionPlain', '')
            if not description:
                # Try to extract from lists
                lists_data = job.get('lists', [])
                parts = []
                for lst in lists_data:
                    parts.append(lst.get('text', ''))
                    parts.append(lst.get('content', ''))
                description = ' '.join(filter(None, parts))

            # Additional opening text
            additional = job.get('additional', '')
            if additional:
                description = f"{description} {additional}"

            # Clean HTML if present
            if '<' in description:
                soup = BeautifulSoup(description, 'lxml')
                description = soup.get_text(separator=' ', strip=True)

            # Get location
            categories = job.get('categories', {})
            location = categories.get('location', 'Not specified')
            if not location:
                location = categories.get('allLocations', ['Not specified'])[0] if categories.get('allLocations') else 'Not specified'

            # Parse date (Lever uses millisecond timestamps)
            created_at = job.get('createdAt')
            posted_at = parse_date(str(created_at)) if created_at else None

            # Build URL
            hosting_url = job.get('hostedUrl', '')
            apply_url = job.get('applyUrl', '')
            url = canonicalize_url(hosting_url or apply_url)

            # Classify function
            family, confidence = classify_function(title, description)

            return Posting(
                company=company.replace('-', ' ').title(),
                title=title,
                function_family=family,
                location=location,
                url=url,
                source=ATSSource.LEVER,
                posted_at=posted_at,
                text=description,
                raw_snippet=description[:500] if description else '',
                confidence=confidence
            )
        except Exception as e:
            logger.warning(f"Failed to parse Lever job: {e}")
            return None

    def fetch_single_job(self, company: str, job_id: str) -> Optional[Posting]:
        """Fetch a single job by ID.

        Args:
            company: Company board slug.
            job_id: Job ID.

        Returns:
            Posting or None.
        """
        url = f"{self.API_BASE}/{company}/{job_id}"
        logger.debug(f"Fetching single Lever job: {url}")

        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            job = response.json()
            return self._parse_job(job, company)
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch Lever job {job_id}: {e}")
            return None
