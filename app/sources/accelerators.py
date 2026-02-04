"""Accelerator portfolio scraper - fetches company lists from YC, Techstars, etc."""

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from datetime import datetime, timedelta

import requests

from app.logging_config import get_logger


logger = get_logger()


@dataclass
class AcceleratorCompany:
    """A company from an accelerator portfolio."""
    name: str
    slug: str
    website: Optional[str] = None
    batch: Optional[str] = None
    accelerator: str = "unknown"
    ats_platform: Optional[str] = None  # greenhouse, lever, ashby
    ats_slug: Optional[str] = None
    verified: bool = False


def name_to_slug(name: str) -> str:
    """Convert company name to potential ATS slug.

    Examples:
        "Stripe" -> "stripe"
        "Acme Corp" -> "acmecorp"
        "Open AI" -> "openai"
    """
    # Lowercase
    slug = name.lower()
    # Remove common suffixes
    for suffix in [', inc.', ', inc', ' inc.', ' inc', ', llc', ' llc', ', ltd', ' ltd']:
        slug = slug.replace(suffix, '')
    # Remove special characters, keep alphanumeric
    slug = re.sub(r'[^a-z0-9]', '', slug)
    return slug


def verify_ats_url(company_name: str, slug: str, platform: str) -> bool:
    """Verify if a company has a job board on the given ATS platform.

    Args:
        company_name: Company name for logging
        slug: The ATS slug to test
        platform: One of 'greenhouse', 'lever', 'ashby'

    Returns:
        True if the job board exists and has jobs
    """
    urls = {
        'greenhouse': f'https://boards-api.greenhouse.io/v1/boards/{slug}/jobs',
        'lever': f'https://api.lever.co/v0/postings/{slug}?mode=json',
        'ashby': f'https://api.ashbyhq.com/posting-api/job-board/{slug}',
    }

    if platform not in urls:
        return False

    try:
        response = requests.get(urls[platform], timeout=5)
        if response.status_code == 200:
            # Check if there are actual jobs
            if platform == 'greenhouse':
                data = response.json()
                jobs = data.get('jobs', [])
                if len(jobs) > 0:
                    logger.debug(f"Verified {company_name} on {platform}: {len(jobs)} jobs")
                    return True
            elif platform == 'lever':
                data = response.json()
                jobs = data if isinstance(data, list) else []
                if len(jobs) > 0:
                    logger.debug(f"Verified {company_name} on {platform}: {len(jobs)} jobs")
                    return True
            elif platform == 'ashby':
                # Ashby API returns JSON with jobs array
                data = response.json()
                jobs = data.get('jobs', [])
                if len(jobs) > 0:
                    logger.debug(f"Verified {company_name} on {platform}: {len(jobs)} jobs")
                    return True
        return False
    except Exception:
        return False


def detect_ats_platform(company: AcceleratorCompany) -> Optional[tuple[str, str]]:
    """Detect which ATS platform a company uses.

    Args:
        company: The company to check

    Returns:
        Tuple of (platform, verified_slug) or None if not found
    """
    # Try different slug variations
    slug_variations = [
        company.slug,
        name_to_slug(company.name),
    ]

    # Add website-based slug if available
    if company.website:
        # Extract domain without TLD
        domain_match = re.search(r'(?:https?://)?(?:www\.)?([^./]+)', company.website)
        if domain_match:
            slug_variations.append(domain_match.group(1).lower())

    # Remove duplicates while preserving order
    seen = set()
    slug_variations = [s for s in slug_variations if not (s in seen or seen.add(s))]

    # Try each platform with each slug
    for platform in ['greenhouse', 'lever', 'ashby']:
        for slug in slug_variations:
            if verify_ats_url(company.name, slug, platform):
                return (platform, slug)
            time.sleep(0.1)  # Small delay between requests

    return None


class AcceleratorScraper:
    """Scrapes company lists from startup accelerators."""

    def __init__(self, cache_dir: str = "cache"):
        """Initialize scraper with cache directory.

        Args:
            cache_dir: Directory to store cached company lists
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.cache_ttl = timedelta(days=7)  # Refresh cache weekly

    def _get_cache_path(self, source: str) -> Path:
        """Get cache file path for a source."""
        return self.cache_dir / f"accelerator_{source}.json"

    def _is_cache_valid(self, source: str) -> bool:
        """Check if cache is still valid."""
        cache_path = self._get_cache_path(source)
        if not cache_path.exists():
            return False

        mtime = datetime.fromtimestamp(cache_path.stat().st_mtime)
        return datetime.now() - mtime < self.cache_ttl

    def _load_cache(self, source: str) -> Optional[list[dict]]:
        """Load companies from cache."""
        cache_path = self._get_cache_path(source)
        if cache_path.exists():
            try:
                with open(cache_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load cache for {source}: {e}")
        return None

    def _save_cache(self, source: str, companies: list[dict]):
        """Save companies to cache."""
        cache_path = self._get_cache_path(source)
        try:
            with open(cache_path, 'w') as f:
                json.dump(companies, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save cache for {source}: {e}")

    def fetch_yc_companies(self, use_cache: bool = True) -> list[AcceleratorCompany]:
        """Fetch Y Combinator company list from the community API.

        Args:
            use_cache: Whether to use cached data if available

        Returns:
            List of AcceleratorCompany objects
        """
        if use_cache and self._is_cache_valid('yc'):
            cached = self._load_cache('yc')
            if cached:
                logger.info(f"Loaded {len(cached)} YC companies from cache")
                return [AcceleratorCompany(**c) for c in cached]

        logger.info("Fetching YC companies from API...")

        try:
            # Use the YC community API
            response = requests.get(
                'https://yc-oss.github.io/api/companies/all.json',
                timeout=30
            )
            response.raise_for_status()
            data = response.json()

            companies = []
            for item in data:
                # Skip dead companies
                if item.get('status') == 'Dead':
                    continue

                name = item.get('name', '')
                if not name:
                    continue

                company = AcceleratorCompany(
                    name=name,
                    slug=name_to_slug(name),
                    website=item.get('website'),
                    batch=item.get('batch'),
                    accelerator='yc'
                )
                companies.append(company)

            logger.info(f"Fetched {len(companies)} active YC companies")

            # Cache the results
            self._save_cache('yc', [
                {
                    'name': c.name,
                    'slug': c.slug,
                    'website': c.website,
                    'batch': c.batch,
                    'accelerator': c.accelerator,
                    'ats_platform': c.ats_platform,
                    'ats_slug': c.ats_slug,
                    'verified': c.verified
                }
                for c in companies
            ])

            return companies

        except Exception as e:
            logger.error(f"Failed to fetch YC companies: {e}")
            # Try to return stale cache if available
            cached = self._load_cache('yc')
            if cached:
                logger.info("Using stale cache as fallback")
                return [AcceleratorCompany(**c) for c in cached]
            return []

    def discover_ats_boards(
        self,
        companies: list[AcceleratorCompany],
        max_companies: int = 100,
        skip_verified: bool = True
    ) -> dict[str, list[str]]:
        """Discover which ATS platforms companies use.

        This is a slow operation that tests URLs for each company.
        Results are cached for future use.

        Args:
            companies: List of companies to check
            max_companies: Maximum number of companies to check (for rate limiting)
            skip_verified: Skip companies already verified in cache

        Returns:
            Dict mapping ATS platform to list of company slugs
        """
        results = {
            'greenhouse': [],
            'lever': [],
            'ashby': []
        }

        checked = 0
        for company in companies:
            if checked >= max_companies:
                break

            if skip_verified and company.verified:
                if company.ats_platform and company.ats_slug:
                    results[company.ats_platform].append(company.ats_slug)
                continue

            logger.debug(f"Checking ATS for {company.name}...")
            result = detect_ats_platform(company)

            if result:
                platform, slug = result
                company.ats_platform = platform
                company.ats_slug = slug
                company.verified = True
                results[platform].append(slug)
                logger.info(f"Found {company.name} on {platform} ({slug})")

            checked += 1
            time.sleep(0.2)  # Rate limiting

        logger.info(f"Discovered: Greenhouse={len(results['greenhouse'])}, "
                   f"Lever={len(results['lever'])}, Ashby={len(results['ashby'])}")

        return results

    def get_verified_boards(self, source: str = 'yc') -> dict[str, list[str]]:
        """Get previously verified ATS boards from cache.

        Args:
            source: Accelerator source ('yc', etc.)

        Returns:
            Dict mapping ATS platform to list of verified company slugs
        """
        cache_path = self.cache_dir / f"verified_boards_{source}.json"

        if cache_path.exists():
            try:
                with open(cache_path, 'r') as f:
                    return json.load(f)
            except Exception:
                pass

        return {'greenhouse': [], 'lever': [], 'ashby': []}

    def save_verified_boards(self, boards: dict[str, list[str]], source: str = 'yc'):
        """Save verified ATS boards to cache.

        Args:
            boards: Dict mapping ATS platform to list of company slugs
            source: Accelerator source
        """
        cache_path = self.cache_dir / f"verified_boards_{source}.json"
        try:
            with open(cache_path, 'w') as f:
                json.dump(boards, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save verified boards: {e}")


def update_config_with_accelerator_companies(
    config_path: str = "config.yaml",
    max_new_companies: int = 50
) -> dict[str, int]:
    """Discover and add accelerator companies to config.

    This is a utility function that can be run periodically to update
    the config with newly discovered companies.

    Args:
        config_path: Path to config.yaml
        max_new_companies: Max new companies to discover per run

    Returns:
        Dict with counts of companies added per platform
    """
    import yaml

    scraper = AcceleratorScraper()

    # Fetch YC companies
    yc_companies = scraper.fetch_yc_companies()

    # Load existing verified boards
    verified = scraper.get_verified_boards('yc')
    existing_count = sum(len(v) for v in verified.values())

    # Filter to companies not yet verified
    unverified = [c for c in yc_companies if not c.verified and c.slug not in
                  verified['greenhouse'] + verified['lever'] + verified['ashby']]

    # Discover ATS boards for new companies
    if unverified:
        logger.info(f"Checking {min(len(unverified), max_new_companies)} unverified companies...")
        new_boards = scraper.discover_ats_boards(unverified, max_companies=max_new_companies)

        # Merge with existing
        for platform in ['greenhouse', 'lever', 'ashby']:
            verified[platform] = list(set(verified[platform] + new_boards[platform]))

        # Save updated verified boards
        scraper.save_verified_boards(verified, 'yc')

    new_count = sum(len(v) for v in verified.values()) - existing_count
    logger.info(f"Added {new_count} new company boards")

    return {
        'greenhouse': len(verified['greenhouse']),
        'lever': len(verified['lever']),
        'ashby': len(verified['ashby']),
        'new': new_count
    }
