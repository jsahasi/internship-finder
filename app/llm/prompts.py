"""Prompt templates for LLM classification."""

SYSTEM_PROMPT = """You are an expert job posting classifier for underclass (freshman/sophomore) internships.

Your task is to analyze job postings and determine if they are specifically targeted at underclassmen (freshmen and sophomores).

## Classification Rules

### MUST EXCLUDE if ANY of these are true:
1. Contains "2027" or "2028" anywhere (these are junior/senior graduation years)
2. Contains terms: "junior", "senior", "penultimate", "rising senior", "final year", "final-year", "3rd year", "4th year", "upperclassmen", "third year", "fourth year"
3. No explicit underclass-targeting language found

### MUST INCLUDE only if ALL of these are true:
1. Contains explicit underclass signals: "freshman", "sophomore", "first-year", "second-year", "underclassmen", "discovery", "pre-internship", "early insight", "explore program"
2. Role is in target functions: Software Engineering (SWE), Product Management (PM), Consulting, or Investment Banking (IB)
3. Does NOT contain any exclusion criteria above

## Role Classification
- SWE: Software engineering, development, coding, technical roles
- PM: Product management, program management
- Consulting: Strategy consulting, management consulting, advisory
- IB: Investment banking, finance, capital markets, M&A
- Other: Anything else (should be excluded)

## Output Format
You MUST respond with valid JSON only. No additional text.

{
  "decision": "include" or "exclude",
  "role_family": "SWE" or "PM" or "Consulting" or "IB" or "Other",
  "underclass_evidence": "exact phrase from posting showing underclass targeting" or null,
  "why_fits": "brief 1-sentence explanation",
  "summary_bullets": ["bullet 1", "bullet 2"],
  "confidence": 0.0 to 1.0,
  "exclude_reason": "reason if excluded" or null
}"""


CLASSIFICATION_PROMPT = """Analyze this job posting and classify it according to the rules.

## Job Posting
Company: {company}
Title: {title}
Location: {location}

Description:
{description}

---

Respond with JSON only. Remember:
- If you see "2027" or "2028" anywhere, decision MUST be "exclude"
- If you see "junior", "senior", "penultimate", etc., decision MUST be "exclude"
- If no explicit underclass terms (freshman/sophomore/first-year/etc.), decision MUST be "exclude"
- Summary bullets should be 2-4 concise points about the role
- Extract the EXACT underclass evidence phrase from the text"""


BATCH_CLASSIFICATION_PROMPT = """Analyze these {count} job postings and classify each one.

{postings_text}

---

Respond with a JSON array of classification objects, one per posting in order.
Each object must have: decision, role_family, underclass_evidence, why_fits, summary_bullets, confidence, exclude_reason

Example response format:
[
  {{"decision": "include", "role_family": "SWE", ...}},
  {{"decision": "exclude", "role_family": "Other", ...}}
]"""


def format_posting_for_prompt(
    company: str,
    title: str,
    location: str,
    description: str,
    max_desc_length: int = 3000
) -> str:
    """Format a posting for the classification prompt.

    Args:
        company: Company name.
        title: Job title.
        location: Job location.
        description: Job description.
        max_desc_length: Max chars for description.

    Returns:
        Formatted prompt string.
    """
    # Truncate description if needed
    if len(description) > max_desc_length:
        description = description[:max_desc_length] + "... [truncated]"

    return CLASSIFICATION_PROMPT.format(
        company=company,
        title=title,
        location=location,
        description=description
    )


def format_batch_for_prompt(postings: list[dict], max_per_batch: int = 5) -> str:
    """Format multiple postings for batch classification.

    Args:
        postings: List of posting dicts.
        max_per_batch: Max postings per batch.

    Returns:
        Formatted prompt string.
    """
    postings = postings[:max_per_batch]
    parts = []

    for i, p in enumerate(postings, 1):
        desc = p.get('description', '')[:2000]
        part = f"""
### Posting {i}
Company: {p.get('company', 'Unknown')}
Title: {p.get('title', 'Unknown')}
Location: {p.get('location', 'Not specified')}

Description:
{desc}
"""
        parts.append(part)

    postings_text = "\n---\n".join(parts)

    return BATCH_CLASSIFICATION_PROMPT.format(
        count=len(postings),
        postings_text=postings_text
    )
