"""SQLite persistence for articles, recurring directions, and opportunities."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from ..models import ContentItem
from .schemas import OpportunityCandidate, TriageDecision


@dataclass(frozen=True)
class EventStats:
    occurrence_count: int
    source_count: int
    first_seen: datetime
    last_seen: datetime


class HistoryStore:
    """Owns the Startup Radar database and all history-aware decisions."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self._create_schema()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "HistoryStore":
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS articles (
                article_hash TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                source TEXT NOT NULL,
                published_at TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS events (
                direction_key TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                occurrence_count INTEGER NOT NULL DEFAULT 1,
                source_count INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS event_articles (
                direction_key TEXT NOT NULL,
                article_hash TEXT NOT NULL,
                source TEXT NOT NULL,
                seen_at TEXT NOT NULL,
                PRIMARY KEY (direction_key, article_hash),
                FOREIGN KEY (direction_key) REFERENCES events(direction_key),
                FOREIGN KEY (article_hash) REFERENCES articles(article_hash)
            );

            CREATE TABLE IF NOT EXISTS opportunities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                direction_key TEXT NOT NULL,
                article_hash TEXT NOT NULL,
                analysis_json TEXT NOT NULL,
                score REAL NOT NULL,
                prompt_version TEXT NOT NULL,
                model TEXT NOT NULL,
                run_date TEXT NOT NULL,
                was_output INTEGER NOT NULL DEFAULT 0,
                UNIQUE (direction_key, article_hash, run_date),
                FOREIGN KEY (direction_key) REFERENCES events(direction_key),
                FOREIGN KEY (article_hash) REFERENCES articles(article_hash)
            );

            CREATE INDEX IF NOT EXISTS idx_opportunities_direction_date
            ON opportunities(direction_key, run_date);

            CREATE TABLE IF NOT EXISTS article_triage (
                article_hash TEXT NOT NULL,
                triage_version TEXT NOT NULL,
                model TEXT NOT NULL,
                decision_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (article_hash, triage_version, model),
                FOREIGN KEY (article_hash) REFERENCES articles(article_hash)
            );
            """
        )
        self.connection.commit()

    def get_triage(
        self, article_hash: str, triage_version: str, model: str
    ) -> TriageDecision | None:
        row = self.connection.execute(
            """
            SELECT decision_json FROM article_triage
            WHERE article_hash = ? AND triage_version = ? AND model = ?
            """,
            (article_hash, triage_version, model),
        ).fetchone()
        if row is None:
            return None
        return TriageDecision.model_validate_json(row["decision_json"])

    def record_triage(
        self,
        article_hash: str,
        triage_version: str,
        model: str,
        decision: TriageDecision,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO article_triage
                (article_hash, triage_version, model, decision_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(article_hash, triage_version, model) DO UPDATE SET
                decision_json = excluded.decision_json,
                created_at = excluded.created_at
            """,
            (
                article_hash,
                triage_version,
                model,
                decision.model_dump_json(),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.connection.commit()

    @staticmethod
    def article_hash(item: ContentItem) -> str:
        parsed = urlsplit(str(item.url))
        normalized_url = urlunsplit(
            (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), parsed.query, "")
        )
        payload = f"{normalized_url}\n{item.title.strip().lower()}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def add_article(self, item: ContentItem) -> tuple[str, bool]:
        article_hash = self.article_hash(item)
        existed = self.connection.execute(
            "SELECT 1 FROM articles WHERE article_hash = ?", (article_hash,)
        ).fetchone() is not None
        self.connection.execute(
            """
            INSERT INTO articles
                (article_hash, title, url, source, published_at, fetched_at, content)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(article_hash) DO UPDATE SET
                fetched_at = excluded.fetched_at,
                content = CASE
                    WHEN length(excluded.content) > length(articles.content)
                    THEN excluded.content ELSE articles.content
                END
            """,
            (
                article_hash,
                item.title,
                str(item.url),
                item.source_type.value,
                item.published_at.isoformat(),
                item.fetched_at.isoformat(),
                item.content or "",
            ),
        )
        self.connection.commit()
        return article_hash, not existed

    def was_analyzed(self, article_hash: str, prompt_version: str | None = None) -> bool:
        version_clause = " AND prompt_version = ?" if prompt_version else ""
        params = (article_hash, prompt_version) if prompt_version else (article_hash,)
        row = self.connection.execute(
            f"SELECT 1 FROM opportunities WHERE article_hash = ?{version_clause} LIMIT 1",
            params,
        ).fetchone()
        return row is not None

    def record_candidate(
        self,
        candidate: OpportunityCandidate,
        *,
        score: float,
        prompt_version: str,
        model: str,
        run_date: date,
    ) -> EventStats:
        key = candidate.analysis.direction_key
        now = datetime.now(timezone.utc).isoformat()
        self.connection.execute(
            """
            INSERT INTO events(direction_key, label, first_seen, last_seen)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(direction_key) DO UPDATE SET
                label = excluded.label,
                last_seen = excluded.last_seen
            """,
            (key, candidate.analysis.signal, now, now),
        )
        self.connection.execute(
            """
            INSERT OR IGNORE INTO event_articles(direction_key, article_hash, source, seen_at)
            VALUES (?, ?, ?, ?)
            """,
            (key, candidate.article_hash, candidate.source_type, now),
        )
        counts = self.connection.execute(
            """
            SELECT COUNT(*) AS occurrence_count, COUNT(DISTINCT source) AS source_count
            FROM event_articles WHERE direction_key = ?
            """,
            (key,),
        ).fetchone()
        self.connection.execute(
            """
            UPDATE events SET occurrence_count = ?, source_count = ?, last_seen = ?
            WHERE direction_key = ?
            """,
            (counts["occurrence_count"], counts["source_count"], now, key),
        )
        self.connection.execute(
            """
            INSERT INTO opportunities
                (direction_key, article_hash, analysis_json, score, prompt_version, model, run_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(direction_key, article_hash, run_date) DO UPDATE SET
                analysis_json = excluded.analysis_json,
                score = excluded.score,
                prompt_version = excluded.prompt_version,
                model = excluded.model
            """,
            (
                key,
                candidate.article_hash,
                candidate.analysis.model_dump_json(),
                score,
                prompt_version,
                model,
                run_date.isoformat(),
            ),
        )
        self.connection.commit()
        return self.event_stats(key)

    def event_stats(self, direction_key: str) -> EventStats:
        row = self.connection.execute(
            "SELECT * FROM events WHERE direction_key = ?", (direction_key,)
        ).fetchone()
        if row is None:
            raise KeyError(direction_key)
        return EventStats(
            occurrence_count=row["occurrence_count"],
            source_count=row["source_count"],
            first_seen=datetime.fromisoformat(row["first_seen"]),
            last_seen=datetime.fromisoformat(row["last_seen"]),
        )

    def list_directions(self, limit: int = 100) -> list[dict[str, str]]:
        rows = self.connection.execute(
            """
            SELECT direction_key, label FROM events
            ORDER BY last_seen DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            {"direction_key": row["direction_key"], "signal": row["label"]}
            for row in rows
        ]

    def recently_output(self, direction_key: str, run_date: date, cooldown_days: int) -> bool:
        earliest = run_date - timedelta(days=cooldown_days)
        row = self.connection.execute(
            """
            SELECT 1 FROM opportunities
            WHERE direction_key = ? AND was_output = 1
              AND run_date >= ? AND run_date < ?
            LIMIT 1
            """,
            (direction_key, earliest.isoformat(), run_date.isoformat()),
        ).fetchone()
        return row is not None

    def mark_output(self, direction_key: str, article_hash: str, run_date: date) -> None:
        self.connection.execute(
            """
            UPDATE opportunities SET was_output = 1
            WHERE direction_key = ? AND article_hash = ? AND run_date = ?
            """,
            (direction_key, article_hash, run_date.isoformat()),
        )
        self.connection.commit()
