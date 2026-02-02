"""Date parsing and validation utilities."""

import re
from datetime import datetime, timedelta
from typing import Optional

import dateparser


def parse_date(date_string: Optional[str]) -> Optional[datetime]:
    """Parse a date string into datetime.

    Handles various formats:
    - ISO 8601: 2024-01-15, 2024-01-15T10:30:00Z
    - Relative: "2 days ago", "1 week ago", "yesterday"
    - Natural: "January 15, 2024", "Jan 15 2024"
    - Epoch timestamps (milliseconds)

    Args:
        date_string: Date string to parse.

    Returns:
        Parsed datetime or None if parsing fails.
    """
    if date_string is None:
        return None

    date_string = str(date_string).strip()
    if not date_string:
        return None

    # Handle epoch timestamps (milliseconds)
    if date_string.isdigit() and len(date_string) >= 10:
        try:
            timestamp = int(date_string)
            # If it's in milliseconds, convert to seconds
            if timestamp > 1e12:
                timestamp = timestamp / 1000
            return datetime.fromtimestamp(timestamp)
        except (ValueError, OSError):
            pass

    # Use dateparser for flexible parsing
    try:
        parsed = dateparser.parse(
            date_string,
            settings={
                'PREFER_DATES_FROM': 'past',
                'STRICT_PARSING': False,
                'RETURN_AS_TIMEZONE_AWARE': False
            }
        )
        return parsed
    except Exception:
        return None


def is_within_days(dt: Optional[datetime], days: int) -> bool:
    """Check if datetime is within N days of now.

    Args:
        dt: Datetime to check.
        days: Number of days threshold.

    Returns:
        True if within range, False otherwise.
    """
    if dt is None:
        return False

    cutoff = datetime.utcnow() - timedelta(days=days)
    return dt >= cutoff


def extract_date_from_text(text: str) -> Optional[datetime]:
    """Try to extract a posting date from job description text.

    Looks for patterns like:
    - "Posted on January 15, 2024"
    - "Date posted: 2024-01-15"
    - "Published 3 days ago"

    Args:
        text: Job description text.

    Returns:
        Extracted datetime or None.
    """
    patterns = [
        r'(?:posted|published|date)\s*(?:on|:)?\s*([A-Za-z]+\s+\d{1,2},?\s+\d{4})',
        r'(?:posted|published|date)\s*(?:on|:)?\s*(\d{4}-\d{2}-\d{2})',
        r'(?:posted|published)\s+(\d+\s+(?:day|week|month)s?\s+ago)',
        r'(?:posted|published)\s+(yesterday|today)',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            date_str = match.group(1)
            parsed = parse_date(date_str)
            if parsed:
                return parsed

    return None


def format_relative_date(dt: Optional[datetime]) -> str:
    """Format datetime as relative string.

    Args:
        dt: Datetime to format.

    Returns:
        Relative date string like "2 days ago".
    """
    if dt is None:
        return "Unknown"

    delta = datetime.utcnow() - dt
    days = delta.days

    if days == 0:
        return "Today"
    elif days == 1:
        return "Yesterday"
    elif days < 7:
        return f"{days} days ago"
    elif days < 30:
        weeks = days // 7
        return f"{weeks} week{'s' if weeks > 1 else ''} ago"
    else:
        return dt.strftime("%Y-%m-%d")
