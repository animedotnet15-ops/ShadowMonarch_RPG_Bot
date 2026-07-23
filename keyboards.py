from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="📖 Continue Story", callback_data="menu:story")],
        [InlineKeyboardButton(text="🚪 Gates", callback_data="menu:gates"),
         InlineKeyboardButton(text="🎲 Roll Character", callback_data="menu:roll")],
        [InlineKeyboardButton(text="🧙 My Characters", callback_data="menu:characters")],
        [InlineKeyboardButton(text="👤 Profile", callback_data="menu:profile"),
         InlineKeyboardButton(text="🎒 Inventory", callback_data="menu:inventory")],
        [InlineKeyboardButton(text="🌑 Shadow Army", callback_data="menu:shadows"),
         InlineKeyboardButton(text="🔮 Extract Shadow", callback_data="menu:summon")],
        [InlineKeyboardButton(text="📅 Daily", callback_data="menu:daily"),
         InlineKeyboardButton(text="⏰ Hourly", callback_data="menu:hourly")],
        [InlineKeyboardButton(text="🏪 Shop", callback_data="menu:shop"),
         InlineKeyboardButton(text="🗃️ Vault", callback_data="menu:vault")],
        [InlineKeyboardButton(text="🎡 Lucky Wheel", callback_data="menu:wheel"),
         InlineKeyboardButton(text="🏯 Guild", callback_data="menu:guild")],
        [InlineKeyboardButton(text="❓ Quiz", callback_data="menu:quiz"),
         InlineKeyboardButton(text="🏆 Leaderboard", callback_data="menu:leaderboard")],
        [InlineKeyboardButton(text="📊 Group Activity", callback_data="menu:activity")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def gates_keyboard(gate_status: list[tuple[str, str, int]]) -> InlineKeyboardMarkup:
    """gate_status: list of (gate_id, label_text, seconds_remaining)."""
    rows = []
    for gate_id, label, remaining in gate_status:
        text = label if remaining <= 0 else f"🔒 {label}"
        rows.append([InlineKeyboardButton(text=text, callback_data=f"gate:{gate_id}")])
    rows.append([InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def gate_battle_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="⚔️ Attack", callback_data="gatebattle:attack")],
        [InlineKeyboardButton(text="🛡️ Defend", callback_data="gatebattle:defend")],
        [InlineKeyboardButton(text="🏃 Flee", callback_data="gatebattle:flee")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def characters_keyboard(owned: list, characters: dict, active: str) -> InlineKeyboardMarkup:
    rows = []
    for row in owned:
        info = characters.get(row["character_id"], {})
        label = f"{'✅ ' if row['character_id'] == active else ''}{info.get('name', row['character_id'])} x{row['count']}"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"setactive:{row['character_id']}")])
    rows.append([InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def shop_keyboard(items: dict, weapons: dict) -> InlineKeyboardMarkup:
    rows = []
    for item_id, info in items.items():
        w = weapons.get(item_id, {})
        rows.append([InlineKeyboardButton(text=f"{w.get('name', item_id)} — 💰{info['cost_gold']}", callback_data=f"buy:{item_id}")])
    rows.append([InlineKeyboardButton(text="🎯 Buy a Character (Mana)", callback_data="menu:buychar")])
    rows.append([InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def buy_character_keyboard(pool: dict, mana_cost_fn) -> InlineKeyboardMarkup:
    rows = []
    for char_id, info in pool.items():
        cost = mana_cost_fn(info["rarity"])
        rows.append([InlineKeyboardButton(text=f"{info['name']} ({info['rarity']}) — 🔷{cost}", callback_data=f"buychar:{char_id}")])
    rows.append([InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pvp_challenge_keyboard(battle_id: str) -> InlineKeyboardMarkup:
    rows = [[
        InlineKeyboardButton(text="⚔️ Accept Duel", callback_data=f"pvp:{battle_id}:accept"),
        InlineKeyboardButton(text="❌ Decline", callback_data=f"pvp:{battle_id}:decline"),
    ]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pvp_battle_keyboard(battle_id: str) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="⚔️ Attack", callback_data=f"pvp:{battle_id}:attack")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def story_choices_keyboard(choices: list[dict]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=c["text"], callback_data=f"story:{c['next']}")] for c in choices]
    if not rows:
        rows = [[InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu:main")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def battle_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="⚔️ Attack", callback_data="battle:attack")],
        [InlineKeyboardButton(text="🛡️ Defend", callback_data="battle:defend")],
        [InlineKeyboardButton(text="🏃 Flee", callback_data="battle:flee")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def quiz_keyboard(options: list[str], idx: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=opt, callback_data=f"quiz:{idx}:{i}")] for i, opt in enumerate(options)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def inventory_keyboard(owned: list[str], weapons: dict, equipped: str) -> InlineKeyboardMarkup:
    rows = []
    for wid in owned:
        info = weapons.get(wid, {})
        label = f"{'✅ ' if wid == equipped else ''}{info.get('name', wid)} (ATK {info.get('atk', 0)})"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"equip:{wid}")])
    rows.append([InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def stat_allocation_keyboard(points: int) -> InlineKeyboardMarkup:
    if points <= 0:
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu:main")]])
    rows = [
        [InlineKeyboardButton(text="💪 STR", callback_data="stat:str"),
         InlineKeyboardButton(text="🏃 AGI", callback_data="stat:agi")],
        [InlineKeyboardButton(text="🧠 INT", callback_data="stat:intel"),
         InlineKeyboardButton(text="❤️ VIT", callback_data="stat:vit")],
        [InlineKeyboardButton(text="👁️ PER", callback_data="stat:per")],
        [InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def main_menu_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu:main")]])


# ------------------------------------------------------------------ #
#  Bot settings dashboard (owner only)
# ------------------------------------------------------------------ #
def settings_main_keyboard(ai_images_enabled: bool = False, bot_enabled: bool = True) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="✍️ Welcome Text", callback_data="set:welcometext")],
        [InlineKeyboardButton(text="🖼️ Welcome Photo", callback_data="set:welcomephoto")],
        [InlineKeyboardButton(text="🎬 Start Sticker", callback_data="set:startsticker")],
        [InlineKeyboardButton(text="👑 Owner Button", callback_data="set:ownerbtn"),
         InlineKeyboardButton(text="🥷 Admin Button", callback_data="set:adminbtn")],
        [InlineKeyboardButton(text="🤝 Support Button", callback_data="set:supportbtn"),
         InlineKeyboardButton(text="🌐 Website Button", callback_data="set:websitebtn")],
        [InlineKeyboardButton(text="✏️ Button Labels", callback_data="set:labels")],
        [InlineKeyboardButton(text="✨ Premium Emoji", callback_data="set:premiumemoji")],
        [InlineKeyboardButton(
            text=f"🎨 AI Images: {'🟢 ON' if ai_images_enabled else '🔴 OFF'}",
            callback_data="set:toggleaiimages"
        )],
        [InlineKeyboardButton(
            text=f"🤖 Bot: {'🟢 ON' if bot_enabled else '🔴 OFF'}",
            callback_data="set:togglebot"
        )],
        [InlineKeyboardButton(text="👀 Preview /start", callback_data="set:preview")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def button_labels_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="👑 Owner Label", callback_data="set:label:owner"),
         InlineKeyboardButton(text="🥷 Admin Label", callback_data="set:label:admin")],
        [InlineKeyboardButton(text="🤝 Support Label", callback_data="set:label:support"),
         InlineKeyboardButton(text="🌐 Website Label", callback_data="set:label:website")],
        [InlineKeyboardButton(text="🌑 Enter-System Label", callback_data="set:label:enter")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="set:main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_to_settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Back", callback_data="set:main")]])


def wheel_keyboard(can_freespin: bool) -> InlineKeyboardMarkup:
    rows = []
    if can_freespin:
        rows.append([InlineKeyboardButton(text="🎡 Free Daily Spin", callback_data="wheel:free")])
    rows.append([InlineKeyboardButton(text="💎 Paid Spin (10 gems)", callback_data="wheel:paid")])
    rows.append([InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def guild_none_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🏯 Create Guild", callback_data="guild:create")],
        [InlineKeyboardButton(text="🔎 Browse Guilds", callback_data="guild:browse")],
        [InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def guild_joined_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="💰 Contribute Gold", callback_data="guild:contribute:gold"),
         InlineKeyboardButton(text="💎 Contribute Gems", callback_data="guild:contribute:gems")],
        [InlineKeyboardButton(text="👥 Members", callback_data="guild:members")],
        [InlineKeyboardButton(text="🏆 Guild Leaderboard", callback_data="guild:top")],
        [InlineKeyboardButton(text="🚪 Leave Guild", callback_data="guild:leave")],
        [InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def wild_gate_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⚔️ Attack!", callback_data="wildgate:attack")]])


def group_quiz_keyboard(chat_id: int, options: list) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=opt, callback_data=f"gquiz:{chat_id}:{i}")] for i, opt in enumerate(options)]
    return InlineKeyboardMarkup(inline_keyboard=rows)
