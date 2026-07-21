from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import aiosqlite

from config import config
import game_data as gd

STARTING_STATS = {"str": 10, "agi": 10, "intel": 10, "vit": 10, "per": 10}
BASE_HP = 100


class Database:
    def __init__(self, path: str) -> None:
        self.path = path

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[aiosqlite.Connection]:
        db = await aiosqlite.connect(self.path)
        db.row_factory = aiosqlite.Row
        try:
            yield db
        finally:
            await db.close()

    async def init(self) -> None:
        parent = Path(self.path).parent
        if str(parent) != ".":
            parent.mkdir(parents=True, exist_ok=True)
        async with self.connection() as db:
            await db.executescript(
                """
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS players (
                    user_id       INTEGER PRIMARY KEY,
                    first_name    TEXT NOT NULL DEFAULT '',
                    rank          TEXT NOT NULL DEFAULT 'E',
                    level         INTEGER NOT NULL DEFAULT 1,
                    xp            INTEGER NOT NULL DEFAULT 0,
                    xp_next       INTEGER NOT NULL DEFAULT 50,
                    hp            INTEGER NOT NULL DEFAULT 100,
                    max_hp        INTEGER NOT NULL DEFAULT 100,
                    str_stat      INTEGER NOT NULL DEFAULT 10,
                    agi_stat      INTEGER NOT NULL DEFAULT 10,
                    intel_stat    INTEGER NOT NULL DEFAULT 10,
                    vit_stat      INTEGER NOT NULL DEFAULT 10,
                    per_stat      INTEGER NOT NULL DEFAULT 10,
                    stat_points   INTEGER NOT NULL DEFAULT 0,
                    gold          INTEGER NOT NULL DEFAULT 50,
                    gems          INTEGER NOT NULL DEFAULT 10,
                    equipped_weapon TEXT NOT NULL DEFAULT 'rusty_dagger',
                    active_character TEXT NOT NULL DEFAULT '',
                    mana_crystals INTEGER NOT NULL DEFAULT 0,
                    essence_stones INTEGER NOT NULL DEFAULT 0,
                    daily_claimed_at INTEGER NOT NULL DEFAULT 0,
                    hourly_claimed_at INTEGER NOT NULL DEFAULT 0,
                    story_arc     TEXT NOT NULL DEFAULT 'arc1',
                    story_node    TEXT NOT NULL DEFAULT 'n1',
                    completed_arcs TEXT NOT NULL DEFAULT '[]',
                    created_at    INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS inventory (
                    user_id   INTEGER NOT NULL,
                    weapon_id TEXT NOT NULL,
                    PRIMARY KEY(user_id, weapon_id)
                );

                CREATE TABLE IF NOT EXISTS shadow_army (
                    user_id   INTEGER NOT NULL,
                    shadow_id TEXT NOT NULL,
                    count     INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY(user_id, shadow_id)
                );

                CREATE TABLE IF NOT EXISTS quiz_answered (
                    user_id       INTEGER NOT NULL,
                    question_idx  INTEGER NOT NULL,
                    PRIMARY KEY(user_id, question_idx)
                );

                CREATE TABLE IF NOT EXISTS battle_state (
                    user_id      INTEGER PRIMARY KEY,
                    monster_id   TEXT NOT NULL,
                    monster_hp   INTEGER NOT NULL,
                    next_node    TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS player_characters (
                    user_id      INTEGER NOT NULL,
                    character_id TEXT NOT NULL,
                    count        INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY(user_id, character_id)
                );

                CREATE TABLE IF NOT EXISTS gate_cooldowns (
                    user_id  INTEGER NOT NULL,
                    gate_id  TEXT NOT NULL,
                    last_at  INTEGER NOT NULL,
                    PRIMARY KEY(user_id, gate_id)
                );

                CREATE TABLE IF NOT EXISTS gate_battle_state (
                    user_id     INTEGER PRIMARY KEY,
                    gate_id     TEXT NOT NULL,
                    monster_id  TEXT NOT NULL,
                    monster_hp  INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pvp_battles (
                    battle_id      TEXT PRIMARY KEY,
                    chat_id        INTEGER NOT NULL,
                    message_id     INTEGER NOT NULL,
                    challenger_id  INTEGER NOT NULL,
                    target_id      INTEGER NOT NULL,
                    challenger_hp  INTEGER NOT NULL,
                    target_hp      INTEGER NOT NULL,
                    turn_user_id   INTEGER NOT NULL,
                    status         TEXT NOT NULL DEFAULT 'pending',
                    created_at     INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            await db.commit()

    # ------------------------------------------------------------------ #
    #  Settings (welcome message customization etc.)
    # ------------------------------------------------------------------ #
    async def get_setting(self, key: str, default: str = "") -> str:
        async with self.connection() as db:
            row = await (await db.execute("SELECT value FROM settings WHERE key=?", (key,))).fetchone()
            return str(row["value"]) if row else default

    async def set_setting(self, key: str, value: str) -> None:
        async with self.connection() as db:
            await db.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            await db.commit()

    # ------------------------------------------------------------------ #
    #  Player lifecycle
    # ------------------------------------------------------------------ #
    async def get_or_create_player(self, user_id: int, first_name: str) -> aiosqlite.Row:
        import html as _html
        first_name = _html.escape(first_name or "Hunter")
        async with self.connection() as db:
            row = await (await db.execute("SELECT * FROM players WHERE user_id=?", (user_id,))).fetchone()
            if row:
                return row
            await db.execute(
                """
                INSERT INTO players(user_id, first_name, hp, max_hp, str_stat, agi_stat, intel_stat, vit_stat, per_stat, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id, first_name, BASE_HP, BASE_HP,
                    STARTING_STATS["str"], STARTING_STATS["agi"], STARTING_STATS["intel"],
                    STARTING_STATS["vit"], STARTING_STATS["per"], int(time.time()),
                ),
            )
            await db.execute(
                "INSERT OR IGNORE INTO inventory(user_id, weapon_id) VALUES(?, ?)",
                (user_id, gd.STARTING_WEAPON),
            )
            await db.commit()
            return await (await db.execute("SELECT * FROM players WHERE user_id=?", (user_id,))).fetchone()

    async def get_player(self, user_id: int) -> aiosqlite.Row | None:
        async with self.connection() as db:
            return await (await db.execute("SELECT * FROM players WHERE user_id=?", (user_id,))).fetchone()

    async def update_player(self, user_id: int, **fields) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        values = list(fields.values()) + [user_id]
        async with self.connection() as db:
            await db.execute(f"UPDATE players SET {cols} WHERE user_id=?", values)
            await db.commit()

    async def add_gold_xp(self, user_id: int, gold: int = 0, xp: int = 0, gems: int = 0,
                           mana_crystals: int = 0, essence_stones: int = 0) -> dict:
        """Applies gold/xp/gems/resources, handles level-ups, returns a summary of what changed."""
        player = await self.get_player(user_id)
        if not player:
            return {}
        new_gold = player["gold"] + gold
        new_gems = player["gems"] + gems
        new_mana = player["mana_crystals"] + mana_crystals
        new_essence = player["essence_stones"] + essence_stones
        new_xp = player["xp"] + xp
        level = player["level"]
        xp_next = player["xp_next"]
        max_hp = player["max_hp"]
        stat_points = player["stat_points"]
        levels_gained = 0

        while new_xp >= xp_next:
            new_xp -= xp_next
            level += 1
            levels_gained += 1
            xp_next = int(xp_next * 1.35) + 20
            max_hp += 15
            stat_points += 3

        rank = _rank_for_level(level)

        async with self.connection() as db:
            await db.execute(
                """
                UPDATE players SET gold=?, gems=?, mana_crystals=?, essence_stones=?, xp=?, level=?,
                       xp_next=?, max_hp=?, hp=?, stat_points=?, rank=?
                WHERE user_id=?
                """,
                (new_gold, new_gems, new_mana, new_essence, new_xp, level, xp_next, max_hp,
                 max_hp if levels_gained else player["hp"], stat_points, rank, user_id),
            )
            await db.commit()
        return {"levels_gained": levels_gained, "level": level, "rank": rank}

    async def spend_stat_point(self, user_id: int, stat: str) -> bool:
        col = {"str": "str_stat", "agi": "agi_stat", "intel": "intel_stat", "vit": "vit_stat", "per": "per_stat"}.get(stat)
        if not col:
            return False
        player = await self.get_player(user_id)
        if not player or player["stat_points"] <= 0:
            return False
        async with self.connection() as db:
            await db.execute(
                f"UPDATE players SET {col} = {col} + 1, stat_points = stat_points - 1 WHERE user_id=?",
                (user_id,),
            )
            await db.commit()
        return True

    # ------------------------------------------------------------------ #
    #  Inventory / weapons
    # ------------------------------------------------------------------ #
    async def grant_weapon(self, user_id: int, weapon_id: str) -> None:
        async with self.connection() as db:
            await db.execute(
                "INSERT OR IGNORE INTO inventory(user_id, weapon_id) VALUES(?, ?)", (user_id, weapon_id)
            )
            await db.commit()

    async def owned_weapons(self, user_id: int) -> list[str]:
        async with self.connection() as db:
            rows = await (await db.execute("SELECT weapon_id FROM inventory WHERE user_id=?", (user_id,))).fetchall()
            return [r["weapon_id"] for r in rows]

    async def equip_weapon(self, user_id: int, weapon_id: str) -> None:
        await self.update_player(user_id, equipped_weapon=weapon_id)

    # ------------------------------------------------------------------ #
    #  Shadow army
    # ------------------------------------------------------------------ #
    async def add_shadow(self, user_id: int, shadow_id: str) -> int:
        async with self.connection() as db:
            await db.execute(
                """
                INSERT INTO shadow_army(user_id, shadow_id, count) VALUES(?, ?, 1)
                ON CONFLICT(user_id, shadow_id) DO UPDATE SET count = count + 1
                """,
                (user_id, shadow_id),
            )
            await db.commit()
            row = await (
                await db.execute(
                    "SELECT count FROM shadow_army WHERE user_id=? AND shadow_id=?", (user_id, shadow_id)
                )
            ).fetchone()
            return int(row["count"])

    async def get_shadow_army(self, user_id: int) -> list[aiosqlite.Row]:
        async with self.connection() as db:
            return await (
                await db.execute("SELECT shadow_id, count FROM shadow_army WHERE user_id=?", (user_id,))
            ).fetchall()

    async def shadow_army_atk_bonus(self, user_id: int) -> int:
        rows = await self.get_shadow_army(user_id)
        total = 0
        for r in rows:
            info = gd.SHADOWS.get(r["shadow_id"])
            if info:
                total += info["atk_bonus"] * r["count"]
        return total

    # ------------------------------------------------------------------ #
    #  Story progress
    # ------------------------------------------------------------------ #
    async def set_story_position(self, user_id: int, arc: str, node: str) -> None:
        await self.update_player(user_id, story_arc=arc, story_node=node)

    async def complete_arc(self, user_id: int, arc: str) -> None:
        player = await self.get_player(user_id)
        completed = json.loads(player["completed_arcs"]) if player else []
        if arc not in completed:
            completed.append(arc)
        await self.update_player(user_id, completed_arcs=json.dumps(completed))

    async def completed_arcs(self, user_id: int) -> list[str]:
        player = await self.get_player(user_id)
        return json.loads(player["completed_arcs"]) if player else []

    # ------------------------------------------------------------------ #
    #  Battle state
    # ------------------------------------------------------------------ #
    async def start_battle(self, user_id: int, monster_id: str, monster_hp: int, next_node: str) -> None:
        async with self.connection() as db:
            await db.execute(
                "INSERT INTO battle_state(user_id, monster_id, monster_hp, next_node) VALUES(?, ?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET monster_id=excluded.monster_id, monster_hp=excluded.monster_hp, next_node=excluded.next_node",
                (user_id, monster_id, monster_hp, next_node),
            )
            await db.commit()

    async def get_battle(self, user_id: int) -> aiosqlite.Row | None:
        async with self.connection() as db:
            return await (await db.execute("SELECT * FROM battle_state WHERE user_id=?", (user_id,))).fetchone()

    async def update_battle_hp(self, user_id: int, monster_hp: int) -> None:
        async with self.connection() as db:
            await db.execute("UPDATE battle_state SET monster_hp=? WHERE user_id=?", (monster_hp, user_id))
            await db.commit()

    async def end_battle(self, user_id: int) -> None:
        async with self.connection() as db:
            await db.execute("DELETE FROM battle_state WHERE user_id=?", (user_id,))
            await db.commit()

    # ------------------------------------------------------------------ #
    #  Quiz
    # ------------------------------------------------------------------ #
    async def has_answered(self, user_id: int, idx: int) -> bool:
        async with self.connection() as db:
            row = await (
                await db.execute(
                    "SELECT 1 FROM quiz_answered WHERE user_id=? AND question_idx=?", (user_id, idx)
                )
            ).fetchone()
            return row is not None

    async def mark_answered(self, user_id: int, idx: int) -> None:
        async with self.connection() as db:
            await db.execute(
                "INSERT OR IGNORE INTO quiz_answered(user_id, question_idx) VALUES(?, ?)", (user_id, idx)
            )
            await db.commit()

    # ------------------------------------------------------------------ #
    #  Playable characters
    # ------------------------------------------------------------------ #
    async def add_character(self, user_id: int, character_id: str) -> int:
        async with self.connection() as db:
            await db.execute(
                """
                INSERT INTO player_characters(user_id, character_id, count) VALUES(?, ?, 1)
                ON CONFLICT(user_id, character_id) DO UPDATE SET count = count + 1
                """,
                (user_id, character_id),
            )
            await db.commit()
            row = await (
                await db.execute(
                    "SELECT count FROM player_characters WHERE user_id=? AND character_id=?",
                    (user_id, character_id),
                )
            ).fetchone()
            return int(row["count"])

    async def get_characters(self, user_id: int) -> list[aiosqlite.Row]:
        async with self.connection() as db:
            return await (
                await db.execute(
                    "SELECT character_id, count FROM player_characters WHERE user_id=?", (user_id,)
                )
            ).fetchall()

    async def set_active_character(self, user_id: int, character_id: str) -> None:
        await self.update_player(user_id, active_character=character_id)

    # ------------------------------------------------------------------ #
    #  Gates
    # ------------------------------------------------------------------ #
    async def gate_cooldown_remaining(self, user_id: int, gate_id: str, cooldown_min: int) -> int:
        async with self.connection() as db:
            row = await (
                await db.execute(
                    "SELECT last_at FROM gate_cooldowns WHERE user_id=? AND gate_id=?", (user_id, gate_id)
                )
            ).fetchone()
        if not row:
            return 0
        elapsed = int(time.time()) - int(row["last_at"])
        remaining = cooldown_min * 60 - elapsed
        return max(0, remaining)

    async def set_gate_cooldown(self, user_id: int, gate_id: str) -> None:
        async with self.connection() as db:
            await db.execute(
                "INSERT INTO gate_cooldowns(user_id, gate_id, last_at) VALUES(?, ?, ?) "
                "ON CONFLICT(user_id, gate_id) DO UPDATE SET last_at=excluded.last_at",
                (user_id, gate_id, int(time.time())),
            )
            await db.commit()

    async def start_gate_battle(self, user_id: int, gate_id: str, monster_id: str, monster_hp: int) -> None:
        async with self.connection() as db:
            await db.execute(
                "INSERT INTO gate_battle_state(user_id, gate_id, monster_id, monster_hp) VALUES(?, ?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET gate_id=excluded.gate_id, monster_id=excluded.monster_id, monster_hp=excluded.monster_hp",
                (user_id, gate_id, monster_id, monster_hp),
            )
            await db.commit()

    async def get_gate_battle(self, user_id: int) -> aiosqlite.Row | None:
        async with self.connection() as db:
            return await (
                await db.execute("SELECT * FROM gate_battle_state WHERE user_id=?", (user_id,))
            ).fetchone()

    async def update_gate_battle_hp(self, user_id: int, monster_hp: int) -> None:
        async with self.connection() as db:
            await db.execute("UPDATE gate_battle_state SET monster_hp=? WHERE user_id=?", (monster_hp, user_id))
            await db.commit()

    async def end_gate_battle(self, user_id: int) -> None:
        async with self.connection() as db:
            await db.execute("DELETE FROM gate_battle_state WHERE user_id=?", (user_id,))
            await db.commit()

    # ------------------------------------------------------------------ #
    #  Missions
    # ------------------------------------------------------------------ #
    async def daily_status(self, user_id: int) -> int:
        """Returns seconds remaining until next daily claim (0 = claimable now)."""
        p = await self.get_player(user_id)
        if not p or p["daily_claimed_at"] == 0:
            return 0
        remaining = 86400 - (int(time.time()) - p["daily_claimed_at"])
        return max(0, remaining)

    async def claim_daily(self, user_id: int) -> None:
        await self.update_player(user_id, daily_claimed_at=int(time.time()))

    async def hourly_status(self, user_id: int) -> int:
        p = await self.get_player(user_id)
        if not p or p["hourly_claimed_at"] == 0:
            return 0
        remaining = 3600 - (int(time.time()) - p["hourly_claimed_at"])
        return max(0, remaining)

    async def claim_hourly(self, user_id: int) -> None:
        await self.update_player(user_id, hourly_claimed_at=int(time.time()))

    # ------------------------------------------------------------------ #
    #  PvP
    # ------------------------------------------------------------------ #
    async def create_pvp_battle(self, battle_id: str, chat_id: int, message_id: int, challenger_id: int,
                                 target_id: int, challenger_hp: int, target_hp: int) -> None:
        async with self.connection() as db:
            await db.execute(
                """
                INSERT INTO pvp_battles(battle_id, chat_id, message_id, challenger_id, target_id,
                    challenger_hp, target_hp, turn_user_id, status, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (battle_id, chat_id, message_id, challenger_id, target_id, challenger_hp, target_hp,
                 challenger_id, int(time.time())),
            )
            await db.commit()

    async def get_pvp_battle(self, battle_id: str) -> aiosqlite.Row | None:
        async with self.connection() as db:
            return await (
                await db.execute("SELECT * FROM pvp_battles WHERE battle_id=?", (battle_id,))
            ).fetchone()

    async def update_pvp_battle(self, battle_id: str, **fields) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        values = list(fields.values()) + [battle_id]
        async with self.connection() as db:
            await db.execute(f"UPDATE pvp_battles SET {cols} WHERE battle_id=?", values)
            await db.commit()

    async def delete_pvp_battle(self, battle_id: str) -> None:
        async with self.connection() as db:
            await db.execute("DELETE FROM pvp_battles WHERE battle_id=?", (battle_id,))
            await db.commit()

    # ------------------------------------------------------------------ #
    #  Leaderboard
    # ------------------------------------------------------------------ #
    async def top_players(self, limit: int = 10) -> list[aiosqlite.Row]:
        async with self.connection() as db:
            return await (
                await db.execute(
                    "SELECT first_name, level, rank, gold FROM players ORDER BY level DESC, gold DESC LIMIT ?",
                    (limit,),
                )
            ).fetchall()


def _rank_for_level(level: int) -> str:
    if level >= 40:
        return "S"
    if level >= 30:
        return "A"
    if level >= 20:
        return "B"
    if level >= 10:
        return "C"
    if level >= 5:
        return "D"
    return "E"


database = Database(config.database_path)
