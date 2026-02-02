"""LLM response schema definitions."""

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class LLMClassificationResponse(BaseModel):
    """Schema for LLM classification response."""

    decision: str = Field(
        ...,
        pattern="^(include|exclude)$",
        description="Whether to include or exclude the posting"
    )
    role_family: str = Field(
        ...,
        pattern="^(SWE|PM|Consulting|IB|Other)$",
        description="Job function category"
    )
    underclass_evidence: Optional[str] = Field(
        None,
        description="Exact phrase indicating underclass targeting"
    )
    why_fits: str = Field(
        ...,
        description="Brief explanation of why this fits underclass criteria"
    )
    summary_bullets: list[str] = Field(
        ...,
        min_length=1,
        max_length=4,
        description="2-4 bullet points summarizing the role"
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score 0-1"
    )
    exclude_reason: Optional[str] = Field(
        None,
        description="Reason for exclusion if decision is exclude"
    )

    @field_validator('summary_bullets')
    @classmethod
    def validate_bullets(cls, v: list[str]) -> list[str]:
        """Ensure bullets are non-empty and reasonably sized."""
        cleaned = []
        for bullet in v:
            bullet = bullet.strip()
            if bullet and len(bullet) <= 200:
                cleaned.append(bullet)
        if not cleaned:
            raise ValueError("At least one non-empty summary bullet required")
        return cleaned[:4]  # Max 4 bullets

    @field_validator('why_fits')
    @classmethod
    def validate_why_fits(cls, v: str) -> str:
        """Ensure why_fits is concise."""
        v = v.strip()
        if len(v) > 300:
            v = v[:297] + "..."
        return v


class LLMBatchRequest(BaseModel):
    """Request for batch classification."""

    postings: list[dict] = Field(
        ...,
        description="List of posting data to classify"
    )
    max_tokens: int = Field(
        default=2000,
        description="Max tokens for response"
    )


class LLMBatchResponse(BaseModel):
    """Response from batch classification."""

    results: list[LLMClassificationResponse] = Field(
        ...,
        description="Classification results for each posting"
    )
    usage: dict = Field(
        default_factory=dict,
        description="Token usage statistics"
    )
