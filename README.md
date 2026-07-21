# Shadow Monarch RPG Bot (Phase 1)

A Telegram RPG game bot inspired by the general premise of Solo Leveling — rank up,
fight through story battles, collect weapons, extract shadow soldiers, and answer
trivia — all playable through inline buttons, no typing required.

**This is Phase 1.** Building the *entire* story with *all* characters/weapons/powers
in one go isn't realistic — the source material spans 14+ volumes and 200+ chapters.
Instead, the bot is architected so new arcs, monsters, weapons, and shadows can be
added as plain data (in `game_data.py`) without touching the game engine. Ask for the
next arc whenever you're ready and it'll be added the same way.

## What's included (Phase 1 + Phase 2)

- Full RPG engine: leveling, stats (STR/AGI/INT/VIT/PER), ranks E→S, HP, gold, gems
- Turn-based battles (attack/defend/flee) tied into the story
- Branching story mode (Arc 1 — "Double Dungeon")
- Weapon inventory + equip system, NPC shop
- Shadow extraction (gacha) + playable Character rolls, both rarity-tiered
- Gates (E/D/C/B/A/Red), each on its own per-player cooldown, dropping Mana Crystals
  / Essence Stones
- Daily + hourly mission claims
- PvP duels (`/duel` as a reply to another player, works great in groups)
- Vault summary, leaderboard, quiz mode
- Owner-only `/setting` dashboard: welcome text/photo, start sticker, animated
  `/start` sequence, Owner/Admin/Support/Website buttons
- Owner-only `/admin` panel: give currency, reset a player, bot stats, broadcast

## Content included (Phase 1)

- **Story:** Arc 1 — Double Dungeon (awakening, two battles, job-change quest)
- **Monsters:** Cartenon Stone Soldier, Cartenon Elite Guardian
- **Weapons:** Rusty Dagger (starter), Novice Hunter's Dagger (Arc 1 reward), Knight
  Killer (locked — arrives with Arc 2)
- **Shadows:** Ordinary Shadow Soldier, Shadow Knight, Iron, Tank, Igris
- **Characters:** Rookie Hunter → Monarch's Heir (6 rarity tiers)
- **Gates:** E through Red Gate, each with their own monster and rewards
- **Quiz:** 10 general trivia questions

## Adding future arcs

Everything content-related lives in `game_data.py`:
- Add new entries to `MONSTERS`, `WEAPONS`, `SHADOWS`, `CHARACTERS`, `GATES`, `QUIZ_QUESTIONS`
- Add a new arc under `STORY_ARCS` with its own `nodes` dict (same node shape as Arc 1:
  `text` + either `choices`, `battle`, or `reward`)
- Chain arcs by pointing the final node's `complete_arc` reward to unlock the next
  arc's starter weapon, and update `set_story_position` calls / a new `menu:story`
  transition to move players from one arc to the next once they finish the current one

No database migrations needed for new content — only new arcs/mechanics.

## Customizing the welcome message

As the owner (set via `OWNER_ID`), send `/setting` to the bot for a menu to customize:
- Welcome text (supports a `{name}` placeholder)
- Welcome photo
- The sticker played during the `/start` animation
- Owner / Admin / Support / Website buttons shown under the welcome message
- A "👀 Preview /start" button to see changes immediately

`/start` always plays a short typing animation ("Hey {name}...", "Start...", etc.)
followed by the sticker (if set), then the welcome message.

## Setup (local)

1. `pip install -r requirements.txt`
2. Copy `.env.example` to `.env`, fill in `BOT_TOKEN` (from @BotFather) and `OWNER_ID`
3. `python main.py`

## Deploying

### Railway
1. Push this folder to a GitHub repo → **New Project → Deploy from GitHub repo**.
2. Add environment variables (below) in the **Variables** tab.
3. **Persistence:** Railway's disk resets on redeploy. Add a **Volume** (mount at
   e.g. `/data`) and set `DATABASE_PATH=/data/shadowmonarch.db`, or player progress
   will reset every time you redeploy.

### Render
1. Push to GitHub → **New → Background Worker** (or use the included `render.yaml`
   via **New → Blueprint**, which auto-attaches a persistent disk at `/var/data`).
2. Add environment variables in the **Environment** tab.
3. If deploying as a "Web Service" instead of "Background Worker", `main.py` already
   starts a small health-check server automatically when Render sets `$PORT`, so the
   health check will still pass either way.

### Environment variables

| Variable | Required | Notes |
|---|---|---|
| `BOT_TOKEN` | ✅ | From @BotFather |
| `OWNER_ID` | ✅ | Your numeric Telegram ID — controls `/setting` and `/admin` |
| `DATABASE_PATH` | recommended | Point into a mounted volume/disk so progress persists across redeploys |
