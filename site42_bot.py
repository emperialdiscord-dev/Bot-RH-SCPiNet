"""
Crowbot — bot Discord à préfixe
Python 3.10+
Installation :
pip install -U discord.py python-dotenv

Dans le fichier .env :
DISCORD_TOKEN=TON_TOKEN
OWNER_ID=TON_ID_DISCORD
"""

from __future__ import annotations

import os
import json
import time
import random
import asyncio
import datetime as dt
from pathlib import Path
from typing import Optional

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
PREFIX = "="
DATA_PATH = Path("crowbot_data.json")

OWNER_ID = int(os.getenv("OWNER_ID", "0"))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))
TICKET_CATEGORY_ID = int(os.getenv("TICKET_CATEGORY_ID", "0"))
STAFF_ROLE_ID = int(os.getenv("STAFF_ROLE_ID", "0"))
TICKET_SUPPORT_ROLE_ID = int(os.getenv("TICKET_SUPPORT_ROLE_ID", "0"))
WELCOME_CHANNEL_ID = int(os.getenv("WELCOME_CHANNEL_ID", "0"))
GOODBYE_CHANNEL_ID = int(os.getenv("GOODBYE_CHANNEL_ID", "0"))

COLOR = discord.Color.from_rgb(75, 88, 190)
ERROR_COLOR = discord.Color.from_rgb(220, 65, 75)
SUCCESS_COLOR = discord.Color.from_rgb(55, 170, 110)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(
    command_prefix=PREFIX,
    intents=intents,
    help_command=None,
    case_insensitive=True
)

DEFAULT_DATA = {
    "sanctions": {},
    "tempbans": {},
    "logs_channel": LOG_CHANNEL_ID,
    "tickets": {},
    "giveaways": {},
    "giveaway_counter": 0,
    "joinmessage": "Bienvenue {mention} sur **{server}** !",
    "leavemessage": "**{name}** vient de quitter le serveur.",
    "settings": {
        "banner": "",
        "pic": "",
        "name": "",
        "status": "Crowbot • =help"
    }
}


def load_data():
    if not DATA_PATH.exists():
        save_data(DEFAULT_DATA.copy())

    try:
        with DATA_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        data = {}

    for key, value in DEFAULT_DATA.items():
        if key not in data:
            data[key] = (
                value.copy()
                if isinstance(value, (dict, list))
                else value
            )

    return data


def save_data(data):
    temporary = DATA_PATH.with_suffix(".tmp")

    with temporary.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    temporary.replace(DATA_PATH)


def make_embed(
    title: str,
    description: str = "",
    color: discord.Color = COLOR
):
    result = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=discord.utils.utcnow()
    )
    result.set_footer(text="Crowbot • Administration")
    return result


async def send_log(guild, title, description, color=COLOR):
    if guild is None:
        return

    data = load_data()
    channel_id = int(data.get("logs_channel", 0) or LOG_CHANNEL_ID)

    if not channel_id:
        return

    channel = guild.get_channel(channel_id)

    if channel:
        try:
            await channel.send(
                embed=make_embed(title, description, color)
            )
        except discord.HTTPException:
            pass


def is_owner():
    async def predicate(ctx):
        if OWNER_ID and ctx.author.id == OWNER_ID:
            return True

        if await bot.is_owner(ctx.author):
            return True

        raise commands.CheckFailure(
            "Cette commande est réservée au propriétaire du bot."
        )

    return commands.check(predicate)


def staff_or_permissions(*permissions):
    async def predicate(ctx):
        if OWNER_ID and ctx.author.id == OWNER_ID:
            return True

        if ctx.author.guild_permissions.administrator:
            return True

        if any(
            getattr(ctx.author.guild_permissions, permission, False)
            for permission in permissions
        ):
            return True

        if STAFF_ROLE_ID and any(
            role.id == STAFF_ROLE_ID
            for role in getattr(ctx.author, "roles", [])
        ):
            return True

        raise commands.CheckFailure(
            "Tu n'as pas les permissions nécessaires."
        )

    return commands.check(predicate)


def parse_duration(value: str) -> Optional[int]:
    value = value.lower().strip()

    units = {
        "s": 1,
        "m": 60,
        "h": 3600,
        "j": 86400,
        "d": 86400,
        "w": 604800
    }

    digits = "".join(char for char in value if char.isdigit())
    unit = "".join(char for char in value if char.isalpha())

    if not digits or unit not in units:
        return None

    seconds = int(digits) * units[unit]
    return seconds if seconds > 0 else None


def record_sanction(
    member_id: int,
    kind: str,
    reason: str,
    moderator_id: int,
    duration: str = ""
):
    data = load_data()
    records = data["sanctions"].setdefault(str(member_id
