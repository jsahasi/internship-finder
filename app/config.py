"""Configuration loader with Pydantic validation."""

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings


class SearchConfig(BaseModel):
    """Search provider configuration."""
    provider: str = Field(default="claude", pattern="^(claude|google_cse|bing|serpapi)$")
    recency_days: int = Field(default=7, ge=1, le=30)
    queries: list[str] = Field(default_factory=list)
    target_companies: list[str] = Field(default_factory=list, description="Companies to specifically search for internships at via LLM search")
    max_results_per_query: int = Field(default=50, ge=1, le=100)
    max_company_batches: int = Field(default=10, ge=1, le=50, description="Max batches of target companies to search per LLM provider")
    require_post_date: bool = Field(default=False, description="Require postings to have a date (LLM search results often lack dates)")
    require_underclass_terms: bool = Field(default=False, description="Require explicit underclass terms (freshman/sophomore). If false, includes any internship not explicitly for upperclassmen.")


class ATSCompanies(BaseModel):
    """Target companies by ATS platform."""
    greenhouse: list[str] = Field(default_factory=list)
    lever: list[str] = Field(default_factory=list)
    ashby: list[str] = Field(default_factory=list)


class TargetsConfig(BaseModel):
    """Target companies configuration."""
    ats_companies: ATSCompanies = Field(default_factory=ATSCompanies)


class FunctionFamilyConfig(BaseModel):
    """Configuration for a single function family."""
    display_name: str = Field(..., description="Human-readable name")
    title_patterns: list[str] = Field(default_factory=list, description="Regex patterns for title matching")
    description_patterns: list[str] = Field(default_factory=list, description="Regex patterns for description matching")
    boost_keywords: list[str] = Field(default_factory=list, description="Keywords that boost classification confidence")
    target: bool = Field(default=True, description="Whether this is a target function for inclusion")


class FunctionsConfig(BaseModel):
    """Function families configuration."""
    families: dict[str, FunctionFamilyConfig] = Field(default_factory=lambda: {
        "SWE": FunctionFamilyConfig(
            display_name="Software Engineering",
            title_patterns=[
                r'\b(?:software|swe|developer|engineer(?:ing)?|programming|coding)\b',
                r'\b(?:backend|frontend|full[- ]?stack|devops|sre|platform)\b',
                r'\b(?:data\s+engineer|ml\s+engineer|machine\s+learning)\b',
                r'\b(?:ios|android|mobile)\s+(?:developer|engineer)\b',
                r'\b(?:web\s+developer|application\s+developer)\b',
            ],
            boost_keywords=[
                'python', 'java', 'javascript', 'typescript', 'react', 'node',
                'sql', 'database', 'api', 'cloud', 'aws', 'azure', 'gcp',
                'git', 'agile', 'scrum', 'ci/cd', 'kubernetes', 'docker'
            ],
            target=True
        ),
        "PM": FunctionFamilyConfig(
            display_name="Product Management",
            title_patterns=[
                r'\b(?:product\s+manag|pm\b|product\s+lead)',
                r'\b(?:program\s+manag|technical\s+program)\b',
                r'\b(?:product\s+owner|product\s+strateg)\b',
                r'\bapm\b',
            ],
            boost_keywords=[
                'roadmap', 'stakeholder', 'user research', 'sprint', 'backlog',
                'prioritization', 'metrics', 'kpi', 'a/b test', 'user story',
                'product vision', 'go-to-market', 'feature'
            ],
            target=True
        ),
        "Consulting": FunctionFamilyConfig(
            display_name="Consulting",
            title_patterns=[
                r'\b(?:consult(?:ant|ing)?)\b',
                r'\b(?:strategy|strateg(?:ic|y)\s+(?:analyst|associate))\b',
                r'\b(?:management\s+consult|business\s+analyst)\b',
                r'\b(?:advisory|transformation)\b',
            ],
            boost_keywords=[
                'client', 'engagement', 'deliverable', 'workstream', 'framework',
                'recommendation', 'presentation', 'deck', 'case study', 'bain',
                'mckinsey', 'bcg', 'deloitte', 'accenture', 'pwc', 'ey', 'kpmg'
            ],
            target=True
        ),
        "IB": FunctionFamilyConfig(
            display_name="Investment Banking",
            title_patterns=[
                r'\b(?:investment\s+bank(?:ing)?|ib\s+analyst)\b',
                r'\b(?:m&a|mergers?\s+(?:and|&)\s+acquisitions?)\b',
                r'\b(?:capital\s+markets|equity\s+research)\b',
                r'\b(?:corporate\s+finance|financial\s+analyst)\b',
                r'\b(?:private\s+equity|venture\s+capital|pe/vc)\b',
                r'\b(?:trading|sales\s+(?:and|&)\s+trading)\b',
                r'\bsummer\s+analyst\b',
            ],
            boost_keywords=[
                'deal', 'transaction', 'valuation', 'dcf', 'lbo', 'pitch book',
                'financial model', 'due diligence', 'goldman', 'morgan stanley',
                'jpmorgan', 'citi', 'barclays', 'bofa', 'ubs', 'credit suisse'
            ],
            target=True
        ),
    })


class KeywordsConfig(BaseModel):
    """Keyword configuration for filtering."""
    underclass: list[str] = Field(default_factory=lambda: [
        "freshman", "sophomore", "first-year", "first year", "second-year",
        "second year", "underclassmen", "underclassman",
        "pre-internship", "early insight", "early insights",
        "freshman/sophomore", "1st year", "2nd year"
    ])
    internship_terms: list[str] = Field(default_factory=lambda: [
        "intern", "internship", "co-op", "coop", "summer analyst",
        "summer associate", "discovery program", "explore program"
    ])
    role_terms: list[str] = Field(default_factory=lambda: [
        "software", "engineer", "developer", "swe", "product", "pm",
        "consulting", "consultant", "investment banking", "ib", "analyst"
    ])


class ExclusionsConfig(BaseModel):
    """Exclusion rules configuration."""
    graduation_years: list[int] = Field(default_factory=lambda: [2027, 2028])
    upperclass_terms: list[str] = Field(default_factory=lambda: [
        "junior", "senior", "penultimate", "rising senior", "final year",
        "final-year", "3rd year", "4th year", "upperclassmen", "upperclassman",
        "third year", "fourth year", "junior/senior", "new grad", "new graduate"
    ])


class EmailConfig(BaseModel):
    """Email delivery configuration."""
    provider: str = Field(default="smtp", pattern="^(sendgrid|ses|smtp)$")
    from_address: str = Field(default="internships@example.com")
    smtp_host: Optional[str] = None
    smtp_port: int = Field(default=587)
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    sendgrid_api_key: Optional[str] = None


class AppConfig(BaseModel):
    """Main application configuration."""
    recipients: list[str] = Field(default_factory=list)
    search: SearchConfig = Field(default_factory=SearchConfig)
    targets: TargetsConfig = Field(default_factory=TargetsConfig)
    keywords: KeywordsConfig = Field(default_factory=KeywordsConfig)
    exclusions: ExclusionsConfig = Field(default_factory=ExclusionsConfig)
    functions: FunctionsConfig = Field(default_factory=FunctionsConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    database_path: str = Field(default="internships.db")

    @field_validator('recipients')
    @classmethod
    def validate_recipients(cls, v: list[str]) -> list[str]:
        """Validate email addresses."""
        for email in v:
            if '@' not in email:
                raise ValueError(f"Invalid email address: {email}")
        return v


class EnvSettings(BaseSettings):
    """Environment variable settings."""
    # LLM API Keys
    anthropic_api_key: Optional[str] = Field(default=None, alias="ANTHROPIC_API_KEY")
    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    xai_api_key: Optional[str] = Field(default=None, alias="XAI_API_KEY")

    # Search API Keys (optional, Claude/OpenAI search is default)
    google_cse_api_key: Optional[str] = Field(default=None, alias="GOOGLE_CSE_API_KEY")
    google_cse_cx: Optional[str] = Field(default=None, alias="GOOGLE_CSE_CX")
    bing_api_key: Optional[str] = Field(default=None, alias="BING_API_KEY")
    serpapi_key: Optional[str] = Field(default=None, alias="SERPAPI_KEY")

    # Email settings
    sendgrid_api_key: Optional[str] = Field(default=None, alias="SENDGRID_API_KEY")
    smtp_host: Optional[str] = Field(default=None, alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_user: Optional[str] = Field(default=None, alias="SMTP_USER")
    smtp_password: Optional[str] = Field(default=None, alias="SMTP_PASSWORD")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


def load_config(config_path: str | Path) -> AppConfig:
    """Load configuration from YAML file."""
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, 'r', encoding='utf-8') as f:
        raw_config = yaml.safe_load(f) or {}

    return AppConfig(**raw_config)


def get_env_settings() -> EnvSettings:
    """Load environment settings."""
    return EnvSettings()
