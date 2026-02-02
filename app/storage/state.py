"""SQLite storage for deduplication state."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.extract.normalize import Posting
from app.logging_config import get_logger


logger = get_logger()


class StateStore:
    """SQLite-based state storage for deduplication."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS postings_seen (
        hash TEXT PRIMARY KEY,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        url TEXT NOT NULL,
        company TEXT NOT NULL,
        title TEXT NOT NULL,
        emailed_at TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_company ON postings_seen(company);
    CREATE INDEX IF NOT EXISTS idx_last_seen ON postings_seen(last_seen_at);
    """

    def __init__(self, db_path: str | Path = "internships.db"):
        """Initialize state store.

        Args:
            db_path: Path to SQLite database file.
        """
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with self._get_connection() as conn:
            conn.executescript(self.SCHEMA)
            conn.commit()
        logger.debug(f"Initialized database at {self.db_path}")

    @contextmanager
    def _get_connection(self):
        """Get database connection context manager."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def is_seen(self, posting: Posting) -> bool:
        """Check if a posting has been seen before.

        Args:
            posting: Posting to check.

        Returns:
            True if already seen.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT hash FROM postings_seen WHERE hash = ?",
                (posting.posting_hash,)
            )
            return cursor.fetchone() is not None

    def mark_seen(self, posting: Posting) -> None:
        """Mark a posting as seen.

        Args:
            posting: Posting to mark.
        """
        now = datetime.utcnow().isoformat()

        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO postings_seen (hash, first_seen_at, last_seen_at, url, company, title)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(hash) DO UPDATE SET last_seen_at = ?
            """, (
                posting.posting_hash,
                now,
                now,
                posting.url,
                posting.company,
                posting.title,
                now
            ))
            conn.commit()

    def mark_emailed(self, posting: Posting) -> None:
        """Mark a posting as emailed.

        Args:
            posting: Posting that was emailed.
        """
        now = datetime.utcnow().isoformat()

        with self._get_connection() as conn:
            conn.execute("""
                UPDATE postings_seen SET emailed_at = ? WHERE hash = ?
            """, (now, posting.posting_hash))
            conn.commit()

    def filter_new(self, postings: list[Posting]) -> list[Posting]:
        """Filter out already-seen postings.

        Args:
            postings: List of postings to filter.

        Returns:
            List of postings not previously seen.
        """
        new_postings = []
        seen_count = 0

        for posting in postings:
            if self.is_seen(posting):
                seen_count += 1
                # Update last_seen timestamp
                self.mark_seen(posting)
            else:
                new_postings.append(posting)
                self.mark_seen(posting)

        logger.info(f"Dedupe: {len(new_postings)} new, {seen_count} previously seen")
        return new_postings

    def get_recent_postings(self, days: int = 7) -> list[dict]:
        """Get postings seen in the last N days.

        Args:
            days: Number of days to look back.

        Returns:
            List of posting records.
        """
        cutoff = datetime.utcnow().replace(
            hour=0, minute=0, second=0
        )
        cutoff = cutoff.isoformat()

        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM postings_seen
                WHERE last_seen_at >= date(?, '-' || ? || ' days')
                ORDER BY last_seen_at DESC
            """, (cutoff, days))
            return [dict(row) for row in cursor.fetchall()]

    def get_stats(self) -> dict:
        """Get database statistics.

        Returns:
            Dict with counts and stats.
        """
        with self._get_connection() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM postings_seen"
            ).fetchone()[0]

            emailed = conn.execute(
                "SELECT COUNT(*) FROM postings_seen WHERE emailed_at IS NOT NULL"
            ).fetchone()[0]

            companies = conn.execute(
                "SELECT COUNT(DISTINCT company) FROM postings_seen"
            ).fetchone()[0]

        return {
            "total_postings": total,
            "emailed_postings": emailed,
            "unique_companies": companies
        }

    def clear_old_entries(self, days: int = 90) -> int:
        """Remove entries older than N days.

        Args:
            days: Age threshold in days.

        Returns:
            Number of entries removed.
        """
        cutoff = datetime.utcnow().isoformat()

        with self._get_connection() as conn:
            cursor = conn.execute("""
                DELETE FROM postings_seen
                WHERE last_seen_at < date(?, '-' || ? || ' days')
            """, (cutoff, days))
            conn.commit()
            return cursor.rowcount
