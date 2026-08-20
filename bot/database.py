from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bot.constants import STATUS_HAS_TEAM, STATUS_LOOKING


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def dumps_list(values: list[str]) -> str:
    return json.dumps(values, ensure_ascii=False)


def loads_list(value: str | None) -> list[str]:
    if not value:
        return []
    return list(json.loads(value))


@dataclass(slots=True)
class Profile:
    user_id: int
    name: str
    championships: list[str]
    roles: list[str]
    status: str
    looking_for_roles: list[str]
    city: str
    username: str | None
    contact: str
    about: str | None
    photo_file_id: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Profile":
        return cls(
            user_id=row["id"],
            name=row["name"],
            championships=loads_list(row["championships"]),
            roles=loads_list(row["roles"]),
            status=row["status"],
            looking_for_roles=loads_list(row["looking_for_roles"]),
            city=row["city"],
            username=row["username"],
            contact=row["contact"],
            about=row["about"],
            photo_file_id=row["photo_file_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class Database:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")

    def close(self) -> None:
        self.connection.close()

    def init_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS profiles (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                championships TEXT NOT NULL,
                roles TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('looking', 'has_team')),
                looking_for_roles TEXT,
                city TEXT NOT NULL,
                username TEXT,
                contact TEXT NOT NULL,
                about TEXT,
                photo_file_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS likes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_user_id INTEGER NOT NULL,
                to_user_id INTEGER NOT NULL,
                reaction TEXT NOT NULL CHECK(reaction IN ('like', 'pass')),
                created_at TEXT NOT NULL,
                UNIQUE(from_user_id, to_user_id)
            );

            CREATE TABLE IF NOT EXISTS matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_low_id INTEGER NOT NULL,
                user_high_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(user_low_id, user_high_id)
            );

            CREATE INDEX IF NOT EXISTS idx_likes_to_user ON likes (to_user_id, reaction);
            CREATE INDEX IF NOT EXISTS idx_matches_users ON matches (user_low_id, user_high_id);
            """
        )
        self.connection.commit()

    def upsert_profile(self, profile: Profile) -> None:
        self.connection.execute(
            """
            INSERT INTO profiles (
                id, name, championships, roles, status, looking_for_roles,
                city, username, contact, about, photo_file_id, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                championships=excluded.championships,
                roles=excluded.roles,
                status=excluded.status,
                looking_for_roles=excluded.looking_for_roles,
                city=excluded.city,
                username=excluded.username,
                contact=excluded.contact,
                about=excluded.about,
                photo_file_id=excluded.photo_file_id,
                updated_at=excluded.updated_at
            """,
            (
                profile.user_id,
                profile.name,
                dumps_list(profile.championships),
                dumps_list(profile.roles),
                profile.status,
                dumps_list(profile.looking_for_roles) if profile.status == STATUS_HAS_TEAM else None,
                profile.city,
                profile.username,
                profile.contact,
                profile.about,
                profile.photo_file_id,
                profile.created_at,
                profile.updated_at,
            ),
        )
        self.connection.commit()

    def get_profile(self, user_id: int) -> Profile | None:
        row = self.connection.execute(
            "SELECT * FROM profiles WHERE id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        return Profile.from_row(row)

    def list_profiles(self) -> list[Profile]:
        rows = self.connection.execute(
            "SELECT * FROM profiles ORDER BY updated_at DESC, created_at DESC"
        ).fetchall()
        return [Profile.from_row(row) for row in rows]

    def delete_profile(self, user_id: int) -> None:
        self.connection.execute(
            "DELETE FROM likes WHERE from_user_id = ? OR to_user_id = ?",
            (user_id, user_id),
        )
        self.connection.execute(
            "DELETE FROM matches WHERE user_low_id = ? OR user_high_id = ?",
            (user_id, user_id),
        )
        self.connection.execute("DELETE FROM profiles WHERE id = ?", (user_id,))
        self.connection.commit()

    def save_reaction(self, from_user_id: int, to_user_id: int, reaction: str) -> bool:
        try:
            self.connection.execute(
                """
                INSERT INTO likes (from_user_id, to_user_id, reaction, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (from_user_id, to_user_id, reaction, now_iso()),
            )
            self.connection.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def is_mutual_like(self, first_user_id: int, second_user_id: int) -> bool:
        row = self.connection.execute(
            """
            SELECT 1
            FROM likes
            WHERE from_user_id = ? AND to_user_id = ? AND reaction = 'like'
            LIMIT 1
            """,
            (second_user_id, first_user_id),
        ).fetchone()
        return row is not None

    def create_match(self, first_user_id: int, second_user_id: int) -> bool:
        low_id, high_id = sorted((first_user_id, second_user_id))
        try:
            self.connection.execute(
                """
                INSERT INTO matches (user_low_id, user_high_id, created_at)
                VALUES (?, ?, ?)
                """,
                (low_id, high_id, now_iso()),
            )
            self.connection.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_matches_for_user(self, user_id: int) -> list[tuple[Profile, str]]:
        rows = self.connection.execute(
            """
            SELECT user_low_id, user_high_id, created_at
            FROM matches
            WHERE user_low_id = ? OR user_high_id = ?
            ORDER BY created_at DESC
            """,
            (user_id, user_id),
        ).fetchall()

        matches: list[tuple[Profile, str]] = []
        for row in rows:
            other_id = row["user_high_id"] if row["user_low_id"] == user_id else row["user_low_id"]
            profile = self.get_profile(other_id)
            if profile is not None:
                matches.append((profile, row["created_at"]))
        return matches

    def get_feed_candidates(self, viewer_id: int, filters: dict[str, list[str]]) -> list[Profile]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM profiles
            WHERE id != ?
              AND id NOT IN (
                SELECT to_user_id
                FROM likes
                WHERE from_user_id = ?
              )
            ORDER BY updated_at DESC, created_at DESC
            """,
            (viewer_id, viewer_id),
        ).fetchall()

        candidates = [Profile.from_row(row) for row in rows]
        filtered: list[Profile] = []

        wanted_championships = set(filters.get("championships", []))
        wanted_roles = set(filters.get("roles", []))
        wanted_looking_for_roles = set(filters.get("looking_for_roles", []))

        for profile in candidates:
            if wanted_championships and not wanted_championships.intersection(profile.championships):
                continue
            if wanted_roles and not wanted_roles.intersection(profile.roles):
                continue
            if wanted_looking_for_roles and not wanted_looking_for_roles.intersection(profile.looking_for_roles):
                continue
            filtered.append(profile)

        return filtered

    def get_profile_ids(self) -> list[int]:
        rows = self.connection.execute("SELECT id FROM profiles ORDER BY id").fetchall()
        return [row["id"] for row in rows]

    def get_stats(self) -> dict[str, Any]:
        profiles = self.list_profiles()
        by_status = Counter({STATUS_LOOKING: 0, STATUS_HAS_TEAM: 0})
        by_championship = Counter()

        for profile in profiles:
            by_status[profile.status] += 1
            for championship in profile.championships:
                by_championship[championship] += 1

        likes_count = self.connection.execute(
            "SELECT COUNT(*) AS count FROM likes WHERE reaction = 'like'"
        ).fetchone()["count"]
        matches_count = self.connection.execute(
            "SELECT COUNT(*) AS count FROM matches"
        ).fetchone()["count"]

        return {
            "profiles_count": len(profiles),
            "by_status": dict(by_status),
            "by_championship": dict(by_championship),
            "likes_count": likes_count,
            "matches_count": matches_count,
        }
