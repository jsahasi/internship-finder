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
from app.reporting.emailer import create_email_provider
from app.reporting.render import ReportRenderer
from app.sources.ashby import AshbyAdapter
from app.sources.generic_html import GenericHTMLParser
from app.sources.greenhouse import GreenhouseAdapter
from app.sources.lever import LeverAdapter
from app.sources.claude_search import ClaudeSearchProvider
from app.sources.search_provider import (
    create_search_provider,
    build_internship_query
)
from app.storage.state import StateStore


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
    return parser.parse_args()


def fetch_from_ats(
    config: AppConfig,
    logger
) -> list[Posting]:
    """Fetch postings from configured ATS companies.

    Args:
        config: Application configuration.
        logger: Logger instance.

    Returns:
        List of fetched postings.
    """
    postings = []
    ats_config = config.targets.ats_companies

    # Greenhouse
    if ats_config.greenhouse:
        logger.info(f"Fetching from {len(ats_config.greenhouse)} Greenhouse boards")
        gh_adapter = GreenhouseAdapter()
        for company in ats_config.greenhouse:
            try:
                jobs = gh_adapter.fetch_jobs(company)
                postings.extend(jobs)
            except Exception as e:
                logger.warning(f"Greenhouse '{company}' failed: {e}")

    # Lever
    if ats_config.lever:
        logger.info(f"Fetching from {len(ats_config.lever)} Lever boards")
        lever_adapter = LeverAdapter()
        for company in ats_config.lever:
            try:
                jobs = lever_adapter.fetch_jobs(company)
                postings.extend(jobs)
            except Exception as e:
                logger.warning(f"Lever '{company}' failed: {e}")

    # Ashby
    if ats_config.ashby:
        logger.info(f"Fetching from {len(ats_config.ashby)} Ashby boards")
        ashby_adapter = AshbyAdapter()
        for company in ats_config.ashby:
            try:
                jobs = ashby_adapter.fetch_jobs(company)
                postings.extend(jobs)
            except Exception as e:
                logger.warning(f"Ashby '{company}' failed: {e}")

    logger.info(f"ATS fetch complete: {len(postings)} total postings")
    return postings


def fetch_from_search(
    config: AppConfig,
    env: EnvSettings,
    logger
) -> list[Posting]:
    """Fetch postings via search provider.

    Args:
        config: Application configuration.
        env: Environment settings.
        logger: Logger instance.

    Returns:
        List of fetched postings.
    """
    postings = []
    provider_type = config.search.provider

    # Claude search (default - uses LLM with web search)
    if provider_type == 'claude':
        if not env.anthropic_api_key:
            logger.warning("Anthropic API key not configured, skipping Claude search")
            return []

        logger.info("Using Claude-powered search")
        claude_search = ClaudeSearchProvider(
            api_key=env.anthropic_api_key,
            max_results=config.search.max_results_per_query
        )

        # Get target function families
        target_functions = [
            key for key, cfg in config.functions.families.items()
            if cfg.target
        ]

        # Search using Claude
        postings = claude_search.search(
            target_functions=target_functions,
            underclass_terms=config.keywords.underclass,
            recency_days=config.search.recency_days
        )

        logger.info(f"Claude search complete: {len(postings)} postings, {claude_search.get_usage_stats()}")
        return postings

    # Traditional search API providers
    api_key = None
    cx = None

    if provider_type == 'google_cse':
        api_key = env.google_cse_api_key
        cx = env.google_cse_cx
        if not api_key or not cx:
            logger.warning("Google CSE credentials not configured, skipping search")
            return []
    elif provider_type == 'bing':
        api_key = env.bing_api_key
        if not api_key:
            logger.warning("Bing API key not configured, skipping search")
            return []
    elif provider_type == 'serpapi':
        api_key = env.serpapi_key
        if not api_key:
            logger.warning("SerpAPI key not configured, skipping search")
            return []

    try:
        provider = create_search_provider(provider_type, api_key, cx)
    except ValueError as e:
        logger.error(f"Failed to create search provider: {e}")
        return []

    # Build queries
    queries = config.search.queries
    if not queries:
        # Build default query
        queries = [build_internship_query(
            config.keywords.underclass[:5],
            config.keywords.role_terms[:5]
        )]

    # Execute searches
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

                # Route to appropriate adapter
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
                    # Generic HTML parsing
                    posting = generic_parser.parse_url(result.url)

                if posting:
                    postings.append(posting)

            except Exception as e:
                logger.debug(f"Failed to parse result {result.url}: {e}")

    logger.info(f"Search fetch complete: {len(postings)} postings")
    return postings


def run_pipeline(
    config: AppConfig,
    env: EnvSettings,
    dry_run: bool = False,
    force: bool = False,
    max_results: Optional[int] = None
) -> int:
    """Run the main processing pipeline.

    Args:
        config: Application configuration.
        env: Environment settings.
        dry_run: Skip email sending.
        force: Ignore deduplication.
        max_results: Maximum results to process.

    Returns:
        Exit code (0 for success).
    """
    logger = get_logger()
    logger.info("=" * 60)
    logger.info("Starting Underclass Internship Scanner")
    logger.info("=" * 60)

    # Initialize components
    state_store = StateStore(config.database_path)
    posting_filter = PostingFilter(
        config.keywords,
        config.exclusions,
        config.search.recency_days,
        config.functions
    )
    renderer = ReportRenderer()

    # Phase 1: Fetch postings
    logger.info("Phase 1: Fetching postings")
    all_postings = []

    # Fetch from ATS
    ats_postings = fetch_from_ats(config, logger)
    all_postings.extend(ats_postings)

    # Fetch from search
    search_postings = fetch_from_search(config, env, logger)
    all_postings.extend(search_postings)

    logger.info(f"Total postings fetched: {len(all_postings)}")

    if not all_postings:
        logger.warning("No postings found")
        print("\n0 postings found. Check your configuration.")
        return 0

    # Limit if requested
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

    # Phase 4: LLM enrichment (if API key available)
    if env.anthropic_api_key and included:
        logger.info("Phase 4: LLM classification")
        try:
            claude = ClaudeClient(env.anthropic_api_key)
            included = claude.classify_batch(included)
            logger.info(f"LLM usage: {claude.get_usage_stats()}")
        except Exception as e:
            logger.warning(f"LLM enrichment failed: {e}")
    elif not env.anthropic_api_key:
        logger.info("Phase 4: Skipping LLM (no API key)")

    # Phase 5: Render report
    logger.info("Phase 5: Rendering report")
    html_report = renderer.render_html(included, near_misses)
    text_report = renderer.render_text(included, near_misses)

    # Print results
    print("\n" + text_report)

    # Phase 6: Send email
    if not dry_run and config.recipients:
        logger.info("Phase 6: Sending email")

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

            # Prepare CSV attachment
            csv_data = renderer.to_csv(included)
            attachments = []
            if csv_data:
                attachments.append((
                    f"internships_{datetime.utcnow().strftime('%Y%m%d')}.csv",
                    csv_data.encode()
                ))

            success = email_provider.send(
                recipients=config.recipients,
                subject=f"Underclass Internship Digest - {datetime.utcnow().strftime('%Y-%m-%d')}",
                html_body=html_report,
                text_body=text_report,
                attachments=attachments
            )

            if success:
                # Mark postings as emailed
                for posting in included:
                    state_store.mark_emailed(posting)
                logger.info("Email sent successfully")
            else:
                logger.error("Email sending failed")

        except ValueError as e:
            logger.error(f"Email configuration error: {e}")
        except Exception as e:
            logger.error(f"Email error: {e}")

    elif dry_run:
        logger.info("Phase 6: Skipping email (dry run)")
    else:
        logger.info("Phase 6: Skipping email (no recipients configured)")

    # Summary
    logger.info("=" * 60)
    logger.info(f"Scan complete: {len(included)} included, {len(near_misses)} near misses")
    logger.info("=" * 60)

    return 0


def main() -> int:
    """Main entry point."""
    # Load .env file
    load_dotenv()

    # Parse arguments
    args = parse_args()

    # Setup logging
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

    # Load environment settings
    env = get_env_settings()

    # Run pipeline
    try:
        return run_pipeline(
            config=config,
            env=env,
            dry_run=args.dry_run,
            force=args.force,
            max_results=args.max_results
        )
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 130
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
