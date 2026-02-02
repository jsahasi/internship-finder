"""Normalized posting data model."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, computed_field


class FunctionFamily(str, Enum):
    """Job function categories."""
    SWE = "SWE"
    PM = "PM"
    CONSULTING = "Consulting"
    IB = "IB"
    OTHER = "Other"


class ATSSource(str, Enum):
    """ATS platform sources."""
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"
    WORKDAY = "workday"
    GENERIC = "generic"
    SEARCH = "search"


class Posting(BaseModel):
    """Normalized job posting model."""
    company: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    function_family: FunctionFamily = Field(default=FunctionFamily.OTHER)
    location: str = Field(default="Not specified")
    url: str = Field(..., min_length=1)
    source: ATSSource = Field(default=ATSSource.GENERIC)
    posted_at: Optional[datetime] = None
    text: str = Field(default="")
    raw_snippet: str = Field(default="")
    retrieved_at: datetime = Field(default_factory=datetime.utcnow)

    # LLM-enriched fields (populated after classification)
    underclass_evidence: Optional[str] = None
    why_fits: Optional[str] = None
    summary_bullets: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @computed_field
    @property
    def posting_hash(self) -> str:
        """Compute unique hash for deduplication."""
        import hashlib
        content = f"{self.company}|{self.title}|{self.url}|{self.location}"
        return hashlib.sha256(content.encode()).hexdigest()

    @computed_field
    @property
    def age_days(self) -> Optional[int]:
        """Days since posting."""
        if self.posted_at is None:
            return None
        delta = datetime.utcnow() - self.posted_at
        return delta.days

    def to_table_row(self) -> dict:
        """Convert to table row format for reporting."""
        return {
            "Company": self.company,
            "Role": self.title,
            "Function": self.function_family.value,
            "Location": self.location,
            "Posted": self.posted_at.strftime("%Y-%m-%d") if self.posted_at else "Unknown",
            "Evidence": self.underclass_evidence or "",
            "Why Fits": self.why_fits or "",
            "URL": self.url
        }


class NearMiss(BaseModel):
    """Excluded posting with reason."""
    posting: Posting
    exclusion_reason: str
    evidence_snippet: str = ""

    def to_table_row(self) -> dict:
        """Convert to table row format."""
        return {
            "Company": self.posting.company,
            "Role": self.posting.title,
            "URL": self.posting.url,
            "Exclusion Reason": self.exclusion_reason,
            "Evidence": self.evidence_snippet
        }
