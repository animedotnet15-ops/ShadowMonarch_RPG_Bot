"""Thin wrapper around the Gemini API's image generation (Nano Banana) model.

Uses the REST endpoint directly via aiohttp so we don't need the heavier
google-generativeai SDK as a dependency. Fails soft everywhere — if the key
is missing, invalid, or the request errors out, generate_image() returns
None and the caller should fall back to text-only output.
"""
from __future__ import annotations

import base64
import logging

import aiohttp

from config import config

LOG = logging.getLogger("gemini_image")

MODEL = "gemini-3.1-flash-image"
ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"


def is_configured() -> bool:
    return bool(config.gemini_api_key)


async def generate_image(prompt: str) -> bytes | None:
    """Returns raw PNG/JPEG bytes, or None if generation isn't available/failed."""
    if not config.gemini_api_key:
        return None

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }
    headers = {"Content-Type": "application/json", "x-goog-api-key": config.gemini_api_key}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                ENDPOINT, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=45)
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    LOG.warning(f"Gemini image request failed ({resp.status}): {body[:300]}")
                    return None
                data = await resp.json()
    except Exception as e:
        LOG.warning(f"Gemini image request errored: {e}")
        return None

    try:
        for candidate in data.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    return base64.b64decode(inline["data"])
    except Exception as e:
        LOG.warning(f"Could not parse Gemini image response: {e}")
    return None


def character_prompt(name: str, rarity: str) -> str:
    return (
        f"A digital fantasy RPG character portrait of '{name}', a {rarity}-rarity hunter "
        f"in a dark urban-fantasy setting inspired by shadow magic and monster-hunting. "
        f"Dramatic lighting, detailed armor/clothing fitting their rarity tier, painterly "
        f"game-splash-art style, vertical portrait composition, no text or watermarks."
    )


def battle_prompt(monster_name: str, setting: str = "a dungeon gate") -> str:
    return (
        f"A dramatic digital painting of a monster called '{monster_name}' inside {setting}, "
        f"dark fantasy RPG boss-encounter splash art, cinematic lighting, no text or watermarks."
    )
