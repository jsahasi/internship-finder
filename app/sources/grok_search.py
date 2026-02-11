"""Grok-powered job search using X.AI's API with web search capabilities."""

import json
from datetime import datetime
from typing import Optional

from tenacity import retry, stop_after_attempt, wait_exponential

from app.extract.canonical import canonicalize_url, detect_ats_type
from app.extract.dates import parse_date
from app.extract.normalize import OTHER_FUNCTION, Posting, ATSSource
from app.logging_config import get_logger


logger = get_logger()


SEARCH_PROMPT = """Search for underclass (freshman/sophomore) internship programs.

Requirements:
- Must be explicitly for freshmen, sophomores, first-year, or second-year students
- Programs labeled: "Discovery", "Explore", "Early Insight", "Pre-internship"
- Roles in: {functions}
- Posted within the last {days} days
- On job boards: Greenhouse, Lever, Ashby, Workday

EXCLUDE any postings mentioning:
- "2027" or "2028" graduation years
- "junior", "senior", "penultimate", "rising senior"
- PhD, masters, graduate students

Search query: {query}

Return a JSON array of findings with:
- company: Company name
- title: Job title
- url: Direct link to posting
- location: City/State or Remote
- posted_at: Date if known (YYYY-MM-DD) or null
- underclass_evidence: Exact phrase showing underclass targeting
- function_family: SWE, PM, Consulting, IB, or Other
- description: Brief 1-2 sentence description

Return ONLY valid JSON array. Empty array [] if none found."""


class GrokSearchProvider:
    """Search provider using Grok (X.AI) with web search capabilities."""

    def __init__(self, api_key: str, max_results: int = 20):
        """Initialize Grok search provider.

        Args:
            api_key: X.AI API key.
            max_results: Maximum results to return.
        """
        try:
            from openai import OpenAI
            # Grok uses OpenAI-compatible API
            self.client = OpenAI(
                api_key=api_key,
                base_url="https://api.x.ai/v1"
            )
        except ImportError:
            raise ImportError("openai package required: pip install openai")

        self.max_results = max_results
        self.tokens_used = 0

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def search(
        self,
        target_functions: list[str],
        underclass_terms: list[str],
        companies: Optional[list[str]] = None,
        recency_days: int = 7
    ) -> list[Posting]:
        """Search for underclass internships using Grok.

        Args:
            target_functions: Function families to search for.
            underclass_terms: Terms indicating underclass targeting.
            companies: Optional specific companies.
            recency_days: Only include recent postings.

        Returns:
            List of Posting objects.
        """
        functions_str = ", ".join(target_functions)
        terms_str = " OR ".join(underclass_terms[:5])

        if companies:
            query_companies = ", ".join(companies[:10])
            query = f"({terms_str}) internship ({functions_str}) at {query_companies}"
            companies_list = "\n".join(f"- {c}" for c in companies)
            companies_addendum = f"\n\nPRIORITY COMPANIES TO CHECK:\n{companies_list}\n\nSearch for internship programs at ALL of these companies."
        else:
            query = f"({terms_str}) internship 2026 ({functions_str}) site:greenhouse.io OR site:lever.co OR site:ashbyhq.com"
            companies_addendum = ""

        logger.info(f"Grok searching: {query[:80]}... ({len(companies) if companies else 0} target companies)")

        prompt = SEARCH_PROMPT.format(
            functions=functions_str,
            days=recency_days,
            query=query
        ) + companies_addendum

        try:
            response = self.client.chat.completions.create(
                model="grok-3",
                max_tokens=4096,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a job search assistant with real-time web access. Search the web for current job postings and return structured JSON results."
                    },
                    {"role": "user", "content": prompt}
                ]
            )

            content = response.choices[0].message.content
            if response.usage:
                self.tokens_used += response.usage.total_tokens

            return self._parse_results(content)

        except Exception as e:
            logger.error(f"Grok search failed: {e}")
            return []

    def _parse_results(self, content: str) -> list[Posting]:
        """Parse Grok response into Posting objects."""
        postings = []

        try:
            # Clean markdown
            content = content.strip()
            if content.startswith('```'):
                lines = content.split('\n')
                content = '\n'.join(lines[1:-1] if lines[-1].startswith('```') else lines[1:])

            # Find JSON array
            start = content.find('[')
            end = content.rfind(']') + 1
            if start >= 0 and end > start:
                results = json.loads(content[start:end])
            else:
                return []

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse Grok response: {e}")
            return []

        for item in results[:self.max_results]:
            try:
                posted_at = parse_date(item.get('posted_at')) if item.get('posted_at') else None
                url = item.get('url', '')

                ats_type = detect_ats_type(url)
                source = ATSSource.SEARCH
                if ats_type == 'greenhouse':
                    source = ATSSource.GREENHOUSE
                elif ats_type == 'lever':
                    source = ATSSource.LEVER
                elif ats_type == 'ashby':
                    source = ATSSource.ASHBY

                posting = Posting(
                    company=item.get('company', 'Unknown'),
                    title=item.get('title', 'Unknown'),
                    function_family=item.get('function_family', OTHER_FUNCTION),
                    location=item.get('location', 'Not specified'),
                    url=canonicalize_url(url),
                    source=source,
                    posted_at=posted_at,
                    text=item.get('description', ''),
                    raw_snippet=item.get('description', '')[:500],
                    underclass_evidence=item.get('underclass_evidence'),
                    search_provider="Grok"
                )
                postings.append(posting)

            except Exception as e:
                logger.debug(f"Failed to parse posting: {e}")

        logger.info(f"Grok search found {len(postings)} postings")
        return postings

    def get_usage_stats(self) -> dict:
        """Get usage statistics."""
        return {
            "total_tokens": self.tokens_used,
            "provider": "grok"
        }
