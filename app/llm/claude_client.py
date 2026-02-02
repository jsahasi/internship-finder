"""Claude API client for posting classification."""

import json
from typing import Optional

from anthropic import Anthropic
from pydantic import ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential

from app.extract.normalize import Posting
from app.llm.prompts import SYSTEM_PROMPT, format_posting_for_prompt
from app.llm.schema import LLMClassificationResponse
from app.logging_config import get_logger


logger = get_logger()


class ClaudeClient:
    """Client for Claude API classification."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 1500
    ):
        """Initialize Claude client.

        Args:
            api_key: Anthropic API key.
            model: Model to use.
            max_tokens: Max tokens for response.
        """
        self.client = Anthropic(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens
        self.total_tokens_used = 0

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def classify_posting(self, posting: Posting) -> Optional[LLMClassificationResponse]:
        """Classify a single posting using Claude.

        Args:
            posting: Posting to classify.

        Returns:
            LLMClassificationResponse or None if classification fails.
        """
        prompt = format_posting_for_prompt(
            company=posting.company,
            title=posting.title,
            location=posting.location,
            description=posting.text
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}]
            )

            # Track token usage
            usage = response.usage
            self.total_tokens_used += usage.input_tokens + usage.output_tokens

            # Extract response text
            content = response.content[0].text

            # Parse JSON response
            return self._parse_response(content)

        except Exception as e:
            logger.error(f"Claude API error: {e}")
            return None

    def _parse_response(self, content: str) -> Optional[LLMClassificationResponse]:
        """Parse LLM response into validated schema.

        Args:
            content: Raw response text.

        Returns:
            Validated response or None.
        """
        try:
            # Clean potential markdown code blocks
            content = content.strip()
            if content.startswith('```'):
                lines = content.split('\n')
                content = '\n'.join(lines[1:-1] if lines[-1] == '```' else lines[1:])

            data = json.loads(content)
            return LLMClassificationResponse(**data)

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON response: {e}")
            logger.debug(f"Raw content: {content[:500]}")
            return None
        except ValidationError as e:
            logger.warning(f"Response validation failed: {e}")
            return None

    def enrich_posting(self, posting: Posting) -> Posting:
        """Enrich a posting with LLM classification data.

        Args:
            posting: Posting to enrich.

        Returns:
            Enriched posting (modified in place).
        """
        result = self.classify_posting(posting)

        if result is None:
            logger.warning(f"Could not classify posting: {posting.title}")
            return posting

        # Update posting with LLM data
        # Set function family directly as string
        posting.function_family = result.role_family

        posting.underclass_evidence = result.underclass_evidence
        posting.why_fits = result.why_fits
        posting.summary_bullets = result.summary_bullets
        posting.confidence = result.confidence

        return posting

    def classify_batch(
        self,
        postings: list[Posting],
        skip_if_enriched: bool = True
    ) -> list[Posting]:
        """Classify a batch of postings.

        Args:
            postings: List of postings to classify.
            skip_if_enriched: Skip postings that already have classification data.

        Returns:
            List of enriched postings.
        """
        results = []

        for posting in postings:
            # Skip already enriched
            if skip_if_enriched and posting.why_fits:
                results.append(posting)
                continue

            enriched = self.enrich_posting(posting)
            results.append(enriched)

            logger.debug(
                f"Classified '{posting.title}': "
                f"family={posting.function_family}, "
                f"confidence={posting.confidence:.2f}"
            )

        logger.info(
            f"Classified {len(postings)} postings, "
            f"total tokens: {self.total_tokens_used}"
        )

        return results

    def should_include(self, posting: Posting) -> tuple[bool, str]:
        """Use LLM to make final include/exclude decision.

        Args:
            posting: Posting to evaluate.

        Returns:
            Tuple of (should_include, reason).
        """
        result = self.classify_posting(posting)

        if result is None:
            return False, "LLM classification failed"

        if result.decision == "exclude":
            return False, result.exclude_reason or "LLM decided to exclude"

        return True, result.why_fits

    def get_usage_stats(self) -> dict:
        """Get token usage statistics."""
        return {
            "total_tokens": self.total_tokens_used,
            "model": self.model
        }
