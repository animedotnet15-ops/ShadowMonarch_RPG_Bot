from __future__ import annotations

import asyncio
import html
import json
import logging
import random
import re
import time

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, BufferedInputFile

from config import config
from database import database
import game_data as gd
import gemini_image
import keyboards as kb

LOG = logging.getLogger("shadowmonarch")

bot = Bot(token=config.bot_token, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
router = Router()
dp.include_router(router)


@router.message.outer_middleware()
async def bot_enabled_message_middleware(handler, event: Message, data):
    owner = event.from_user and event.from_user.id == config.owner_id
    if not owner:
        enabled = await database.get_setting("bot_enabled", "1") == "1"
        if not enabled:
            try:
                await event.answer("🔴 <b>The bot is currently offline for maintenance.</b> Please check back later.")
            except Exception:
                pass
            return
    return await handler(event, data)


@router.callback_query.outer_middleware()
async def bot_enabled_callback_middleware(handler, event: CallbackQuery, data):
    owner = event.from_user and event.from_user.id == config.owner_id
    if not owner:
        enabled = await database.get_setting("bot_enabled", "1") == "1"
        if not enabled:
            await event.answer("🔴 Bot is offline for maintenance.", show_alert=True)
            return
    return await handler(event, data)

WELCOME_TEXT = (
    "🌑 <b>Welcome to the System, {name}.</b>\n\n"
    "You were an ordinary E-rank hunter — until a routine gate hid something far worse "
    "beneath it. Something changed you down there. Something is still watching.\n\n"
    "Climb the ranks. Master your weapons. Build a Shadow Army that answers to no one but you.\n\n"
    "<i>Your story starts now.</i>"
)

AWAITING: dict[int, str] = {}  # user_id -> setting key being edited
BOT_USERNAME = ""  # populated at startup via bot.get_me()


def stat_col(stat: str) -> str:
    return {"str": "str_stat", "agi": "agi_stat", "intel": "intel_stat", "vit": "vit_stat", "per": "per_stat"}[stat]


async def full_character_pool() -> dict:
    """Static CHARACTERS from game_data.py, merged with admin-added custom characters."""
    pool = dict(gd.CHARACTERS)
    for row in await database.all_custom_characters():
        pool[row["character_id"]] = {
            "name": row["name"],
            "rarity": row["rarity"],
            "base_atk": row["atk_bonus"],
            "base_hp": row["hp_bonus"],
            "rate": row["rate"],
            "photo_file_id": row["photo_file_id"],
        }
    return pool


async def ai_images_on() -> bool:
    return gemini_image.is_configured() and await database.get_setting("ai_images_enabled", "0") == "1"


async def send_generated_photo(chat_id: int, cache_key: str, prompt: str, caption: str, reply_markup=None, existing_file_id: str = "") -> bool:
    """Sends a photo for cache_key — reuses an existing file_id, a cache hit, or generates fresh via Gemini.
    Returns True if a photo was sent, False if the caller should fall back to plain text."""
    if existing_file_id:
        try:
            await bot.send_photo(chat_id, existing_file_id, caption=caption, reply_markup=reply_markup)
            return True
        except Exception:
            pass

    cached = await database.get_cached_image(cache_key)
    if cached:
        try:
            await bot.send_photo(chat_id, cached, caption=caption, reply_markup=reply_markup)
            return True
        except Exception:
            pass

    if not await ai_images_on():
        return False

    image_bytes = await gemini_image.generate_image(prompt)
    if not image_bytes:
        return False
    try:
        sent = await bot.send_photo(
            chat_id, BufferedInputFile(image_bytes, filename="art.png"), caption=caption, reply_markup=reply_markup
        )
        await database.cache_image(cache_key, sent.photo[-1].file_id)
        return True
    except Exception as e:
        LOG.warning(f"Could not send generated image: {e}")
        return False


async def announce_to_group_if_dm(chat, user, text: str) -> None:
    """If this action happened in a private DM, also post a short public announcement
    to the player's last-active group (if any) so the group stays in the loop."""
    if chat.type != "private":
        return
    player = await database.get_player(user.id)
    if not player or not player["last_active_chat_id"]:
        return
    try:
        await bot.send_message(player["last_active_chat_id"], text)
    except Exception:
        pass


async def maybe_unlock_achievement(user_id: int, achievement_id: str, condition: bool, chat_id: int | None = None) -> None:
    if not condition:
        return
    newly = await database.unlock_achievement(user_id, achievement_id)
    if not newly:
        return
    info = gd.ACHIEVEMENTS.get(achievement_id)
    if not info:
        return
    text = f"🏅 <b>Achievement Unlocked!</b>\n\n{info['name']}\n<i>{info['desc']}</i>\n\n🎖️ Title earned: <b>{info['title']}</b>"
    try:
        await bot.send_message(user_id, text)
    except Exception:
        pass
    if chat_id:
        try:
            player = await database.get_player(user_id)
            if player and chat_id != user_id:
                await bot.send_message(chat_id, f"🏅 <b>{html.escape(player['first_name'])}</b> unlocked: {info['name']}!")
        except Exception:
            pass


async def maybe_announce_levelup(user_id: int, chat_id: int, summary: dict) -> None:
    if not summary.get("levels_gained"):
        return
    level, rank = summary["level"], summary["rank"]
    caption = f"🆙 <b>LEVEL UP!</b>\n\nYou are now <b>Level {level}</b> (Rank {rank}) ✨"
    prompt = (
        f"An epic digital RPG level-up celebration screen, glowing text energy, "
        f"a hunter silhouette ascending in light, rank '{rank}' theme, dark fantasy "
        f"game UI splash art, no readable text, no watermarks."
    )
    await send_generated_photo(chat_id, f"levelup_rank:{rank}", prompt, caption)
    rank_order = ["E", "D", "C", "B", "A", "S"]
    reached = rank_order.index(rank) if rank in rank_order else 0
    await maybe_unlock_achievement(user_id, "first_levelup", level >= 2, chat_id)
    await maybe_unlock_achievement(user_id, "rank_c", reached >= rank_order.index("C"), chat_id)
    await maybe_unlock_achievement(user_id, "rank_s", reached >= rank_order.index("S"), chat_id)


async def safe_edit(message: Message, text: str, reply_markup=None) -> None:
    """edit_text() fails on photo messages — this handles both cases with a message fallback."""
    if message.photo:
        try:
            await message.edit_caption(caption=text, reply_markup=reply_markup)
            return
        except Exception:
            pass
        await message.answer(text, reply_markup=reply_markup)
        return
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest:
        await message.answer(text, reply_markup=reply_markup)


async def player_attack_power(user_id: int) -> int:
    player = await database.get_player(user_id)
    weapon = gd.WEAPONS.get(player["equipped_weapon"], gd.WEAPONS[gd.STARTING_WEAPON])
    pool = await full_character_pool()
    char = pool.get(player["active_character"], {})
    shadow_bonus = await database.shadow_army_atk_bonus(user_id)
    return weapon["atk"] + char.get("base_atk", 0) + player["str_stat"] // 3 + shadow_bonus


async def render_profile(user_id: int) -> tuple[str, object]:
    p = await database.get_player(user_id)
    weapon = gd.WEAPONS.get(p["equipped_weapon"], {})
    pool = await full_character_pool()
    char = pool.get(p["active_character"])
    char_line = f"🧙 Character: {char['name']} ({char['rarity']})\n" if char else "🧙 Character: — (roll one!)\n"
    energy, max_energy, secs = await database.get_energy(user_id)
    energy_line = f"⚡ Energy: {energy}/{max_energy}" + (f" (full in {secs // 60}m)" if energy < max_energy else " (full!)")
    text = (
        f"👤 <b>{p['first_name']}</b>" + (f" — <i>\"{p['equipped_title']}\"</i>" if p["equipped_title"] else "") + "\n"
        f"Rank {p['rank']} | Level {p['level']}\n\n"
        f"✨ XP: {p['xp']}/{p['xp_next']}\n"
        f"❤️ HP: {p['hp']}/{p['max_hp']}\n"
        f"{energy_line}\n"
        f"🔥 Daily Streak: {p['streak_days']} day{'s' if p['streak_days'] != 1 else ''}\n"
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


async def render_story_node(user_id: int, chat_id: int | None = None) -> tuple[str, object]:
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
            if chat_id:
                await send_generated_photo(
                    chat_id, f"storymonster:{monster_id}",
                    gemini_image.battle_prompt(monster["name"], "an ancient dungeon"),
                    f"⚔️ <b>{monster['name']} appears!</b>",
                )
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


async def premium_emoji_prefix() -> str:
    emoji_id = await database.get_setting("premium_emoji_id", "")
    fallback = await database.get_setting("premium_emoji_fallback", "🌑")
    if emoji_id:
        return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji> '
    return f"{fallback} "


async def build_welcome_text(name: str, extra_text: str = "") -> str:
    text = await database.get_setting("welcome_text", WELCOME_TEXT)
    text = text.replace("{name}", html.escape(name))
    prefix = await premium_emoji_prefix()
    text = prefix + text
    if extra_text:
        text = extra_text + "\n\n" + text
    return text


async def build_welcome_keyboard(for_group: bool = False) -> InlineKeyboardMarkup:
    owner_username = await database.get_setting("owner_username", "")
    admin_username = await database.get_setting("admin_username", "")
    support_link = await database.get_setting("support_link", "")
    website_link = await database.get_setting("website_link", "")
    owner_label = await database.get_setting("owner_btn_label", "👑 Owner")
    admin_label = await database.get_setting("admin_btn_label", "🥷 Admin")
    support_label = await database.get_setting("support_btn_label", "🤝 Support")
    website_label = await database.get_setting("website_btn_label", "🌐 Website")
    enter_label = await database.get_setting("enter_btn_label", "🌑 Enter the System")

    rows = []
    row1 = []
    if owner_username:
        row1.append(InlineKeyboardButton(text=owner_label, url=f"https://t.me/{owner_username.lstrip('@')}"))
    if admin_username:
        row1.append(InlineKeyboardButton(text=admin_label, url=f"https://t.me/{admin_username.lstrip('@')}"))
    if row1:
        rows.append(row1)
    row2 = []
    if support_link:
        row2.append(InlineKeyboardButton(text=support_label, url=support_link))
    if website_link:
        row2.append(InlineKeyboardButton(text=website_label, url=website_link))
    if row2:
        rows.append(row2)

    if for_group and BOT_USERNAME:
        rows.append([InlineKeyboardButton(text=enter_label, url=f"https://t.me/{BOT_USERNAME}?start=fromgroup")])
    else:
        rows.append([InlineKeyboardButton(text=enter_label, callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_welcome(message: Message, name: str, extra_text: str = "") -> None:
    text = await build_welcome_text(name, extra_text)
    photo_id = await database.get_setting("welcome_photo", "")
    keyboard = await build_welcome_keyboard(for_group=False)

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


async def send_group_welcome(chat_id: int, name: str) -> None:
    text = await build_welcome_text(name)
    photo_id = await database.get_setting("welcome_photo", "")
    keyboard = await build_welcome_keyboard(for_group=True)
    try:
        if photo_id:
            await bot.send_photo(chat_id, photo_id, caption=text, reply_markup=keyboard)
        else:
            await bot.send_message(chat_id, text, reply_markup=keyboard)
    except TelegramBadRequest:
        if photo_id:
            await bot.send_photo(chat_id, photo_id, caption=text, reply_markup=keyboard, parse_mode=None)
        else:
            await bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode=None)


@router.message(F.new_chat_members)
async def new_group_member_handler(message: Message):
    for member in message.new_chat_members:
        if member.is_bot:
            continue
        await database.register_group(message.chat.id, message.chat.title or "")
        await send_group_welcome(message.chat.id, member.first_name or "Hunter")


async def track_group_activity(chat, user) -> None:
    """Registers the group, logs one activity point, and remembers this as the player's
    'home' group so personal reminders can be routed there instead of DM."""
    if chat.type not in {"group", "supergroup"}:
        return
    await database.register_group(chat.id, chat.title or "")
    await database.record_activity(chat.id, user.id, user.first_name or "Hunter")
    await database.set_last_active_chat(user.id, chat.id)


# ------------------------------------------------------------------ #
#  /start
# ------------------------------------------------------------------ #
@router.message(Command("start"))
async def log_new_user(user) -> None:
    channel_id = await database.get_setting("db_channel_id", "")
    if not channel_id:
        return
    text = (
        "🆕 <b>New Hunter Registered</b>\n\n"
        f"👤 Name: {html.escape(user.first_name or '')}\n"
        f"🔗 Username: @{user.username if user.username else '—'}\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"🕐 Time: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}"
    )
    try:
        await bot.send_message(int(channel_id), text)
    except Exception as e:
        LOG.warning(f"Could not log new user to DB channel: {e}")


async def start_handler(message: Message):
    user = message.from_user
    player = await database.get_player(user.id)
    is_new = player is None
    await database.get_or_create_player(user.id, user.first_name or "Hunter")
    name = user.first_name or "Hunter"

    payload = (message.text or "").split(maxsplit=1)
    ref_id = None
    if len(payload) > 1 and payload[1].startswith("ref_"):
        try:
            ref_id = int(payload[1][4:])
        except ValueError:
            ref_id = None

    if is_new:
        await log_new_user(user)
        if ref_id:
            await database.set_referrer(user.id, ref_id)
            await database.add_gold_xp(ref_id, gold=gd.REFERRAL_REWARD_GOLD)
            try:
                await bot.send_message(ref_id, f"🔗 <b>{html.escape(name)}</b> joined using your referral link! +{gd.REFERRAL_REWARD_GOLD} Gold")
            except Exception:
                pass
        await play_start_animation(message, name)

    await send_welcome(message, name)


@router.callback_query(F.data == "menu:main")
async def menu_main_cb(cb: CallbackQuery):
    await cb.answer()
    text = f"🌑 <b>Main Menu</b>\n\nWhat would you like to do, {html.escape(cb.from_user.first_name or 'Hunter')}?"
    markup = kb.main_menu_keyboard()
    if cb.message.photo:
        # Welcome message was a photo — can't edit_text a photo message, send a fresh one instead
        await cb.message.answer(text, reply_markup=markup)
        return
    try:
        await cb.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        await cb.message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "menu:story")
async def menu_story_cb(cb: CallbackQuery):
    await database.get_or_create_player(cb.from_user.id, cb.from_user.first_name or "Hunter")
    await cb.answer()
    text, markup = await render_story_node(cb.from_user.id, cb.message.chat.id)
    await cb.message.edit_text(text, reply_markup=markup)


@router.callback_query(F.data.startswith("story:"))
async def story_advance_cb(cb: CallbackQuery):
    user_id = cb.from_user.id
    next_node = cb.data.split(":", 1)[1]
    p = await database.get_player(user_id)
    await database.set_story_position(user_id, p["story_arc"], next_node)
    await cb.answer()
    text, markup = await render_story_node(user_id, cb.message.chat.id)
    await cb.message.edit_text(text, reply_markup=markup)


# ------------------------------------------------------------------ #
#  Battle
# ------------------------------------------------------------------ #
@router.callback_query(F.data.startswith("battle:"))
async def battle_action_cb(cb: CallbackQuery):
    await track_group_activity(cb.message.chat, cb.from_user)
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
        story_text, story_markup = await render_story_node(user_id, cb.message.chat.id)
        await cb.message.edit_text(f"{text}\n\n{story_text}", reply_markup=story_markup)
        await maybe_announce_levelup(user_id, cb.message.chat.id, summary)
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
    try:
        await database.get_or_create_player(cb.from_user.id, cb.from_user.first_name or "Hunter")
        await cb.answer()
        text, markup = await render_profile(cb.from_user.id)
        # Show the profile instantly — never block the main response on slow/stuck AI image calls
        await safe_edit(cb.message, text, markup)

        player = await database.get_player(cb.from_user.id)
        pool = await full_character_pool()
        char = pool.get(player["active_character"])
        if char:
            try:
                await send_generated_photo(
                    cb.message.chat.id, f"char:{player['active_character']}",
                    gemini_image.character_prompt(char["name"], char["rarity"]), text, markup,
                    existing_file_id=char.get("photo_file_id", ""),
                )
            except Exception as e:
                LOG.warning(f"Profile art follow-up failed for {cb.from_user.id}: {e}")
    except Exception as e:
        LOG.warning(f"menu_profile_cb failed for {cb.from_user.id}: {e}")
        try:
            await cb.message.answer(f"⚠️ Something went wrong loading your profile. Try again — if it keeps happening, tell the owner: {e}")
        except Exception:
            pass


@router.callback_query(F.data.startswith("stat:"))
async def stat_allocate_cb(cb: CallbackQuery):
    stat = cb.data.split(":", 1)[1]
    ok = await database.spend_stat_point(cb.from_user.id, stat)
    await cb.answer("✅ Stat increased!" if ok else "⚠️ No stat points available.")
    text, markup = await render_profile(cb.from_user.id)
    await safe_edit(cb.message, text, markup)


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
    try:
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
        await safe_edit(cb.message, text, kb.main_menu_button())
    except Exception as e:
        LOG.warning(f"menu_shadows_cb failed for {cb.from_user.id}: {e}")
        try:
            await cb.message.answer(f"⚠️ Something went wrong loading your Shadow Army. Try again — if it keeps happening, tell the owner: {e}")
        except Exception:
            pass


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
    await track_group_activity(cb.message.chat, cb.from_user)
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
    try:
        await database.get_or_create_player(message.from_user.id, message.from_user.first_name or "Hunter")
        text, markup = await render_profile(message.from_user.id)
        await message.answer(text, reply_markup=markup)

        player = await database.get_player(message.from_user.id)
        pool = await full_character_pool()
        char = pool.get(player["active_character"])
        if char:
            try:
                await send_generated_photo(
                    message.chat.id, f"char:{player['active_character']}",
                    gemini_image.character_prompt(char["name"], char["rarity"]), text, markup,
                    existing_file_id=char.get("photo_file_id", ""),
                )
            except Exception as e:
                LOG.warning(f"Profile art follow-up failed for {message.from_user.id}: {e}")
    except Exception as e:
        LOG.warning(f"profile_cmd failed for {message.from_user.id}: {e}")
        await message.answer(f"⚠️ Something went wrong loading your profile: {e}")


@router.message(Command("checkprofile"))
async def checkprofile_cmd(message: Message):
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.answer("⚠️ <b>Reply to a player's message</b> with <code>/checkprofile</code> to view their profile.")
        return
    target = message.reply_to_message.from_user
    if target.is_bot:
        await message.answer("❌ Can't check a bot's profile.")
        return
    player = await database.get_player(target.id)
    if not player:
        await message.answer("❌ That user hasn't started playing yet.")
        return
    pool = await full_character_pool()
    char = pool.get(player["active_character"])
    weapon = gd.WEAPONS.get(player["equipped_weapon"], {})
    text = (
        f"👤 <b>{html.escape(player['first_name'])}</b> — Rank {player['rank']} | Level {player['level']}\n\n"
        f"✨ XP: {player['xp']}/{player['xp_next']}\n"
        f"❤️ HP: {player['hp']}/{player['max_hp']}\n"
        f"🧙 Character: {char['name'] if char else '— none rolled'}\n"
        f"⚔️ Weapon: {weapon.get('name', '—')} (ATK {weapon.get('atk', 0)})\n\n"
        f"💪 STR {player['str_stat']}  🏃 AGI {player['agi_stat']}  🧠 INT {player['intel_stat']}\n"
        f"❤️ VIT {player['vit_stat']}  👁️ PER {player['per_stat']}\n\n"
        f"💰 Gold: {player['gold']}   💎 Gems: {player['gems']}"
    )
    await message.answer(text)
    if char:
        try:
            await send_generated_photo(
                message.chat.id, f"char:{player['active_character']}",
                gemini_image.character_prompt(char["name"], char["rarity"]), text,
                existing_file_id=char.get("photo_file_id", ""),
            )
        except Exception as e:
            LOG.warning(f"checkprofile art follow-up failed: {e}")


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
    pool = await full_character_pool()
    for char_id, info in pool.items():
        cumulative += info["rate"]
        if roll <= cumulative:
            chosen = char_id
            break
    chosen = chosen or "rookie_hunter"

    await database.update_player(user_id, gold=player["gold"] - gd.CHARACTER_ROLL_COST_GOLD)
    count = await database.add_character(user_id, chosen)
    if not player["active_character"]:
        await database.set_active_character(user_id, chosen)
    info = pool[chosen]
    caption = (
        f"🎲 <b>Roll complete!</b>\n\n"
        f"✨ You got: <b>{info['name']}</b> ({info['rarity']})\n"
        f"⚔️ Base ATK: {info['base_atk']}   ❤️ Base HP: {info['base_hp']}\n"
        f"📦 You now own {count}x {info['name']}"
    )
    sent = await send_generated_photo(
        cb.message.chat.id, f"char:{chosen}", gemini_image.character_prompt(info["name"], info["rarity"]),
        caption, kb.main_menu_button(), existing_file_id=info.get("photo_file_id", ""),
    )
    if not sent:
        await cb.message.edit_text(caption, reply_markup=kb.main_menu_button())
    await maybe_unlock_achievement(user_id, "legendary_character", info["rarity"] in {"Legendary", "Mythic"}, cb.message.chat.id)


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
    pool = await full_character_pool()
    for char_id, info in pool.items():
        cumulative += info["rate"]
        if roll <= cumulative:
            chosen = char_id
            break
    chosen = chosen or "rookie_hunter"
    await database.update_player(message.from_user.id, gold=player["gold"] - gd.CHARACTER_ROLL_COST_GOLD)
    count = await database.add_character(message.from_user.id, chosen)
    if not player["active_character"]:
        await database.set_active_character(message.from_user.id, chosen)
    info = pool[chosen]
    await message.answer(f"🎲 You got: <b>{info['name']}</b> ({info['rarity']})! You now own {count}x.")
    await maybe_unlock_achievement(message.from_user.id, "legendary_character", info["rarity"] in {"Legendary", "Mythic"}, message.chat.id)


@router.callback_query(F.data == "menu:characters")
async def menu_characters_cb(cb: CallbackQuery):
    user_id = cb.from_user.id
    owned = await database.get_characters(user_id)
    player = await database.get_player(user_id)
    pool = await full_character_pool()
    await cb.answer()
    if not owned:
        await cb.message.edit_text("🎲 <b>You don't own any characters yet.</b> Roll one from the main menu!", reply_markup=kb.main_menu_button())
        return
    await cb.message.edit_text("🧙 <b>Your Characters</b>\nTap one to set as active.", reply_markup=kb.characters_keyboard(owned, pool, player["active_character"]))


@router.callback_query(F.data == "menu:achievements")
async def menu_achievements_cb(cb: CallbackQuery):
    user_id = cb.from_user.id
    await database.get_or_create_player(user_id, cb.from_user.first_name or "Hunter")
    unlocked = await database.get_achievements(user_id)
    await cb.answer()
    if not unlocked:
        await cb.message.edit_text(
            "🏅 <b>Achievements</b>\n\n<i>None unlocked yet — play through gates, duels, story, and more to earn titles!</i>",
            reply_markup=kb.main_menu_button(),
        )
        return
    lines = []
    for aid in unlocked:
        info = gd.ACHIEVEMENTS.get(aid)
        if info:
            lines.append(f"✅ {info['name']} — <i>{info['desc']}</i>")
    locked_count = len(gd.ACHIEVEMENTS) - len(unlocked)
    text = f"🏅 <b>Achievements</b> ({len(unlocked)}/{len(gd.ACHIEVEMENTS)})\n\n" + "\n".join(lines)
    if locked_count > 0:
        text += f"\n\n🔒 {locked_count} more to discover..."
    await cb.message.edit_text(text, reply_markup=kb.achievements_keyboard(unlocked, gd.ACHIEVEMENTS))


@router.callback_query(F.data.startswith("equiptitle:"))
async def equip_title_cb(cb: CallbackQuery):
    aid = cb.data.split(":", 1)[1]
    if not await database.has_achievement(cb.from_user.id, aid):
        await cb.answer("You haven't unlocked that one.", show_alert=True)
        return
    info = gd.ACHIEVEMENTS.get(aid)
    if not info:
        await cb.answer("Unknown achievement.", show_alert=True)
        return
    await database.set_equipped_title(cb.from_user.id, info["title"])
    await cb.answer(f"✅ Title equipped: {info['title']}")
    unlocked = await database.get_achievements(cb.from_user.id)
    lines = [f"✅ {gd.ACHIEVEMENTS[a]['name']} — <i>{gd.ACHIEVEMENTS[a]['desc']}</i>" for a in unlocked if a in gd.ACHIEVEMENTS]
    text = f"🏅 <b>Achievements</b> ({len(unlocked)}/{len(gd.ACHIEVEMENTS)})\n\n" + "\n".join(lines) + f"\n\n🎖️ <b>Equipped title:</b> {info['title']}"
    await cb.message.edit_text(text, reply_markup=kb.achievements_keyboard(unlocked, gd.ACHIEVEMENTS))


@router.callback_query(F.data.startswith("setactive:"))
async def set_active_character_cb(cb: CallbackQuery):
    char_id = cb.data.split(":", 1)[1]
    await database.set_active_character(cb.from_user.id, char_id)
    pool = await full_character_pool()
    await cb.answer(f"✅ {pool.get(char_id, {}).get('name', char_id)} is now active!")
    owned = await database.get_characters(cb.from_user.id)
    await cb.message.edit_text("🧙 <b>Your Characters</b>\nTap one to set as active.", reply_markup=kb.characters_keyboard(owned, pool, char_id))


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
    cost = gd.ENERGY_COST["gate"]
    if not await database.spend_energy(user_id, cost):
        current, max_e, secs = await database.get_energy(user_id)
        m, s = divmod(secs, 60)
        await cb.answer(f"⚡ Not enough energy ({current}/{max_e}). Entering a gate costs {cost}. Next point in {m}m {s}s.", show_alert=True)
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
    sent = await send_generated_photo(
        cb.message.chat.id, f"gatemonster:{gate['monster']}",
        gemini_image.battle_prompt(monster["name"], gate["name"]), text, kb.gate_battle_keyboard(),
    )
    if not sent:
        await cb.message.edit_text(text, reply_markup=kb.gate_battle_keyboard())


@router.callback_query(F.data.startswith("gatebattle:"))
async def gate_battle_action_cb(cb: CallbackQuery):
    await track_group_activity(cb.message.chat, cb.from_user)
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
        await maybe_announce_levelup(user_id, cb.message.chat.id, summary)
        await maybe_unlock_achievement(user_id, "first_gate_win", True, cb.message.chat.id)
        player_after = await database.get_player(user_id)
        await maybe_unlock_achievement(user_id, "wealthy", player_after["gold"] >= 5000, cb.message.chat.id)
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
    await track_group_activity(cb.message.chat, cb.from_user)
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
    streak = await database.claim_daily_with_streak(user_id)
    bonus_gold = gd.STREAK_BONUS_PER_DAY["gold"] * streak
    bonus_gems = gd.STREAK_BONUS_PER_DAY["gems"] * streak
    await database.add_gold_xp(
        user_id,
        gold=r.get("gold", 0) + bonus_gold,
        gems=r.get("gems", 0) + bonus_gems,
        mana_crystals=r.get("mana_crystals", 0),
    )
    await cb.message.edit_text(
        f"📅 <b>Daily reward claimed!</b>\n\n"
        f"🔥 Streak: <b>{streak} day{'s' if streak != 1 else ''}</b> "
        f"(day {min(streak, gd.STREAK_MAX_DAYS)}/{gd.STREAK_MAX_DAYS} bonus)\n\n"
        f"💰 +{r.get('gold',0) + bonus_gold} Gold   💎 +{r.get('gems',0) + bonus_gems} Gems   "
        f"🔷 +{r.get('mana_crystals',0)} Mana Crystals\n\n"
        f"<i>Come back tomorrow to keep your streak alive — miss a day and it resets!</i>",
        reply_markup=kb.main_menu_button(),
    )
    await announce_to_group_if_dm(cb.message.chat, cb.from_user, f"📅 <b>{html.escape(cb.from_user.first_name or 'A hunter')}</b> claimed their daily mission! 🔥 {streak}-day streak.")
    await maybe_unlock_achievement(cb.from_user.id, "daily_streak_7", streak >= 7, cb.message.chat.id)


@router.callback_query(F.data == "menu:hourly")
async def menu_hourly_cb(cb: CallbackQuery):
    await track_group_activity(cb.message.chat, cb.from_user)
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
    await database.update_player(user_id, hourly_reminded=0)
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


@router.callback_query(F.data == "menu:buychar")
async def menu_buychar_cb(cb: CallbackQuery):
    await cb.answer()
    pool = await full_character_pool()
    mana_cost = lambda rarity: gd.RARITY_MANA_COST.get(rarity, gd.CHARACTER_BUY_COST_MANA)
    await cb.message.edit_text(
        "🎯 <b>Buy a Character</b>\n<i>Skip the RNG — pay Mana Crystals for a guaranteed character.</i>",
        reply_markup=kb.buy_character_keyboard(pool, mana_cost),
    )


@router.callback_query(F.data.startswith("buychar:"))
async def buychar_cb(cb: CallbackQuery):
    char_id = cb.data.split(":", 1)[1]
    pool = await full_character_pool()
    info = pool.get(char_id)
    if not info:
        await cb.answer("Unknown character.", show_alert=True)
        return
    user_id = cb.from_user.id
    player = await database.get_player(user_id)
    cost = gd.RARITY_MANA_COST.get(info["rarity"], gd.CHARACTER_BUY_COST_MANA)
    if player["mana_crystals"] < cost:
        await cb.answer(f"⚠️ Need {cost} Mana Crystals (you have {player['mana_crystals']}).", show_alert=True)
        return
    await database.update_player(user_id, mana_crystals=player["mana_crystals"] - cost)
    count = await database.add_character(user_id, char_id)
    if not player["active_character"]:
        await database.set_active_character(user_id, char_id)
    await cb.answer(f"✅ Purchased {info['name']}!")
    caption = f"✅ <b>Purchased!</b>\n\n🧙 <b>{info['name']}</b> ({info['rarity']})\n📦 You now own {count}x"
    sent = await send_generated_photo(
        cb.message.chat.id, f"char:{char_id}", gemini_image.character_prompt(info["name"], info["rarity"]),
        caption, kb.main_menu_button(), existing_file_id=info.get("photo_file_id", ""),
    )
    if not sent:
        await safe_edit(cb.message, caption, kb.main_menu_button())
    await maybe_unlock_achievement(user_id, "legendary_character", info["rarity"] in {"Legendary", "Mythic"}, cb.message.chat.id)


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
#  Lucky Wheel
# ------------------------------------------------------------------ #
@router.callback_query(F.data == "menu:wheel")
async def menu_wheel_cb(cb: CallbackQuery):
    await track_group_activity(cb.message.chat, cb.from_user)
    user_id = cb.from_user.id
    await database.get_or_create_player(user_id, cb.from_user.first_name or "Hunter")
    can_free = await database.freespin_available(user_id)
    await cb.answer()
    await cb.message.edit_text(
        "🎡 <b>Lucky Wheel</b>\n\nSpin for gold, gems, resources — or the jackpot!",
        reply_markup=kb.wheel_keyboard(can_free),
    )


def _spin_wheel() -> dict:
    roll = random.random()
    cumulative = 0.0
    for prize in gd.WHEEL_PRIZES:
        cumulative += prize["rate"]
        if roll <= cumulative:
            return prize
    return gd.WHEEL_PRIZES[0]


@router.callback_query(F.data.startswith("wheel:"))
async def wheel_spin_cb(cb: CallbackQuery):
    try:
        kind = cb.data.split(":", 1)[1]
        user_id = cb.from_user.id

        if kind == "free":
            if not await database.freespin_available(user_id):
                await cb.answer("Already used your free spin today.", show_alert=True)
                return
            await database.use_freespin(user_id)
        else:
            player = await database.get_player(user_id)
            if player["gems"] < gd.WHEEL_SPIN_COST_GEMS:
                await cb.answer(f"⚠️ Need {gd.WHEEL_SPIN_COST_GEMS} gems to spin.", show_alert=True)
                return
            await database.update_player(user_id, gems=player["gems"] - gd.WHEEL_SPIN_COST_GEMS)

        prize = _spin_wheel()
        await database.add_gold_xp(
            user_id, gold=prize.get("gold", 0), gems=prize.get("gems", 0),
            mana_crystals=prize.get("mana", 0), essence_stones=prize.get("essence", 0),
        )
        await cb.answer("🎉 Spinning!")

        try:
            dice_msg = await bot.send_dice(cb.message.chat.id, emoji="🎰")
            await asyncio.sleep(2.5)  # let the native Telegram slot-machine animation play out
            try:
                await dice_msg.delete()
            except Exception:
                pass
        except Exception as e:
            LOG.warning(f"Could not send slot machine animation: {e}")

        can_free = await database.freespin_available(user_id)
        await cb.message.answer(
            f"🎡 <b>The wheel lands on:</b>\n\n✨ <b>{prize['label']}</b>",
            reply_markup=kb.wheel_keyboard(can_free),
        )
    except Exception as e:
        LOG.warning(f"wheel_spin_cb failed for {cb.from_user.id}: {e}")
        try:
            await cb.answer("⚠️ Something went wrong.", show_alert=True)
        except Exception:
            pass
        try:
            await cb.message.answer(f"⚠️ The wheel jammed. Try again — if it keeps happening, tell the owner: {e}")
        except Exception:
            pass


# ------------------------------------------------------------------ #
#  Guild system
# ------------------------------------------------------------------ #
@router.callback_query(F.data == "menu:guild")
async def menu_guild_cb(cb: CallbackQuery):
    await track_group_activity(cb.message.chat, cb.from_user)
    user_id = cb.from_user.id
    await database.get_or_create_player(user_id, cb.from_user.first_name or "Hunter")
    player = await database.get_player(user_id)
    await cb.answer()
    if not player["guild_id"]:
        await cb.message.edit_text(
            "🏯 <b>You're not in a guild yet.</b>\nCreate one or join an existing one.",
            reply_markup=kb.guild_none_keyboard(),
        )
        return
    guild = await database.get_guild(player["guild_id"])
    count = await database.guild_member_count(player["guild_id"])
    text = (
        f"🏯 <b>{guild['name']}</b>\n\n"
        f"👥 Members: {count}\n"
        f"💰 Vault Gold: {guild['vault_gold']}\n"
        f"💎 Vault Gems: {guild['vault_gems']}\n"
        f"🔷 Vault Mana: {guild['vault_mana']}\n"
        f"🔶 Vault Essence: {guild['vault_essence']}"
    )
    await cb.message.edit_text(text, reply_markup=kb.guild_joined_keyboard())


@router.callback_query(F.data == "guild:create")
async def guild_create_cb(cb: CallbackQuery):
    AWAITING[cb.from_user.id] = "guild_create"
    await cb.answer()
    await cb.message.edit_text("🏯 <b>Send a name for your new guild.</b>", reply_markup=kb.back_to_settings_keyboard())


@router.callback_query(F.data == "guild:browse")
async def guild_browse_cb(cb: CallbackQuery):
    top = await database.top_guilds(10)
    await cb.answer()
    if not top:
        text = "🔎 <b>No guilds exist yet.</b> Be the first to create one!"
    else:
        lines = [f"{i}. {g['name']} — 💰{g['vault_gold']}" for i, g in enumerate(top, start=1)]
        text = "🔎 <b>Guilds</b>\n\n" + "\n".join(lines) + "\n\n<i>Send the guild name to join it.</i>"
        AWAITING[cb.from_user.id] = "guild_join"
    await cb.message.edit_text(text, reply_markup=kb.guild_none_keyboard())


@router.callback_query(F.data == "guild:leave")
async def guild_leave_cb(cb: CallbackQuery):
    await database.leave_guild(cb.from_user.id)
    await cb.answer("You left the guild.")
    await cb.message.edit_text("🚪 <b>You left your guild.</b>", reply_markup=kb.guild_none_keyboard())


@router.callback_query(F.data == "guild:members")
async def guild_members_cb(cb: CallbackQuery):
    player = await database.get_player(cb.from_user.id)
    await cb.answer()
    if not player["guild_id"]:
        await cb.message.edit_text("🏯 <b>You're not in a guild.</b>", reply_markup=kb.guild_none_keyboard())
        return
    members = await database.guild_members(player["guild_id"])
    lines = [f"• {m['first_name']} — Lv.{m['level']}" for m in members]
    await cb.message.edit_text("👥 <b>Guild Members</b>\n\n" + "\n".join(lines), reply_markup=kb.guild_joined_keyboard())


@router.callback_query(F.data == "guild:top")
async def guild_top_cb(cb: CallbackQuery):
    top = await database.top_guilds(10)
    await cb.answer()
    lines = [f"{i}. {g['name']} — 💰{g['vault_gold']}" for i, g in enumerate(top, start=1)] or ["No guilds yet."]
    await cb.message.edit_text("🏆 <b>Top Guilds</b>\n\n" + "\n".join(lines), reply_markup=kb.guild_joined_keyboard())


@router.callback_query(F.data.startswith("guild:contribute:"))
async def guild_contribute_cb(cb: CallbackQuery):
    resource = cb.data.split(":")[2]
    player = await database.get_player(cb.from_user.id)
    if not player["guild_id"]:
        await cb.answer("You're not in a guild.", show_alert=True)
        return
    AWAITING[cb.from_user.id] = f"guild_contribute_{resource}"
    await cb.answer()
    await cb.message.edit_text(f"💰 <b>Send the amount of {resource} to contribute.</b>", reply_markup=kb.back_to_settings_keyboard())


# ------------------------------------------------------------------ #
#  Group Activity Leaderboard
# ------------------------------------------------------------------ #
@router.callback_query(F.data == "menu:activity")
async def menu_activity_cb(cb: CallbackQuery):
    await cb.answer()
    if cb.message.chat.type not in {"group", "supergroup"}:
        await cb.message.edit_text(
            "📊 <b>Group Activity</b>\n\n<i>This only works inside a group — add me to your group and play there!</i>",
            reply_markup=kb.main_menu_button(),
        )
        return
    top = await database.top_activity_today(cb.message.chat.id, 10)
    if not top:
        text = "📊 <b>No activity recorded yet today.</b>\nPlay a battle, gate, quiz, or duel to show up here!"
    else:
        lines = [f"{i}. {html.escape(r['first_name'])} — {r['action_count']} actions" for i, r in enumerate(top, start=1)]
        text = "📊 <b>Today's Most Active Hunters</b>\n\n" + "\n".join(lines)
    await cb.message.edit_text(text, reply_markup=kb.main_menu_button())


# ------------------------------------------------------------------ #
#  Group Quiz answers (first correct wins)
# ------------------------------------------------------------------ #
@router.callback_query(F.data.startswith("gquiz:"))
async def group_quiz_answer_cb(cb: CallbackQuery):
    _, chat_id_str, sel_str = cb.data.split(":")
    chat_id, sel = int(chat_id_str), int(sel_str)
    await track_group_activity(cb.message.chat, cb.from_user)
    await database.get_or_create_player(cb.from_user.id, cb.from_user.first_name or "Hunter")

    quiz = await database.get_group_quiz(chat_id)
    if not quiz or quiz["closed"]:
        await cb.answer("This quiz already closed.", show_alert=True)
        return
    q = gd.QUIZ_QUESTIONS[quiz["question_idx"]]
    if sel != q["answer"]:
        await cb.answer("❌ Wrong answer!", show_alert=True)
        return

    won = await database.close_group_quiz(chat_id)
    if not won:
        await cb.answer("Someone already answered correctly!", show_alert=True)
        return

    await database.add_gold_xp(cb.from_user.id, gold=gd.GROUP_QUIZ_REWARD_GOLD, xp=gd.GROUP_QUIZ_REWARD_XP)
    await database.clear_group_quiz(chat_id)
    await cb.answer("✅ Correct! You won!")
    await cb.message.edit_text(
        f"❓ <b>Group Quiz</b>\n\n{q['q']}\n\n"
        f"🏆 <b>{html.escape(cb.from_user.first_name or 'A hunter')}</b> answered correctly first and won "
        f"💰{gd.GROUP_QUIZ_REWARD_GOLD} + ✨{gd.GROUP_QUIZ_REWARD_XP}XP!",
        reply_markup=None,
    )


# ------------------------------------------------------------------ #
#  Wild Gates (group-wide auto-spawning boss events)
# ------------------------------------------------------------------ #
@router.callback_query(F.data == "wildgate:attack")
async def wildgate_attack_cb(cb: CallbackQuery):
    if cb.message.chat.type not in {"group", "supergroup"}:
        await cb.answer("Wild Gates only spawn in groups.", show_alert=True)
        return
    await track_group_activity(cb.message.chat, cb.from_user)
    user_id = cb.from_user.id
    chat_id = cb.message.chat.id
    await database.get_or_create_player(user_id, cb.from_user.first_name or "Hunter")

    gate = await database.get_wild_gate(chat_id)
    if not gate:
        await cb.answer("No active Wild Gate right now.", show_alert=True)
        return
    if gate["expires_at"] <= int(time.time()):
        await cb.answer("This Wild Gate already escaped!", show_alert=True)
        return

    atk = await player_attack_power(user_id)
    damage = max(1, atk + random.randint(-3, 5))
    remaining_hp = await database.wild_gate_deal_damage(chat_id, user_id, damage)
    await cb.answer(f"⚔️ You dealt {damage} damage!")

    if remaining_hp > 0:
        await cb.message.reply(
            f"⚔️ <b>{html.escape(cb.from_user.first_name or 'A hunter')}</b> hit the "
            f"<b>{gate['monster_name']}</b> for {damage}!\n❤️ {remaining_hp}/{gate['max_hp']} HP remaining."
        )
        return

    rewards = json.loads(gate["rewards_json"])
    participants = await database.wild_gate_participants(chat_id)
    total_damage = sum(p["damage"] for p in participants) or 1
    await database.clear_wild_gate(chat_id)

    active_count = await database.active_players_today(chat_id)
    bonus = min(gd.GROUP_BONUS_MAX, (active_count // gd.GROUP_BONUS_ACTIVE_PLAYERS_STEP) * gd.GROUP_BONUS_PER_ACTIVE_PLAYERS)

    lines = [f"🏆 <b>The {gate['monster_name']} has been defeated!</b>"]
    if bonus > 0:
        lines.append(f"🔥 <i>Active-group bonus: +{int(bonus * 100)}% rewards ({active_count} active hunters today)</i>")
    lines.append("")
    for p in participants[:10]:
        share = p["damage"] / total_damage
        gold = max(1, int(rewards.get("gold", 0) * share * (1 + bonus)))
        xp = max(1, int(rewards.get("xp", 0) * share * (1 + bonus)))
        mana = int(rewards.get("mana", 0) * share * (1 + bonus))
        essence = int(rewards.get("essence", 0) * share * (1 + bonus))
        gems = int(rewards.get("gems", 0) * share * (1 + bonus))
        summary = await database.add_gold_xp(p["user_id"], gold=gold, xp=xp, mana_crystals=mana, essence_stones=essence, gems=gems)
        lines.append(f"• {html.escape(p['first_name'])} — {p['damage']} dmg → 💰{gold} ✨{xp}xp")
        await maybe_unlock_achievement(p["user_id"], "first_wildgate", True, chat_id)
        if summary.get("levels_gained"):
            try:
                await bot.send_message(p["user_id"], f"🆙 <b>Level up from the Wild Gate victory!</b> Now level {summary['level']}.")
            except Exception:
                pass
    await cb.message.reply("\n".join(lines))


@router.message(Command("redeem"))
async def redeem_cmd(message: Message, command: CommandObject):
    await database.get_or_create_player(message.from_user.id, message.from_user.first_name or "Hunter")
    code = (command.args or "").strip()
    if not code:
        await message.answer("⚠️ <b>Usage:</b> <code>/redeem CODE</code>")
        return
    reward = await database.redeem_coupon(code, message.from_user.id)
    if not reward:
        await message.answer("❌ <b>Invalid, expired, or already-used code.</b>")
        return
    await database.add_gold_xp(
        message.from_user.id, gold=reward["gold"], gems=reward["gems"],
        mana_crystals=reward["mana"], essence_stones=reward["essence"],
    )
    await message.answer(
        f"✅ <b>Code redeemed!</b>\n\n💰 +{reward['gold']} Gold   💎 +{reward['gems']} Gems   "
        f"🔷 +{reward['mana']} Mana   🔶 +{reward['essence']} Essence"
    )


@router.message(Command("referral"))
async def referral_cmd(message: Message):
    await database.get_or_create_player(message.from_user.id, message.from_user.first_name or "Hunter")
    player = await database.get_player(message.from_user.id)
    link = f"https://t.me/{BOT_USERNAME}?start=ref_{message.from_user.id}"
    await message.answer(
        f"🔗 <b>Your Referral Link</b>\n{link}\n\n"
        f"👥 Friends invited: <b>{player['referral_count']}</b>\n"
        f"💰 You earn {gd.REFERRAL_REWARD_GOLD} Gold per new friend who joins!"
    )


@router.message(Command("rob"))
async def rob_cmd(message: Message):
    await track_group_activity(message.chat, message.from_user)
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.answer("⚠️ <b>Reply to a player's message</b> with <code>/rob</code> to try robbing them.")
        return
    target = message.reply_to_message.from_user
    if target.is_bot or target.id == message.from_user.id:
        await message.answer("❌ Can't rob that.")
        return
    await database.get_or_create_player(message.from_user.id, message.from_user.first_name or "Hunter")
    if not await database.get_player(target.id):
        await message.answer("❌ That user hasn't started playing yet.")
        return
    remaining = await database.rob_cooldown_remaining(message.from_user.id)
    if remaining > 0:
        m, s = divmod(remaining, 60)
        await message.answer(f"🔒 <b>On cooldown.</b> Try again in {m}m {s}s.")
        return
    result = await database.do_rob(message.from_user.id, target.id)
    if result["success"]:
        await message.answer(f"🥷 <b>Success!</b> You stole 💰{result['stolen']} gold from {html.escape(target.first_name or 'them')}!")
    else:
        await message.answer(f"🚨 <b>Caught!</b> You got fined 💰{result['fine']} gold.")


@router.message(Command("slots"))
async def slots_cmd(message: Message):
    await track_group_activity(message.chat, message.from_user)
    await database.get_or_create_player(message.from_user.id, message.from_user.first_name or "Hunter")
    player = await database.get_player(message.from_user.id)
    if player["gold"] < gd.SLOTS_COST_GOLD:
        await message.answer(f"⚠️ Need {gd.SLOTS_COST_GOLD} gold to play (you have {player['gold']}).")
        return
    await database.update_player(message.from_user.id, gold=player["gold"] - gd.SLOTS_COST_GOLD)
    dice_msg = await bot.send_dice(message.chat.id, emoji="🎰")
    await asyncio.sleep(2.5)
    value = dice_msg.dice.value  # 1-64, 64 is a jackpot (three 7s)
    if value == 64:
        win = gd.SLOTS_COST_GOLD * 10
    elif value in (1, 22, 43):  # three-of-a-kind combos
        win = gd.SLOTS_COST_GOLD * 4
    elif value % 7 == 0:
        win = gd.SLOTS_COST_GOLD * 2
    else:
        win = 0
    if win:
        await database.add_gold_xp(message.from_user.id, gold=win)
        await message.answer(f"🎰 <b>You won 💰{win} Gold!</b>")
    else:
        await message.answer("🎰 <b>No win this time.</b> Try again!")


@router.message(Command("bank"))
async def bank_cmd(message: Message, command: CommandObject):
    await database.get_or_create_player(message.from_user.id, message.from_user.first_name or "Hunter")
    args = (command.args or "").strip().split()
    player = await database.get_player(message.from_user.id)
    if not args:
        await message.answer(
            f"🏦 <b>Bank</b>\n\n💰 Wallet: {player['gold']}\n🏦 Banked: {player['bank_gold']}\n\n"
            f"<code>/bank deposit [amount]</code>\n<code>/bank withdraw [amount]</code>\n"
            f"<i>Banked gold earns {int(gd.BANK_DAILY_INTEREST*100)}% interest per day.</i>"
        )
        return
    if len(args) != 2 or args[0] not in {"deposit", "withdraw"}:
        await message.answer("⚠️ Usage: <code>/bank deposit [amount]</code> or <code>/bank withdraw [amount]</code>")
        return
    try:
        amount = int(args[1])
    except ValueError:
        await message.answer("❌ Amount must be a number.")
        return
    ok = await (database.bank_deposit(message.from_user.id, amount) if args[0] == "deposit" else database.bank_withdraw(message.from_user.id, amount))
    if not ok:
        await message.answer("❌ Not enough funds.")
        return
    await message.answer(f"✅ {'Deposited' if args[0]=='deposit' else 'Withdrew'} 💰{amount}.")


@router.message(Command("testai"))
async def test_ai_cmd(message: Message):
    if not _is_owner(message.from_user.id):
        return
    if not gemini_image.is_configured():
        await message.answer("❌ <b>GEMINI_API_KEY is not set</b> in your environment variables.")
        return
    ai_on = await database.get_setting("ai_images_enabled", "0") == "1"
    status = await message.answer(f"🔎 <b>Testing Gemini...</b>\nAI Images toggle: {'🟢 ON' if ai_on else '🔴 OFF'}\nKey configured: ✅\n\nGenerating a test image...")
    image_bytes = await gemini_image.generate_image("a glowing blue magic portal, fantasy digital art, no text")
    if not image_bytes:
        await status.edit_text(
            f"❌ <b>Gemini call failed.</b>\nAI Images toggle: {'🟢 ON' if ai_on else '🔴 OFF — turn it on via /setting'}\n"
            f"Key configured: ✅\n\nCheck Railway logs for 'Gemini image request failed' for the exact API error."
        )
        return
    await status.delete()
    await message.answer_photo(BufferedInputFile(image_bytes, filename="test.png"), caption="✅ Gemini is working correctly!")


# ------------------------------------------------------------------ #
#  PvP Duels (group-friendly — reply to a user's message with /duel)
# ------------------------------------------------------------------ #
@router.message(Command("duel"))
async def duel_cmd(message: Message):
    await track_group_activity(message.chat, message.from_user)
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

    cost = gd.ENERGY_COST["duel"]
    if not await database.spend_energy(challenger.id, cost):
        current, max_e, secs = await database.get_energy(challenger.id)
        m, s = divmod(secs, 60)
        await message.answer(f"⚡ Not enough energy ({current}/{max_e}). Dueling costs {cost}. Next point in {m}m {s}s.")
        return

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
    await track_group_activity(cb.message.chat, cb.from_user)
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
        cost = gd.ENERGY_COST["duel"]
        if not await database.spend_energy(user_id, cost):
            current, max_e, secs = await database.get_energy(user_id)
            m, s = divmod(secs, 60)
            await cb.answer(f"⚡ Not enough energy ({current}/{max_e}). Dueling costs {cost}. Next point in {m}m {s}s.", show_alert=True)
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
            await maybe_unlock_achievement(winner["user_id"], "first_pvp_win", True, cb.message.chat.id)
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
    ai_on = await database.get_setting("ai_images_enabled", "0") == "1"
    bot_on = await database.get_setting("bot_enabled", "1") == "1"
    await message.answer("⚙️ <b>Bot Settings</b>\nCustomize the /start welcome experience.", reply_markup=kb.settings_main_keyboard(ai_on, bot_on))


@router.callback_query(F.data == "set:main")
async def set_main_cb(cb: CallbackQuery):
    if not _is_owner(cb.from_user.id):
        await cb.answer("⛔ Owner only.", show_alert=True)
        return
    AWAITING.pop(cb.from_user.id, None)
    await cb.answer()
    ai_on = await database.get_setting("ai_images_enabled", "0") == "1"
    bot_on = await database.get_setting("bot_enabled", "1") == "1"
    await cb.message.edit_text("⚙️ <b>Bot Settings</b>\nCustomize the /start welcome experience.", reply_markup=kb.settings_main_keyboard(ai_on, bot_on))


@router.callback_query(F.data == "set:toggleaiimages")
async def toggle_ai_images_cb(cb: CallbackQuery):
    if not _is_owner(cb.from_user.id):
        await cb.answer("⛔ Owner only.", show_alert=True)
        return
    current = await database.get_setting("ai_images_enabled", "0") == "1"
    if not current and not gemini_image.is_configured():
        await cb.answer("⚠️ Set GEMINI_API_KEY in your environment first.", show_alert=True)
        return
    await database.set_setting("ai_images_enabled", "0" if current else "1")
    ai_on = not current
    bot_on = await database.get_setting("bot_enabled", "1") == "1"
    await cb.answer(f"AI Images turned {'ON' if ai_on else 'OFF'}.")
    await cb.message.edit_text("⚙️ <b>Bot Settings</b>\nCustomize the /start welcome experience.", reply_markup=kb.settings_main_keyboard(ai_on, bot_on))


@router.callback_query(F.data == "set:togglebot")
async def toggle_bot_cb(cb: CallbackQuery):
    if not _is_owner(cb.from_user.id):
        await cb.answer("⛔ Owner only.", show_alert=True)
        return
    current = await database.get_setting("bot_enabled", "1") == "1"
    await database.set_setting("bot_enabled", "0" if current else "1")
    bot_on = not current
    ai_on = await database.get_setting("ai_images_enabled", "0") == "1"
    await cb.answer(f"Bot turned {'ON' if bot_on else 'OFF'}.")
    await cb.message.edit_text("⚙️ <b>Bot Settings</b>\nCustomize the /start welcome experience.", reply_markup=kb.settings_main_keyboard(ai_on, bot_on))


@router.callback_query(F.data == "set:labels")
async def set_labels_cb(cb: CallbackQuery):
    if not _is_owner(cb.from_user.id):
        await cb.answer("⛔ Owner only.", show_alert=True)
        return
    await cb.answer()
    await cb.message.edit_text("✏️ <b>Which button's label do you want to change?</b>", reply_markup=kb.button_labels_keyboard())


@router.callback_query(F.data.startswith("set:label:"))
async def set_label_pick_cb(cb: CallbackQuery):
    if not _is_owner(cb.from_user.id):
        await cb.answer("⛔ Owner only.", show_alert=True)
        return
    which = cb.data.split(":")[2]
    AWAITING[cb.from_user.id] = f"label_{which}"
    await cb.answer()
    await cb.message.edit_text(f"✏️ <b>Send the new label text</b> for the {which} button (emoji + text is fine, e.g. <code>🔥 Owner</code>).", reply_markup=kb.back_to_settings_keyboard())


@router.callback_query(F.data == "set:premiumemoji")
async def set_premiumemoji_cb(cb: CallbackQuery):
    if not _is_owner(cb.from_user.id):
        await cb.answer("⛔ Owner only.", show_alert=True)
        return
    await cb.answer()
    await cb.message.edit_text(
        "✨ <b>Premium Emoji</b>\n\n"
        "Send a message containing a <b>custom/Premium emoji</b> (forward one, or type it if you have "
        "Telegram Premium). I'll use it to decorate key bot messages.\n\n"
        "<i>Note: custom emoji only render for other Premium users — everyone else sees the fallback "
        "character automatically.</i>",
        reply_markup=kb.back_to_settings_keyboard(),
    )
    AWAITING[cb.from_user.id] = "premium_emoji"


@router.message(F.entities.func(lambda entities: any(e.type == "custom_emoji" for e in (entities or []))))
async def awaiting_premium_emoji_handler(message: Message):
    if AWAITING.get(message.from_user.id) != "premium_emoji":
        return
    custom = next((e for e in message.entities if e.type == "custom_emoji"), None)
    if not custom:
        return
    AWAITING.pop(message.from_user.id, None)
    fallback = message.text[custom.offset: custom.offset + custom.length] if message.text else "🌑"
    await database.set_setting("premium_emoji_id", custom.custom_emoji_id)
    await database.set_setting("premium_emoji_fallback", fallback)
    await message.answer("✅ <b>Premium emoji saved!</b> It'll now appear on welcome/level-up messages.", reply_markup=kb.settings_main_keyboard())


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
    state = AWAITING.get(user_id)
    if state == "new_character_photo":
        AWAITING.pop(user_id, None)
        await message.answer("📢 <b>Broadcasting new character to all players...</b>")
        await _finalize_new_character(user_id, message.photo[-1].file_id)
        return
    if state != "welcome_photo":
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

    if key == "new_character_photo" and text.lower() == "skip":
        AWAITING.pop(user_id, None)
        await message.answer("📢 <b>Broadcasting new character to all players...</b>")
        await _finalize_new_character(user_id, "")
        return

    if key.startswith("label_"):
        which = key.replace("label_", "")
        setting_key = {
            "owner": "owner_btn_label", "admin": "admin_btn_label",
            "support": "support_btn_label", "website": "website_btn_label",
            "enter": "enter_btn_label",
        }.get(which)
        AWAITING.pop(user_id, None)
        if not setting_key:
            return
        await database.set_setting(setting_key, text)
        await message.answer("✅ <b>Label updated!</b>", reply_markup=kb.button_labels_keyboard())
        return

    if key == "premium_emoji":
        await message.answer(
            "⚠️ <b>That doesn't contain a custom/Premium emoji.</b> Send a message with one, "
            "or tap Back to cancel.", reply_markup=kb.back_to_settings_keyboard(),
        )
        return

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

    elif key == "guild_create":
        AWAITING.pop(user_id, None)
        if len(text) < 3 or len(text) > 32:
            await message.answer("❌ Guild name must be 3-32 characters. Try again from the Guild menu.")
            return
        guild_id = await database.create_guild(text, user_id)
        if guild_id is None:
            await message.answer("❌ That guild name is already taken.")
            return
        await message.answer(f"🏯 <b>Guild '{html.escape(text)}' created!</b> You're now the guild owner.", reply_markup=kb.guild_joined_keyboard())
        await maybe_unlock_achievement(user_id, "guild_member", True, message.chat.id)

    elif key == "guild_join":
        AWAITING.pop(user_id, None)
        guild = await database.get_guild_by_name(text)
        if not guild:
            await message.answer("❌ No guild found with that name.")
            return
        await database.join_guild(user_id, guild["guild_id"])
        await message.answer(f"🏯 <b>You joined {html.escape(guild['name'])}!</b>", reply_markup=kb.guild_joined_keyboard())
        await maybe_unlock_achievement(user_id, "guild_member", True, message.chat.id)

    elif key.startswith("guild_contribute_"):
        resource = key.replace("guild_contribute_", "")
        AWAITING.pop(user_id, None)
        try:
            amount = int(text)
        except ValueError:
            await message.answer("❌ Send a whole number.")
            return
        if amount <= 0:
            await message.answer("❌ Amount must be positive.")
            return
        player = await database.get_player(user_id)
        ok = await database.contribute_to_guild(
            user_id, player["guild_id"],
            gold=amount if resource == "gold" else 0,
            gems=amount if resource == "gems" else 0,
            mana=amount if resource == "mana" else 0,
            essence=amount if resource == "essence" else 0,
        )
        if not ok:
            await message.answer(f"❌ You don't have {amount} {resource}.")
            return
        await message.answer(f"✅ <b>Contributed {amount} {resource} to the guild vault!</b>", reply_markup=kb.guild_joined_keyboard())


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
        "<code>/broadcast [text]</code> — message every player\n\n"
        "<code>/createcoupon CODE GOLD GEMS MANA ESSENCE MAX_USES</code>\n"
        "<code>/newcharacter Name | Rarity | ATK | HP | Rate</code> — then send a photo (or 'skip')\n"
        "<code>/setdbchannel [channel_id]</code> — periodic DB backups\n"
        "<code>/backupnow</code> — trigger a backup immediately\n\n"
        "<code>/listmonsters</code> — see all monster IDs\n"
        "<code>/setmonsterimage [id]</code> — reply to a photo to set custom monster art\n"
        "<code>/setcharacterimage [id]</code> — reply to a photo to set custom character art\n"
        "✨ Premium Emoji — set via /setting → Premium Emoji"
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


PENDING_CHARACTER: dict[int, dict] = {}  # owner_id -> pending new-character data


@router.message(Command("createcoupon"))
async def create_coupon_cmd(message: Message, command: CommandObject):
    if not _is_owner(message.from_user.id):
        return
    parts = (command.args or "").split()
    if len(parts) != 6:
        await message.answer("⚠️ Usage: <code>/createcoupon CODE GOLD GEMS MANA ESSENCE MAX_USES</code>")
        return
    code, gold, gems, mana, essence, max_uses = parts
    try:
        gold, gems, mana, essence, max_uses = int(gold), int(gems), int(mana), int(essence), int(max_uses)
    except ValueError:
        await message.answer("❌ Gold/gems/mana/essence/max_uses must be numbers.")
        return
    await database.create_coupon(code, gold, gems, mana, essence, max_uses)
    await message.answer(f"✅ <b>Coupon <code>{code.upper()}</code> created.</b>\nUsable {max_uses}x, redeemable via <code>/redeem {code.upper()}</code>")


@router.message(Command("newcharacter"))
async def new_character_cmd(message: Message, command: CommandObject):
    if not _is_owner(message.from_user.id):
        return
    parts = [p.strip() for p in (command.args or "").split("|")]
    if len(parts) != 5:
        await message.answer("⚠️ Usage: <code>/newcharacter Name | Rarity | ATK | HP | Rate</code>\ne.g. <code>/newcharacter Iron Fang Knight | Epic | 45 | 60 | 0.03</code>")
        return
    name, rarity, atk_s, hp_s, rate_s = parts
    try:
        atk, hp, rate = int(atk_s), int(hp_s), float(rate_s)
    except ValueError:
        await message.answer("❌ ATK/HP must be whole numbers, Rate must be a decimal (e.g. 0.03).")
        return
    character_id = "custom_" + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    PENDING_CHARACTER[message.from_user.id] = {
        "character_id": character_id, "name": name, "rarity": rarity, "atk": atk, "hp": hp, "rate": rate,
    }
    AWAITING[message.from_user.id] = "new_character_photo"
    await message.answer(f"🧙 <b>{html.escape(name)}</b> ready. Now send a photo for this character, or type <code>skip</code>.")


async def _finalize_new_character(owner_id: int, photo_file_id: str = "") -> None:
    data = PENDING_CHARACTER.pop(owner_id, None)
    if not data:
        return

    if not photo_file_id and await ai_images_on():
        image_bytes = await gemini_image.generate_image(gemini_image.character_prompt(data["name"], data["rarity"]))
        if image_bytes:
            try:
                preview = await bot.send_photo(owner_id, BufferedInputFile(image_bytes, filename="art.png"), caption="🎨 Auto-generated art for this character.")
                photo_file_id = preview.photo[-1].file_id
            except Exception as e:
                LOG.warning(f"Could not upload auto-generated character art: {e}")

    await database.add_custom_character(
        data["character_id"], data["name"], data["rarity"], data["atk"], data["hp"],
        photo_file_id=photo_file_id, rate=data["rate"],
    )
    if photo_file_id:
        await database.cache_image(f"char:{data['character_id']}", photo_file_id)
    user_ids = await database.all_user_ids()
    caption = (
        f"🆕 <b>New Character Available!</b>\n\n"
        f"🧙 <b>{html.escape(data['name'])}</b> ({data['rarity']})\n"
        f"⚔️ ATK +{data['atk']}   ❤️ HP +{data['hp']}\n\n"
        f"Roll for a chance to get it — /roll or the Roll Character button!"
    )
    sent, failed = 0, 0
    for uid in user_ids:
        try:
            if photo_file_id:
                await bot.send_photo(uid, photo_file_id, caption=caption)
            else:
                await bot.send_message(uid, caption)
            sent += 1
        except Exception:
            failed += 1
    await bot.send_message(owner_id, f"✅ <b>{html.escape(data['name'])} added and announced!</b>\n📢 Sent: {sent}   ❌ Failed: {failed}")


@router.message(Command("setdbchannel"))
async def set_db_channel_cmd(message: Message, command: CommandObject):
    if not _is_owner(message.from_user.id):
        return
    arg = (command.args or "").strip()
    try:
        int(arg)
    except ValueError:
        await message.answer("⚠️ Usage: <code>/setdbchannel [channel_id]</code>")
        return
    await database.set_setting("db_channel_id", arg)
    await message.answer(f"✅ Database channel set to <code>{arg}</code>.\n📝 New hunters get logged there live, plus a full DB backup runs automatically every 6 hours.")


@router.message(Command("backupnow"))
async def backup_now_cmd(message: Message):
    if not _is_owner(message.from_user.id):
        return
    channel_id = await database.get_setting("db_channel_id", "")
    if not channel_id:
        await message.answer("⚠️ No DB backup channel set. Use <code>/setdbchannel [channel_id]</code> first.")
        return
    try:
        await bot.send_document(int(channel_id), FSInputFile(config.database_path), caption=f"🗃️ Manual backup — {time.strftime('%Y-%m-%d %H:%M UTC')}")
        await message.answer("✅ Backup sent.")
    except Exception as e:
        await message.answer(f"❌ Backup failed: {e}")


@router.message(Command("listmonsters"))
async def list_monsters_cmd(message: Message):
    if not _is_owner(message.from_user.id):
        return
    lines = ["<b>Story monsters:</b>"]
    lines += [f"• <code>{mid}</code> — {m['name']}" for mid, m in gd.MONSTERS.items()]
    lines.append("\n<b>Gate monsters:</b>")
    lines += [f"• <code>{mid}</code> — {m['name']}" for mid, m in gd.GATE_MONSTERS.items()]
    lines.append("\n<i>Use these IDs with /setmonsterimage.</i>")
    await message.answer("\n".join(lines))


@router.message(Command("setmonsterimage"))
async def set_monster_image_cmd(message: Message, command: CommandObject):
    if not _is_owner(message.from_user.id):
        return
    monster_id = (command.args or "").strip()
    if not monster_id or not message.reply_to_message or not message.reply_to_message.photo:
        await message.answer(
            "⚠️ <b>Usage:</b> Reply to a photo with <code>/setmonsterimage [monster_id]</code>\n"
            "Use <code>/listmonsters</code> to see valid IDs.\n"
            "Story monster IDs use key <code>storymonster:ID</code>, gate monsters use <code>gatemonster:ID</code> — I'll figure out which automatically."
        )
        return
    file_id = message.reply_to_message.photo[-1].file_id
    if monster_id in gd.MONSTERS:
        await database.cache_image(f"storymonster:{monster_id}", file_id)
        await message.answer(f"✅ Custom image set for story monster <b>{gd.MONSTERS[monster_id]['name']}</b>.")
    elif monster_id in gd.GATE_MONSTERS:
        await database.cache_image(f"gatemonster:{monster_id}", file_id)
        await message.answer(f"✅ Custom image set for gate monster <b>{gd.GATE_MONSTERS[monster_id]['name']}</b>.")
    else:
        await message.answer("❌ Unknown monster ID. Check /listmonsters.")


@router.message(Command("setcharacterimage"))
async def set_character_image_cmd(message: Message, command: CommandObject):
    if not _is_owner(message.from_user.id):
        return
    character_id = (command.args or "").strip()
    if not character_id or not message.reply_to_message or not message.reply_to_message.photo:
        await message.answer(
            "⚠️ <b>Usage:</b> Reply to a photo with <code>/setcharacterimage [character_id]</code>\n"
            "Character IDs are the keys in game_data.py's CHARACTERS dict, or a custom character's slug."
        )
        return
    pool = await full_character_pool()
    if character_id not in pool:
        await message.answer("❌ Unknown character ID.")
        return
    file_id = message.reply_to_message.photo[-1].file_id
    await database.cache_image(f"char:{character_id}", file_id)
    await message.answer(f"✅ Custom image set for <b>{pool[character_id]['name']}</b>.")


@router.message(Command("help"))
async def help_cmd(message: Message):
    text = (
        "🌑 <b>Commands</b>\n\n"
        "/start — begin or resume your journey\n"
        "/profile — view your stats\n"
        "/checkprofile — reply to a player to view their profile\n"
        "/roll — roll a new character\n"
        "/duel — reply to a player's message to challenge them\n"
        "/redeem CODE — redeem a coupon code\n\n"
        "🌀 <b>Wild Gates</b> auto-spawn in groups roughly every hour — tap Attack to help "
        "the group take them down together!\n\n"
        "Everything else is menu-driven — use /start to open the main menu anytime."
    )
    if _is_owner(message.from_user.id):
        text += "\n\n👑 <b>Owner</b>\n/setting — customize the welcome message\n/admin — admin panel"
    await message.answer(text)


# ------------------------------------------------------------------ #
#  Background loop: reminders, group activity reports, DB backups
# ------------------------------------------------------------------ #
DB_BACKUP_INTERVAL_SECONDS = 6 * 3600


async def background_loop() -> None:
    while True:
        try:
            await database.apply_bank_interest()
            now = time.gmtime()
            if now.tm_wday == 6 and now.tm_hour == 12:  # Sunday, ~noon UTC
                last_weekly = await database.get_setting("last_weekly_broadcast", "")
                today_str = time.strftime("%Y-%m-%d", now)
                if last_weekly != today_str:
                    top = await database.top_players(10)
                    if top:
                        lines = [f"{i}. {html.escape(p['first_name'])} — Lv.{p['level']} (Rank {p['rank']}) — 💰{p['gold']}" for i, p in enumerate(top, start=1)]
                        text = "🏆 <b>Weekly Leaderboard</b>\n<i>Top Hunters of the week!</i>\n\n" + "\n".join(lines)
                        for group in await database.all_groups():
                            try:
                                await bot.send_message(group["chat_id"], text)
                            except Exception:
                                pass
                    await database.set_setting("last_weekly_broadcast", today_str)

            for row in await database.due_daily_reminders():
                target_chat = row["last_active_chat_id"] or row["user_id"]
                mention = f'<a href="tg://user?id={row["user_id"]}">{html.escape(row["first_name"] or "Hunter")}</a>'
                text = f"📅 {mention}, your daily mission is ready to claim!" if row["last_active_chat_id"] else "📅 <b>Your daily mission is ready to claim!</b>"
                try:
                    await bot.send_message(target_chat, text)
                except Exception:
                    pass
                await database.mark_daily_reminded(row["user_id"])

            for row in await database.due_hourly_reminders():
                target_chat = row["last_active_chat_id"] or row["user_id"]
                mention = f'<a href="tg://user?id={row["user_id"]}">{html.escape(row["first_name"] or "Hunter")}</a>'
                text = f"⏰ {mention}, your hourly mission is ready to claim!" if row["last_active_chat_id"] else "⏰ <b>Your hourly mission is ready to claim!</b>"
                try:
                    await bot.send_message(target_chat, text)
                except Exception:
                    pass
                await database.mark_hourly_reminded(row["user_id"])

            for row in await database.due_energy_reminders():
                target_chat = row["last_active_chat_id"] or row["user_id"]
                mention = f'<a href="tg://user?id={row["user_id"]}">{html.escape(row["first_name"] or "Hunter")}</a>'
                text = (
                    f"⚡ {mention}, your energy is full ({row['max_energy']}/{row['max_energy']})! Time to hit some gates."
                    if row["last_active_chat_id"] else
                    f"⚡ <b>Your energy is full ({row['max_energy']}/{row['max_energy']})!</b> Time to hit some gates."
                )
                try:
                    await bot.send_message(target_chat, text)
                except Exception:
                    pass
                await database.mark_energy_reminded(row["user_id"])

            for group in await database.groups_due_for_report():
                top = await database.top_activity_today(group["chat_id"], 5)
                if top:
                    lines = [f"{i}. {html.escape(r['first_name'])} — {r['action_count']} actions" for i, r in enumerate(top, start=1)]
                    text = "📊 <b>Daily Activity Report</b>\n\n" + "\n".join(lines) + "\n\n<i>Keep playing to top tomorrow's board!</i>"
                    try:
                        await bot.send_message(group["chat_id"], text)
                    except Exception:
                        pass
                await database.mark_group_reported(group["chat_id"])

            for group in await database.groups_due_for_quiz():
                idx = random.randrange(len(gd.QUIZ_QUESTIONS))
                q = gd.QUIZ_QUESTIONS[idx]
                await database.spawn_group_quiz(group["chat_id"], idx)
                try:
                    await bot.send_message(
                        group["chat_id"],
                        f"❓ <b>Group Quiz!</b> First correct answer wins 💰{gd.GROUP_QUIZ_REWARD_GOLD} + ✨{gd.GROUP_QUIZ_REWARD_XP}XP\n\n{q['q']}",
                        reply_markup=kb.group_quiz_keyboard(group["chat_id"], q["options"]),
                    )
                except Exception as e:
                    LOG.warning(f"Could not spawn group quiz in {group['chat_id']}: {e}")

            for quiz in await database.expired_group_quizzes():
                await database.clear_group_quiz(quiz["chat_id"])
                try:
                    correct = gd.QUIZ_QUESTIONS[quiz["question_idx"]]["options"][gd.QUIZ_QUESTIONS[quiz["question_idx"]]["answer"]]
                    await bot.send_message(quiz["chat_id"], f"⌛ <b>Group Quiz closed!</b> Nobody answered in time. The answer was: <b>{correct}</b>")
                except Exception:
                    pass

            for group in await database.groups_due_for_wild_gate():
                monster = random.choice(gd.WILD_GATE_MONSTERS)
                await database.spawn_wild_gate(group["chat_id"], monster["name"], monster["hp"], monster)
                text = (
                    f"🌀 <b>Wild Gate Alert!</b>\n\n"
                    f"👹 A <b>{monster['name']}</b> has broken through into the city!\n"
                    f"❤️ HP: {monster['hp']}\n\n"
                    f"<i>Everyone in this group can tap Attack to help take it down — you have "
                    f"{gd.WILD_GATE_DURATION_SECONDS // 60} minutes before it escapes.</i>"
                )
                try:
                    photo_sent = await send_generated_photo(
                        group["chat_id"], f"wildgate:{monster['name']}",
                        gemini_image.battle_prompt(monster["name"], "a city street at night"),
                        text, kb.wild_gate_keyboard(),
                    )
                    if not photo_sent:
                        await bot.send_message(group["chat_id"], text, reply_markup=kb.wild_gate_keyboard())
                except Exception as e:
                    LOG.warning(f"Could not spawn wild gate in {group['chat_id']}: {e}")

            for gate in await database.expired_wild_gates():
                await database.clear_wild_gate(gate["chat_id"])
                try:
                    await bot.send_message(gate["chat_id"], f"💨 <b>The {gate['monster_name']} escaped!</b> A new Wild Gate may appear later.")
                except Exception:
                    pass

            db_channel = await database.get_setting("db_channel_id", "")
            if db_channel:
                last_backup = await database.get_setting("last_db_backup_at", "0")
                if int(time.time()) - int(last_backup) >= DB_BACKUP_INTERVAL_SECONDS:
                    try:
                        await bot.send_document(
                            int(db_channel), FSInputFile(config.database_path),
                            caption=f"🗃️ Auto backup — {time.strftime('%Y-%m-%d %H:%M UTC')}",
                        )
                    except Exception as e:
                        LOG.warning(f"DB auto-backup failed: {e}")
                    await database.set_setting("last_db_backup_at", str(int(time.time())))
        except Exception as e:
            LOG.warning(f"Background loop error: {e}")

        await asyncio.sleep(gd.REMINDER_CHECK_INTERVAL_SECONDS)
