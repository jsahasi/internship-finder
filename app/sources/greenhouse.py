"""Greenhouse ATS adapter."""

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


class GreenhouseAdapter:
    """Adapter for Greenhouse ATS API."""

    API_BASE = "https://boards-api.greenhouse.io/v1/boards"

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
        """Fetch all jobs from a Greenhouse board.

        Args:
            company: Company board slug.

        Returns:
            List of normalized Posting objects.
        """
        url = f"{self.API_BASE}/{company}/jobs?content=true"
        logger.debug(f"Fetching Greenhouse jobs: {url}")

        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch Greenhouse board '{company}': {e}")
            return []

        jobs = data.get('jobs', [])
        postings = []

        for job in jobs:
            posting = self._parse_job(job, company)
            if posting:
                postings.append(posting)

        logger.info(f"Greenhouse '{company}': {len(postings)} jobs fetched")
        return postings

    def _parse_job(self, job: dict, company: str) -> Optional[Posting]:
        """Parse a single job from Greenhouse API response.

        Args:
            job: Job dict from API.
            company: Company slug.

        Returns:
            Posting or None if parsing fails.
        """
        try:
            job_id = job.get('id')
            title = job.get('title', '')
            content = job.get('content', '')

            # Extract plain text from HTML content
            if content:
                soup = BeautifulSoup(content, 'lxml')
                text = soup.get_text(separator=' ', strip=True)
            else:
                text = ''

            # Get location
            location_data = job.get('location', {})
            location = location_data.get('name', 'Not specified') if location_data else 'Not specified'

            # Parse date
            updated_at = job.get('updated_at')
            posted_at = parse_date(updated_at)

            # Build canonical URL
            absolute_url = job.get('absolute_url', '')
            if not absolute_url and job_id:
                absolute_url = f"https://boards.greenhouse.io/{company}/jobs/{job_id}"
            url = canonicalize_url(absolute_url)

            # Classify function
            family, confidence = classify_function(title, text)

            return Posting(
                company=company.replace('-', ' ').title(),
                title=title,
                function_family=family,
                location=location,
                url=url,
                source=ATSSource.GREENHOUSE,
                posted_at=posted_at,
                text=text,
                raw_snippet=text[:500] if text else '',
                confidence=confidence
            )
        except Exception as e:
            logger.warning(f"Failed to parse Greenhouse job: {e}")
            return None

    def fetch_single_job(self, company: str, job_id: str) -> Optional[Posting]:
        """Fetch a single job by ID.

        Args:
            company: Company board slug.
            job_id: Job ID.

        Returns:
            Posting or None.
        """
        url = f"{self.API_BASE}/{company}/jobs/{job_id}"
        logger.debug(f"Fetching single Greenhouse job: {url}")

        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            job = response.json()
            return self._parse_job(job, company)
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch Greenhouse job {job_id}: {e}")
            return None
