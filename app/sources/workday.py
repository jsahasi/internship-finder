"""Workday ATS adapter."""

from datetime import datetime, timedelta
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


class WorkdayAdapter:
    """Adapter for Workday CXS API."""

    PAGE_SIZE = 20

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    def _base_url(self, tenant: str, instance: str) -> str:
        return f"https://{tenant}.{instance}.myworkdayjobs.com"

    def _cxs_url(self, tenant: str, instance: str, portal: str) -> str:
        return f"{self._base_url(tenant, instance)}/wday/cxs/{tenant}/{portal}"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def fetch_jobs(self, tenant: str, instance: str, portal: str) -> list[Posting]:
        """Fetch all jobs from a Workday career site.

        Args:
            tenant: Company identifier (e.g., "nvidia").
            instance: Data center (e.g., "wd5").
            portal: Career site name (e.g., "NVIDIAExternalCareerSite").

        Returns:
            List of normalized Posting objects.
        """
        postings = []
        offset = 0
        total = None

        while True:
            url = f"{self._cxs_url(tenant, instance, portal)}/jobs"
            payload = {
                "limit": self.PAGE_SIZE,
                "offset": offset,
                "appliedFacets": {},
                "searchText": ""
            }

            try:
                response = self.session.post(url, json=payload, timeout=self.timeout)
                response.raise_for_status()
                data = response.json()
            except requests.RequestException as e:
                logger.warning(f"Failed to fetch Workday board '{tenant}': {e}")
                break

            if total is None:
                total = data.get('total', 0)
                logger.debug(f"Workday '{tenant}': {total} total jobs")

            job_postings = data.get('jobPostings', [])
            if not job_postings:
                break

            for job in job_postings:
                posting = self._parse_job(job, tenant, instance, portal)
                if posting:
                    postings.append(posting)

            offset += len(job_postings)
            if offset >= total:
                break

        logger.info(f"Workday '{tenant}': {len(postings)} jobs fetched")
        return postings

    def _parse_job(self, job: dict, tenant: str, instance: str, portal: str) -> Optional[Posting]:
        """Parse a single job from Workday jobs list response.

        Args:
            job: Job dict from API (jobPostings item).
            tenant: Company tenant.
            instance: Data center instance.
            portal: Career site portal name.

        Returns:
            Posting or None if parsing fails.
        """
        try:
            title = job.get('title', '')
            external_path = job.get('externalPath', '')
            location = job.get('locationsText', 'Not specified')
            posted_on = job.get('postedOn', '')

            # Parse the posted date (e.g., "Posted Yesterday", "Posted 2 Days Ago", "Posted 30+ Days Ago")
            posted_at = self._parse_workday_date(posted_on)

            # Build canonical URL
            base = self._base_url(tenant, instance)
            raw_url = f"{base}/{portal}{external_path}"
            url = canonicalize_url(raw_url)

            # Extract bullet fields for extra context
            bullet_fields = job.get('bulletFields', [])
            bullet_text = ' | '.join(bullet_fields) if bullet_fields else ''

            # Classify function from title + bullets
            family, confidence = classify_function(title, bullet_text)

            # Use tenant name as company, title-cased
            company_name = tenant.replace('-', ' ').replace('_', ' ').title()

            return Posting(
                company=company_name,
                title=title,
                function_family=family,
                location=location,
                url=url,
                source=ATSSource.WORKDAY,
                posted_at=posted_at,
                text=bullet_text,
                raw_snippet=bullet_text[:500],
                confidence=confidence
            )
        except Exception as e:
            logger.warning(f"Failed to parse Workday job: {e}")
            return None

    def _parse_workday_date(self, posted_on: str) -> Optional[datetime]:
        """Parse Workday's relative date strings.

        Workday uses formats like:
        - "Posted Yesterday"
        - "Posted Today"
        - "Posted 2 Days Ago"
        - "Posted 30+ Days Ago"

        Args:
            posted_on: Workday date string.

        Returns:
            Parsed datetime or None.
        """
        if not posted_on:
            return None

        text = posted_on.strip().lower()

        if 'today' in text:
            return datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        elif 'yesterday' in text:
            return (datetime.utcnow() - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            # Try to extract "N Days Ago" or "30+ Days Ago"
            import re
            match = re.search(r'(\d+)\+?\s*days?\s*ago', text)
            if match:
                days = int(match.group(1))
                return (datetime.utcnow() - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)

        # Fallback to dateparser
        return parse_date(posted_on)

    def fetch_single_job(self, tenant: str, instance: str, portal: str, external_path: str) -> Optional[Posting]:
        """Fetch a single job's full details.

        Args:
            tenant: Company tenant.
            instance: Data center instance.
            portal: Career site portal name.
            external_path: Job's external path from the listing.

        Returns:
            Posting or None.
        """
        url = f"{self._cxs_url(tenant, instance, portal)}{external_path}"
        logger.debug(f"Fetching single Workday job: {url}")

        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch Workday job {external_path}: {e}")
            return None

        try:
            info = data.get('jobPostingInfo', {})
            title = info.get('title', '')
            description_html = info.get('jobDescription', '')
            location = info.get('location', 'Not specified')
            start_date = info.get('startDate', '')

            # Extract plain text from HTML description
            text = ''
            if description_html:
                soup = BeautifulSoup(description_html, 'lxml')
                text = soup.get_text(separator=' ', strip=True)

            # Build canonical URL
            base = self._base_url(tenant, instance)
            raw_url = f"{base}/{portal}{external_path}"
            job_url = canonicalize_url(raw_url)

            # Parse date
            posted_at = parse_date(start_date) if start_date else None

            family, confidence = classify_function(title, text)
            company_name = tenant.replace('-', ' ').replace('_', ' ').title()

            return Posting(
                company=company_name,
                title=title,
                function_family=family,
                location=location,
                url=job_url,
                source=ATSSource.WORKDAY,
                posted_at=posted_at,
                text=text,
                raw_snippet=text[:500] if text else '',
                confidence=confidence
            )
        except Exception as e:
            logger.warning(f"Failed to parse Workday job detail: {e}")
            return None
