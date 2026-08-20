from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Settings:
    bot_token: str
    admin_id: int
    database_path: Path


def load_dotenv_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


def load_settings() -> Settings:
    load_dotenv_file(Path(".env"))

    bot_token = os.getenv("BOT_TOKEN", "").strip()
    if not bot_token:
        raise RuntimeError("BOT_TOKEN not found. Create .env from .env.example.")

    admin_id_raw = os.getenv("ADMIN_ID", "896449496").strip()
    database_path_raw = os.getenv("DATABASE_PATH", "data/team_matcher.sqlite3").strip()

    return Settings(
        bot_token=bot_token,
        admin_id=int(admin_id_raw),
        database_path=Path(database_path_raw),
    )
