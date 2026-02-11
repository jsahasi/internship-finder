"""LinkedIn job search via linkedin-jobs-api (Node.js)."""

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.extract.normalize import ATSSource, Posting
from app.filtering.taxonomy import classify_function
from app.logging_config import get_logger


logger = get_logger()

LINKEDIN_SEARCH_SCRIPT = """
const linkedIn = require('linkedin-jobs-api');

const queryOptions = {
  keyword: KEYWORD_PLACEHOLDER,
  location: 'United States',
  dateSincePosted: 'past 24 hours',
  jobType: '',
  remoteFilter: '',
  salary: '',
  experienceLevel: 'internship',
  limit: '50',
  page: '0',
};

linkedIn.query(queryOptions).then(response => {
  const results = response.map(job => ({
    title: job.position || '',
    company: job.company || '',
    location: job.location || '',
    url: job.jobUrl || '',
    date: job.date || '',
    agoTime: job.agoTime || '',
  }));
  console.log(JSON.stringify(results));
}).catch(err => {
  console.error(JSON.stringify({error: err.message}));
  process.exit(1);
});
"""


def search_linkedin(keyword: str = "summer 2026 internship", limit: int = 50) -> list[Posting]:
    """Search LinkedIn for internship postings using linkedin-jobs-api.

    Args:
        keyword: Search keyword.
        limit: Max results.

    Returns:
        List of Posting objects.
    """
    script = LINKEDIN_SEARCH_SCRIPT.replace(
        'KEYWORD_PLACEHOLDER',
        json.dumps(keyword)
    ).replace("'50'", f"'{limit}'")

    try:
        # Run from project root where node_modules is installed
        project_root = str(Path(__file__).resolve().parent.parent.parent)
        result = subprocess.run(
            ['node', '-e', script],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=project_root
        )

        if result.returncode != 0:
            logger.warning(f"LinkedIn search failed: {result.stderr.strip()}")
            return []

        # The library prints debug lines to stdout before JSON; extract only the JSON line
        stdout_lines = result.stdout.strip().split('\n')
        json_line = None
        for line in reversed(stdout_lines):
            line = line.strip()
            if line.startswith('['):
                json_line = line
                break
        if not json_line:
            logger.warning("LinkedIn search: no JSON output found")
            return []

        jobs = json.loads(json_line)
    except subprocess.TimeoutExpired:
        logger.warning("LinkedIn search timed out")
        return []
    except (json.JSONDecodeError, FileNotFoundError) as e:
        logger.warning(f"LinkedIn search error: {e}")
        return []

    postings = []
    for job in jobs:
        title = job.get('title', '').strip()
        company = job.get('company', '').strip()
        location = job.get('location', '').strip()
        url = job.get('url', '').strip()

        if not title or not company or not url:
            continue

        # Clean LinkedIn tracking from URL
        if '?' in url:
            url = url.split('?')[0]

        family, confidence = classify_function(title, '')

        postings.append(Posting(
            company=company,
            title=title,
            function_family=family,
            location=location or 'Not specified',
            url=url,
            source=ATSSource.SEARCH,
            search_provider='LinkedIn',
            posted_at=datetime.utcnow(),
            text='',
            raw_snippet='',
            confidence=confidence
        ))

    logger.info(f"LinkedIn search: {len(postings)} postings found")
    return postings


def extract_companies(postings: list[Posting]) -> list[str]:
    """Extract unique company names from LinkedIn postings.

    Args:
        postings: LinkedIn search results.

    Returns:
        List of unique company names.
    """
    return list({p.company for p in postings if p.company})
