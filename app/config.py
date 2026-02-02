"""Configuration loader with Pydantic validation."""

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings


class SearchConfig(BaseModel):
    """Search provider configuration."""
    provider: str = Field(default="google_cse", pattern="^(google_cse|bing|serpapi)$")
    recency_days: int = Field(default=7, ge=1, le=30)
    queries: list[str] = Field(default_factory=list)
    max_results_per_query: int = Field(default=50, ge=1, le=100)


class ATSCompanies(BaseModel):
    """Target companies by ATS platform."""
    greenhouse: list[str] = Field(default_factory=list)
    lever: list[str] = Field(default_factory=list)
    ashby: list[str] = Field(default_factory=list)


class TargetsConfig(BaseModel):
    """Target companies configuration."""
    ats_companies: ATSCompanies = Field(default_factory=ATSCompanies)


class KeywordsConfig(BaseModel):
    """Keyword configuration for filtering."""
    underclass: list[str] = Field(default_factory=lambda: [
        "freshman", "sophomore", "first-year", "first year", "second-year",
        "second year", "underclassmen", "underclassman", "discovery",
        "pre-internship", "early insight", "early insights", "explore",
        "freshman/sophomore", "1st year", "2nd year"
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
        "third year", "fourth year", "junior/senior"
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
    google_cse_api_key: Optional[str] = Field(default=None, alias="GOOGLE_CSE_API_KEY")
    google_cse_cx: Optional[str] = Field(default=None, alias="GOOGLE_CSE_CX")
    bing_api_key: Optional[str] = Field(default=None, alias="BING_API_KEY")
    serpapi_key: Optional[str] = Field(default=None, alias="SERPAPI_KEY")
    anthropic_api_key: Optional[str] = Field(default=None, alias="ANTHROPIC_API_KEY")
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
