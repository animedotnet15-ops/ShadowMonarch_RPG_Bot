from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True)
class Config:
    bot_token: str
    owner_id: int
    database_path: str

    @classmethod
    def from_env(cls) -> "Config":
        try:
            owner_id = int(os.getenv("OWNER_ID", "0"))
        except ValueError:
            owner_id = 0
        return cls(
            bot_token=_required("BOT_TOKEN"),
            owner_id=owner_id,
            database_path=os.getenv("DATABASE_PATH", "shadowmonarch.db").strip(),
        )


config = Config.from_env()
