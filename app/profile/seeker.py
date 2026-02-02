"""Parse user seeking profile and resume."""

import re
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from app.logging_config import get_logger


logger = get_logger()


class SeekerProfile(BaseModel):
    """User's job seeking profile."""
    year: str = Field(default="sophomore", description="Current year in college")
    graduation_year: Optional[int] = Field(default=None, description="Expected graduation year")
    roles: list[str] = Field(default_factory=list, description="Target role types")
    industries: list[str] = Field(default_factory=list, description="Preferred industries")
    locations: list[str] = Field(default_factory=list, description="Location preferences")
    skills: list[str] = Field(default_factory=list, description="Skills to highlight")
    additional_criteria: str = Field(default="", description="Additional requirements")
    about_me: str = Field(default="", description="Self-description for cover letters")
    resume_text: str = Field(default="", description="Extracted resume text")
    resume_path: Optional[str] = Field(default=None, description="Path to resume PDF")

    def is_underclass(self) -> bool:
        """Check if seeker is an underclassman."""
        return self.year.lower() in ['freshman', 'sophomore', 'first-year', 'second-year']

    def get_underclass_terms(self) -> list[str]:
        """Get underclass terms based on year."""
        year_map = {
            'freshman': ['freshman', 'first-year', 'first year', '1st year'],
            'sophomore': ['sophomore', 'second-year', 'second year', '2nd year'],
        }
        base_terms = ['underclassmen', 'underclassman', 'discovery', 'pre-internship', 'early insight', 'explore']

        year_terms = year_map.get(self.year.lower(), [])
        return year_terms + base_terms

    def get_excluded_years(self) -> list[int]:
        """Get graduation years to exclude (upperclassmen)."""
        if self.graduation_year:
            # Exclude years before graduation_year - 2 (juniors/seniors)
            return [self.graduation_year - 2, self.graduation_year - 1]
        # Default exclusions for current underclassmen
        return [2027, 2028]


def parse_seeking_file(file_path: str | Path) -> SeekerProfile:
    """Parse the seeking.txt profile file.

    Args:
        file_path: Path to seeking.txt file.

    Returns:
        SeekerProfile object.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        logger.warning(f"Seeking file not found: {file_path}")
        return SeekerProfile()

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    profile_data = {}

    # Parse year
    year_match = re.search(r'^year:\s*(.+)$', content, re.MULTILINE)
    if year_match:
        profile_data['year'] = year_match.group(1).strip()

    # Parse graduation year
    grad_match = re.search(r'^graduation_year:\s*(\d+)$', content, re.MULTILINE)
    if grad_match:
        profile_data['graduation_year'] = int(grad_match.group(1))

    # Parse list fields
    list_fields = ['roles', 'industries', 'locations', 'skills']
    for field in list_fields:
        pattern = rf'^{field}:\s*\n((?:- .+\n?)+)'
        match = re.search(pattern, content, re.MULTILINE)
        if match:
            items = re.findall(r'^- (.+)$', match.group(1), re.MULTILINE)
            profile_data[field] = [item.strip() for item in items]

    # Parse multiline text fields
    text_fields = ['additional_criteria', 'about_me']
    for field in text_fields:
        pattern = rf'^{field}:\s*\|\s*\n((?:  .+\n?)+)'
        match = re.search(pattern, content, re.MULTILINE)
        if match:
            text = match.group(1)
            # Remove leading spaces from each line
            lines = [line[2:] if line.startswith('  ') else line for line in text.split('\n')]
            profile_data[field] = '\n'.join(lines).strip()

    return SeekerProfile(**profile_data)


def find_resume(config_dir: str | Path) -> Optional[Path]:
    """Find resume PDF in config directory.

    Args:
        config_dir: Path to config directory.

    Returns:
        Path to resume file or None.
    """
    config_dir = Path(config_dir)
    if not config_dir.exists():
        return None

    # Look for files matching *resume*.pdf (case insensitive)
    for file in config_dir.iterdir():
        if file.is_file() and 'resume' in file.name.lower() and file.suffix.lower() == '.pdf':
            logger.info(f"Found resume: {file}")
            return file

    return None


def extract_resume_text(pdf_path: Path) -> str:
    """Extract text from resume PDF.

    Args:
        pdf_path: Path to PDF file.

    Returns:
        Extracted text content.
    """
    try:
        # Try PyPDF2 first
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(str(pdf_path))
            text_parts = []
            for page in reader.pages:
                text_parts.append(page.extract_text() or '')
            return '\n'.join(text_parts)
        except ImportError:
            pass

        # Try pdfplumber
        try:
            import pdfplumber
            with pdfplumber.open(pdf_path) as pdf:
                text_parts = []
                for page in pdf.pages:
                    text_parts.append(page.extract_text() or '')
                return '\n'.join(text_parts)
        except ImportError:
            pass

        logger.warning("No PDF library available. Install PyPDF2 or pdfplumber.")
        return ""

    except Exception as e:
        logger.error(f"Failed to extract resume text: {e}")
        return ""


def load_seeker_profile(config_dir: str | Path = "config") -> SeekerProfile:
    """Load complete seeker profile including resume.

    Args:
        config_dir: Path to config directory.

    Returns:
        Complete SeekerProfile.
    """
    config_dir = Path(config_dir)

    # Parse seeking.txt
    seeking_file = config_dir / "seeking.txt"
    profile = parse_seeking_file(seeking_file)

    # Find and extract resume
    resume_path = find_resume(config_dir)
    if resume_path:
        profile.resume_path = str(resume_path)
        profile.resume_text = extract_resume_text(resume_path)
        if profile.resume_text:
            logger.info(f"Extracted {len(profile.resume_text)} chars from resume")

    return profile
