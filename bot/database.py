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
    age: int | None
    study_info: str | None
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
            age=row["age"],
            study_info=row["study_info"],
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

    def backup_to(self, destination: str | Path) -> Path:
        destination_path = Path(destination)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(destination_path) as backup_connection:
            self.connection.backup(backup_connection)
            backup_connection.commit()
        return destination_path

    def init_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS profiles (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                age INTEGER,
                study_info TEXT,
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
                from_user_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                to_user_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                reaction TEXT NOT NULL CHECK(reaction IN ('like', 'pass')),
                created_at TEXT NOT NULL,
                UNIQUE(from_user_id, to_user_id)
            );

            CREATE TABLE IF NOT EXISTS matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_low_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                user_high_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                UNIQUE(user_low_id, user_high_id)
            );

            CREATE INDEX IF NOT EXISTS idx_likes_to_user ON likes (to_user_id, reaction);
            CREATE INDEX IF NOT EXISTS idx_matches_users ON matches (user_low_id, user_high_id);
            """
        )
        self._migrate_profiles_table()
        self._migrate_relational_tables()
        self.connection.commit()

    def _profile_column_names(self) -> set[str]:
        rows = self.connection.execute("PRAGMA table_info(profiles)").fetchall()
        return {row["name"] for row in rows}

    def _migrate_profiles_table(self) -> None:
        columns = self._profile_column_names()
        if "age" not in columns:
            self.connection.execute("ALTER TABLE profiles ADD COLUMN age INTEGER")
        if "study_info" not in columns:
            self.connection.execute("ALTER TABLE profiles ADD COLUMN study_info TEXT")

    def _table_has_foreign_keys(self, table_name: str) -> bool:
        rows = self.connection.execute(f"PRAGMA foreign_key_list({table_name})").fetchall()
        return bool(rows)

    def _migrate_relational_tables(self) -> None:
        if not self._table_has_foreign_keys("likes"):
            self.connection.executescript(
                """
                ALTER TABLE likes RENAME TO likes_old;
                CREATE TABLE likes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    from_user_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                    to_user_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                    reaction TEXT NOT NULL CHECK(reaction IN ('like', 'pass')),
                    created_at TEXT NOT NULL,
                    UNIQUE(from_user_id, to_user_id)
                );
                INSERT OR IGNORE INTO likes (id, from_user_id, to_user_id, reaction, created_at)
                SELECT lo.id, lo.from_user_id, lo.to_user_id, lo.reaction, lo.created_at
                FROM likes_old lo
                JOIN profiles pf ON pf.id = lo.from_user_id
                JOIN profiles pt ON pt.id = lo.to_user_id;
                DROP TABLE likes_old;
                CREATE INDEX IF NOT EXISTS idx_likes_to_user ON likes (to_user_id, reaction);
                """
            )

        if not self._table_has_foreign_keys("matches"):
            self.connection.executescript(
                """
                ALTER TABLE matches RENAME TO matches_old;
                CREATE TABLE matches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_low_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                    user_high_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    UNIQUE(user_low_id, user_high_id)
                );
                INSERT OR IGNORE INTO matches (id, user_low_id, user_high_id, created_at)
                SELECT mo.id, mo.user_low_id, mo.user_high_id, mo.created_at
                FROM matches_old mo
                JOIN profiles pl ON pl.id = mo.user_low_id
                JOIN profiles ph ON ph.id = mo.user_high_id;
                DROP TABLE matches_old;
                CREATE INDEX IF NOT EXISTS idx_matches_users ON matches (user_low_id, user_high_id);
                """
            )

    def profile_exists(self, user_id: int) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM profiles WHERE id = ? LIMIT 1",
            (user_id,),
        ).fetchone()
        return row is not None

    def profiles_exist(self, *user_ids: int) -> bool:
        if not user_ids:
            return True
        placeholders = ", ".join("?" for _ in user_ids)
        row = self.connection.execute(
            f"SELECT COUNT(*) AS count FROM profiles WHERE id IN ({placeholders})",
            user_ids,
        ).fetchone()
        return row["count"] == len(set(user_ids))

    def upsert_profile(self, profile: Profile) -> None:
        self.connection.execute(
            """
            INSERT INTO profiles (
                id, name, age, study_info, championships, roles, status, looking_for_roles,
                city, username, contact, about, photo_file_id, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                age=excluded.age,
                study_info=excluded.study_info,
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
                profile.age,
                profile.study_info,
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
        if from_user_id == to_user_id or not self.profiles_exist(from_user_id, to_user_id):
            return False
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
        if first_user_id == second_user_id or not self.profiles_exist(first_user_id, second_user_id):
            return False
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

    def get_health_snapshot(self) -> dict[str, Any]:
        stats = self.get_stats()
        fsm_sessions = 0
        table_exists = self.connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'fsm_storage'
            LIMIT 1
            """
        ).fetchone()
        if table_exists is not None:
            fsm_sessions = self.connection.execute(
                "SELECT COUNT(*) AS count FROM fsm_storage"
            ).fetchone()["count"]

        db_size_bytes = self.db_path.stat().st_size if self.db_path.exists() else 0
        return {
            **stats,
            "db_path": str(self.db_path),
            "db_size_bytes": db_size_bytes,
            "fsm_sessions": fsm_sessions,
        }
