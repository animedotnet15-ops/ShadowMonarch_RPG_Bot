from __future__ import annotations

import json
import random
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
                    streak_days   INTEGER NOT NULL DEFAULT 0,
                    last_daily_date TEXT NOT NULL DEFAULT '',
                    energy        INTEGER NOT NULL DEFAULT 20,
                    max_energy    INTEGER NOT NULL DEFAULT 20,
                    last_energy_update INTEGER NOT NULL DEFAULT 0,
                    hourly_reminded INTEGER NOT NULL DEFAULT 1,
                    daily_reminded INTEGER NOT NULL DEFAULT 1,
                    energy_reminded INTEGER NOT NULL DEFAULT 1,
                    reminders_enabled INTEGER NOT NULL DEFAULT 1,
                    guild_id      INTEGER,
                    last_freespin_date TEXT NOT NULL DEFAULT '',
                    last_active_chat_id INTEGER,
                    equipped_title TEXT NOT NULL DEFAULT '',
                    referred_by   INTEGER,
                    referral_count INTEGER NOT NULL DEFAULT 0,
                    last_rob_at   INTEGER NOT NULL DEFAULT 0,
                    bank_gold     INTEGER NOT NULL DEFAULT 0,
                    last_interest_at INTEGER NOT NULL DEFAULT 0,
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

                CREATE TABLE IF NOT EXISTS groups (
                    chat_id       INTEGER PRIMARY KEY,
                    title         TEXT NOT NULL DEFAULT '',
                    registered_at INTEGER NOT NULL,
                    last_report_at INTEGER NOT NULL DEFAULT 0,
                    last_wild_gate_at INTEGER NOT NULL DEFAULT 0,
                    last_group_quiz_at INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS group_quiz (
                    chat_id      INTEGER PRIMARY KEY,
                    question_idx INTEGER NOT NULL,
                    expires_at   INTEGER NOT NULL,
                    closed       INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS achievements (
                    user_id        INTEGER NOT NULL,
                    achievement_id TEXT NOT NULL,
                    unlocked_at    INTEGER NOT NULL,
                    PRIMARY KEY(user_id, achievement_id)
                );

                CREATE TABLE IF NOT EXISTS wild_gates (
                    chat_id      INTEGER PRIMARY KEY,
                    monster_name TEXT NOT NULL,
                    hp           INTEGER NOT NULL,
                    max_hp       INTEGER NOT NULL,
                    message_id   INTEGER NOT NULL DEFAULT 0,
                    expires_at   INTEGER NOT NULL,
                    rewards_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS wild_gate_participants (
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    damage  INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(chat_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS group_activity (
                    chat_id      INTEGER NOT NULL,
                    user_id      INTEGER NOT NULL,
                    first_name   TEXT NOT NULL DEFAULT '',
                    action_date  TEXT NOT NULL,
                    action_count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(chat_id, user_id, action_date)
                );

                CREATE TABLE IF NOT EXISTS guilds (
                    guild_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                    name        TEXT NOT NULL UNIQUE,
                    owner_id    INTEGER NOT NULL,
                    vault_gold  INTEGER NOT NULL DEFAULT 0,
                    vault_gems  INTEGER NOT NULL DEFAULT 0,
                    vault_mana  INTEGER NOT NULL DEFAULT 0,
                    vault_essence INTEGER NOT NULL DEFAULT 0,
                    created_at  INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS coupons (
                    code        TEXT PRIMARY KEY,
                    gold        INTEGER NOT NULL DEFAULT 0,
                    gems        INTEGER NOT NULL DEFAULT 0,
                    mana        INTEGER NOT NULL DEFAULT 0,
                    essence     INTEGER NOT NULL DEFAULT 0,
                    max_uses    INTEGER NOT NULL DEFAULT 1,
                    used_count  INTEGER NOT NULL DEFAULT 0,
                    created_at  INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS coupon_redemptions (
                    code    TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    PRIMARY KEY(code, user_id)
                );

                CREATE TABLE IF NOT EXISTS custom_characters (
                    character_id TEXT PRIMARY KEY,
                    name         TEXT NOT NULL,
                    rarity       TEXT NOT NULL,
                    atk_bonus    INTEGER NOT NULL DEFAULT 0,
                    hp_bonus     INTEGER NOT NULL DEFAULT 0,
                    rate         REAL NOT NULL DEFAULT 0.02,
                    photo_file_id TEXT NOT NULL DEFAULT '',
                    added_at     INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS generated_images (
                    cache_key  TEXT PRIMARY KEY,
                    file_id    TEXT NOT NULL,
                    created_at INTEGER NOT NULL
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
                INSERT INTO players(user_id, first_name, hp, max_hp, str_stat, agi_stat, intel_stat, vit_stat, per_stat, created_at, last_energy_update)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id, first_name, BASE_HP, BASE_HP,
                    STARTING_STATS["str"], STARTING_STATS["agi"], STARTING_STATS["intel"],
                    STARTING_STATS["vit"], STARTING_STATS["per"], int(time.time()), int(time.time()),
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

    async def all_user_ids(self) -> list[int]:
        async with self.connection() as db:
            rows = await (await db.execute("SELECT user_id FROM players")).fetchall()
            return [int(r["user_id"]) for r in rows]


    # ------------------------------------------------------------------ #
    #  Energy / Stamina
    # ------------------------------------------------------------------ #
    async def get_energy(self, user_id: int) -> tuple[int, int, int]:
        """Lazily regenerates energy based on elapsed time. Returns (current, max, seconds_to_next_point)."""
        player = await self.get_player(user_id)
        if not player:
            return 0, gd.MAX_ENERGY, 0
        now = int(time.time())
        elapsed = now - (player["last_energy_update"] or now)
        regen_seconds = gd.ENERGY_REGEN_MINUTES * 60
        gained = elapsed // regen_seconds
        current = min(player["max_energy"], player["energy"] + gained)
        if gained > 0:
            leftover_seconds = elapsed % regen_seconds
            new_last_update = now - leftover_seconds
            async with self.connection() as db:
                await db.execute(
                    "UPDATE players SET energy=?, last_energy_update=? WHERE user_id=?",
                    (current, new_last_update, user_id),
                )
                if current < player["max_energy"]:
                    await db.execute("UPDATE players SET energy_reminded=0 WHERE user_id=?", (user_id,))
                await db.commit()
        seconds_to_next = 0 if current >= player["max_energy"] else regen_seconds - (now - (player["last_energy_update"] or now)) % regen_seconds
        return current, player["max_energy"], max(0, seconds_to_next)

    async def spend_energy(self, user_id: int, amount: int) -> bool:
        current, max_e, _ = await self.get_energy(user_id)
        if current < amount:
            return False
        async with self.connection() as db:
            await db.execute(
                "UPDATE players SET energy = energy - ?, energy_reminded = 0 WHERE user_id=?",
                (amount, user_id),
            )
            await db.commit()
        return True

    # ------------------------------------------------------------------ #
    #  Daily streak
    # ------------------------------------------------------------------ #
    async def claim_daily_with_streak(self, user_id: int) -> int:
        """Updates streak_days based on whether yesterday was claimed, returns the new streak count."""
        player = await self.get_player(user_id)
        today = time.strftime("%Y-%m-%d", time.gmtime())
        yesterday = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 86400))
        if player["last_daily_date"] == yesterday:
            new_streak = min(gd.STREAK_MAX_DAYS, player["streak_days"] + 1)
        elif player["last_daily_date"] == today:
            new_streak = player["streak_days"]  # already claimed today (shouldn't happen, guarded elsewhere)
        else:
            new_streak = 1
        async with self.connection() as db:
            await db.execute(
                "UPDATE players SET daily_claimed_at=?, last_daily_date=?, streak_days=?, daily_reminded=0 WHERE user_id=?",
                (int(time.time()), today, new_streak, user_id),
            )
            await db.commit()
        return new_streak

    # ------------------------------------------------------------------ #
    #  Reminder flags
    # ------------------------------------------------------------------ #
    async def mark_hourly_reminded(self, user_id: int) -> None:
        await self.update_player(user_id, hourly_reminded=1)

    async def mark_energy_reminded(self, user_id: int) -> None:
        await self.update_player(user_id, energy_reminded=1)

    async def toggle_reminders(self, user_id: int) -> bool:
        player = await self.get_player(user_id)
        new_val = 0 if player["reminders_enabled"] else 1
        await self.update_player(user_id, reminders_enabled=new_val)
        return bool(new_val)

    # ------------------------------------------------------------------ #
    #  Groups + activity leaderboard
    # ------------------------------------------------------------------ #
    async def register_group(self, chat_id: int, title: str) -> None:
        async with self.connection() as db:
            await db.execute(
                "INSERT INTO groups(chat_id, title, registered_at) VALUES(?, ?, ?) "
                "ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title",
                (chat_id, title, int(time.time())),
            )
            await db.commit()

    async def all_groups(self) -> list[aiosqlite.Row]:
        async with self.connection() as db:
            return await (await db.execute("SELECT * FROM groups")).fetchall()

    async def groups_due_for_report(self) -> list[aiosqlite.Row]:
        cutoff = int(time.time()) - gd.GROUP_REPORT_INTERVAL_SECONDS
        async with self.connection() as db:
            return await (
                await db.execute("SELECT * FROM groups WHERE last_report_at <= ?", (cutoff,))
            ).fetchall()

    async def mark_group_reported(self, chat_id: int) -> None:
        async with self.connection() as db:
            await db.execute("UPDATE groups SET last_report_at=? WHERE chat_id=?", (int(time.time()), chat_id))
            await db.commit()

    async def record_activity(self, chat_id: int, user_id: int, first_name: str) -> None:
        today = time.strftime("%Y-%m-%d", time.gmtime())
        async with self.connection() as db:
            await db.execute(
                """
                INSERT INTO group_activity(chat_id, user_id, first_name, action_date, action_count)
                VALUES(?, ?, ?, ?, 1)
                ON CONFLICT(chat_id, user_id, action_date) DO UPDATE SET
                    action_count = action_count + 1, first_name = excluded.first_name
                """,
                (chat_id, user_id, first_name, today),
            )
            await db.commit()

    async def top_activity_today(self, chat_id: int, limit: int = 10) -> list[aiosqlite.Row]:
        today = time.strftime("%Y-%m-%d", time.gmtime())
        async with self.connection() as db:
            return await (
                await db.execute(
                    "SELECT first_name, action_count FROM group_activity "
                    "WHERE chat_id=? AND action_date=? ORDER BY action_count DESC LIMIT ?",
                    (chat_id, today, limit),
                )
            ).fetchall()

    async def active_players_today(self, chat_id: int) -> int:
        today = time.strftime("%Y-%m-%d", time.gmtime())
        async with self.connection() as db:
            row = await (
                await db.execute(
                    "SELECT COUNT(*) c FROM group_activity WHERE chat_id=? AND action_date=?", (chat_id, today)
                )
            ).fetchone()
            return int(row["c"])

    # ------------------------------------------------------------------ #
    #  Wild Gates (group-wide auto-spawning boss events)
    # ------------------------------------------------------------------ #
    async def groups_due_for_wild_gate(self) -> list[aiosqlite.Row]:
        cutoff = int(time.time()) - gd.WILD_GATE_SPAWN_INTERVAL_SECONDS
        async with self.connection() as db:
            return await (
                await db.execute(
                    "SELECT g.* FROM groups g LEFT JOIN wild_gates w ON g.chat_id = w.chat_id "
                    "WHERE g.last_wild_gate_at <= ? AND w.chat_id IS NULL",
                    (cutoff,),
                )
            ).fetchall()

    async def spawn_wild_gate(self, chat_id: int, monster_name: str, hp: int, rewards: dict) -> None:
        now = int(time.time())
        async with self.connection() as db:
            await db.execute(
                "INSERT INTO wild_gates(chat_id, monster_name, hp, max_hp, expires_at, rewards_json) "
                "VALUES(?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(chat_id) DO UPDATE SET monster_name=excluded.monster_name, hp=excluded.hp, "
                "max_hp=excluded.max_hp, expires_at=excluded.expires_at, rewards_json=excluded.rewards_json",
                (chat_id, monster_name, hp, hp, now + gd.WILD_GATE_DURATION_SECONDS, json.dumps(rewards)),
            )
            await db.execute("UPDATE groups SET last_wild_gate_at=? WHERE chat_id=?", (now, chat_id))
            await db.execute("DELETE FROM wild_gate_participants WHERE chat_id=?", (chat_id,))
            await db.commit()

    async def set_wild_gate_message_id(self, chat_id: int, message_id: int) -> None:
        async with self.connection() as db:
            await db.execute("UPDATE wild_gates SET message_id=? WHERE chat_id=?", (message_id, chat_id))
            await db.commit()

    async def get_wild_gate(self, chat_id: int) -> aiosqlite.Row | None:
        async with self.connection() as db:
            return await (await db.execute("SELECT * FROM wild_gates WHERE chat_id=?", (chat_id,))).fetchone()

    async def wild_gate_deal_damage(self, chat_id: int, user_id: int, damage: int) -> int:
        """Applies damage, records participant contribution, returns remaining HP (>=0)."""
        async with self.connection() as db:
            await db.execute(
                "INSERT INTO wild_gate_participants(chat_id, user_id, damage) VALUES(?, ?, ?) "
                "ON CONFLICT(chat_id, user_id) DO UPDATE SET damage = damage + excluded.damage",
                (chat_id, user_id, damage),
            )
            await db.execute("UPDATE wild_gates SET hp = MAX(0, hp - ?) WHERE chat_id=?", (damage, chat_id))
            await db.commit()
            row = await (await db.execute("SELECT hp FROM wild_gates WHERE chat_id=?", (chat_id,))).fetchone()
            return int(row["hp"]) if row else 0

    async def wild_gate_participants(self, chat_id: int) -> list[aiosqlite.Row]:
        async with self.connection() as db:
            return await (
                await db.execute(
                    "SELECT p.user_id, p.damage, pl.first_name FROM wild_gate_participants p "
                    "JOIN players pl ON pl.user_id = p.user_id WHERE p.chat_id=? ORDER BY p.damage DESC",
                    (chat_id,),
                )
            ).fetchall()

    async def clear_wild_gate(self, chat_id: int) -> None:
        async with self.connection() as db:
            await db.execute("DELETE FROM wild_gates WHERE chat_id=?", (chat_id,))
            await db.execute("DELETE FROM wild_gate_participants WHERE chat_id=?", (chat_id,))
            await db.commit()

    async def expired_wild_gates(self) -> list[aiosqlite.Row]:
        async with self.connection() as db:
            return await (
                await db.execute("SELECT * FROM wild_gates WHERE expires_at <= ?", (int(time.time()),))
            ).fetchall()

    # ------------------------------------------------------------------ #
    #  Group Quiz (auto-posted, first correct answer wins)
    # ------------------------------------------------------------------ #
    async def groups_due_for_quiz(self) -> list[aiosqlite.Row]:
        cutoff = int(time.time()) - gd.GROUP_QUIZ_INTERVAL_SECONDS
        async with self.connection() as db:
            return await (
                await db.execute(
                    "SELECT g.* FROM groups g LEFT JOIN group_quiz q ON g.chat_id = q.chat_id "
                    "WHERE g.last_group_quiz_at <= ? AND q.chat_id IS NULL",
                    (cutoff,),
                )
            ).fetchall()

    async def spawn_group_quiz(self, chat_id: int, question_idx: int) -> None:
        now = int(time.time())
        async with self.connection() as db:
            await db.execute(
                "INSERT INTO group_quiz(chat_id, question_idx, expires_at) VALUES(?, ?, ?) "
                "ON CONFLICT(chat_id) DO UPDATE SET question_idx=excluded.question_idx, "
                "expires_at=excluded.expires_at, closed=0",
                (chat_id, question_idx, now + gd.GROUP_QUIZ_ANSWER_WINDOW_SECONDS),
            )
            await db.execute("UPDATE groups SET last_group_quiz_at=? WHERE chat_id=?", (now, chat_id))
            await db.commit()

    async def get_group_quiz(self, chat_id: int) -> aiosqlite.Row | None:
        async with self.connection() as db:
            return await (await db.execute("SELECT * FROM group_quiz WHERE chat_id=?", (chat_id,))).fetchone()

    async def close_group_quiz(self, chat_id: int) -> bool:
        """Atomically closes the quiz. Returns True if this call was the one that closed it (i.e. won the race)."""
        async with self.connection() as db:
            cur = await db.execute("UPDATE group_quiz SET closed=1 WHERE chat_id=? AND closed=0", (chat_id,))
            await db.commit()
            return cur.rowcount > 0

    async def clear_group_quiz(self, chat_id: int) -> None:
        async with self.connection() as db:
            await db.execute("DELETE FROM group_quiz WHERE chat_id=?", (chat_id,))
            await db.commit()

    async def expired_group_quizzes(self) -> list[aiosqlite.Row]:
        async with self.connection() as db:
            return await (
                await db.execute("SELECT * FROM group_quiz WHERE expires_at <= ?", (int(time.time()),))
            ).fetchall()

    # ------------------------------------------------------------------ #
    #  Achievements / Titles
    # ------------------------------------------------------------------ #
    async def has_achievement(self, user_id: int, achievement_id: str) -> bool:
        async with self.connection() as db:
            row = await (
                await db.execute(
                    "SELECT 1 FROM achievements WHERE user_id=? AND achievement_id=?", (user_id, achievement_id)
                )
            ).fetchone()
            return row is not None

    async def unlock_achievement(self, user_id: int, achievement_id: str) -> bool:
        """Returns True if this call newly unlocked it (False if already had it)."""
        async with self.connection() as db:
            try:
                await db.execute(
                    "INSERT INTO achievements(user_id, achievement_id, unlocked_at) VALUES(?, ?, ?)",
                    (user_id, achievement_id, int(time.time())),
                )
                await db.commit()
                return True
            except aiosqlite.IntegrityError:
                return False

    async def get_achievements(self, user_id: int) -> list[str]:
        async with self.connection() as db:
            rows = await (
                await db.execute("SELECT achievement_id FROM achievements WHERE user_id=?", (user_id,))
            ).fetchall()
            return [r["achievement_id"] for r in rows]

    async def set_equipped_title(self, user_id: int, title: str) -> None:
        await self.update_player(user_id, equipped_title=title)

    # ------------------------------------------------------------------ #
    #  Referral
    # ------------------------------------------------------------------ #
    async def set_referrer(self, user_id: int, referrer_id: int) -> None:
        player = await self.get_player(user_id)
        if player and not player["referred_by"] and referrer_id != user_id:
            await self.update_player(user_id, referred_by=referrer_id)
            async with self.connection() as db:
                await db.execute("UPDATE players SET referral_count = referral_count + 1 WHERE user_id=?", (referrer_id,))
                await db.commit()

    # ------------------------------------------------------------------ #
    #  Rob
    # ------------------------------------------------------------------ #
    async def rob_cooldown_remaining(self, user_id: int) -> int:
        player = await self.get_player(user_id)
        remaining = gd.ROB_COOLDOWN_SECONDS - (int(time.time()) - player["last_rob_at"])
        return max(0, remaining)

    async def do_rob(self, robber_id: int, target_id: int) -> dict:
        robber = await self.get_player(robber_id)
        target = await self.get_player(target_id)
        await self.update_player(robber_id, last_rob_at=int(time.time()))
        if random.random() > gd.ROB_SUCCESS_CHANCE:
            fine = min(gd.ROB_FAIL_FINE, robber["gold"])
            await self.update_player(robber_id, gold=robber["gold"] - fine)
            return {"success": False, "fine": fine}
        stolen = min(gd.ROB_MAX_STEAL, int(target["gold"] * gd.ROB_STEAL_PERCENT))
        stolen = max(0, min(stolen, target["gold"]))
        await self.update_player(target_id, gold=target["gold"] - stolen)
        await self.update_player(robber_id, gold=robber["gold"] + stolen)
        return {"success": True, "stolen": stolen}

    # ------------------------------------------------------------------ #
    #  Bank
    # ------------------------------------------------------------------ #
    async def bank_deposit(self, user_id: int, amount: int) -> bool:
        player = await self.get_player(user_id)
        if player["gold"] < amount or amount <= 0:
            return False
        await self.update_player(user_id, gold=player["gold"] - amount, bank_gold=player["bank_gold"] + amount)
        return True

    async def bank_withdraw(self, user_id: int, amount: int) -> bool:
        player = await self.get_player(user_id)
        if player["bank_gold"] < amount or amount <= 0:
            return False
        await self.update_player(user_id, gold=player["gold"] + amount, bank_gold=player["bank_gold"] - amount)
        return True

    async def apply_bank_interest(self) -> None:
        now = int(time.time())
        async with self.connection() as db:
            rows = await (
                await db.execute("SELECT user_id, bank_gold, last_interest_at FROM players WHERE bank_gold > 0")
            ).fetchall()
            for r in rows:
                elapsed_days = (now - (r["last_interest_at"] or now)) / 86400
                if elapsed_days >= 1:
                    interest = int(r["bank_gold"] * gd.BANK_DAILY_INTEREST * elapsed_days)
                    if interest > 0:
                        await db.execute(
                            "UPDATE players SET bank_gold = bank_gold + ?, last_interest_at=? WHERE user_id=?",
                            (interest, now, r["user_id"]),
                        )
            await db.commit()

    # ------------------------------------------------------------------ #
    #  Player's last-active group (for routing personal reminders there)
    # ------------------------------------------------------------------ #
    async def set_last_active_chat(self, user_id: int, chat_id: int) -> None:
        await self.update_player(user_id, last_active_chat_id=chat_id)

    async def due_hourly_reminders(self) -> list[aiosqlite.Row]:
        cutoff = int(time.time()) - 3600
        async with self.connection() as db:
            return await (
                await db.execute(
                    "SELECT user_id, first_name, last_active_chat_id FROM players "
                    "WHERE hourly_claimed_at <= ? AND hourly_reminded=0 AND reminders_enabled=1",
                    (cutoff,),
                )
            ).fetchall()

    async def due_daily_reminders(self) -> list[aiosqlite.Row]:
        cutoff = int(time.time()) - 86400
        async with self.connection() as db:
            return await (
                await db.execute(
                    "SELECT user_id, first_name, last_active_chat_id FROM players "
                    "WHERE daily_claimed_at <= ? AND daily_reminded=0 AND reminders_enabled=1",
                    (cutoff,),
                )
            ).fetchall()

    async def mark_daily_reminded(self, user_id: int) -> None:
        await self.update_player(user_id, daily_reminded=1)

    async def due_energy_reminders(self) -> list[aiosqlite.Row]:
        async with self.connection() as db:
            return await (
                await db.execute(
                    "SELECT user_id, first_name, energy, max_energy, last_active_chat_id FROM players "
                    "WHERE energy >= max_energy AND energy_reminded=0 AND reminders_enabled=1"
                )
            ).fetchall()



    # ------------------------------------------------------------------ #
    #  Guilds
    # ------------------------------------------------------------------ #
    async def create_guild(self, name: str, owner_id: int) -> int | None:
        async with self.connection() as db:
            try:
                cur = await db.execute(
                    "INSERT INTO guilds(name, owner_id, created_at) VALUES(?, ?, ?)",
                    (name, owner_id, int(time.time())),
                )
                await db.commit()
                guild_id = cur.lastrowid
            except aiosqlite.IntegrityError:
                return None
            await db.execute("UPDATE players SET guild_id=? WHERE user_id=?", (guild_id, owner_id))
            await db.commit()
            return guild_id

    async def get_guild(self, guild_id: int) -> aiosqlite.Row | None:
        async with self.connection() as db:
            return await (await db.execute("SELECT * FROM guilds WHERE guild_id=?", (guild_id,))).fetchone()

    async def get_guild_by_name(self, name: str) -> aiosqlite.Row | None:
        async with self.connection() as db:
            return await (
                await db.execute("SELECT * FROM guilds WHERE name=? COLLATE NOCASE", (name,))
            ).fetchone()

    async def join_guild(self, user_id: int, guild_id: int) -> None:
        await self.update_player(user_id, guild_id=guild_id)

    async def leave_guild(self, user_id: int) -> None:
        await self.update_player(user_id, guild_id=None)

    async def guild_members(self, guild_id: int) -> list[aiosqlite.Row]:
        async with self.connection() as db:
            return await (
                await db.execute(
                    "SELECT user_id, first_name, level FROM players WHERE guild_id=? ORDER BY level DESC", (guild_id,)
                )
            ).fetchall()

    async def guild_member_count(self, guild_id: int) -> int:
        async with self.connection() as db:
            row = await (
                await db.execute("SELECT COUNT(*) c FROM players WHERE guild_id=?", (guild_id,))
            ).fetchone()
            return int(row["c"])

    async def contribute_to_guild(self, user_id: int, guild_id: int, gold: int = 0, gems: int = 0, mana: int = 0, essence: int = 0) -> bool:
        player = await self.get_player(user_id)
        if player["gold"] < gold or player["gems"] < gems or player["mana_crystals"] < mana or player["essence_stones"] < essence:
            return False
        async with self.connection() as db:
            await db.execute(
                "UPDATE players SET gold=gold-?, gems=gems-?, mana_crystals=mana_crystals-?, essence_stones=essence_stones-? WHERE user_id=?",
                (gold, gems, mana, essence, user_id),
            )
            await db.execute(
                "UPDATE guilds SET vault_gold=vault_gold+?, vault_gems=vault_gems+?, vault_mana=vault_mana+?, vault_essence=vault_essence+? WHERE guild_id=?",
                (gold, gems, mana, essence, guild_id),
            )
            await db.commit()
        return True

    async def top_guilds(self, limit: int = 10) -> list[aiosqlite.Row]:
        async with self.connection() as db:
            return await (
                await db.execute(
                    "SELECT * FROM guilds ORDER BY (vault_gold + vault_gems*10 + vault_mana*5 + vault_essence*5) DESC LIMIT ?",
                    (limit,),
                )
            ).fetchall()

    # ------------------------------------------------------------------ #
    #  Lucky wheel
    # ------------------------------------------------------------------ #
    async def freespin_available(self, user_id: int) -> bool:
        player = await self.get_player(user_id)
        today = time.strftime("%Y-%m-%d", time.gmtime())
        return player["last_freespin_date"] != today

    async def use_freespin(self, user_id: int) -> None:
        today = time.strftime("%Y-%m-%d", time.gmtime())
        await self.update_player(user_id, last_freespin_date=today)

    # ------------------------------------------------------------------ #
    #  Coupons / redeem codes
    # ------------------------------------------------------------------ #
    async def create_coupon(self, code: str, gold: int = 0, gems: int = 0, mana: int = 0, essence: int = 0, max_uses: int = 1) -> None:
        async with self.connection() as db:
            await db.execute(
                "INSERT INTO coupons(code, gold, gems, mana, essence, max_uses, created_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(code) DO UPDATE SET gold=excluded.gold, gems=excluded.gems, mana=excluded.mana, "
                "essence=excluded.essence, max_uses=excluded.max_uses",
                (code.upper(), gold, gems, mana, essence, max_uses, int(time.time())),
            )
            await db.commit()

    async def redeem_coupon(self, code: str, user_id: int) -> dict | None:
        code = code.upper().strip()
        async with self.connection() as db:
            coupon = await (await db.execute("SELECT * FROM coupons WHERE code=?", (code,))).fetchone()
            if not coupon:
                return None
            if coupon["used_count"] >= coupon["max_uses"]:
                return None
            already = await (
                await db.execute("SELECT 1 FROM coupon_redemptions WHERE code=? AND user_id=?", (code, user_id))
            ).fetchone()
            if already:
                return None
            await db.execute("INSERT INTO coupon_redemptions(code, user_id) VALUES(?, ?)", (code, user_id))
            await db.execute("UPDATE coupons SET used_count = used_count + 1 WHERE code=?", (code,))
            await db.commit()
            return {"gold": coupon["gold"], "gems": coupon["gems"], "mana": coupon["mana"], "essence": coupon["essence"]}

    # ------------------------------------------------------------------ #
    #  Custom (admin-added) characters
    # ------------------------------------------------------------------ #
    async def add_custom_character(self, character_id: str, name: str, rarity: str, atk_bonus: int, hp_bonus: int, photo_file_id: str = "", rate: float = 0.02) -> None:
        async with self.connection() as db:
            await db.execute(
                "INSERT INTO custom_characters(character_id, name, rarity, atk_bonus, hp_bonus, rate, photo_file_id, added_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(character_id) DO UPDATE SET name=excluded.name, rarity=excluded.rarity, "
                "atk_bonus=excluded.atk_bonus, hp_bonus=excluded.hp_bonus, rate=excluded.rate, photo_file_id=excluded.photo_file_id",
                (character_id, name, rarity, atk_bonus, hp_bonus, rate, photo_file_id, int(time.time())),
            )
            await db.commit()

    async def all_custom_characters(self) -> list[aiosqlite.Row]:
        async with self.connection() as db:
            return await (await db.execute("SELECT * FROM custom_characters")).fetchall()

    # ------------------------------------------------------------------ #
    #  Generated image cache (avoids re-billing Gemini for the same asset)
    # ------------------------------------------------------------------ #
    async def get_cached_image(self, cache_key: str) -> str | None:
        async with self.connection() as db:
            row = await (
                await db.execute("SELECT file_id FROM generated_images WHERE cache_key=?", (cache_key,))
            ).fetchone()
            return row["file_id"] if row else None

    async def cache_image(self, cache_key: str, file_id: str) -> None:
        async with self.connection() as db:
            await db.execute(
                "INSERT INTO generated_images(cache_key, file_id, created_at) VALUES(?, ?, ?) "
                "ON CONFLICT(cache_key) DO UPDATE SET file_id=excluded.file_id",
                (cache_key, file_id, int(time.time())),
            )
            await db.commit()



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
