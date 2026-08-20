from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from aiogram.fsm.storage.base import BaseStorage, StateType, StorageKey

from bot.database import now_iso


def _storage_key_to_string(key: StorageKey) -> str:
    payload = {
        "bot_id": key.bot_id,
        "chat_id": key.chat_id,
        "user_id": key.user_id,
        "thread_id": key.thread_id,
        "business_connection_id": key.business_connection_id,
        "destiny": key.destiny,
    }
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


class SQLiteStorage(BaseStorage):
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS fsm_storage (
                storage_key TEXT PRIMARY KEY,
                state TEXT,
                data TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        storage_key = _storage_key_to_string(key)
        state_value = None if state is None else str(state)
        existing = self.connection.execute(
            "SELECT data FROM fsm_storage WHERE storage_key = ?",
            (storage_key,),
        ).fetchone()
        data_value = existing["data"] if existing is not None else "{}"
        self.connection.execute(
            """
            INSERT INTO fsm_storage (storage_key, state, data, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(storage_key) DO UPDATE SET
                state=excluded.state,
                updated_at=excluded.updated_at
            """,
            (storage_key, state_value, data_value, now_iso()),
        )
        self.connection.commit()

    async def get_state(self, key: StorageKey) -> str | None:
        storage_key = _storage_key_to_string(key)
        row = self.connection.execute(
            "SELECT state FROM fsm_storage WHERE storage_key = ?",
            (storage_key,),
        ).fetchone()
        if row is None:
            return None
        return row["state"]

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        storage_key = _storage_key_to_string(key)
        state_row = self.connection.execute(
            "SELECT state FROM fsm_storage WHERE storage_key = ?",
            (storage_key,),
        ).fetchone()
        state_value = state_row["state"] if state_row is not None else None
        self.connection.execute(
            """
            INSERT INTO fsm_storage (storage_key, state, data, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(storage_key) DO UPDATE SET
                data=excluded.data,
                updated_at=excluded.updated_at
            """,
            (storage_key, state_value, json.dumps(dict(data), ensure_ascii=False), now_iso()),
        )
        self.connection.commit()

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        storage_key = _storage_key_to_string(key)
        row = self.connection.execute(
            "SELECT data FROM fsm_storage WHERE storage_key = ?",
            (storage_key,),
        ).fetchone()
        if row is None:
            return {}
        return dict(json.loads(row["data"]))

    async def close(self) -> None:
        self.connection.close()
