from __future__ import annotations

import asyncio
import html
import logging
import random

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from config import config
from database import database
import game_data as gd
import keyboards as kb

LOG = logging.getLogger("shadowmonarch")

bot = Bot(token=config.bot_token, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
router = Router()
dp.include_router(router)

WELCOME_TEXT = (
    "🌑 <b>Welcome to the System, {name}.</b>\n\n"
    "You were an ordinary E-rank hunter — until a routine gate hid something far worse "
    "beneath it. Something changed you down there. Something is still watching.\n\n"
    "Climb the ranks. Master your weapons. Build a Shadow Army that answers to no one but you.\n\n"
    "<i>Your story starts now.</i>"
)

AWAITING: dict[int, str] = {}  # user_id -> setting key being edited


def stat_col(stat: str) -> str:
    return {"str": "str_stat", "agi": "agi_stat", "intel": "intel_stat", "vit": "vit_stat", "per": "per_stat"}[stat]


async def player_attack_power(user_id: int) -> int:
    player = await database.get_player(user_id)
    weapon = gd.WEAPONS.get(player["equipped_weapon"], gd.WEAPONS[gd.STARTING_WEAPON])
    char = gd.CHARACTERS.get(player["active_character"], {})
    shadow_bonus = await database.shadow_army_atk_bonus(user_id)
    return weapon["atk"] + char.get("base_atk", 0) + player["str_stat"] // 3 + shadow_bonus


async def render_profile(user_id: int) -> tuple[str, object]:
    p = await database.get_player(user_id)
    weapon = gd.WEAPONS.get(p["equipped_weapon"], {})
    char = gd.CHARACTERS.get(p["active_character"])
    char_line = f"🧙 Character: {char['name']} ({char['rarity']})\n" if char else "🧙 Character: — (roll one!)\n"
    text = (
        f"👤 <b>{p['first_name']}</b> — Rank {p['rank']} | Level {p['level']}\n\n"
        f"✨ XP: {p['xp']}/{p['xp_next']}\n"
        f"❤️ HP: {p['hp']}/{p['max_hp']}\n"
        f"{char_line}"
        f"⚔️ Weapon: {weapon.get('name', '—')} (ATK {weapon.get('atk', 0)})\n\n"
        f"💪 STR: {p['str_stat']}   🏃 AGI: {p['agi_stat']}\n"
        f"🧠 INT: {p['intel_stat']}   ❤️ VIT: {p['vit_stat']}\n"
        f"👁️ PER: {p['per_stat']}\n\n"
        f"💰 Gold: {p['gold']}   💎 Gems: {p['gems']}\n"
        f"🔷 Mana Crystals: {p['mana_crystals']}   🔶 Essence Stones: {p['essence_stones']}\n"
    )
    if p["stat_points"] > 0:
        text += f"\n🆙 <b>{p['stat_points']} stat point(s) available!</b> Tap a stat to increase it."
    return text, kb.stat_allocation_keyboard(p["stat_points"])


async def render_story_node(user_id: int) -> tuple[str, object]:
    p = await database.get_player(user_id)
    arc = gd.STORY_ARCS.get(p["story_arc"])
    if not arc:
        return "📖 <b>No further story is available yet.</b> More arcs are coming soon!", kb.main_menu_button()
    node = arc["nodes"].get(p["story_node"])
    if not node:
        return "📖 <b>No further story is available yet.</b> More arcs are coming soon!", kb.main_menu_button()

    if "battle" in node:
        monster_id = node["battle"]
        monster = gd.MONSTERS[monster_id]
        battle = await database.get_battle(user_id)
        if not battle:
            await database.start_battle(user_id, monster_id, monster["hp"], node["next"])
        text = f"⚔️ <b>{monster['name']} appears!</b>\n<i>{monster['intro']}</i>\n\n{await render_battle_status(user_id)}"
        return text, kb.battle_keyboard()

    if "reward" in node and node["reward"]:
        reward = node["reward"]
        if reward.get("complete_arc") not in await database.completed_arcs(user_id):
            summary = await database.add_gold_xp(user_id, gold=reward.get("gold", 0), xp=reward.get("xp", 0))
            if reward.get("unlock_weapon"):
                await database.grant_weapon(user_id, reward["unlock_weapon"])
            if reward.get("complete_arc"):
                await database.complete_arc(user_id, reward["complete_arc"])
            extra = f"\n\n💰 +{reward.get('gold', 0)} Gold  ✨ +{reward.get('xp', 0)} XP"
            if reward.get("unlock_weapon"):
                extra += f"\n🗡️ New weapon unlocked: <b>{gd.WEAPONS[reward['unlock_weapon']]['name']}</b>"
            if summary.get("levels_gained"):
                extra += f"\n🆙 <b>Level up! Now level {summary['level']} (Rank {summary['rank']})</b>"
            node_text = node["text"] + extra
        else:
            node_text = node["text"]
        return node_text, kb.story_choices_keyboard(node.get("choices", []))

    return node["text"], kb.story_choices_keyboard(node.get("choices", []))


async def render_battle_status(user_id: int) -> str:
    battle = await database.get_battle(user_id)
    player = await database.get_player(user_id)
    monster = gd.MONSTERS[battle["monster_id"]]
    return (
        f"👤 You: {player['hp']}/{player['max_hp']} HP\n"
        f"👹 {monster['name']}: {battle['monster_hp']}/{monster['hp']} HP"
    )


async def play_start_animation(message: Message, name: str) -> None:
    m = html.escape(name)
    msg = await message.answer(f"Hᴇʏ {m} 👋...")
    await asyncio.sleep(1)
    await msg.edit_text("Sᴛᴀʀᴛ... !!")
    await asyncio.sleep(1)
    await msg.edit_text("Sᴛᴀʀᴛɪɴɢ...‼️")
    await asyncio.sleep(1)
    await msg.edit_text(f"🔑 {m} sʏɴᴄɪɴɢ ᴡɪᴛʜ ᴛʜᴇ Sʏsᴛᴇᴍ...")
    await asyncio.sleep(1)

    sticker_id = await database.get_setting("start_sticker", "")
    if sticker_id:
        try:
            sticker_msg = await message.answer_sticker(sticker_id)
            await asyncio.sleep(1)
            await sticker_msg.delete()
        except Exception:
            pass
    try:
        await msg.delete()
    except Exception:
        pass


async def send_welcome(message: Message, name: str, extra_text: str = "") -> None:
    text = await database.get_setting("welcome_text", WELCOME_TEXT)
    text = text.replace("{name}", html.escape(name))
    if extra_text:
        text = extra_text + "\n\n" + text
    photo_id = await database.get_setting("welcome_photo", "")

    rows = []
    owner_username = await database.get_setting("owner_username", "")
    admin_username = await database.get_setting("admin_username", "")
    support_link = await database.get_setting("support_link", "")
    website_link = await database.get_setting("website_link", "")

    row1 = []
    if owner_username:
        row1.append(InlineKeyboardButton(text="👑 Owner", url=f"https://t.me/{owner_username.lstrip('@')}"))
    if admin_username:
        row1.append(InlineKeyboardButton(text="🥷 Admin", url=f"https://t.me/{admin_username.lstrip('@')}"))
    if row1:
        rows.append(row1)
    row2 = []
    if support_link:
        row2.append(InlineKeyboardButton(text="🤝 Support", url=support_link))
    if website_link:
        row2.append(InlineKeyboardButton(text="🌐 Website", url=website_link))
    if row2:
        rows.append(row2)
    rows.append([InlineKeyboardButton(text="🌑 Enter the System", callback_data="menu:main")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=rows)

    try:
        if photo_id:
            await message.answer_photo(photo_id, caption=text, reply_markup=keyboard)
        else:
            await message.answer(text, reply_markup=keyboard)
    except TelegramBadRequest:
        # Custom welcome text had broken HTML — fall back to plain text so /start never crashes
        if photo_id:
            await message.answer_photo(photo_id, caption=text, reply_markup=keyboard, parse_mode=None)
        else:
            await message.answer(text, reply_markup=keyboard, parse_mode=None)


# ------------------------------------------------------------------ #
#  /start
# ------------------------------------------------------------------ #
@router.message(Command("start"))
async def start_handler(message: Message):
    user = message.from_user
    player = await database.get_player(user.id)
    is_new = player is None
    await database.get_or_create_player(user.id, user.first_name or "Hunter")
    name = user.first_name or "Hunter"

    if is_new:
        await play_start_animation(message, name)
        await send_welcome(message, name)
    else:
        await message.answer(f"🌑 Welcome back, {html.escape(name)}.", reply_markup=kb.main_menu_keyboard())


@router.callback_query(F.data == "menu:main")
async def menu_main_cb(cb: CallbackQuery):
    await cb.answer()
    await cb.message.edit_text(f"🌑 <b>Main Menu</b>\n\nWhat would you like to do, {html.escape(cb.from_user.first_name or 'Hunter')}?", reply_markup=kb.main_menu_keyboard())


@router.callback_query(F.data == "menu:story")
async def menu_story_cb(cb: CallbackQuery):
    await database.get_or_create_player(cb.from_user.id, cb.from_user.first_name or "Hunter")
    await cb.answer()
    text, markup = await render_story_node(cb.from_user.id)
    await cb.message.edit_text(text, reply_markup=markup)


@router.callback_query(F.data.startswith("story:"))
async def story_advance_cb(cb: CallbackQuery):
    user_id = cb.from_user.id
    next_node = cb.data.split(":", 1)[1]
    p = await database.get_player(user_id)
    await database.set_story_position(user_id, p["story_arc"], next_node)
    await cb.answer()
    text, markup = await render_story_node(user_id)
    await cb.message.edit_text(text, reply_markup=markup)


# ------------------------------------------------------------------ #
#  Battle
# ------------------------------------------------------------------ #
@router.callback_query(F.data.startswith("battle:"))
async def battle_action_cb(cb: CallbackQuery):
    user_id = cb.from_user.id
    action = cb.data.split(":", 1)[1]
    battle = await database.get_battle(user_id)
    if not battle:
        await cb.answer("No active battle.", show_alert=True)
        return
    player = await database.get_player(user_id)
    monster = gd.MONSTERS[battle["monster_id"]]

    if action == "flee":
        await database.end_battle(user_id)
        await cb.answer("You fled the fight.")
        await cb.message.edit_text("🏃 <b>You disengaged and retreated.</b>", reply_markup=kb.main_menu_button())
        return

    await cb.answer()
    log_lines = []
    monster_hp = battle["monster_hp"]

    if action == "attack":
        atk = await player_attack_power(user_id)
        dmg = max(1, atk - monster["defense"] + random.randint(-2, 3))
        monster_hp -= dmg
        log_lines.append(f"⚔️ You strike for <b>{dmg}</b> damage.")
    elif action == "defend":
        atk = await player_attack_power(user_id)
        dmg = max(1, (atk // 2) - monster["defense"])
        monster_hp -= dmg
        log_lines.append(f"🛡️ You brace and counter for <b>{dmg}</b> damage.")

    if monster_hp <= 0:
        xp, gold = monster["xp"], monster["gold"]
        summary = await database.add_gold_xp(user_id, gold=gold, xp=xp)
        await database.end_battle(user_id)
        next_node = battle["next_node"]
        p = await database.get_player(user_id)
        await database.set_story_position(user_id, p["story_arc"], next_node)
        text = (
            f"🏆 <b>{monster['name']} defeated!</b>\n\n"
            f"💰 +{gold} Gold   ✨ +{xp} XP"
        )
        if summary.get("levels_gained"):
            text += f"\n🆙 <b>Level up! Now level {summary['level']} (Rank {summary['rank']})</b>"
        story_text, story_markup = await render_story_node(user_id)
        await cb.message.edit_text(f"{text}\n\n{story_text}", reply_markup=story_markup)
        return

    # Monster retaliates
    reduction = 0.5 if action == "defend" else 1.0
    player_def = player["vit_stat"] // 5
    monster_dmg = max(1, int((monster["atk"] - player_def) * reduction) + random.randint(-1, 2))
    new_hp = max(0, player["hp"] - monster_dmg)
    log_lines.append(f"👹 {monster['name']} hits you for <b>{monster_dmg}</b> damage.")

    await database.update_battle_hp(user_id, monster_hp)

    if new_hp <= 0:
        await database.update_player(user_id, hp=1)
        await database.end_battle(user_id)
        await cb.message.edit_text(
            "💀 <b>You were knocked unconscious!</b>\nA rescue team pulls you out just in time. "
            "You wake up back at the Association, HP restored to 1.\n\n<i>Rest up and try again.</i>",
            reply_markup=kb.main_menu_button(),
        )
        return

    await database.update_player(user_id, hp=new_hp)
    status = await render_battle_status(user_id)
    await cb.message.edit_text("\n".join(log_lines) + f"\n\n{status}", reply_markup=kb.battle_keyboard())


# ------------------------------------------------------------------ #
#  Profile / stat allocation
# ------------------------------------------------------------------ #
@router.callback_query(F.data == "menu:profile")
async def menu_profile_cb(cb: CallbackQuery):
    await database.get_or_create_player(cb.from_user.id, cb.from_user.first_name or "Hunter")
    await cb.answer()
    text, markup = await render_profile(cb.from_user.id)
    await cb.message.edit_text(text, reply_markup=markup)


@router.callback_query(F.data.startswith("stat:"))
async def stat_allocate_cb(cb: CallbackQuery):
    stat = cb.data.split(":", 1)[1]
    ok = await database.spend_stat_point(cb.from_user.id, stat)
    await cb.answer("✅ Stat increased!" if ok else "⚠️ No stat points available.")
    text, markup = await render_profile(cb.from_user.id)
    await cb.message.edit_text(text, reply_markup=markup)


# ------------------------------------------------------------------ #
#  Inventory / equip
# ------------------------------------------------------------------ #
@router.callback_query(F.data == "menu:inventory")
async def menu_inventory_cb(cb: CallbackQuery):
    user_id = cb.from_user.id
    owned = await database.owned_weapons(user_id)
    player = await database.get_player(user_id)
    await cb.answer()
    text = "🎒 <b>Your Weapons</b>\nTap one to equip it."
    await cb.message.edit_text(text, reply_markup=kb.inventory_keyboard(owned, gd.WEAPONS, player["equipped_weapon"]))


@router.callback_query(F.data.startswith("equip:"))
async def equip_weapon_cb(cb: CallbackQuery):
    weapon_id = cb.data.split(":", 1)[1]
    await database.equip_weapon(cb.from_user.id, weapon_id)
    await cb.answer(f"✅ Equipped {gd.WEAPONS.get(weapon_id, {}).get('name', weapon_id)}!")
    owned = await database.owned_weapons(cb.from_user.id)
    await cb.message.edit_text(
        "🎒 <b>Your Weapons</b>\nTap one to equip it.",
        reply_markup=kb.inventory_keyboard(owned, gd.WEAPONS, weapon_id),
    )


# ------------------------------------------------------------------ #
#  Shadow extraction (gacha)
# ------------------------------------------------------------------ #
@router.callback_query(F.data == "menu:shadows")
async def menu_shadows_cb(cb: CallbackQuery):
    army = await database.get_shadow_army(cb.from_user.id)
    await cb.answer()
    if not army:
        text = "🌑 <b>Your Shadow Army is empty.</b>\nExtract shadows from defeated enemies to build your army."
    else:
        lines = []
        for row in army:
            info = gd.SHADOWS.get(row["shadow_id"], {})
            lines.append(f"• {info.get('name', row['shadow_id'])} x{row['count']} (+{info.get('atk_bonus', 0) * row['count']} ATK)")
        text = "🌑 <b>Your Shadow Army</b>\n\n" + "\n".join(lines)
    await cb.message.edit_text(text, reply_markup=kb.main_menu_button())


@router.callback_query(F.data == "menu:summon")
async def menu_summon_cb(cb: CallbackQuery):
    user_id = cb.from_user.id
    player = await database.get_player(user_id)
    await cb.answer()
    if player["gems"] < gd.EXTRACTION_COST_GEMS:
        await cb.message.edit_text(
            f"💎 <b>Not enough gems.</b>\nShadow extraction costs {gd.EXTRACTION_COST_GEMS} gems "
            f"(you have {player['gems']}). Earn gems through quizzes and story progress.",
            reply_markup=kb.main_menu_button(),
        )
        return

    roll = random.random()
    cumulative = 0.0
    chosen = None
    for shadow_id, info in gd.SHADOWS.items():
        cumulative += info["rate"]
        if roll <= cumulative:
            chosen = shadow_id
            break
    if not chosen:
        chosen = "shadow_soldier"

    await database.update_player(user_id, gems=player["gems"] - gd.EXTRACTION_COST_GEMS)
    count = await database.add_shadow(user_id, chosen)
    info = gd.SHADOWS[chosen]
    await cb.message.edit_text(
        f"🌑 <b>Extraction complete!</b>\n\n"
        f"✨ You extracted: <b>{info['name']}</b> ({info['rarity']})\n"
        f"⚔️ ATK Bonus: +{info['atk_bonus']}\n"
        f"📦 You now own {count}x {info['name']}",
        reply_markup=kb.main_menu_button(),
    )


# ------------------------------------------------------------------ #
#  Quiz
# ------------------------------------------------------------------ #
@router.callback_query(F.data == "menu:quiz")
async def menu_quiz_cb(cb: CallbackQuery):
    user_id = cb.from_user.id
    await cb.answer()
    unanswered = [i for i in range(len(gd.QUIZ_QUESTIONS)) if not await database.has_answered(user_id, i)]
    if not unanswered:
        await cb.message.edit_text("❓ <b>You've answered every quiz question!</b> More will be added with future arcs.", reply_markup=kb.main_menu_button())
        return
    idx = random.choice(unanswered)
    q = gd.QUIZ_QUESTIONS[idx]
    await cb.message.edit_text(f"❓ <b>Quiz</b>\n\n{q['q']}", reply_markup=kb.quiz_keyboard(q["options"], idx))


@router.callback_query(F.data.startswith("quiz:"))
async def quiz_answer_cb(cb: CallbackQuery):
    _, idx_str, sel_str = cb.data.split(":")
    idx, sel = int(idx_str), int(sel_str)
    q = gd.QUIZ_QUESTIONS[idx]
    user_id = cb.from_user.id

    if await database.has_answered(user_id, idx):
        await cb.answer("Already answered.", show_alert=True)
        return

    await database.mark_answered(user_id, idx)
    if sel == q["answer"]:
        await database.add_gold_xp(user_id, gold=q["reward"])
        await cb.answer("✅ Correct!")
        text = f"✅ <b>Correct!</b>\n💰 +{q['reward']} Gold"
    else:
        await cb.answer("❌ Wrong.")
        correct_text = q["options"][q["answer"]]
        text = f"❌ <b>Not quite.</b>\nThe correct answer was: <b>{correct_text}</b>"

    rows = [[kb.InlineKeyboardButton(text="➡️ Next Question", callback_data="menu:quiz")],
            [kb.InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu:main")]]
    await cb.message.edit_text(text, reply_markup=kb.InlineKeyboardMarkup(inline_keyboard=rows))


# ------------------------------------------------------------------ #
#  Leaderboard
# ------------------------------------------------------------------ #
@router.callback_query(F.data == "menu:leaderboard")
async def menu_leaderboard_cb(cb: CallbackQuery):
    top = await database.top_players(10)
    await cb.answer()
    if not top:
        text = "🏆 <b>No hunters ranked yet.</b>"
    else:
        lines = [f"{i}. {p['first_name']} — Lv.{p['level']} (Rank {p['rank']}) — 💰{p['gold']}" for i, p in enumerate(top, start=1)]
        text = "🏆 <b>Top Hunters</b>\n\n" + "\n".join(lines)
    await cb.message.edit_text(text, reply_markup=kb.main_menu_button())


@router.message(Command("profile"))
async def profile_cmd(message: Message):
    await database.get_or_create_player(message.from_user.id, message.from_user.first_name or "Hunter")
    text, markup = await render_profile(message.from_user.id)
    await message.answer(text, reply_markup=markup)


# ------------------------------------------------------------------ #
#  Character Roll (gacha for playable avatar)
# ------------------------------------------------------------------ #
@router.callback_query(F.data == "menu:roll")
async def menu_roll_cb(cb: CallbackQuery):
    user_id = cb.from_user.id
    player = await database.get_player(user_id)
    await cb.answer()
    if player["gold"] < gd.CHARACTER_ROLL_COST_GOLD:
        await cb.message.edit_text(
            f"🎲 <b>Not enough gold.</b>\nRolling a character costs {gd.CHARACTER_ROLL_COST_GOLD} gold "
            f"(you have {player['gold']}). Earn gold from gates, missions, and quizzes.",
            reply_markup=kb.main_menu_button(),
        )
        return

    roll = random.random()
    cumulative = 0.0
    chosen = None
    for char_id, info in gd.CHARACTERS.items():
        cumulative += info["rate"]
        if roll <= cumulative:
            chosen = char_id
            break
    chosen = chosen or "rookie_hunter"

    await database.update_player(user_id, gold=player["gold"] - gd.CHARACTER_ROLL_COST_GOLD)
    count = await database.add_character(user_id, chosen)
    if not player["active_character"]:
        await database.set_active_character(user_id, chosen)
    info = gd.CHARACTERS[chosen]
    await cb.message.edit_text(
        f"🎲 <b>Roll complete!</b>\n\n"
        f"✨ You got: <b>{info['name']}</b> ({info['rarity']})\n"
        f"⚔️ Base ATK: {info['base_atk']}   ❤️ Base HP: {info['base_hp']}\n"
        f"📦 You now own {count}x {info['name']}",
        reply_markup=kb.main_menu_button(),
    )


@router.message(Command("roll"))
async def roll_cmd(message: Message):
    await database.get_or_create_player(message.from_user.id, message.from_user.first_name or "Hunter")
    player = await database.get_player(message.from_user.id)
    if player["gold"] < gd.CHARACTER_ROLL_COST_GOLD:
        await message.answer(f"🎲 Not enough gold. Rolling costs {gd.CHARACTER_ROLL_COST_GOLD} gold (you have {player['gold']}).")
        return
    roll = random.random()
    cumulative = 0.0
    chosen = None
    for char_id, info in gd.CHARACTERS.items():
        cumulative += info["rate"]
        if roll <= cumulative:
            chosen = char_id
            break
    chosen = chosen or "rookie_hunter"
    await database.update_player(message.from_user.id, gold=player["gold"] - gd.CHARACTER_ROLL_COST_GOLD)
    count = await database.add_character(message.from_user.id, chosen)
    if not player["active_character"]:
        await database.set_active_character(message.from_user.id, chosen)
    info = gd.CHARACTERS[chosen]
    await message.answer(f"🎲 You got: <b>{info['name']}</b> ({info['rarity']})! You now own {count}x.")


@router.callback_query(F.data == "menu:characters")
async def menu_characters_cb(cb: CallbackQuery):
    user_id = cb.from_user.id
    owned = await database.get_characters(user_id)
    player = await database.get_player(user_id)
    await cb.answer()
    if not owned:
        await cb.message.edit_text("🎲 <b>You don't own any characters yet.</b> Roll one from the main menu!", reply_markup=kb.main_menu_button())
        return
    await cb.message.edit_text("🧙 <b>Your Characters</b>\nTap one to set as active.", reply_markup=kb.characters_keyboard(owned, gd.CHARACTERS, player["active_character"]))


@router.callback_query(F.data.startswith("setactive:"))
async def set_active_character_cb(cb: CallbackQuery):
    char_id = cb.data.split(":", 1)[1]
    await database.set_active_character(cb.from_user.id, char_id)
    await cb.answer(f"✅ {gd.CHARACTERS.get(char_id, {}).get('name', char_id)} is now active!")
    owned = await database.get_characters(cb.from_user.id)
    await cb.message.edit_text("🧙 <b>Your Characters</b>\nTap one to set as active.", reply_markup=kb.characters_keyboard(owned, gd.CHARACTERS, char_id))


# ------------------------------------------------------------------ #
#  Gates
# ------------------------------------------------------------------ #
async def render_gates(user_id: int) -> tuple[str, object]:
    status = []
    lines = []
    for gate_id, gate in gd.GATES.items():
        remaining = await database.gate_cooldown_remaining(user_id, gate_id, gate["cooldown_min"])
        status.append((gate_id, gate["name"], remaining))
        if remaining <= 0:
            lines.append(f"✅ {gate['name']} — ready")
        else:
            m, s = divmod(remaining, 60)
            lines.append(f"🔒 {gate['name']} — {m}m {s}s left")
    text = "🚪 <b>Gates</b>\nClear a gate to earn resources, gold, and XP. Tap a ready gate to enter.\n\n" + "\n".join(lines)
    return text, kb.gates_keyboard(status)


@router.callback_query(F.data == "menu:gates")
async def menu_gates_cb(cb: CallbackQuery):
    await database.get_or_create_player(cb.from_user.id, cb.from_user.first_name or "Hunter")
    await cb.answer()
    text, markup = await render_gates(cb.from_user.id)
    await cb.message.edit_text(text, reply_markup=markup)


@router.callback_query(F.data.startswith("gate:"))
async def enter_gate_cb(cb: CallbackQuery):
    gate_id = cb.data.split(":", 1)[1]
    gate = gd.GATES.get(gate_id)
    user_id = cb.from_user.id
    if not gate:
        await cb.answer()
        return
    remaining = await database.gate_cooldown_remaining(user_id, gate_id, gate["cooldown_min"])
    if remaining > 0:
        m, s = divmod(remaining, 60)
        await cb.answer(f"🔒 On cooldown — {m}m {s}s left.", show_alert=True)
        return
    await cb.answer()
    monster = gd.GATE_MONSTERS[gate["monster"]]
    await database.start_gate_battle(user_id, gate_id, gate["monster"], monster["hp"])
    player = await database.get_player(user_id)
    text = (
        f"🚪 <b>Entering {gate['name']}...</b>\n\n"
        f"⚔️ <b>{monster['name']} appears!</b>\n\n"
        f"👤 You: {player['hp']}/{player['max_hp']} HP\n"
        f"👹 {monster['name']}: {monster['hp']}/{monster['hp']} HP"
    )
    await cb.message.edit_text(text, reply_markup=kb.gate_battle_keyboard())


@router.callback_query(F.data.startswith("gatebattle:"))
async def gate_battle_action_cb(cb: CallbackQuery):
    user_id = cb.from_user.id
    action = cb.data.split(":", 1)[1]
    battle = await database.get_gate_battle(user_id)
    if not battle:
        await cb.answer("No active gate battle.", show_alert=True)
        return
    gate = gd.GATES[battle["gate_id"]]
    monster = gd.GATE_MONSTERS[battle["monster_id"]]
    player = await database.get_player(user_id)

    if action == "flee":
        await database.end_gate_battle(user_id)
        await cb.answer("You retreated from the gate.")
        await cb.message.edit_text("🏃 <b>You retreated from the gate.</b> No cooldown was used.", reply_markup=kb.main_menu_button())
        return

    await cb.answer()
    monster_hp = battle["monster_hp"]
    log_lines = []

    if action == "attack":
        atk = await player_attack_power(user_id)
        dmg = max(1, atk - monster["defense"] + random.randint(-2, 3))
        monster_hp -= dmg
        log_lines.append(f"⚔️ You strike for <b>{dmg}</b> damage.")
    else:  # defend
        atk = await player_attack_power(user_id)
        dmg = max(1, (atk // 2) - monster["defense"])
        monster_hp -= dmg
        log_lines.append(f"🛡️ You brace and counter for <b>{dmg}</b> damage.")

    if monster_hp <= 0:
        resource_key = gate["resource"]
        resource_amt = gate["resource_amount"]
        kwargs = {"gold": monster["gold"], "xp": monster["xp"], resource_key: resource_amt}
        summary = await database.add_gold_xp(user_id, **kwargs)
        await database.end_gate_battle(user_id)
        await database.set_gate_cooldown(user_id, battle["gate_id"])
        resource_label = "🔷 Mana Crystals" if resource_key == "mana_crystals" else "🔶 Essence Stones"
        text = (
            f"🏆 <b>{gate['name']} cleared!</b>\n\n"
            f"💰 +{monster['gold']} Gold   ✨ +{monster['xp']} XP\n"
            f"{resource_label}: +{resource_amt}"
        )
        if summary.get("levels_gained"):
            text += f"\n🆙 <b>Level up! Now level {summary['level']} (Rank {summary['rank']})</b>"
        await cb.message.edit_text(text, reply_markup=kb.main_menu_button())
        return

    player_def = player["vit_stat"] // 5
    reduction = 0.5 if action == "defend" else 1.0
    monster_dmg = max(1, int((monster["atk"] - player_def) * reduction) + random.randint(-1, 2))
    new_hp = max(0, player["hp"] - monster_dmg)
    log_lines.append(f"👹 {monster['name']} hits you for <b>{monster_dmg}</b> damage.")

    await database.update_gate_battle_hp(user_id, monster_hp)

    if new_hp <= 0:
        await database.update_player(user_id, hp=1)
        await database.end_gate_battle(user_id)
        await database.set_gate_cooldown(user_id, battle["gate_id"])
        await cb.message.edit_text(
            "💀 <b>You were overwhelmed and pulled from the gate!</b>\nYou wake up back outside, HP restored to 1.",
            reply_markup=kb.main_menu_button(),
        )
        return

    await database.update_player(user_id, hp=new_hp)
    status = f"👤 You: {new_hp}/{player['max_hp']} HP\n👹 {monster['name']}: {monster_hp}/{monster['hp']} HP"
    await cb.message.edit_text("\n".join(log_lines) + f"\n\n{status}", reply_markup=kb.gate_battle_keyboard())


# ------------------------------------------------------------------ #
#  Missions (Daily / Hourly)
# ------------------------------------------------------------------ #
@router.callback_query(F.data == "menu:daily")
async def menu_daily_cb(cb: CallbackQuery):
    user_id = cb.from_user.id
    await database.get_or_create_player(user_id, cb.from_user.first_name or "Hunter")
    remaining = await database.daily_status(user_id)
    await cb.answer()
    if remaining > 0:
        h, rem = divmod(remaining, 3600)
        m, _ = divmod(rem, 60)
        await cb.message.edit_text(f"📅 <b>Daily mission already claimed.</b>\nCome back in {h}h {m}m.", reply_markup=kb.main_menu_button())
        return
    r = gd.DAILY_REWARD
    await database.add_gold_xp(user_id, gold=r.get("gold", 0), gems=r.get("gems", 0), mana_crystals=r.get("mana_crystals", 0))
    await database.claim_daily(user_id)
    await cb.message.edit_text(
        f"📅 <b>Daily reward claimed!</b>\n\n💰 +{r.get('gold',0)} Gold   💎 +{r.get('gems',0)} Gems   "
        f"🔷 +{r.get('mana_crystals',0)} Mana Crystals",
        reply_markup=kb.main_menu_button(),
    )


@router.callback_query(F.data == "menu:hourly")
async def menu_hourly_cb(cb: CallbackQuery):
    user_id = cb.from_user.id
    await database.get_or_create_player(user_id, cb.from_user.first_name or "Hunter")
    remaining = await database.hourly_status(user_id)
    await cb.answer()
    if remaining > 0:
        m, s = divmod(remaining, 60)
        await cb.message.edit_text(f"⏰ <b>Hourly mission already claimed.</b>\nCome back in {m}m {s}s.", reply_markup=kb.main_menu_button())
        return
    r = gd.HOURLY_REWARD
    await database.add_gold_xp(user_id, gold=r.get("gold", 0), mana_crystals=r.get("mana_crystals", 0))
    await database.claim_hourly(user_id)
    await cb.message.edit_text(
        f"⏰ <b>Hourly reward claimed!</b>\n\n💰 +{r.get('gold',0)} Gold   🔷 +{r.get('mana_crystals',0)} Mana Crystals",
        reply_markup=kb.main_menu_button(),
    )


# ------------------------------------------------------------------ #
#  Shop
# ------------------------------------------------------------------ #
@router.callback_query(F.data == "menu:shop")
async def menu_shop_cb(cb: CallbackQuery):
    await cb.answer()
    await cb.message.edit_text("🏪 <b>Shop</b>\nSpend gold on gear.", reply_markup=kb.shop_keyboard(gd.SHOP_ITEMS, gd.WEAPONS))


@router.callback_query(F.data.startswith("buy:"))
async def buy_item_cb(cb: CallbackQuery):
    item_id = cb.data.split(":", 1)[1]
    item = gd.SHOP_ITEMS.get(item_id)
    if not item:
        await cb.answer()
        return
    user_id = cb.from_user.id
    player = await database.get_player(user_id)
    if item_id in await database.owned_weapons(user_id):
        await cb.answer("You already own this.", show_alert=True)
        return
    if player["gold"] < item["cost_gold"]:
        await cb.answer("Not enough gold.", show_alert=True)
        return
    await database.update_player(user_id, gold=player["gold"] - item["cost_gold"])
    await database.grant_weapon(user_id, item_id)
    await cb.answer(f"✅ Purchased {gd.WEAPONS[item_id]['name']}!")
    await cb.message.edit_text("🏪 <b>Shop</b>\nSpend gold on gear.", reply_markup=kb.shop_keyboard(gd.SHOP_ITEMS, gd.WEAPONS))


# ------------------------------------------------------------------ #
#  Vault
# ------------------------------------------------------------------ #
@router.callback_query(F.data == "menu:vault")
async def menu_vault_cb(cb: CallbackQuery):
    user_id = cb.from_user.id
    p = await database.get_player(user_id)
    weapons = await database.owned_weapons(user_id)
    shadows = await database.get_shadow_army(user_id)
    characters = await database.get_characters(user_id)
    await cb.answer()
    text = (
        "🗃️ <b>Vault</b>\n\n"
        f"💰 Gold: {p['gold']}   💎 Gems: {p['gems']}\n"
        f"🔷 Mana Crystals: {p['mana_crystals']}   🔶 Essence Stones: {p['essence_stones']}\n\n"
        f"⚔️ Weapons owned: {len(weapons)}\n"
        f"🧙 Characters owned: {len(characters)}\n"
        f"🌑 Shadows owned: {sum(r['count'] for r in shadows)}"
    )
    await cb.message.edit_text(text, reply_markup=kb.main_menu_button())


# ------------------------------------------------------------------ #
#  PvP Duels (group-friendly — reply to a user's message with /duel)
# ------------------------------------------------------------------ #
@router.message(Command("duel"))
async def duel_cmd(message: Message):
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.answer("⚔️ Reply to another player's message with <code>/duel</code> to challenge them.")
        return
    challenger = message.from_user
    target = message.reply_to_message.from_user
    if target.id == challenger.id:
        await message.answer("⚔️ You can't duel yourself.")
        return
    if target.is_bot:
        await message.answer("⚔️ You can't duel a bot.")
        return

    await database.get_or_create_player(challenger.id, challenger.first_name or "Hunter")
    await database.get_or_create_player(target.id, target.first_name or "Hunter")
    challenger_p = await database.get_player(challenger.id)
    target_p = await database.get_player(target.id)

    import uuid
    battle_id = uuid.uuid4().hex[:12]
    sent = await message.answer(
        f"⚔️ <b>{html.escape(challenger.first_name)} challenges {html.escape(target.first_name)} to a duel!</b>\n\n"
        f"{html.escape(target.first_name)}, do you accept?",
        reply_markup=kb.pvp_challenge_keyboard(battle_id),
    )
    await database.create_pvp_battle(
        battle_id, message.chat.id, sent.message_id, challenger.id, target.id,
        challenger_p["max_hp"], target_p["max_hp"],
    )


@router.callback_query(F.data.startswith("pvp:"))
async def pvp_action_cb(cb: CallbackQuery):
    _, battle_id, action = cb.data.split(":")
    battle = await database.get_pvp_battle(battle_id)
    if not battle:
        await cb.answer("This duel no longer exists.", show_alert=True)
        return
    user_id = cb.from_user.id

    if action == "decline":
        if user_id != battle["target_id"]:
            await cb.answer("Only the challenged player can decline.", show_alert=True)
            return
        await database.delete_pvp_battle(battle_id)
        await cb.answer("Duel declined.")
        await cb.message.edit_text("❌ <b>Duel declined.</b>", reply_markup=None)
        return

    if action == "accept":
        if user_id != battle["target_id"]:
            await cb.answer("Only the challenged player can accept.", show_alert=True)
            return
        await database.update_pvp_battle(battle_id, status="active")
        challenger = await database.get_player(battle["challenger_id"])
        target = await database.get_player(battle["target_id"])
        await cb.answer("Duel accepted!")
        text = (
            f"⚔️ <b>Duel started!</b>\n\n"
            f"👤 {html.escape(challenger['first_name'])}: {battle['challenger_hp']} HP\n"
            f"👤 {html.escape(target['first_name'])}: {battle['target_hp']} HP\n\n"
            f"It's <b>{html.escape(challenger['first_name'])}'s</b> turn."
        )
        await cb.message.edit_text(text, reply_markup=kb.pvp_battle_keyboard(battle_id))
        return

    if action == "attack":
        if battle["status"] != "active":
            await cb.answer("This duel hasn't started yet.", show_alert=True)
            return
        if user_id != battle["turn_user_id"]:
            await cb.answer("It's not your turn.", show_alert=True)
            return

        attacker_id = user_id
        defender_id = battle["target_id"] if attacker_id == battle["challenger_id"] else battle["challenger_id"]
        atk = await player_attack_power(attacker_id)
        dmg = max(1, atk + random.randint(-2, 3))

        if defender_id == battle["target_id"]:
            new_target_hp = max(0, battle["target_hp"] - dmg)
            new_challenger_hp = battle["challenger_hp"]
        else:
            new_challenger_hp = max(0, battle["challenger_hp"] - dmg)
            new_target_hp = battle["target_hp"]

        await cb.answer(f"You hit for {dmg} damage!")

        challenger_p = await database.get_player(battle["challenger_id"])
        target_p = await database.get_player(battle["target_id"])

        if new_target_hp <= 0 or new_challenger_hp <= 0:
            winner = challenger_p if new_target_hp <= 0 else target_p
            loser = target_p if new_target_hp <= 0 else challenger_p
            await database.add_gold_xp(winner["user_id"], gold=40, xp=25)
            await database.delete_pvp_battle(battle_id)
            await cb.message.edit_text(
                f"🏆 <b>{html.escape(winner['first_name'])} wins the duel!</b>\n"
                f"💰 +40 Gold   ✨ +25 XP\n\n"
                f"Better luck next time, {html.escape(loser['first_name'])}.",
                reply_markup=None,
            )
            return

        next_turn = defender_id
        await database.update_pvp_battle(
            battle_id, challenger_hp=new_challenger_hp, target_hp=new_target_hp, turn_user_id=next_turn
        )
        next_name = challenger_p["first_name"] if next_turn == battle["challenger_id"] else target_p["first_name"]
        text = (
            f"⚔️ <b>Duel in progress</b>\n\n"
            f"👤 {html.escape(challenger_p['first_name'])}: {new_challenger_hp} HP\n"
            f"👤 {html.escape(target_p['first_name'])}: {new_target_hp} HP\n\n"
            f"It's <b>{html.escape(next_name)}'s</b> turn."
        )
        await cb.message.edit_text(text, reply_markup=kb.pvp_battle_keyboard(battle_id))


# ------------------------------------------------------------------ #
#  /setting — welcome message customization (owner only)
# ------------------------------------------------------------------ #
@router.message(Command("setting"))
async def setting_cmd(message: Message):
    if not _is_owner(message.from_user.id):
        return
    AWAITING.pop(message.from_user.id, None)
    await message.answer("⚙️ <b>Bot Settings</b>\nCustomize the /start welcome experience.", reply_markup=kb.settings_main_keyboard())


@router.callback_query(F.data == "set:main")
async def set_main_cb(cb: CallbackQuery):
    if not _is_owner(cb.from_user.id):
        await cb.answer("⛔ Owner only.", show_alert=True)
        return
    AWAITING.pop(cb.from_user.id, None)
    await cb.answer()
    await cb.message.edit_text("⚙️ <b>Bot Settings</b>\nCustomize the /start welcome experience.", reply_markup=kb.settings_main_keyboard())


@router.callback_query(F.data == "set:welcometext")
async def set_welcometext_cb(cb: CallbackQuery):
    if not _is_owner(cb.from_user.id):
        await cb.answer("⛔ Owner only.", show_alert=True)
        return
    AWAITING[cb.from_user.id] = "welcome_text"
    await cb.answer()
    await cb.message.edit_text(
        "✍️ <b>Send the new welcome text now.</b>\n<i>Use <code>{name}</code> where the player's name should appear.</i>",
        reply_markup=kb.back_to_settings_keyboard(),
    )


@router.callback_query(F.data == "set:welcomephoto")
async def set_welcomephoto_cb(cb: CallbackQuery):
    if not _is_owner(cb.from_user.id):
        await cb.answer("⛔ Owner only.", show_alert=True)
        return
    AWAITING[cb.from_user.id] = "welcome_photo"
    await cb.answer()
    await cb.message.edit_text("🖼️ <b>Send the new welcome photo now.</b>", reply_markup=kb.back_to_settings_keyboard())


@router.callback_query(F.data == "set:startsticker")
async def set_startsticker_cb(cb: CallbackQuery):
    if not _is_owner(cb.from_user.id):
        await cb.answer("⛔ Owner only.", show_alert=True)
        return
    AWAITING[cb.from_user.id] = "start_sticker"
    await cb.answer()
    await cb.message.edit_text("🎬 <b>Send the sticker to play during the /start animation.</b>", reply_markup=kb.back_to_settings_keyboard())


@router.callback_query(F.data == "set:ownerbtn")
async def set_ownerbtn_cb(cb: CallbackQuery):
    if not _is_owner(cb.from_user.id):
        await cb.answer("⛔ Owner only.", show_alert=True)
        return
    AWAITING[cb.from_user.id] = "owner_username"
    await cb.answer()
    await cb.message.edit_text("👑 <b>Send the owner's @username</b> (no need for the @).", reply_markup=kb.back_to_settings_keyboard())


@router.callback_query(F.data == "set:adminbtn")
async def set_adminbtn_cb(cb: CallbackQuery):
    if not _is_owner(cb.from_user.id):
        await cb.answer("⛔ Owner only.", show_alert=True)
        return
    AWAITING[cb.from_user.id] = "admin_username"
    await cb.answer()
    await cb.message.edit_text("🥷 <b>Send the admin's @username</b> (no need for the @).", reply_markup=kb.back_to_settings_keyboard())


@router.callback_query(F.data == "set:supportbtn")
async def set_supportbtn_cb(cb: CallbackQuery):
    if not _is_owner(cb.from_user.id):
        await cb.answer("⛔ Owner only.", show_alert=True)
        return
    AWAITING[cb.from_user.id] = "support_link"
    await cb.answer()
    await cb.message.edit_text("🤝 <b>Send the full support link URL.</b>", reply_markup=kb.back_to_settings_keyboard())


@router.callback_query(F.data == "set:websitebtn")
async def set_websitebtn_cb(cb: CallbackQuery):
    if not _is_owner(cb.from_user.id):
        await cb.answer("⛔ Owner only.", show_alert=True)
        return
    AWAITING[cb.from_user.id] = "website_link"
    await cb.answer()
    await cb.message.edit_text("🌐 <b>Send the full website link URL.</b>", reply_markup=kb.back_to_settings_keyboard())


@router.callback_query(F.data == "set:preview")
async def set_preview_cb(cb: CallbackQuery):
    if not _is_owner(cb.from_user.id):
        await cb.answer("⛔ Owner only.", show_alert=True)
        return
    await cb.answer()
    await play_start_animation(cb.message, cb.from_user.first_name or "Hunter")
    await send_welcome(cb.message, cb.from_user.first_name or "Hunter", extra_text="👀 <i>Settings preview</i>")


@router.message(F.photo)
async def awaiting_photo_handler(message: Message):
    user_id = message.from_user.id
    if AWAITING.get(user_id) != "welcome_photo":
        return
    await database.set_setting("welcome_photo", message.photo[-1].file_id)
    AWAITING.pop(user_id, None)
    await message.answer("✅ <b>Welcome photo updated!</b>", reply_markup=kb.settings_main_keyboard())


@router.message(F.sticker)
async def awaiting_sticker_handler(message: Message):
    user_id = message.from_user.id
    if AWAITING.get(user_id) != "start_sticker":
        return
    await database.set_setting("start_sticker", message.sticker.file_id)
    AWAITING.pop(user_id, None)
    await message.answer("✅ <b>Start sticker updated!</b>", reply_markup=kb.settings_main_keyboard())


@router.message(F.text & ~F.text.startswith("/"))
async def awaiting_text_handler(message: Message):
    user_id = message.from_user.id
    key = AWAITING.get(user_id)
    if not key:
        return
    text = message.text.strip()

    if key == "welcome_text":
        await database.set_setting("welcome_text", message.html_text or text)
        AWAITING.pop(user_id, None)
        await message.answer("✅ <b>Welcome text updated!</b>", reply_markup=kb.settings_main_keyboard())
    elif key in {"owner_username", "admin_username"}:
        await database.set_setting(key, text.lstrip("@"))
        AWAITING.pop(user_id, None)
        await message.answer("✅ <b>Saved!</b>", reply_markup=kb.settings_main_keyboard())
    elif key in {"support_link", "website_link"}:
        await database.set_setting(key, text)
        AWAITING.pop(user_id, None)
        await message.answer("✅ <b>Saved!</b>", reply_markup=kb.settings_main_keyboard())


# ------------------------------------------------------------------ #
#  Admin panel (owner only)
# ------------------------------------------------------------------ #
def _is_owner(user_id: int) -> bool:
    return config.owner_id != 0 and user_id == config.owner_id


@router.message(Command("admin"))
async def admin_help_cmd(message: Message):
    if not _is_owner(message.from_user.id):
        return
    await message.answer(
        "🛠️ <b>Admin Panel</b>\n\n"
        "<code>/givegold [user_id] [amount]</code>\n"
        "<code>/givegems [user_id] [amount]</code>\n"
        "<code>/givecrystals [user_id] [amount]</code>\n"
        "<code>/resetplayer [user_id]</code>\n"
        "<code>/botstats</code> — total players, top level\n"
        "<code>/broadcast [text]</code> — message every player"
    )


@router.message(Command("givegold"))
async def give_gold_cmd(message: Message, command: CommandObject):
    if not _is_owner(message.from_user.id):
        return
    parts = (command.args or "").split()
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].lstrip("-").isdigit():
        await message.answer("⚠️ Usage: <code>/givegold [user_id] [amount]</code>")
        return
    target_id, amount = int(parts[0]), int(parts[1])
    await database.add_gold_xp(target_id, gold=amount)
    await message.answer(f"✅ Gave {amount} gold to <code>{target_id}</code>.")


@router.message(Command("givegems"))
async def give_gems_cmd(message: Message, command: CommandObject):
    if not _is_owner(message.from_user.id):
        return
    parts = (command.args or "").split()
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].lstrip("-").isdigit():
        await message.answer("⚠️ Usage: <code>/givegems [user_id] [amount]</code>")
        return
    target_id, amount = int(parts[0]), int(parts[1])
    await database.add_gold_xp(target_id, gems=amount)
    await message.answer(f"✅ Gave {amount} gems to <code>{target_id}</code>.")


@router.message(Command("givecrystals"))
async def give_crystals_cmd(message: Message, command: CommandObject):
    if not _is_owner(message.from_user.id):
        return
    parts = (command.args or "").split()
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].lstrip("-").isdigit():
        await message.answer("⚠️ Usage: <code>/givecrystals [user_id] [amount]</code>")
        return
    target_id, amount = int(parts[0]), int(parts[1])
    await database.add_gold_xp(target_id, mana_crystals=amount)
    await message.answer(f"✅ Gave {amount} mana crystals to <code>{target_id}</code>.")


@router.message(Command("resetplayer"))
async def reset_player_cmd(message: Message, command: CommandObject):
    if not _is_owner(message.from_user.id):
        return
    arg = (command.args or "").strip()
    if not arg.isdigit():
        await message.answer("⚠️ Usage: <code>/resetplayer [user_id]</code>")
        return
    target_id = int(arg)
    async with database.connection() as db:
        for table in ("players", "inventory", "shadow_army", "quiz_answered", "battle_state",
                      "player_characters", "gate_cooldowns", "gate_battle_state"):
            await db.execute(f"DELETE FROM {table} WHERE user_id=?", (target_id,))
        await db.commit()
    await message.answer(f"✅ Player <code>{target_id}</code> has been reset.")


@router.message(Command("botstats"))
async def bot_stats_cmd(message: Message):
    if not _is_owner(message.from_user.id):
        return
    top = await database.top_players(1)
    async with database.connection() as db:
        row = await (await db.execute("SELECT COUNT(*) c FROM players")).fetchone()
        total = row["c"]
    top_line = f"{top[0]['first_name']} (Lv.{top[0]['level']})" if top else "—"
    await message.answer(f"📊 <b>Bot Stats</b>\n\n👥 Total players: {total}\n🏆 Top player: {top_line}")


@router.message(Command("broadcast"))
async def broadcast_cmd(message: Message, command: CommandObject):
    if not _is_owner(message.from_user.id):
        return
    text = (command.args or "").strip()
    if not text:
        await message.answer("⚠️ Usage: <code>/broadcast [text]</code>")
        return
    async with database.connection() as db:
        rows = await (await db.execute("SELECT user_id FROM players")).fetchall()
    sent, failed = 0, 0
    for row in rows:
        try:
            await bot.send_message(row["user_id"], text)
            sent += 1
        except Exception:
            failed += 1
    await message.answer(f"📢 Broadcast done. ✅ {sent} sent, ❌ {failed} failed.")


@router.message(Command("help"))
async def help_cmd(message: Message):
    text = (
        "🌑 <b>Commands</b>\n\n"
        "/start — begin or resume your journey\n"
        "/profile — view your stats\n"
        "/roll — roll a new character\n"
        "/duel — reply to a player's message to challenge them\n\n"
        "Everything else is menu-driven — use /start to open the main menu anytime."
    )
    if _is_owner(message.from_user.id):
        text += "\n\n👑 <b>Owner</b>\n/setting — customize the welcome message\n/admin — admin panel"
    await message.answer(text)
