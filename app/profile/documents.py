"""Generate tailored resumes and cover letters."""

import json
import time
from datetime import datetime
from typing import Optional

from anthropic import Anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from app.extract.normalize import Posting
from app.profile.seeker import SeekerProfile
from app.logging_config import get_logger


logger = get_logger()

# Rate limiting constants
TOKENS_PER_MINUTE_LIMIT = 30000
RATE_LIMIT_BUFFER = 0.8  # Use 80% of limit to be safe


RESUME_TAILOR_PROMPT = """You are an expert resume writer helping a college student tailor their resume for a specific internship.

## Original Resume
{resume_text}

## Target Position
Company: {company}
Title: {title}
Location: {location}
Description: {job_description}

## Student Profile
Year: {year}
Target Roles: {roles}
Key Skills: {skills}

## Instructions
Create a tailored version of this resume that:
1. Highlights experiences and skills most relevant to this specific role
2. Uses keywords from the job description where they truthfully apply
3. Reorders bullet points to prioritize relevant accomplishments
4. Keeps all information FACTUAL - do not add experiences or skills not in the original
5. Maintains professional formatting
6. Is concise (1 page equivalent)

CRITICAL RULES - ABSOLUTELY NO VIOLATIONS:
- Do NOT fabricate, invent, or add ANY information not in the original resume
- Do NOT exaggerate metrics, numbers, or achievements
- Do NOT inflate job titles, responsibilities, or impact
- Do NOT add skills, technologies, or tools not explicitly mentioned
- Do NOT embellish or overstate any accomplishments
- ONLY reorder, rephrase, and highlight EXISTING content
- If something isn't in the original resume, it CANNOT appear in the tailored version

Return the tailored resume as plain text with clear sections.
Every single fact must come directly from the original resume."""


COVER_LETTER_PROMPT = """You are an expert cover letter writer helping a college student apply for an internship.

## Student Resume
{resume_text}

## Student's Self-Description
{about_me}

## Target Position
Company: {company}
Title: {title}
Location: {location}
Description: {job_description}

## Why This Role Fits (from analysis)
{why_fits}

## Student Profile
Year: {year}
Skills: {skills}

## Instructions
Write a compelling cover letter that:
1. Opens with genuine enthusiasm for the specific company and role
2. Connects 2-3 specific experiences from the resume to job requirements
3. Shows knowledge of the company (based on the job description)
4. Explains why this student is a good fit for an underclass program
5. Is professional but shows personality
6. Is concise (3-4 paragraphs, under 400 words)
7. Does NOT use generic phrases like "I am writing to apply for..."

CRITICAL RULES - ABSOLUTELY NO VIOLATIONS:
- ONLY reference experiences, skills, and achievements that appear in the resume
- Do NOT exaggerate or inflate any accomplishments or metrics
- Do NOT claim skills, experiences, or achievements not in the resume
- Do NOT embellish the student's background or qualifications
- Keep claims modest and accurate to what the resume shows
- If the resume shows "contributed to" something, do NOT say "led" or "drove"

Return only the cover letter text, ready to send.
Use today's date: {today}
The student should sign as: {signature}"""


class DocumentGenerator:
    """Generate tailored application documents using LLM."""

    def __init__(
        self,
        anthropic_key: Optional[str] = None,
        openai_key: Optional[str] = None
    ):
        """Initialize document generator.

        Args:
            anthropic_key: Anthropic API key.
            openai_key: OpenAI API key.
        """
        self.anthropic_client = None
        self.openai_client = None

        if anthropic_key:
            self.anthropic_client = Anthropic(api_key=anthropic_key)

        if openai_key:
            try:
                from openai import OpenAI
                self.openai_client = OpenAI(api_key=openai_key)
            except ImportError:
                logger.warning("OpenAI package not installed")

        self.tokens_used = 0
        self.tokens_this_minute = 0
        self.minute_start_time = time.time()

    def _check_rate_limit(self, estimated_tokens: int = 5000) -> None:
        """Check and wait if approaching rate limit.

        Args:
            estimated_tokens: Estimated tokens for next request.
        """
        current_time = time.time()
        elapsed = current_time - self.minute_start_time

        # Reset counter if a minute has passed
        if elapsed >= 60:
            self.tokens_this_minute = 0
            self.minute_start_time = current_time
            return

        # Check if we'd exceed the limit
        safe_limit = TOKENS_PER_MINUTE_LIMIT * RATE_LIMIT_BUFFER
        if self.tokens_this_minute + estimated_tokens > safe_limit:
            # Wait for the remainder of the minute
            wait_time = 60 - elapsed + 2  # Add 2 second buffer
            logger.info(f"Rate limit: waiting {wait_time:.1f}s (used {self.tokens_this_minute} tokens this minute)")
            time.sleep(wait_time)
            self.tokens_this_minute = 0
            self.minute_start_time = time.time()

    def _call_anthropic(self, prompt: str, max_tokens: int = 2000) -> str:
        """Call Anthropic API with rate limiting."""
        if not self.anthropic_client:
            raise ValueError("Anthropic client not configured")

        # Estimate tokens (roughly 4 chars per token)
        estimated_input = len(prompt) // 4
        estimated_total = estimated_input + max_tokens
        self._check_rate_limit(estimated_total)

        response = self.anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}]
        )

        actual_tokens = response.usage.input_tokens + response.usage.output_tokens
        self.tokens_used += actual_tokens
        self.tokens_this_minute += actual_tokens

        return response.content[0].text

    def _call_openai(self, prompt: str, max_tokens: int = 2000) -> str:
        """Call OpenAI API."""
        if not self.openai_client:
            raise ValueError("OpenAI client not configured")

        response = self.openai_client.chat.completions.create(
            model="gpt-4o",
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}]
        )

        return response.choices[0].message.content

    def _call_llm(self, prompt: str, max_tokens: int = 2000) -> str:
        """Call available LLM (prefer Anthropic)."""
        if self.anthropic_client:
            return self._call_anthropic(prompt, max_tokens)
        elif self.openai_client:
            return self._call_openai(prompt, max_tokens)
        else:
            raise ValueError("No LLM client configured")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def generate_tailored_resume(
        self,
        profile: SeekerProfile,
        posting: Posting
    ) -> str:
        """Generate a tailored resume for a specific posting.

        Args:
            profile: Seeker profile with resume.
            posting: Target job posting.

        Returns:
            Tailored resume text.
        """
        if not profile.resume_text:
            logger.warning("No resume text available for tailoring")
            return ""

        prompt = RESUME_TAILOR_PROMPT.format(
            resume_text=profile.resume_text,
            company=posting.company,
            title=posting.title,
            location=posting.location,
            job_description=posting.text[:3000],
            year=profile.year,
            roles=", ".join(profile.roles),
            skills=", ".join(profile.skills)
        )

        try:
            return self._call_llm(prompt)
        except Exception as e:
            logger.error(f"Failed to generate tailored resume: {e}")
            return ""

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def generate_cover_letter(
        self,
        profile: SeekerProfile,
        posting: Posting,
        signature_name: str = "Your Name"
    ) -> str:
        """Generate a cover letter for a specific posting.

        Args:
            profile: Seeker profile.
            posting: Target job posting.
            signature_name: Name for signature.

        Returns:
            Cover letter text.
        """
        prompt = COVER_LETTER_PROMPT.format(
            resume_text=profile.resume_text or "No resume provided",
            about_me=profile.about_me or "A motivated college student",
            company=posting.company,
            title=posting.title,
            location=posting.location,
            job_description=posting.text[:3000],
            why_fits=posting.why_fits or posting.underclass_evidence or "Strong match for underclass program",
            year=profile.year,
            skills=", ".join(profile.skills),
            today=datetime.now().strftime("%B %d, %Y"),
            signature=signature_name
        )

        try:
            return self._call_llm(prompt)
        except Exception as e:
            logger.error(f"Failed to generate cover letter: {e}")
            return ""

    def generate_application_materials(
        self,
        profile: SeekerProfile,
        posting: Posting,
        signature_name: str = "Your Name"
    ) -> dict:
        """Generate all application materials for a posting.

        Args:
            profile: Seeker profile.
            posting: Target job posting.
            signature_name: Name for cover letter signature.

        Returns:
            Dict with 'resume' and 'cover_letter' keys.
        """
        materials = {
            'resume': '',
            'cover_letter': '',
            'company': posting.company,
            'title': posting.title
        }

        if profile.resume_text:
            logger.info(f"Generating tailored resume for {posting.company}")
            materials['resume'] = self.generate_tailored_resume(profile, posting)
            # Small delay between resume and cover letter
            time.sleep(2)

        logger.info(f"Generating cover letter for {posting.company}")
        materials['cover_letter'] = self.generate_cover_letter(
            profile, posting, signature_name
        )

        return materials


def create_pdf_from_text(text: str, title: str) -> bytes:
    """Create a simple PDF from text content.

    Args:
        text: Text content.
        title: Document title.

    Returns:
        PDF bytes.
    """
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.units import inch
        from io import BytesIO

        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=72
        )

        styles = getSampleStyleSheet()
        story = []

        # Title
        title_style = ParagraphStyle(
            'Title',
            parent=styles['Heading1'],
            fontSize=14,
            spaceAfter=12
        )
        story.append(Paragraph(title, title_style))
        story.append(Spacer(1, 0.25 * inch))

        # Content - split into paragraphs
        body_style = ParagraphStyle(
            'Body',
            parent=styles['Normal'],
            fontSize=11,
            leading=14,
            spaceAfter=12
        )

        for para in text.split('\n\n'):
            if para.strip():
                # Escape special characters
                para = para.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                story.append(Paragraph(para.replace('\n', '<br/>'), body_style))

        doc.build(story)
        return buffer.getvalue()

    except ImportError:
        logger.warning("reportlab not installed, returning text as bytes")
        return text.encode('utf-8')
