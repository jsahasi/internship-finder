"""Report rendering with Jinja2 templates."""

from datetime import datetime
from io import StringIO
from typing import Optional

import pandas as pd
from jinja2 import Environment, BaseLoader

from app.extract.normalize import NearMiss, Posting
from app.logging_config import get_logger


logger = get_logger()


EMAIL_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
        }
        h1 {
            color: #2c3e50;
            border-bottom: 2px solid #3498db;
            padding-bottom: 10px;
        }
        h2 {
            color: #34495e;
            margin-top: 30px;
        }
        .summary {
            background: #ecf0f1;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
        }
        table {
            border-collapse: collapse;
            width: 100%;
            margin: 20px 0;
            font-size: 14px;
        }
        th, td {
            border: 1px solid #ddd;
            padding: 10px;
            text-align: left;
        }
        th {
            background: #3498db;
            color: white;
        }
        tr:nth-child(even) {
            background: #f9f9f9;
        }
        tr:hover {
            background: #f1f1f1;
        }
        a {
            color: #3498db;
            text-decoration: none;
        }
        a:hover {
            text-decoration: underline;
        }
        .evidence {
            background: #fffde7;
            padding: 2px 5px;
            border-radius: 3px;
            font-size: 12px;
        }
        .near-miss {
            color: #7f8c8d;
        }
        .footer {
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #ddd;
            font-size: 12px;
            color: #7f8c8d;
        }
        ul {
            margin: 5px 0;
            padding-left: 20px;
        }
        li {
            margin: 3px 0;
        }
    </style>
</head>
<body>
    <h1>Underclass Internship Digest</h1>

    <div class="summary">
        <strong>Scan completed:</strong> {{ run_timestamp }}<br>
        <strong>Postings found:</strong> {{ included_count }} matching roles<br>
        {% if near_miss_count > 0 %}
        <strong>Near misses:</strong> {{ near_miss_count }} (excluded but close)
        {% endif %}
    </div>

    {% if postings %}
    <h2>Matching Internships ({{ included_count }})</h2>
    <table>
        <thead>
            <tr>
                <th>Company</th>
                <th>Role</th>
                <th>Function</th>
                <th>Location</th>
                <th>Posted</th>
                <th>Sourced By</th>
                <th>Why It Fits</th>
                <th>Link</th>
            </tr>
        </thead>
        <tbody>
            {% for p in postings %}
            <tr>
                <td><strong>{{ p.company }}</strong></td>
                <td>{{ p.title }}</td>
                <td>{{ p.function_family }}</td>
                <td>{{ p.location }}</td>
                <td>{{ p.posted }}</td>
                <td>{{ p.sourced_by }}</td>
                <td>
                    {% if p.evidence %}
                    <span class="evidence">{{ p.evidence }}</span><br>
                    {% endif %}
                    {{ p.why_fits }}
                    {% if p.bullets %}
                    <ul>
                        {% for bullet in p.bullets %}
                        <li>{{ bullet }}</li>
                        {% endfor %}
                    </ul>
                    {% endif %}
                </td>
                <td><a href="{{ p.url }}" target="_blank">Apply</a></td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    {% else %}
    <p>No matching internships found in this scan.</p>
    {% endif %}

    {% if near_misses %}
    <h2 class="near-miss">Near Misses ({{ near_miss_count }})</h2>
    <p class="near-miss">These postings were close but excluded:</p>
    <table>
        <thead>
            <tr>
                <th>Company</th>
                <th>Role</th>
                <th>Exclusion Reason</th>
                <th>Link</th>
            </tr>
        </thead>
        <tbody>
            {% for nm in near_misses %}
            <tr class="near-miss">
                <td>{{ nm.company }}</td>
                <td>{{ nm.title }}</td>
                <td>{{ nm.reason }}{% if nm.evidence %}<br><small>{{ nm.evidence }}</small>{% endif %}</td>
                <td><a href="{{ nm.url }}" target="_blank">View</a></td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    {% endif %}

    <div style="background: #eaf2f8; padding: 15px; border-radius: 5px; margin-top: 20px;">
        <strong>Additional Positions</strong> - access via your LinkedIn account:<br>
        <a href="https://www.linkedin.com/jobs/search/?keywords=summer%202026%20internship&f_TPR=r86400&f_E=1" target="_blank">
            Search LinkedIn for Summer 2026 Internships (past 24 hours)
        </a>
    </div>

    <div class="footer">
        <p>Generated by Underclass Internship Scanner</p>
        <p>Targeting: Software Engineering, Product Management, Consulting, Investment Banking</p>
        <p>Filters: Freshman/Sophomore only, excludes Class of 2027/2028</p>
    </div>
</body>
</html>
"""


class ReportRenderer:
    """Render reports from posting data."""

    def __init__(self):
        """Initialize renderer with Jinja2 environment."""
        self.env = Environment(loader=BaseLoader())
        self.template = self.env.from_string(EMAIL_TEMPLATE)

    def render_html(
        self,
        postings: list[Posting],
        near_misses: list[NearMiss],
        run_timestamp: Optional[datetime] = None
    ) -> str:
        """Render HTML email body.

        Args:
            postings: List of included postings.
            near_misses: List of near misses.
            run_timestamp: Scan timestamp.

        Returns:
            HTML string.
        """
        if run_timestamp is None:
            run_timestamp = datetime.utcnow()

        # Format postings for template
        formatted_postings = []
        for p in postings:
            formatted_postings.append({
                'company': p.company,
                'title': p.title,
                'function_family': p.function_family,
                'location': p.location,
                'posted': p.posted_at.strftime('%Y-%m-%d') if p.posted_at else 'Unknown',
                'sourced_by': p.search_provider or 'ATS',
                'evidence': p.underclass_evidence or '',
                'why_fits': p.why_fits or '',
                'bullets': p.summary_bullets[:3] if p.summary_bullets else [],
                'url': p.url
            })

        # Format near misses
        formatted_near_misses = []
        for nm in near_misses[:10]:
            formatted_near_misses.append({
                'company': nm.posting.company,
                'title': nm.posting.title,
                'reason': nm.exclusion_reason,
                'evidence': nm.evidence_snippet,
                'url': nm.posting.url
            })

        return self.template.render(
            run_timestamp=run_timestamp.strftime('%Y-%m-%d %H:%M UTC'),
            included_count=len(postings),
            near_miss_count=len(near_misses),
            postings=formatted_postings,
            near_misses=formatted_near_misses
        )

    def render_text(
        self,
        postings: list[Posting],
        near_misses: list[NearMiss]
    ) -> str:
        """Render plain text summary.

        Args:
            postings: List of included postings.
            near_misses: List of near misses.

        Returns:
            Plain text string.
        """
        lines = [
            "=" * 60,
            "UNDERCLASS INTERNSHIP DIGEST",
            "=" * 60,
            f"Run: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
            f"Included: {len(postings)} | Near Misses: {len(near_misses)}",
            "",
            "-" * 60,
            "MATCHING INTERNSHIPS",
            "-" * 60
        ]

        if postings:
            for p in postings:
                lines.extend([
                    f"\n{p.company} - {p.title}",
                    f"  Function: {p.function_family}",
                    f"  Location: {p.location}",
                    f"  Posted: {p.posted_at.strftime('%Y-%m-%d') if p.posted_at else 'Unknown'}",
                    f"  Sourced By: {p.search_provider or 'ATS'}",
                    f"  Evidence: {p.underclass_evidence or 'N/A'}",
                    f"  URL: {p.url}"
                ])
        else:
            lines.append("\nNo matching internships found.")

        if near_misses:
            lines.extend([
                "",
                "-" * 60,
                "NEAR MISSES",
                "-" * 60
            ])
            for nm in near_misses[:10]:
                lines.extend([
                    f"\n{nm.posting.company} - {nm.posting.title}",
                    f"  Reason: {nm.exclusion_reason}",
                    f"  URL: {nm.posting.url}"
                ])

        lines.extend([
            "",
            "-" * 60,
            "Additional Positions - access via your LinkedIn account:",
            "https://www.linkedin.com/jobs/search/?keywords=summer%202026%20internship&f_TPR=r86400&f_E=1",
        ])

        return '\n'.join(lines)

    def to_csv(self, postings: list[Posting]) -> str:
        """Export postings to CSV string.

        Args:
            postings: List of postings.

        Returns:
            CSV string.
        """
        if not postings:
            return ""

        rows = [p.to_table_row() for p in postings]
        df = pd.DataFrame(rows)

        output = StringIO()
        df.to_csv(output, index=False)
        return output.getvalue()

    def to_dataframe(self, postings: list[Posting]) -> pd.DataFrame:
        """Convert postings to pandas DataFrame.

        Args:
            postings: List of postings.

        Returns:
            DataFrame.
        """
        rows = [p.to_table_row() for p in postings]
        return pd.DataFrame(rows)
