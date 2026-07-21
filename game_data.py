"""
All game content lives here so future arcs/characters/weapons can be added
without touching bot logic. Everything here is original descriptive text
written for this game — inspired by the general Solo Leveling premise
(ranks, the System, shadow extraction, named characters/items as facts),
not copied from the novel/manhwa/anime.
"""
from __future__ import annotations

# ------------------------------------------------------------------ #
#  Weapons
# ------------------------------------------------------------------ #
WEAPONS: dict[str, dict] = {
    "rusty_dagger": {
        "name": "Rusty Dagger",
        "atk": 2,
        "rarity": "Common",
        "desc": "A worn blade you've carried since your first gate. Barely holds an edge.",
    },
    "novices_dagger": {
        "name": "Novice Hunter's Dagger",
        "atk": 6,
        "rarity": "Uncommon",
        "desc": "Standard Association-issue steel. A real upgrade from scrap metal.",
        "unlock": "arc1_complete",
    },
    "knight_killer": {
        "name": "Knight Killer",
        "atk": 18,
        "rarity": "Rare",
        "desc": "Forged to punch through knight-class armor. Rumored to hum before a kill.",
        "unlock": "arc2_complete",
    },
}
STARTING_WEAPON = "rusty_dagger"

# ------------------------------------------------------------------ #
#  Monsters
# ------------------------------------------------------------------ #
MONSTERS: dict[str, dict] = {
    "stone_soldier_1": {
        "name": "Cartenon Stone Soldier",
        "hp": 45, "atk": 6, "defense": 2,
        "xp": 20, "gold": 15,
        "intro": "A statue's cracked eyes flare an unnatural blue and it steps off its pedestal.",
        "boss": False,
    },
    "stone_soldier_2": {
        "name": "Cartenon Elite Guardian",
        "hp": 90, "atk": 11, "defense": 4,
        "xp": 45, "gold": 35,
        "intro": "A second, larger guardian rises — this one's blade is already drawn.",
        "boss": True,
    },
}

# ------------------------------------------------------------------ #
#  Story — Arc 1: Double Dungeon
#  Each node: text, then either "choices" (list of {text, next}) or
#  "battle" (monster_id -> on victory goes to "next").
# ------------------------------------------------------------------ #
STORY_ARCS: dict[str, dict] = {
    "arc1": {
        "title": "Arc 1 — Double Dungeon",
        "start_node": "n1",
        "nodes": {
            "n1": {
                "text": (
                    "🌀 <b>Double Dungeon</b>\n\n"
                    "Another E-rank gate. Another routine clear — or so your party thought. "
                    "Halfway through, the floor gives way beneath you all, dropping the group "
                    "into a second, hidden dungeon buried beneath the first.\n\n"
                    "Torches flicker to life on their own. Ahead, a chamber holds two towering "
                    "stone statues flanking a dust-covered altar."
                ),
                "choices": [
                    {"text": "🔍 Investigate the altar", "next": "n2"},
                    {"text": "⚠️ Warn the others to stay back", "next": "n1b"},
                ],
            },
            "n1b": {
                "text": (
                    "You call out a warning, but curiosity wins — half the party is already "
                    "moving toward the altar. Whatever is about to happen, you're in it now."
                ),
                "choices": [{"text": "➡️ Continue", "next": "n2"}],
            },
            "n2": {
                "text": (
                    "The moment fingers brush the altar's surface, both statues' eyes ignite. "
                    "Stone grinds against stone as one guardian steps down to block the only exit."
                ),
                "battle": "stone_soldier_1",
                "next": "n3",
            },
            "n3": {
                "text": (
                    "The first guardian crumbles to rubble — but the tremor wakes its twin. "
                    "The second statue's blade scrapes free of centuries of dust, and this one "
                    "moves like it was built to kill, not guard."
                ),
                "battle": "stone_soldier_2",
                "next": "n4",
            },
            "n4": {
                "text": (
                    "As the second guardian falls, your vision blurs. Pain you can't place spreads "
                    "through your chest. Then — silence. A pale rectangular window hangs in the air "
                    "in front of you, visible to no one else in the room.\n\n"
                    "<code>[A hidden quest has been discovered.]</code>\n"
                    "<code>[Would you like to accept the Job Change Quest?]</code>"
                ),
                "choices": [
                    {"text": "✅ Accept", "next": "n5"},
                    {"text": "❌ Not yet", "next": "n4b"},
                ],
            },
            "n4b": {
                "text": (
                    "You hesitate — and the window flickers a warning before fading. "
                    "It doesn't feel like something you can put off forever."
                ),
                "choices": [{"text": "↩️ Reconsider", "next": "n4"}],
            },
            "n5": {
                "text": (
                    "The window dissolves into light. When your eyes adjust, your party is gone — "
                    "and so is the dungeon. You're standing alone in white space.\n\n"
                    "<code>[System has recognized you as a Player.]</code>\n"
                    "<code>[Rewards granted.]</code>\n\n"
                    "🎉 <b>Arc 1 Complete — Double Dungeon</b>\n"
                    "Your journey as a Player has begun. More of the story unlocks soon."
                ),
                "reward": {"xp": 80, "gold": 60, "unlock_weapon": "novices_dagger", "complete_arc": "arc1"},
                "choices": [],
            },
        },
    },
}

# ------------------------------------------------------------------ #
#  Shadow Extraction (gacha) pool
# ------------------------------------------------------------------ #
SHADOWS: dict[str, dict] = {
    "shadow_soldier": {"name": "Ordinary Shadow Soldier", "rarity": "Common", "rate": 0.55, "atk_bonus": 3},
    "shadow_knight": {"name": "Shadow Knight", "rarity": "Uncommon", "rate": 0.25, "atk_bonus": 8},
    "iron": {"name": "Iron", "rarity": "Rare", "rate": 0.12, "atk_bonus": 15},
    "tank": {"name": "Tank", "rarity": "Rare", "rate": 0.05, "atk_bonus": 18},
    "igris": {"name": "Igris", "rarity": "Legendary", "rate": 0.03, "atk_bonus": 40},
}
EXTRACTION_COST_GEMS = 5

# ------------------------------------------------------------------ #
#  Playable Characters (rolled via gacha, used in battle as your avatar)
# ------------------------------------------------------------------ #
CHARACTERS: dict[str, dict] = {
    "rookie_hunter": {"name": "Rookie Hunter", "rarity": "Common", "rate": 0.45, "base_atk": 5, "base_hp": 20},
    "blade_dancer": {"name": "Blade Dancer", "rarity": "Uncommon", "rate": 0.25, "base_atk": 10, "base_hp": 35},
    "mage_apprentice": {"name": "Mage Apprentice", "rarity": "Uncommon", "rate": 0.15, "base_atk": 12, "base_hp": 25},
    "steel_knight": {"name": "Steel Knight", "rarity": "Rare", "rate": 0.10, "base_atk": 18, "base_hp": 60},
    "shadow_disciple": {"name": "Shadow Disciple", "rarity": "Epic", "rate": 0.04, "base_atk": 28, "base_hp": 50},
    "monarch_heir": {"name": "Monarch's Heir", "rarity": "Legendary", "rate": 0.01, "base_atk": 45, "base_hp": 90},
}
CHARACTER_ROLL_COST_GOLD = 100

# ------------------------------------------------------------------ #
#  Gates — repeatable farming battles, rank-gated by cooldown
# ------------------------------------------------------------------ #
GATE_MONSTERS: dict[str, dict] = {
    "goblin_grunt": {"name": "Goblin Grunt", "hp": 25, "atk": 4, "defense": 1, "xp": 8, "gold": 8},
    "orc_raider": {"name": "Orc Raider", "hp": 50, "atk": 7, "defense": 3, "xp": 18, "gold": 15},
    "armored_ogre": {"name": "Armored Ogre", "hp": 90, "atk": 11, "defense": 6, "xp": 35, "gold": 28},
    "blood_wraith": {"name": "Blood Wraith", "hp": 140, "atk": 16, "defense": 8, "xp": 55, "gold": 45},
    "frost_giant": {"name": "Frost Giant", "hp": 220, "atk": 22, "defense": 12, "xp": 90, "gold": 70},
    "red_gate_horror": {"name": "Red Gate Horror", "hp": 300, "atk": 28, "defense": 14, "xp": 150, "gold": 120},
}

GATES: dict[str, dict] = {
    "e_gate": {"name": "E-Rank Gate", "monster": "goblin_grunt", "resource": "mana_crystals", "resource_amount": 3, "cooldown_min": 30},
    "d_gate": {"name": "D-Rank Gate", "monster": "orc_raider", "resource": "mana_crystals", "resource_amount": 6, "cooldown_min": 45},
    "c_gate": {"name": "C-Rank Gate", "monster": "armored_ogre", "resource": "essence_stones", "resource_amount": 2, "cooldown_min": 60},
    "b_gate": {"name": "B-Rank Gate", "monster": "blood_wraith", "resource": "essence_stones", "resource_amount": 4, "cooldown_min": 90},
    "a_gate": {"name": "A-Rank Gate", "monster": "frost_giant", "resource": "essence_stones", "resource_amount": 6, "cooldown_min": 120},
    "red_gate": {"name": "🔴 Red Gate", "monster": "red_gate_horror", "resource": "essence_stones", "resource_amount": 15, "cooldown_min": 120},
}

# ------------------------------------------------------------------ #
#  Missions
# ------------------------------------------------------------------ #
DAILY_REWARD = {"gold": 80, "gems": 5, "mana_crystals": 5}
HOURLY_REWARD = {"gold": 20, "mana_crystals": 2}

# ------------------------------------------------------------------ #
#  Shop (NPC — gold for gear; player marketplace is a future phase)
# ------------------------------------------------------------------ #
SHOP_ITEMS: dict[str, dict] = {
    "novices_dagger": {"cost_gold": 150},
    "knight_killer": {"cost_gold": 500},
}

# ------------------------------------------------------------------ #
#  Quiz
# ------------------------------------------------------------------ #
QUIZ_QUESTIONS: list[dict] = [
    {"q": "What is the lowest hunter rank in the Association's ranking system?", "options": ["E-Rank", "S-Rank", "D-Rank", "A-Rank"], "answer": 0, "reward": 10},
    {"q": "What type of gate hid a second, more dangerous dungeon inside it?", "options": ["S-Rank Gate", "Red Gate", "Double Dungeon", "Instant Dungeon"], "answer": 2, "reward": 10},
    {"q": "What mysterious system began guiding the protagonist after a near-death experience?", "options": ["The Ledger", "The System", "The Codex", "The Directive"], "answer": 1, "reward": 10},
    {"q": "What ability lets a hunter summon fallen enemies to fight for them?", "options": ["Shadow Extraction", "Soul Binding", "Mana Fusion", "Spirit Call"], "answer": 0, "reward": 15},
    {"q": "What do hunters call the organization that manages gates and rankings?", "options": ["The Guild Union", "The Hunter Association", "The Gate Council", "The Awakened Bureau"], "answer": 1, "reward": 10},
    {"q": "What is a sudden, unscheduled gate appearance called?", "options": ["Red Gate", "Flash Gate", "Wild Gate", "Break Gate"], "answer": 0, "reward": 15},
    {"q": "Which stat generally governs a hunter's physical striking power?", "options": ["Intelligence", "Strength", "Perception", "Vitality"], "answer": 1, "reward": 10},
    {"q": "What term describes monsters or bosses guarding a dungeon's deepest chamber?", "options": ["Gate Keepers", "Dungeon Bosses", "Floor Guardians", "Rank Sentinels"], "answer": 1, "reward": 10},
    {"q": "What do hunters call unclaimed loot left behind after clearing a dungeon?", "options": ["Gate Drops", "Dungeon Rewards", "Magic Stones", "Clear Bonus"], "answer": 2, "reward": 10},
    {"q": "What term is used for a hunter's combat class after a job change?", "options": ["Job", "Path", "Role", "Class"], "answer": 0, "reward": 15},
]
