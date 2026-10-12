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
    records = data["sanctions"].setdefault(str(member_id), [])

    records.append({
        "type": kind,
        "reason": reason,
        "moderator": moderator_id,
        "time": time.time(),
        "duration": duration
    })

    save_data(data)
    return len(records)


async def notify_user(user, title, reason, guild):
    try:
        await user.send(
            embed=make_embed(
                title,
                f"Serveur : **{guild.name}**\nRaison : {reason}",
                ERROR_COLOR
            )
        )
    except (discord.Forbidden, discord.HTTPException):
        pass


# -------------------- TICKETS --------------------

class TicketActions(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Fermer",
        style=discord.ButtonStyle.danger,
        emoji="🔒",
        custom_id="crowbot:ticket:close"
    )
    async def close_ticket(self, interaction, button):
        if interaction.guild is None:
            return await interaction.response.send_message(
                "Cette action doit être utilisée sur un serveur.",
                ephemeral=True
            )

        member = interaction.user

        is_staff = (
            member.guild_permissions.manage_channels
            or (
                STAFF_ROLE_ID
                and any(role.id == STAFF_ROLE_ID for role in member.roles)
            )
        )

        if not is_staff:
            return await interaction.response.send_message(
                "Tu n'as pas la permission de fermer ce ticket.",
                ephemeral=True
            )

        await interaction.response.send_message(
            "🔒 Ticket fermé. Le salon sera supprimé dans 5 secondes."
        )

        data = load_data()

        for user_id, channel_id in list(data["tickets"].items()):
            if int(channel_id) == interaction.channel.id:
                data["tickets"].pop(user_id, None)

        save_data(data)

        await send_log(
            interaction.guild,
            "🔒 Ticket fermé",
            f"Salon : {interaction.channel.mention}\n"
            f"Par : {member.mention}"
        )

        await asyncio.sleep(5)

        try:
            await interaction.channel.delete(
                reason=f"Ticket fermé par {member}"
            )
        except discord.HTTPException:
            pass


class TicketPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Créer un ticket",
        style=discord.ButtonStyle.primary,
        emoji="🎫",
        custom_id="crowbot:ticket:create"
    )
    async def create_ticket(self, interaction, button):
        guild = interaction.guild

        if guild is None:
            return await interaction.response.send_message(
                "Cette action est disponible sur un serveur.",
                ephemeral=True
            )

        data = load_data()
        existing_id = data["tickets"].get(str(interaction.user.id))

        if existing_id:
            existing = guild.get_channel(int(existing_id))

            if existing:
                return await interaction.response.send_message(
                    f"Tu as déjà un ticket ouvert : {existing.mention}",
                    ephemeral=True
                )

            data["tickets"].pop(str(interaction.user.id), None)

        category = (
            guild.get_channel(TICKET_CATEGORY_ID)
            if TICKET_CATEGORY_ID
            else None
        )

        overwrites = {
            guild.default_role:
                discord.PermissionOverwrite(view_channel=False),

            interaction.user:
                discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True
                )
        }

        bot_member = guild.me

        if bot_member:
            overwrites[bot_member] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True
            )

        support_role = (
            guild.get_role(TICKET_SUPPORT_ROLE_ID)
            if TICKET_SUPPORT_ROLE_ID
            else None
        )

        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True
            )

        safe_name = "".join(
            char for char in interaction.user.name.lower()
            if char.isalnum() or char == "-"
        )[:18] or "membre"

        try:
            channel = await guild.create_text_channel(
                name=f"ticket-{safe_name}",
                category=category,
                overwrites=overwrites,
                topic=(
                    f"Ticket de {interaction.user} "
                    f"({interaction.user.id})"
                )
            )
        except discord.HTTPException:
            return await interaction.response.send_message(
                "Impossible de créer le ticket. Vérifie les permissions du bot.",
                ephemeral=True
            )

        data["tickets"][str(interaction.user.id)] = channel.id
        save_data(data)

        ticket_embed = make_embed(
            "🎫 Nouveau ticket",
            f"Bonjour {interaction.user.mention} !\n\n"
            "Décris ta demande ici. Le staff te répondra dès que possible."
        )

        content = interaction.user.mention

        if support_role:
            content += f" {support_role.mention}"

        await channel.send(
            content=content,
            embed=ticket_embed,
            view=TicketActions()
        )

        await interaction.response.send_message(
            f"Ton ticket a été créé : {channel.mention}",
            ephemeral=True
        )

        await send_log(
            guild,
            "🎫 Ticket créé",
            f"Créé par {interaction.user.mention} • {channel.mention}",
            SUCCESS_COLOR
        )
