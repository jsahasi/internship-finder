"""Main CLI entry point for Underclass Internship Scanner."""

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from app.config import AppConfig, EnvSettings, load_config, get_env_settings
from app.extract.normalize import Posting
from app.filtering.rules import PostingFilter
from app.filtering.taxonomy import classify_function
from app.llm.claude_client import ClaudeClient
from app.logging_config import setup_logging, get_logger
from app.profile.seeker import SeekerProfile, load_seeker_profile
from app.profile.documents import DocumentGenerator, create_pdf_from_text
from app.reporting.emailer import create_email_provider
from app.reporting.render import ReportRenderer
from app.sources.ashby import AshbyAdapter
from app.sources.generic_html import GenericHTMLParser
from app.sources.greenhouse import GreenhouseAdapter
from app.sources.lever import LeverAdapter
from app.sources.workday import WorkdayAdapter
from app.sources.claude_search import ClaudeSearchProvider
from app.sources.search_provider import (
    create_search_provider,
    build_internship_query
)
from app.sources.grok_search import GrokSearchProvider
from app.sources.accelerators import AcceleratorScraper
from app.sources.linkedin_search import search_linkedin, extract_companies
from app.storage.state import StateStore
import requests
import time


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Underclass Internship Scanner - Find freshman/sophomore internships"
    )
    parser.add_argument(
        '--config',
        type=str,
        default='config.yaml',
        help='Path to config YAML file (default: config.yaml)'
    )
    parser.add_argument(
        '--profile_dir',
        type=str,
        default='config',
        help='Path to profile directory with seeking.txt and resume (default: config)'
    )
    parser.add_argument(
        '--dry_run',
        action='store_true',
        help='Print results without sending email'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Ignore deduplication, process all postings'
    )
    parser.add_argument(
        '--max_results',
        type=int,
        default=None,
        help='Maximum postings to process'
    )
    parser.add_argument(
        '--no_documents',
        action='store_true',
        help='Skip generating tailored resumes and cover letters'
    )
    parser.add_argument(
        '--run_once',
        action='store_true',
        help='Run once and exit (default behavior)'
    )
    parser.add_argument(
        '--log_level',
        type=str,
        default='INFO',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        help='Logging level'
    )
    parser.add_argument(
        '--discover_accelerators',
        action='store_true',
        help='Discover company job boards from accelerator portfolios (YC, etc.)'
    )
    parser.add_argument(
        '--use_accelerators',
        action='store_true',
        help='Include discovered accelerator companies in the scan'
    )
    parser.add_argument(
        '--max_discover',
        type=int,
        default=50,
        help='Max new companies to discover from accelerators (default: 50)'
    )
    return parser.parse_args()


def fetch_from_ats(
    config: AppConfig,
    logger,
    extra_boards: Optional[dict[str, list[str]]] = None
) -> list[Posting]:
    """Fetch postings from configured ATS companies.

    Args:
        config: Application config
        logger: Logger instance
        extra_boards: Optional dict with extra boards to fetch from accelerators
                      Format: {'greenhouse': [...], 'lever': [...], 'ashby': [...]}
    """
    postings = []
    ats_config = config.targets.ats_companies

    # Merge extra boards from accelerators if provided
    greenhouse_boards = list(ats_config.greenhouse) if ats_config.greenhouse else []
    lever_boards = list(ats_config.lever) if ats_config.lever else []
    ashby_boards = list(ats_config.ashby) if ats_config.ashby else []

    if extra_boards:
        greenhouse_boards = list(set(greenhouse_boards + extra_boards.get('greenhouse', [])))
        lever_boards = list(set(lever_boards + extra_boards.get('lever', [])))
        ashby_boards = list(set(ashby_boards + extra_boards.get('ashby', [])))
        logger.info(f"Including accelerator boards: +{len(extra_boards.get('greenhouse', []))} GH, "
                   f"+{len(extra_boards.get('lever', []))} Lever, +{len(extra_boards.get('ashby', []))} Ashby")

    if greenhouse_boards:
        logger.info(f"Fetching from {len(greenhouse_boards)} Greenhouse boards")
        gh_adapter = GreenhouseAdapter()
        for company in greenhouse_boards:
            try:
                jobs = gh_adapter.fetch_jobs(company)
                postings.extend(jobs)
            except Exception as e:
                logger.warning(f"Greenhouse '{company}' failed: {e}")

    if lever_boards:
        logger.info(f"Fetching from {len(lever_boards)} Lever boards")
        lever_adapter = LeverAdapter()
        for company in lever_boards:
            try:
                jobs = lever_adapter.fetch_jobs(company)
                postings.extend(jobs)
            except Exception as e:
                logger.warning(f"Lever '{company}' failed: {e}")

    if ashby_boards:
        logger.info(f"Fetching from {len(ashby_boards)} Ashby boards")
        ashby_adapter = AshbyAdapter()
        for company in ashby_boards:
            try:
                jobs = ashby_adapter.fetch_jobs(company)
                postings.extend(jobs)
            except Exception as e:
                logger.warning(f"Ashby '{company}' failed: {e}")

    # Workday boards
    workday_boards = list(ats_config.workday) if ats_config.workday else []
    if workday_boards:
        logger.info(f"Fetching from {len(workday_boards)} Workday boards")
        wd_adapter = WorkdayAdapter()
        for company in workday_boards:
            try:
                jobs = wd_adapter.fetch_jobs(company.tenant, company.instance, company.portal)
                postings.extend(jobs)
            except Exception as e:
                logger.warning(f"Workday '{company.tenant}' failed: {e}")

    logger.info(f"ATS fetch complete: {len(postings)} total postings")
    return postings


def fetch_from_llm_search(
    config: AppConfig,
    env: EnvSettings,
    profile: SeekerProfile,
    logger
) -> list[Posting]:
    """Fetch postings using LLM-powered search (Claude and/or OpenAI).

    Uses both providers if available and deduplicates results.
    Also searches specifically for target companies in batches.
    """
    all_postings = []
    seen_urls = set()

    # Get target function families
    target_functions = [
        key for key, cfg in config.functions.families.items()
        if cfg.target
    ]

    # Get underclass terms from profile or config
    underclass_terms = profile.get_underclass_terms() if profile else config.keywords.underclass

    def _add_postings(postings: list[Posting]) -> int:
        """Add postings to results, deduplicating by URL. Returns count of new postings."""
        added = 0
        for posting in postings:
            if posting.url not in seen_urls:
                seen_urls.add(posting.url)
                all_postings.append(posting)
                added += 1
        return added

    # Batch target companies into groups of 100 for targeted searches
    target_companies = config.search.target_companies
    max_batches = config.search.max_company_batches
    company_batches = [
        target_companies[i:i + 100]
        for i in range(0, len(target_companies), 100)
    ][:max_batches]

    if company_batches:
        logger.info(f"Will search {len(target_companies)} target companies in {len(company_batches)} batches")

    # Claude search
    if env.anthropic_api_key:
        logger.info("Searching with Claude...")
        try:
            claude_search = ClaudeSearchProvider(
                api_key=env.anthropic_api_key,
                max_results=config.search.max_results_per_query
            )
            # Broad search
            claude_results = claude_search.search(
                target_functions=target_functions,
                underclass_terms=underclass_terms,
                recency_days=config.search.recency_days
            )
            added = _add_postings(claude_results)
            logger.info(f"Claude broad search: {len(claude_results)} postings ({added} new)")

            # Targeted company batch searches (with rate limit delays)
            for i, batch in enumerate(company_batches):
                logger.info(f"Claude batch {i+1}/{len(company_batches)}: waiting 65s for rate limit...")
                time.sleep(65)
                try:
                    batch_results = claude_search.search(
                        target_functions=target_functions,
                        underclass_terms=underclass_terms,
                        companies=batch,
                        recency_days=config.search.recency_days
                    )
                    added = _add_postings(batch_results)
                    if added > 0:
                        logger.info(f"Claude batch {i+1}/{len(company_batches)}: {added} new from {', '.join(batch[:3])}...")
                    else:
                        logger.info(f"Claude batch {i+1}/{len(company_batches)}: 0 new postings")
                except Exception as e:
                    logger.warning(f"Claude batch {i+1} failed: {e}")

            logger.info(f"Claude total: {claude_search.get_usage_stats()}")
        except Exception as e:
            logger.warning(f"Claude search failed: {e}")

    # OpenAI search
    if env.openai_api_key:
        logger.info("Searching with OpenAI...")
        try:
            from app.sources.openai_search import OpenAISearchProvider
            openai_search = OpenAISearchProvider(
                api_key=env.openai_api_key,
                max_results=config.search.max_results_per_query
            )
            # Broad search
            openai_results = openai_search.search(
                target_functions=target_functions,
                underclass_terms=underclass_terms,
                recency_days=config.search.recency_days
            )
            added = _add_postings(openai_results)
            logger.info(f"OpenAI broad search: {len(openai_results)} postings ({added} new)")

            # Targeted company batch searches
            for i, batch in enumerate(company_batches):
                try:
                    batch_results = openai_search.search(
                        target_functions=target_functions,
                        underclass_terms=underclass_terms,
                        companies=batch,
                        recency_days=config.search.recency_days
                    )
                    added = _add_postings(batch_results)
                    if added > 0:
                        logger.info(f"OpenAI batch {i+1}/{len(company_batches)}: {added} new from {', '.join(batch[:3])}...")
                except Exception as e:
                    logger.warning(f"OpenAI batch {i+1} failed: {e}")
        except ImportError:
            logger.warning("OpenAI package not installed, skipping OpenAI search")
        except Exception as e:
            logger.warning(f"OpenAI search failed: {e}")

    # Grok search
    if env.xai_api_key:
        logger.info("Searching with Grok...")
        try:
            grok_search = GrokSearchProvider(
                api_key=env.xai_api_key,
                max_results=config.search.max_results_per_query
            )
            # Broad search
            grok_results = grok_search.search(
                target_functions=target_functions,
                underclass_terms=underclass_terms,
                recency_days=config.search.recency_days
            )
            added = _add_postings(grok_results)
            logger.info(f"Grok broad search: {len(grok_results)} postings ({added} new)")

            # Targeted company batch searches
            for i, batch in enumerate(company_batches):
                try:
                    batch_results = grok_search.search(
                        target_functions=target_functions,
                        underclass_terms=underclass_terms,
                        companies=batch,
                        recency_days=config.search.recency_days
                    )
                    added = _add_postings(batch_results)
                    if added > 0:
                        logger.info(f"Grok batch {i+1}/{len(company_batches)}: {added} new from {', '.join(batch[:3])}...")
                except Exception as e:
                    logger.warning(f"Grok batch {i+1} failed: {e}")
        except Exception as e:
            logger.warning(f"Grok search failed: {e}")

    if not env.anthropic_api_key and not env.openai_api_key and not env.xai_api_key:
        logger.warning("No LLM API keys configured for search")

    logger.info(f"LLM search complete: {len(all_postings)} unique postings")
    return all_postings


def fetch_from_traditional_search(
    config: AppConfig,
    env: EnvSettings,
    logger
) -> list[Posting]:
    """Fetch using traditional search APIs (Google CSE, Bing, SerpAPI)."""
    postings = []
    provider_type = config.search.provider

    if provider_type not in ['google_cse', 'bing', 'serpapi']:
        return []

    api_key = None
    cx = None

    if provider_type == 'google_cse':
        api_key = env.google_cse_api_key
        cx = env.google_cse_cx
        if not api_key or not cx:
            logger.warning("Google CSE credentials not configured")
            return []
    elif provider_type == 'bing':
        api_key = env.bing_api_key
        if not api_key:
            logger.warning("Bing API key not configured")
            return []
    elif provider_type == 'serpapi':
        api_key = env.serpapi_key
        if not api_key:
            logger.warning("SerpAPI key not configured")
            return []

    try:
        provider = create_search_provider(provider_type, api_key, cx)
    except ValueError as e:
        logger.error(f"Failed to create search provider: {e}")
        return []

    queries = config.search.queries
    if not queries:
        queries = [build_internship_query(
            config.keywords.underclass[:5],
            config.keywords.role_terms[:6]
        )]

    generic_parser = GenericHTMLParser()
    gh_adapter = GreenhouseAdapter()
    lever_adapter = LeverAdapter()
    ashby_adapter = AshbyAdapter()

    for query in queries:
        logger.info(f"Searching: {query[:80]}...")
        try:
            results = provider.search(
                query,
                recency_days=config.search.recency_days,
                max_results=config.search.max_results_per_query
            )
        except Exception as e:
            logger.warning(f"Search failed: {e}")
            continue

        for result in results:
            try:
                posting = None
                if result.ats_type == 'greenhouse' and result.company_slug:
                    posting = gh_adapter.fetch_single_job(
                        result.company_slug,
                        result.url.split('/')[-1]
                    )
                elif result.ats_type == 'lever' and result.company_slug:
                    posting = lever_adapter.fetch_single_job(
                        result.company_slug,
                        result.url.split('/')[-1]
                    )
                elif result.ats_type == 'ashby' and result.company_slug:
                    posting = ashby_adapter.fetch_single_job(
                        result.company_slug,
                        result.url.split('/')[-1]
                    )
                else:
                    posting = generic_parser.parse_url(result.url)

                if posting:
                    postings.append(posting)
            except Exception as e:
                logger.debug(f"Failed to parse result {result.url}: {e}")

    logger.info(f"Traditional search complete: {len(postings)} postings")
    return postings


def validate_posting_still_open(posting: Posting, logger) -> bool:
    """Check if a job posting is still open by verifying the Apply link works.

    Conservative approach: only include if we can confirm the position is open.
    Better to skip a valid position than email a closed one.

    Args:
        posting: The posting to validate.
        logger: Logger instance.

    Returns:
        True if posting is confirmed still open, False otherwise.
    """
    from urllib.parse import urlparse
    import re

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(posting.url, headers=headers, timeout=10, allow_redirects=True)

        # Any non-200 status means position is likely gone
        if response.status_code != 200:
            logger.info(f"Removed (HTTP {response.status_code}): {posting.company} - {posting.title}")
            return False

        # Check for redirect to generic careers page
        original_url = urlparse(posting.url)
        final_url = urlparse(response.url)

        # Detect if redirected to a different host (likely generic careers site)
        if original_url.netloc != final_url.netloc:
            generic_path_patterns = [
                '/positions', '/careers', '/jobs', '/open-positions',
                '/opportunities', '/search',
            ]
            final_path_lower = final_url.path.lower().rstrip('/')

            if final_path_lower in ['', '/'] or any(final_path_lower == p for p in generic_path_patterns):
                logger.info(f"Removed (redirected to generic page): {posting.company} - {posting.title}")
                return False

        # Check if path lost the job ID after redirect
        original_path = original_url.path.lower()
        final_path = final_url.path.lower()

        job_id_pattern = r'/jobs?/\d+|/positions?/[a-f0-9-]+|/job/[a-z0-9-]+|/\d{5,}'
        had_job_id = re.search(job_id_pattern, original_path)
        has_job_id = re.search(job_id_pattern, final_path)

        if had_job_id and not has_job_id:
            logger.info(f"Removed (job ID lost in redirect): {posting.company} - {posting.title}")
            return False

        content = response.text.lower()

        # Workday-specific: check postingAvailable flag
        if 'myworkdayjobs.com' in posting.url:
            if 'postingavailable: false' in content or '"postingavailable":false' in content:
                logger.info(f"Removed (Workday posting unavailable): {posting.company} - {posting.title}")
                return False

        # LinkedIn-specific: check for auth wall or expired signals
        if 'linkedin.com' in posting.url:
            if 'authwall' in response.url:
                logger.info(f"Removed (LinkedIn auth wall): {posting.company} - {posting.title}")
                return False

        # Check for "position closed" indicators
        closed_indicators = [
            'this position has been filled',
            'this job is no longer available',
            'job no longer exists',
            'position is closed',
            'no longer accepting applications',
            'this posting has expired',
            'job has been removed',
            'position has been closed',
            'no longer open',
            'this role has been filled',
            'this position is no longer available',
            'this job has expired',
            'this requisition is no longer active',
            'the position you are looking for is no longer open',
            'sorry, this position has been filled',
            'this job posting is no longer available',
        ]

        for indicator in closed_indicators:
            if indicator in content:
                logger.info(f"Removed (closed indicator: '{indicator}'): {posting.company} - {posting.title}")
                return False

        # Check for generic listing pages (many jobs listed, not a single job)
        listing_page_indicators = [
            'class="job-listing"',
            'class="jobs-list"',
            'class="position-list"',
            'data-job-count=',
            'showing all jobs',
            'browse all positions',
            'all open positions',
            'filter by location',
            'filter by department',
        ]

        listing_indicator_count = sum(1 for ind in listing_page_indicators if ind in content)
        if listing_indicator_count >= 2:
            logger.info(f"Removed (generic listing page): {posting.company} - {posting.title}")
            return False

        # Check for presence of apply button/link
        apply_indicators = [
            'apply now',
            'apply for this job',
            'submit application',
            'apply to this position',
            'apply for job',
            'class="apply',
            'id="apply',
            'apply-button',
            'btn-apply',
            'apply for role',
            'apply to job',
            'start application',
            'submit your application',
            'apply on company',
            'apply on website',
            'easy apply',
            # Greenhouse
            '#app_apply',
            'application-apply',
            # Lever
            'lever-application',
            'postings-btn-apply',
            # Workday
            'postingavailable: true',
            '"postingavailable":true',
            # Ashby
            'ashby-job-posting',
        ]

        has_apply = any(indicator in content for indicator in apply_indicators)
        if not has_apply:
            logger.info(f"Removed (no apply button found): {posting.company} - {posting.title}")
            return False

        return True

    except requests.RequestException as e:
        # Can't reach the page — don't include an unverifiable posting
        logger.info(f"Removed (unreachable: {e}): {posting.company} - {posting.title}")
        return False


def validate_postings_batch(postings: list[Posting], logger) -> list[Posting]:
    """Validate a batch of postings are still open.

    Args:
        postings: List of postings to validate.
        logger: Logger instance.

    Returns:
        List of postings that are still open.
    """
    valid_postings = []
    closed_count = 0

    for posting in postings:
        if validate_posting_still_open(posting, logger):
            valid_postings.append(posting)
        else:
            closed_count += 1

    if closed_count > 0:
        logger.info(f"Removed {closed_count} closed positions, {len(valid_postings)} still open")

    return valid_postings


def generate_application_documents(
    included: list[Posting],
    profile: SeekerProfile,
    env: EnvSettings,
    logger
) -> dict[str, dict]:
    """Generate tailored resumes and cover letters for each posting.

    Returns:
        Dict mapping posting hash to {'resume': bytes, 'cover_letter': bytes, ...}
    """
    if not profile.resume_text and not profile.about_me:
        logger.warning("No resume or profile found, skipping document generation")
        return {}

    doc_gen = DocumentGenerator(
        anthropic_key=env.anthropic_api_key,
        openai_key=env.openai_api_key
    )

    documents = {}
    for posting in included:
        logger.info(f"Generating documents for {posting.company} - {posting.title}")
        try:
            materials = doc_gen.generate_application_materials(
                profile=profile,
                posting=posting,
                signature_name="[Your Name]"  # User should customize
            )

            docs = {}

            # Create cover letter PDF
            if materials['cover_letter']:
                cover_letter_pdf = create_pdf_from_text(
                    materials['cover_letter'],
                    f"Cover Letter - {posting.company}"
                )
                docs['cover_letter'] = cover_letter_pdf
                docs['cover_letter_text'] = materials['cover_letter']

            # Create tailored resume PDF
            if materials['resume']:
                resume_pdf = create_pdf_from_text(
                    materials['resume'],
                    f"Resume - {posting.company}"
                )
                docs['resume'] = resume_pdf
                docs['resume_text'] = materials['resume']

            docs['company'] = posting.company
            docs['title'] = posting.title

            documents[posting.posting_hash] = docs

        except Exception as e:
            logger.warning(f"Failed to generate documents for {posting.company}: {e}")

    logger.info(f"Generated documents for {len(documents)} postings")
    return documents


def run_pipeline(
    config: AppConfig,
    env: EnvSettings,
    profile: SeekerProfile,
    dry_run: bool = False,
    force: bool = False,
    max_results: Optional[int] = None,
    generate_docs: bool = True,
    accelerator_boards: Optional[dict[str, list[str]]] = None
) -> int:
    """Run the main processing pipeline."""
    logger = get_logger()
    logger.info("=" * 60)
    logger.info("Starting Underclass Internship Scanner")
    logger.info("=" * 60)

    if profile.year:
        logger.info(f"Profile: {profile.year} seeking {', '.join(profile.roles[:3])}")

    # Initialize components
    state_store = StateStore(config.database_path)

    # Override exclusions based on profile
    if profile.graduation_year:
        excluded_years = profile.get_excluded_years()
        config.exclusions.graduation_years = excluded_years
        logger.info(f"Excluding graduation years: {excluded_years}")

    posting_filter = PostingFilter(
        config.keywords,
        config.exclusions,
        config.search.recency_days,
        config.functions,
        require_post_date=config.search.require_post_date,
        require_underclass_terms=config.search.require_underclass_terms
    )
    renderer = ReportRenderer()

    # Phase 1: Fetch postings
    logger.info("Phase 1: Fetching postings")
    all_postings = []

    # Fetch from ATS (including accelerator companies if provided)
    ats_postings = fetch_from_ats(config, logger, extra_boards=accelerator_boards)
    all_postings.extend(ats_postings)

    # Fetch from LLM search (Claude and/or OpenAI)
    if config.search.provider == 'claude' or env.anthropic_api_key or env.openai_api_key:
        llm_postings = fetch_from_llm_search(config, env, profile, logger)
        # Deduplicate against ATS postings
        ats_urls = {p.url for p in ats_postings}
        for posting in llm_postings:
            if posting.url not in ats_urls:
                all_postings.append(posting)

    # Fetch from traditional search if configured
    if config.search.provider in ['google_cse', 'bing', 'serpapi']:
        traditional_postings = fetch_from_traditional_search(config, env, logger)
        existing_urls = {p.url for p in all_postings}
        for posting in traditional_postings:
            if posting.url not in existing_urls:
                all_postings.append(posting)

    # Fetch from LinkedIn search
    try:
        logger.info("Searching LinkedIn...")
        linkedin_postings = search_linkedin("summer 2026 internship")
        existing_urls = {p.url for p in all_postings}
        linkedin_new = [p for p in linkedin_postings if p.url not in existing_urls]
        all_postings.extend(linkedin_new)
        logger.info(f"LinkedIn: {len(linkedin_postings)} found, {len(linkedin_new)} new")

        # Extract new companies and add to target_companies for future LLM searches
        linkedin_companies = extract_companies(linkedin_postings)
        existing_companies = {c.lower() for c in config.search.target_companies}
        new_companies = [c for c in linkedin_companies if c.lower() not in existing_companies]
        if new_companies:
            config.search.target_companies.extend(new_companies)
            logger.info(f"LinkedIn: discovered {len(new_companies)} new companies: {', '.join(new_companies[:10])}")
    except Exception as e:
        logger.warning(f"LinkedIn search failed: {e}")

    logger.info(f"Total postings fetched: {len(all_postings)}")

    if not all_postings:
        logger.warning("No postings found")
        print("\n0 postings found. Check your configuration.")
        return 0

    if max_results:
        all_postings = all_postings[:max_results]

    # Phase 2: Deduplicate
    logger.info("Phase 2: Deduplication")
    if force:
        logger.info("Force mode: skipping deduplication")
        new_postings = all_postings
    else:
        new_postings = state_store.filter_new(all_postings)

    logger.info(f"New postings after dedupe: {len(new_postings)}")

    # Phase 3: Filter
    logger.info("Phase 3: Applying filters")
    included, near_misses = posting_filter.filter_batch(new_postings)
    logger.info(posting_filter.get_stats_summary())

    # Phase 3b: Filter out already-emailed postings (ALWAYS, even with --force)
    if included:
        pre_filter_count = len(included)
        included = state_store.filter_not_emailed(included)
        if pre_filter_count != len(included):
            logger.info(f"Filtered out {pre_filter_count - len(included)} already-emailed, {len(included)} remaining")

    # Phase 3c: Validate positions are still open
    if included:
        logger.info("Phase 3c: Validating positions still open")
        included = validate_postings_batch(included, logger)

    # Phase 4: LLM enrichment
    if (env.anthropic_api_key or env.openai_api_key) and included:
        logger.info("Phase 4: LLM classification")
        try:
            if env.anthropic_api_key:
                claude = ClaudeClient(env.anthropic_api_key)
                included = claude.classify_batch(included)
                logger.info(f"LLM usage: {claude.get_usage_stats()}")
        except Exception as e:
            logger.warning(f"LLM enrichment failed: {e}")
    else:
        logger.info("Phase 4: Skipping LLM (no API key)")

    # Sort: Summer 2026 postings first, then by most recent
    if included:
        included.sort(key=lambda p: (
            -int("summer 2026" in p.title.lower()),
            -(p.posted_at.timestamp() if p.posted_at else 0),
        ))

    # Phase 5: Generate application documents
    documents = {}
    if generate_docs and included and profile.resume_text:
        logger.info("Phase 5: Generating application documents")
        documents = generate_application_documents(included, profile, env, logger)
    else:
        logger.info("Phase 5: Skipping document generation")

    # Phase 6: Render report
    logger.info("Phase 6: Rendering report")
    html_report = renderer.render_html(included, near_misses)
    text_report = renderer.render_text(included, near_misses)

    print("\n" + text_report)

    # Phase 7: Send email (only if there are matching internships)
    if not dry_run and config.recipients and included:
        logger.info("Phase 7: Sending email")

        try:
            email_provider = create_email_provider(
                provider_type=config.email.provider,
                from_address=config.email.from_address,
                smtp_host=config.email.smtp_host or env.smtp_host,
                smtp_port=config.email.smtp_port or env.smtp_port,
                smtp_user=config.email.smtp_user or env.smtp_user,
                smtp_password=config.email.smtp_password or env.smtp_password,
                sendgrid_api_key=config.email.sendgrid_api_key or env.sendgrid_api_key
            )

            # Prepare attachments
            attachments = []

            # CSV of all postings
            csv_data = renderer.to_csv(included)
            if csv_data:
                attachments.append((
                    f"internships_{datetime.utcnow().strftime('%Y%m%d')}.csv",
                    csv_data.encode()
                ))

            # Add generated documents
            for posting in included:
                doc = documents.get(posting.posting_hash)
                if doc:
                    safe_company = "".join(c for c in posting.company if c.isalnum() or c in ' -_')[:30]
                    safe_title = "".join(c for c in posting.title if c.isalnum() or c in ' -_')[:40]
                    # Cover letter as text file
                    if doc.get('cover_letter_text'):
                        attachments.append((
                            f"CoverLetter_{safe_company}_{safe_title}.txt",
                            doc['cover_letter_text'].encode('utf-8')
                        ))
                    # Tailored resume as PDF
                    if doc.get('resume'):
                        attachments.append((
                            f"Resume_{safe_company}_{safe_title}.pdf",
                            doc['resume']
                        ))

            success = email_provider.send(
                recipients=config.recipients,
                subject=f"Underclass Internship Digest - {datetime.utcnow().strftime('%Y-%m-%d')}",
                html_body=html_report,
                text_body=text_report,
                attachments=attachments
            )

            if success:
                for posting in included:
                    state_store.mark_emailed(posting)
                logger.info(f"Email sent with {len(attachments)} attachments")
            else:
                logger.error("Email sending failed")

        except ValueError as e:
            logger.error(f"Email configuration error: {e}")
        except Exception as e:
            logger.error(f"Email error: {e}")

    elif dry_run:
        logger.info("Phase 7: Skipping email (dry run)")
    elif not included:
        logger.info("Phase 7: Skipping email (no matching internships)")
    else:
        logger.info("Phase 7: Skipping email (no recipients configured)")

    # Summary
    logger.info("=" * 60)
    logger.info(f"Scan complete: {len(included)} included, {len(near_misses)} near misses")
    if documents:
        logger.info(f"Generated {len(documents)} sets of application documents")
    logger.info("=" * 60)

    return 0


def main() -> int:
    """Main entry point."""
    # Load .env file
    load_dotenv()

    args = parse_args()
    setup_logging(level=args.log_level)
    logger = get_logger()

    # Load configuration
    config_path = Path(args.config)
    if not config_path.exists():
        logger.error(f"Config file not found: {config_path}")
        print(f"Error: Config file not found: {config_path}")
        print("Create one from config.example.yaml")
        return 1

    try:
        config = load_config(config_path)
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        print(f"Error loading config: {e}")
        return 1

    # Load seeker profile
    profile_dir = Path(args.profile_dir)
    profile = load_seeker_profile(profile_dir)
    if profile.year:
        logger.info(f"Loaded profile: {profile.year}, targeting {len(profile.roles)} role types")
    if profile.resume_text:
        logger.info(f"Resume loaded: {len(profile.resume_text)} characters")

    # Load environment settings
    env = get_env_settings()

    # Handle accelerator discovery mode
    if args.discover_accelerators:
        logger.info("=" * 60)
        logger.info("Accelerator Discovery Mode")
        logger.info("=" * 60)

        scraper = AcceleratorScraper()

        # Fetch YC companies
        logger.info("Fetching Y Combinator company list...")
        yc_companies = scraper.fetch_yc_companies()
        logger.info(f"Found {len(yc_companies)} active YC companies")

        # Load existing verified boards
        verified = scraper.get_verified_boards('yc')
        existing = sum(len(v) for v in verified.values())
        logger.info(f"Already verified: {existing} company boards")

        # Find unverified companies
        verified_slugs = set(verified['greenhouse'] + verified['lever'] + verified['ashby'])
        unverified = [c for c in yc_companies if c.slug not in verified_slugs]
        logger.info(f"Unverified companies: {len(unverified)}")

        # Discover ATS boards for new companies
        if unverified:
            to_check = min(len(unverified), args.max_discover)
            logger.info(f"Checking {to_check} companies for job boards...")
            new_boards = scraper.discover_ats_boards(unverified[:to_check], max_companies=to_check)

            # Merge with existing
            for platform in ['greenhouse', 'lever', 'ashby']:
                verified[platform] = list(set(verified[platform] + new_boards[platform]))

            # Save updated verified boards
            scraper.save_verified_boards(verified, 'yc')

            new_count = sum(len(v) for v in new_boards.values())
            logger.info(f"Discovered {new_count} new company boards")

        # Print summary
        print("\n" + "=" * 60)
        print("ACCELERATOR DISCOVERY RESULTS")
        print("=" * 60)
        print(f"Total verified boards:")
        print(f"  Greenhouse: {len(verified['greenhouse'])}")
        print(f"  Lever: {len(verified['lever'])}")
        print(f"  Ashby: {len(verified['ashby'])}")
        print(f"\nBoards cached in: cache/verified_boards_yc.json")
        print(f"Run with --use_accelerators to include these in scans")

        return 0

    # Load accelerator boards if requested
    accelerator_boards = None
    if args.use_accelerators:
        scraper = AcceleratorScraper()
        accelerator_boards = scraper.get_verified_boards('yc')
        total = sum(len(v) for v in accelerator_boards.values())
        if total > 0:
            logger.info(f"Using {total} accelerator company boards")
        else:
            logger.warning("No verified accelerator boards found. Run --discover_accelerators first.")

    # Run pipeline
    try:
        return run_pipeline(
            config=config,
            env=env,
            profile=profile,
            dry_run=args.dry_run,
            force=args.force,
            max_results=args.max_results,
            generate_docs=not args.no_documents,
            accelerator_boards=accelerator_boards
        )
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 130
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
