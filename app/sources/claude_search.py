"""Claude-powered job search using web search and intelligent parsing."""

import json
from datetime import datetime
from typing import Optional

from anthropic import Anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from app.extract.canonical import canonicalize_url, detect_ats_type
from app.extract.dates import parse_date
from app.extract.normalize import OTHER_FUNCTION, Posting, ATSSource
from app.logging_config import get_logger


logger = get_logger()


SEARCH_SYSTEM_PROMPT = """You are an expert at finding underclass internship opportunities.

Your task is to search for internship postings that are specifically targeted at freshmen and sophomores (underclassmen) in these fields:
- Software Engineering (SWE)
- Product Management (PM)
- Consulting
- Investment Banking (IB)

When searching, focus on:
1. Programs explicitly for "freshman", "sophomore", "first-year", "second-year", "underclassmen"
2. "Discovery", "Explore", "Early Insight", "Pre-internship" programs
3. Postings on official ATS platforms: Greenhouse, Lever, Ashby, Workday

EXCLUDE any postings that:
- Mention "2027" or "2028" graduation years
- Are for "juniors", "seniors", "penultimate year", "rising seniors"
- Don't explicitly mention underclass targeting

For each result found, extract:
- Company name
- Job title
- URL (direct link to posting)
- Location
- Posted date (if available)
- The exact phrase showing it's for underclassmen
- Brief description"""


PARSE_RESULTS_PROMPT = """Analyze these search results and extract structured internship data.

Search Results:
{results}

Return a JSON array of internship postings. Each posting should have:
{{
  "company": "Company Name",
  "title": "Job Title",
  "url": "https://...",
  "location": "City, State or Remote",
  "posted_at": "YYYY-MM-DD or null",
  "underclass_evidence": "exact phrase showing underclass targeting",
  "function_family": "SWE|PM|Consulting|IB|Other",
  "description": "brief 1-2 sentence description"
}}

Only include postings that:
1. Have explicit underclass targeting (freshman/sophomore/first-year/etc.)
2. Are in SWE, PM, Consulting, or IB
3. Do NOT mention 2027/2028 graduation years
4. Do NOT mention juniors/seniors/penultimate

Return ONLY valid JSON array. If no valid postings found, return []."""


class ClaudeSearchProvider:
    """Search provider that uses Claude with web search for intelligent job discovery."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
        max_results: int = 20
    ):
        """Initialize Claude search provider.

        Args:
            api_key: Anthropic API key.
            model: Model to use (must support web search).
            max_results: Maximum results to return.
        """
        self.client = Anthropic(api_key=api_key)
        self.model = model
        self.max_results = max_results
        self.total_tokens_used = 0

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
        """Search for underclass internships using Claude with web search.

        Args:
            target_functions: Function families to search for.
            underclass_terms: Terms indicating underclass targeting.
            companies: Optional list of specific companies to search.
            recency_days: Only include postings from last N days.

        Returns:
            List of Posting objects.
        """
        # Build search query
        functions_str = ", ".join(target_functions)
        terms_str = ", ".join(underclass_terms[:5])

        if companies:
            # Use first few in the search query, full list in the prompt
            query_companies = ", ".join(companies[:10])
            search_query = f"underclass internship ({terms_str}) ({functions_str}) at ({query_companies}) site:greenhouse.io OR site:lever.co OR site:ashbyhq.com"
            companies_context = "\n".join(f"- {c}" for c in companies)
            companies_instruction = f"""

PRIORITY COMPANIES TO SEARCH (check all of these for underclass internship programs):
{companies_context}

Search for internship programs at these specific companies. Do multiple searches if needed to cover them all."""
        else:
            search_query = f"underclass internship 2026 ({terms_str}) ({functions_str}) site:greenhouse.io OR site:lever.co OR site:ashbyhq.com"
            companies_instruction = ""

        logger.info(f"Claude searching: {search_query[:80]}... ({len(companies) if companies else 0} target companies)")

        try:
            # Use Claude with web search tool - more searches for larger company lists
            max_searches = min(5 + (len(companies) // 20 if companies else 0), 10)
            response = self.client.messages.create(
                model=self.model,
                max_tokens=8192,
                system=SEARCH_SYSTEM_PROMPT,
                tools=[{
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": max_searches
                }],
                messages=[{
                    "role": "user",
                    "content": f"""Search for underclass (freshman/sophomore) internship programs in {functions_str}.

Focus on finding programs posted in the last {recency_days} days that explicitly target first-year and second-year students.

Search query to use: {search_query}
{companies_instruction}
After searching, provide the results as a JSON array of postings with: company, title, url, location, posted_at, underclass_evidence, function_family, description.

Return ONLY the JSON array."""
                }]
            )

            # Track usage
            self.total_tokens_used += response.usage.input_tokens + response.usage.output_tokens

            # Extract text content
            text_content = ""
            for block in response.content:
                if hasattr(block, 'text'):
                    text_content += block.text

            # Parse results
            return self._parse_results(text_content)

        except Exception as e:
            logger.error(f"Claude search failed: {e}")
            return []

    def _parse_results(self, content: str) -> list[Posting]:
        """Parse Claude's response into Posting objects.

        Args:
            content: Raw response text.

        Returns:
            List of Posting objects.
        """
        postings = []

        # Try to extract JSON from response
        try:
            # Clean up potential markdown
            content = content.strip()
            if content.startswith('```'):
                lines = content.split('\n')
                content = '\n'.join(lines[1:-1] if lines[-1].startswith('```') else lines[1:])

            # Find JSON array
            start = content.find('[')
            end = content.rfind(']') + 1
            if start >= 0 and end > start:
                json_str = content[start:end]
                results = json.loads(json_str)
            else:
                logger.warning("No JSON array found in Claude response")
                return []

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse Claude response as JSON: {e}")
            return []

        # Convert to Posting objects
        for item in results[:self.max_results]:
            try:
                posted_at = None
                if item.get('posted_at'):
                    posted_at = parse_date(item['posted_at'])

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
                    search_provider="Claude"
                )
                postings.append(posting)

            except Exception as e:
                logger.debug(f"Failed to parse posting: {e}")
                continue

        logger.info(f"Claude search found {len(postings)} postings")
        return postings

    def search_company(self, company: str, ats_type: str) -> list[Posting]:
        """Search for internships at a specific company.

        Args:
            company: Company name or slug.
            ats_type: ATS type (greenhouse, lever, ashby).

        Returns:
            List of Posting objects.
        """
        site_map = {
            'greenhouse': 'boards.greenhouse.io',
            'lever': 'jobs.lever.co',
            'ashby': 'jobs.ashbyhq.com'
        }
        site = site_map.get(ats_type, '')

        query = f"underclass freshman sophomore internship site:{site}/{company}"

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=SEARCH_SYSTEM_PROMPT,
                tools=[{
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": 2
                }],
                messages=[{
                    "role": "user",
                    "content": f"""Search for underclass internship programs at {company}.

Search: {query}

Return results as JSON array with: company, title, url, location, posted_at, underclass_evidence, function_family, description.

Return ONLY valid JSON array."""
                }]
            )

            self.total_tokens_used += response.usage.input_tokens + response.usage.output_tokens

            text_content = ""
            for block in response.content:
                if hasattr(block, 'text'):
                    text_content += block.text

            return self._parse_results(text_content)

        except Exception as e:
            logger.warning(f"Claude company search failed for {company}: {e}")
            return []

    def get_usage_stats(self) -> dict:
        """Get usage statistics."""
        return {
            "total_tokens": self.total_tokens_used,
            "model": self.model
        }
