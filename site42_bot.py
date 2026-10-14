# -*- coding: utf-8 -*-
"""
BOT DISCORD — script complet
Dépendances : discord.py, python-dotenv, flask
Pré-requis : définir DISCORD_TOKEN dans le fichier .env.

Tous les emojis sont centralisés dans EMOJIS. Remplace les valeurs
EMOJI_... par tes emojis personnalisés Discord (ex. <:nom:123456789012345678>).
Aucun emoji Unicode décoratif n'est utilisé dans les messages du bot.
"""

import os
import re
import json
import time
import random
import datetime
from typing import Optional

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

# ============================================================
# CONFIGURATION
# ============================================================

PREFIX = "="
DATA_FILE = "bot_data.json"
BLUE = discord.Colour(0x2563EB)
RED = discord.Colour(0xDC2626)
BLACK = discord.Colour(0x000000)
EMBED_COLOR = BLACK

# Remplace chaque valeur par TON emoji personnalisé.
# Format statique : <:nom:ID> | animé : <a:nom:ID>
EMOJIS = {
    "success": "<:EMOJI_SUCCESS:123456789012345678>",
    "error": "EMOJI_ERREUR",
    "warning": "EMOJI_AVERTISSEMENT",
    "info": "EMOJI_INFO",
    "moderation": "EMOJI_MODERATION",
    "ticket": "EMOJI_TICKET",
    "ticket_purchase": "EMOJI_TICKET_ACHAT",
    "ticket_support": "EMOJI_TICKET_SUPPORT",
    "ticket_close": "EMOJI_TICKET_FERMER",
    "giveaway": "EMOJI_GIVEAWAY",
    "user": "EMOJI_MEMBRE",
    "role": "EMOJI_ROLE",
    "channel": "EMOJI_SALON",
    "logs": "EMOJI_LOGS",
    "stats": "EMOJI_STATS",
    "lock": "EMOJI_VERROU",
    "unlock": "EMOJI_DEVERROU",
    "loading": "EMOJI_CHARGEMENT",
    "arrow": "EMOJI_FLECHE",
    "crown": "EMOJI_COURONNE",
    "calendar": "EMOJI_CALENDRIER",
    "link": "EMOJI_LIEN",
    "bot": "EMOJI_BOT",
}

def em(key: str) -> str:
    """Retourne l'emoji configuré ou un placeholder visible à remplacer."""
    return EMOJIS.get(key, "EMOJI_A_CONFIGURER")

def button_emoji(key: str):
    """Convertit un emoji Discord personnalisé configuré, sinon n'en affiche aucun.

    Remplace les placeholders EMOJI_... par une mention comme <:nom:123456789012345678>
    ou <a:nom:123456789012345678>. Les placeholders ne sont pas envoyés à Discord.
    """
    value = EMOJIS.get(key, "")
    if not isinstance(value, str) or not re.fullmatch(r"<a?:[A-Za-z0-9_]+:\d+>", value):
        return None
    try:
        return discord.PartialEmoji.from_str(value)
    except (TypeError, ValueError):
        return None


# Un rôle peut être associé à chaque niveau P0 à P8 avec =rank <niveau> @role.
# P9 est réservé à OWNER_USER_ID dans les variables d’environnement Render.
ROLE_LEVELS = {level: 0 for level in range(0, 9)}

# Niveau minimum par commande. Toute commande non listée est P9 par défaut.
COMMAND_LEVELS = {
    # P0 — Membres
    "help": 0, "pic": 0, "banner": 0, "stats-invite": 0, "stats-logs": 0, "invite": 0,
    "server-invite": 0,
    # P1 — Staff : gestion des tickets
    "add": 1, "del": 1, "close": 1, "rename": 1,
    # P2 — Staff confirmé
    "warn": 2, "sanction": 2,
    # P3 — Modération
    "tempmute": 3, "staff-list": 3,
    # P4 — Admin
    "mutelist": 4, "mute-list": 4,
    # P5 — Admin supérieur
    "mute": 5, "unmute": 5,
    # P6 — Management
    "kick": 6, "adminlist": 6, "admin-list": 6, "rank": 6, "rank-clear": 6,
    # P7 — Gestion
    "tempban": 7, "unban": 7, "derank": 7, "del-sanction": 7,
    "lock": 7, "unlock": 7, "banlist": 7, "lockall": 7, "unlockall": 7,
    # P8 — Direction
    "ban": 8, "wl": 8, "giveaway": 8, "gcancel": 8, "gend": 8,
    "reroll": 8, "glist": 8,
}
P0_COMMANDS = {name for name, level in COMMAND_LEVELS.items() if level == 0}
OWNER_USER_ID = int(os.getenv("OWNER_USER_ID", "0") or 0)

# IDs facultatifs à configurer.
LOG_CHANNEL_ID = 0
TICKET_CATEGORY_ID = 0
TICKET_STAFF_ROLE_ID = 0
GIVEAWAY_HOST_ROLE_ID = 0

# Les commandes de blacklist ne sont volontairement pas incluses,
# conformément à ta demande de retirer ce système.


# ============================================================
# STOCKAGE JSON
# ============================================================

DEFAULT_DATA = {
    "warnings": {},
    "sanctions": {},
    "tempbans": {},
    "tempmutes": {},
    "tickets": {},
    "giveaways": {},
    "join_message": "Bienvenue {user} sur {server}.",
    "leave_message": "{user} a quitté {server}.",
    "logs_channel": 0,
    "bot_name": None,
    "bot_avatar": None,
    "bot_status": "online",
    "guilds": {},
}

def load_data():
    if not os.path.exists(DATA_FILE):
        save_data(DEFAULT_DATA.copy())
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (json.JSONDecodeError, OSError):
        data = {}
    merged = DEFAULT_DATA.copy()
    merged.update(data)
    for key in ("warnings", "sanctions", "tempbans", "tempmutes",
                "tickets", "giveaways"):
        merged.setdefault(key, {})
    return merged

def save_data(data):
    temp_path = DATA_FILE + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
    os.replace(temp_path, DATA_FILE)

def get_guild_data(data, guild_id):
    """Retourne un espace de configuration isolé pour un serveur."""
    data.setdefault("guilds", {})
    return data["guilds"].setdefault(str(guild_id), {
        "ticket_panels": {}, "tickets": {}, "giveaways": {}, "logs_channel": 0,
        "join_message": "Bienvenue {user} sur {server}.",
        "leave_message": "{user} a quitté {server}.", "owner_role_id": 0,
    })


def can_configure(member):
    return isinstance(member, discord.Member) and (member.guild_permissions.administrator or member.guild_permissions.manage_guild)


def edit_data(callback):
    data = load_data()
    callback(data)
    save_data(data)
    return data


# ============================================================
# OUTILS
# ============================================================

def make_embed(title: str, description: Optional[str] = None,
               emoji: str = "info", color: Optional[discord.Colour] = None):
    # Aucun pied de page ni horodatage automatique.
    return discord.Embed(
        title=f"{em(emoji)} {title}",
        description=description,
        color=BLACK,  # Bande latérale noire pour tous les embeds, sans exception.
    )

def parse_duration(value: str) -> Optional[int]:
    match = re.fullmatch(r"\s*(\d+)\s*([smhdj])\s*", value.lower())
    if not match:
        return None
    amount, unit = int(match.group(1)), match.group(2)
    return amount * {"s": 1, "m": 60, "h": 3600, "d": 86400, "j": 86400}[unit]

def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, _ = divmod(seconds, 60)
    pieces = []
    if days: pieces.append(f"{days}j")
    if hours: pieces.append(f"{hours}h")
    if minutes or not pieces: pieces.append(f"{minutes}min")
    return " ".join(pieces)

def staff_level(member: discord.Member) -> int:
    if OWNER_USER_ID and member.id == OWNER_USER_ID:
        return 9
    if not isinstance(member, discord.Member):
        return 0
    data = load_data()
    gd = get_guild_data(data, member.guild.id)
    configured = gd.get("permission_roles", {})
    ids_by_level = {int(level): int(role_id) for level, role_id in configured.items()
                    if str(level).isdigit() and str(role_id).isdigit() and int(role_id) > 0}
    ids_by_level.update({level: role_id for level, role_id in ROLE_LEVELS.items() if role_id})
    member_role_ids = {role.id for role in member.roles}
    return max((level for level, role_id in ids_by_level.items()
                if role_id in member_role_ids), default=0)

def required_level(command_name: str) -> int:
    return COMMAND_LEVELS.get(command_name, 9)

def has_level(member: discord.Member, command_name: str) -> bool:
    needed = required_level(command_name)
    if needed == 9:
        return bool(OWNER_USER_ID and member.id == OWNER_USER_ID)
    return staff_level(member) >= needed

async def reply_embed(ctx, title, description=None, emoji="info",
                      ephemeral=False, color=None):
    embed = make_embed(title, description, emoji, color)
    if isinstance(ctx, discord.Interaction):
        if ctx.response.is_done():
            await ctx.followup.send(embed=embed, ephemeral=ephemeral)
        else:
            await ctx.response.send_message(embed=embed, ephemeral=ephemeral)
    else:
        await ctx.send(embed=embed)

async def log_action(guild: discord.Guild, title: str, description: str):
    data = load_data()
    gd = get_guild_data(data, guild.id)
    channel_id = gd.get("logs_channel") or data.get("logs_channel") or LOG_CHANNEL_ID
    channel = guild.get_channel(int(channel_id)) if channel_id else None
    if channel:
        try:
            await channel.send(embed=make_embed(title, description, "logs"))
        except discord.HTTPException:
            pass

async def staff_check(ctx, command_name):
    if not isinstance(ctx.author, discord.Member):
        return False
    if has_level(ctx.author, command_name):
        return True
    await reply_embed(ctx, "Permission insuffisante",
                      f"Niveau requis : **P{required_level(command_name)}**.\n"
                      f"Ton niveau : **{staff_level(ctx.author)}**.", "error")
    return False

async def send_dm(member: discord.Member, title: str, description: str):
    try:
        await member.send(f"**{title}**\n{description}")
    except discord.Forbidden:
        pass


# ============================================================
# BOT
# ============================================================

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingRequiredArgument):
        await reply_embed(ctx, "Argument manquant",
                          f"Argument attendu : `{error.param.name}`.", "warning")
        return
    if isinstance(error, commands.MissingPermissions):
        await reply_embed(ctx, "Permission Discord manquante",
                          "Tu n'as pas la permission Discord nécessaire.", "error")
        return
    if isinstance(error, commands.CheckFailure):
        message = str(getattr(error, "original", error))
        try:
            await ctx.send(message or "Tu n'as pas le niveau de permission requis.")
        except discord.HTTPException:
            pass
        return
    if isinstance(error, commands.BadArgument):
        await reply_embed(ctx, "Argument invalide",
                          "Vérifie les membres, rôles, salons et durées fournis.", "error")
        return
    if isinstance(error, commands.CommandOnCooldown):
        await reply_embed(ctx, "Commande en recharge",
                          f"Réessaie dans {error.retry_after:.1f} seconde(s).", "warning")
        return
    await reply_embed(ctx, "Erreur", f"Une erreur est survenue : `{type(error).__name__}`.", "error")
    raise error


@bot.check
async def guild_only_check(ctx):
    return ctx.guild is not None


@bot.check
async def permission_level_check(ctx):
    # Les commandes inconnues du tableau sont P9 par défaut.
    if ctx.command is None:
        return False
    if has_level(ctx.author, ctx.command.name):
        return True
    needed = required_level(ctx.command.name)
    current = staff_level(ctx.author) if isinstance(ctx.author, discord.Member) else 0
    raise commands.CheckFailure(
        f"Niveau insuffisant : cette commande exige P{needed}; ton niveau est P{current}."
    )


# ============================================================
# AIDE / INFOS
# ============================================================

@bot.command(name="help", aliases=["aide"])
async def help_command(ctx):
    embed = make_embed(f"Commandes de {ctx.guild.name}", emoji="bot")
    sections = {
        "Informations": "`=help`, `=invite`, `=server-invite`, `=stats-logs`, `=pic`, `=banner`",
        "Modération": "`=warn`, `=sanction`, `=tempmute`, `=mute`, `=unmute`, `=ban`, `=tempban`, `=unban`, `=kick`, `=rank`, `=derank`, `=add-role`, `=del-role`, `=del-sanction`, `=mutelist`, `=banlist`, `=adminlist`, `=staff-list`",
        "Salons": "`=lock`, `=unlock`, `=lockall`, `=unlockall`, `=scan`, `=logs-global`",
        "Tickets": "`=ticket`, `=add`, `=del`, `=close`, `=rename`, `=ticket-stats`",
        "Giveaways": "`=giveaway`, `=gcancel`, `=gend`, `=reroll`, `=glist`",
        "Messages": "`=joinmessage`, `=leavemessage`, `=mp`, `=dmall`, `=say`",
        "Configuration": "`=setbanner`, `=setpic`, `=setname`, `=setstatus`, `=online`, `=dnd`, `=owner`",
    }
    for name, value in sections.items():
        embed.add_field(name=name, value=value, inline=False)
    await ctx.send(embed=embed)

@bot.command(name="invite", aliases=["server-invite"])
async def invite_cmd(ctx):
    invite = await ctx.channel.create_invite(max_age=86400, max_uses=0, unique=True)
    await reply_embed(ctx, "Invitation", invite.url, "link")

@bot.command(name="pic")
async def pic_cmd(ctx, membre: Optional[discord.Member] = None):
    membre = membre or ctx.author
    embed = make_embed(f"Avatar de {membre}", emoji="user")
    embed.set_image(url=membre.display_avatar.url)
    await ctx.send(embed=embed)

@bot.command(name="banner")
async def banner_cmd(ctx, membre: Optional[discord.User] = None):
    membre = membre or ctx.author
    user = await bot.fetch_user(membre.id)
    if not user.banner:
        return await reply_embed(ctx, "Bannière introuvable",
                                 "Ce compte n'a pas de bannière publique.", "warning")
    embed = make_embed(f"Bannière de {user}", emoji="user")
    embed.set_image(url=user.banner.url)
    await ctx.send(embed=embed)

@bot.command(name="stats-logs", aliases=["stats-invite"])
async def stats_logs(ctx):
    data = load_data()
    await reply_embed(ctx, "Statistiques des logs",
                      f"Sanctions enregistrées : **{sum(map(len, data['sanctions'].values()))}**\n"
                      f"Tickets suivis : **{len(data['tickets'])}**\n"
                      f"Giveaways suivis : **{len(data['giveaways'])}**", "stats")

@bot.command(name="logs-global")
async def logs_global(ctx):
    data = load_data()
    gd = get_guild_data(data, ctx.guild.id)
    gd["logs_channel"] = ctx.channel.id
    save_data(data)
    await reply_embed(ctx, "Logs configurés",
                      f"Les logs seront envoyés dans {ctx.channel.mention}.", "success")


# ============================================================
# MODÉRATION
# ============================================================

@bot.command(name="warn")
async def warn_cmd(ctx, membre: discord.Member, *, raison="Aucune raison précisée"):
    if not await staff_check(ctx, "warn"): return
    data = load_data()
    data["warnings"].setdefault(str(membre.id), []).append({
        "reason": raison, "moderator": ctx.author.id, "at": time.time()
    })
    data["sanctions"].setdefault(str(membre.id), []).append({
        "type": "Avertissement", "reason": raison, "moderator": ctx.author.id, "at": time.time()
    })
    save_data(data)
    await send_dm(membre, "Avertissement reçu", f"Serveur : {ctx.guild.name}\nRaison : {raison}")
    await ctx.send(f"{em('success')} {membre.id} a été warn avec succès")
    await log_action(ctx.guild, "Avertissement", f"{membre.mention} — {raison} — par {ctx.author.mention}")

@bot.command(name="sanction", aliases=["sanctions"])
async def sanction_cmd(ctx, membre: discord.Member):
    if not await staff_check(ctx, "sanction"): return
    sanctions = load_data()["sanctions"].get(str(membre.id), [])
    embed = make_embed(f"Sanctions de {membre}", emoji="moderation")
    if not sanctions:
        embed.description = "Aucune sanction enregistrée."
    else:
        for i, item in enumerate(sanctions[-20:], start=max(1, len(sanctions)-19)):
            embed.add_field(name=f"S.{i} — {item['type']}",
                            value=f"Raison : {item['reason']}\nModérateur ID : {item['moderator']}",
                            inline=False)
    await ctx.send(embed=embed)

@bot.command(name="del-sanction")
async def del_sanction_cmd(ctx, membre: discord.Member, numero: int):
    if not await staff_check(ctx, "del-sanction"): return
    data = load_data()
    items = data["sanctions"].get(str(membre.id), [])
    if numero < 1 or numero > len(items):
        return await reply_embed(ctx, "Sanction introuvable", "Numéro de sanction invalide.", "error")
    removed = items.pop(numero - 1)
    save_data(data)
    await ctx.send(
        f"Sanction supprimée sur **{ctx.guild.name}**.\n"
        f"{removed['type']} retirée pour {membre.mention}."
    )

@bot.command(name="tempmute")
async def tempmute_cmd(ctx, membre: discord.Member, duree: str, *, raison="Aucune raison précisée"):
    if not await staff_check(ctx, "tempmute"): return
    seconds = parse_duration(duree)
    if seconds is None or seconds > 28 * 86400:
        return await reply_embed(ctx, "Durée invalide", "Exemples : `10m`, `2h`, `3j` (maximum 28j).", "error")
    until = discord.utils.utcnow() + datetime.timedelta(seconds=seconds)
    await membre.timeout(until, reason=raison)
    data = load_data()
    data["tempmutes"][str(membre.id)] = {"until": time.time() + seconds, "guild": ctx.guild.id}
    data["sanctions"].setdefault(str(membre.id), []).append({
        "type": f"Timeout {duree}", "reason": raison, "moderator": ctx.author.id, "at": time.time()
    })
    save_data(data)
    await send_dm(membre, "Timeout appliqué", f"Durée : {duree}\nRaison : {raison}")
    await ctx.send(f"{em('success')} {membre.id} a été tempmute avec succès")

@bot.command(name="mute")
async def mute_cmd(ctx, membre: discord.Member, *, raison="Aucune raison précisée"):
    if not await staff_check(ctx, "mute"): return
    await membre.timeout(discord.utils.utcnow() + datetime.timedelta(days=28), reason=raison)
    await ctx.send(f"{em('success')} {membre.id} a été mute avec succès")

@bot.command(name="unmute")
async def unmute_cmd(ctx, membre: discord.Member):
    if not await staff_check(ctx, "mute"): return
    await membre.timeout(None, reason=f"Unmute par {ctx.author}")
    await ctx.send(f"Timeout retiré sur **{ctx.guild.name}** : {membre.mention} peut de nouveau parler.")

@bot.command(name="ban")
async def ban_cmd(ctx, membre: discord.Member, *, raison="Aucune raison précisée"):
    if not await staff_check(ctx, "ban"): return
    await send_dm(membre, "Bannissement", f"Serveur : {ctx.guild.name}\nRaison : {raison}")
    await membre.ban(reason=raison)
    await ctx.send(f"{em('success')} {membre.id} a été ban avec succès")
    await log_action(ctx.guild, "Bannissement", f"{membre} — {raison}")

@bot.command(name="tempban")
async def tempban_cmd(ctx, membre: discord.Member, duree: str, *, raison="Aucune raison précisée"):
    if not await staff_check(ctx, "tempban"): return
    seconds = parse_duration(duree)
    if seconds is None:
        return await reply_embed(ctx, "Durée invalide", "Exemples : `10m`, `2h`, `3j`.", "error")
    data = load_data()
    data["tempbans"][str(membre.id)] = {
        "until": time.time() + seconds, "guild": ctx.guild.id
    }
    save_data(data)
    await send_dm(membre, "Bannissement temporaire", f"Durée : {duree}\nRaison : {raison}")
    await membre.ban(reason=raison)
    await ctx.send(f"{em('success')} {membre.id} a été tempban avec succès")

@bot.command(name="unban")
async def unban_cmd(ctx, user_id: int, *, raison="Levée du bannissement"):
    if not await staff_check(ctx, "unban"): return
    await ctx.guild.unban(discord.Object(id=user_id), reason=raison)
    await ctx.send(f"{em('success')} {user_id} a été unban avec succès")

@bot.command(name="kick")
async def kick_cmd(ctx, membre: discord.Member, *, raison="Aucune raison précisée"):
    if not await staff_check(ctx, "kick"): return
    await send_dm(membre, "Expulsion", f"Raison : {raison}")
    await membre.kick(reason=raison)
    await ctx.send(f"{em('success')} {membre.id} a été kick avec succès")

@bot.command(name="rank")
async def rank_cmd(ctx, niveau: Optional[int] = None, role: Optional[discord.Role] = None):
    if not await staff_check(ctx, "rank"):
        return
    data = load_data()
    gd = get_guild_data(data, ctx.guild.id)
    configured = gd.setdefault("permission_roles", {})

    # Sans argument, affiche les emplacements de rôles pour tous les niveaux.
    if niveau is None and role is None:
        lines = []
        for lvl in range(0, 9):
            role_id = int(configured.get(str(lvl), ROLE_LEVELS.get(lvl, 0)) or 0)
            configured_role = ctx.guild.get_role(role_id) if role_id else None
            lines.append(f"**P{lvl}** — {configured_role.mention if configured_role else 'Aucun rôle configuré'}")
        lines.append("**P9** — Propriétaire via `OWNER_USER_ID` dans Render (pas de rôle à configurer).")
        lines.append("\nPour associer un rôle : `=rank <0-8> @role`. Pour retirer un rôle d’un niveau : `=rank-clear <0-8>`. ")
        return await ctx.send(embed=make_embed("Configuration des rôles P0–P9", "\n".join(lines), "role"))

    if niveau is None or role is None or niveau < 0 or niveau > 8:
        return await ctx.send("Utilisation : `=rank <0-8> @role`. P9 est réservé au propriétaire configuré dans Render.")
    configured[str(niveau)] = role.id
    save_data(data)
    await ctx.send(f"Le rôle {role.mention} est maintenant associé à **P{niveau}**. Les niveaux supérieurs héritent des permissions inférieures. Utilise `=rank` pour voir tous les emplacements.")

@bot.command(name="rank-clear")
async def rank_clear_cmd(ctx, niveau: int):
    if not await staff_check(ctx, "rank-clear"):
        return
    if niveau < 0 or niveau > 8:
        return await ctx.send("Utilisation : `=rank-clear <0-8>`. P9 est réservé au propriétaire configuré dans Render.")
    data = load_data()
    gd = get_guild_data(data, ctx.guild.id)
    gd.setdefault("permission_roles", {}).pop(str(niveau), None)
    save_data(data)
    await ctx.send(f"Le rôle associé à P{niveau} a été retiré. Utilise `=rank` pour voir la configuration.")

@bot.command(name="derank")
async def derank_cmd(ctx, membre: discord.Member, niveau: int):
    if not await staff_check(ctx, "derank"): return
    data = load_data()
    gd = get_guild_data(data, ctx.guild.id)
    configured = gd.get("permission_roles", {})
    role_id = int(configured.get(str(niveau), ROLE_LEVELS.get(niveau, 0)) or 0)
    role = ctx.guild.get_role(role_id) if role_id else None
    if not role:
        return await reply_embed(ctx, "Rôle introuvable", f"Aucun rôle n'est configuré pour P{niveau}. Utilise `=rank {niveau} @role`.", "error")
    await membre.remove_roles(role, reason=f"Retrait du niveau P{niveau} par {ctx.author}")
    await ctx.send(f"Le rôle {role.mention} (P{niveau}) a été retiré à {membre.mention}.")

@bot.command(name="add-role")
async def add_role_cmd(ctx, membre: discord.Member, role: discord.Role):
    if not await staff_check(ctx, "add-role"): return
    await membre.add_roles(role, reason=f"Par {ctx.author}")
    await reply_embed(ctx, "Rôle ajouté", f"{role.mention} ajouté à {membre.mention}.", "success")

@bot.command(name="del-role")
async def del_role_cmd(ctx, membre: discord.Member, role: discord.Role):
    if not await staff_check(ctx, "del-role"): return
    await membre.remove_roles(role, reason=f"Par {ctx.author}")
    await reply_embed(ctx, "Rôle retiré", f"{role.mention} retiré à {membre.mention}.", "success")

@bot.command(name="mutelist")
async def mutelist_cmd(ctx):
    data = load_data()
    active = []
    for user_id, info in data["tempmutes"].items():
        if info["until"] > time.time():
            active.append(f"<@{user_id}> — fin <t:{int(info['until'])}:R>")
    await ctx.send(embed=make_embed("Timeouts suivis", "\n".join(active) or "Aucun timeout temporaire suivi.", "moderation"))

@bot.command(name="banlist")
async def banlist_cmd(ctx):
    bans = [entry async for entry in ctx.guild.bans()]
    embed = make_embed("Liste des bannissements", emoji="moderation")
    embed.description = "\n".join(f"{entry.user} — ID `{entry.user.id}`" for entry in bans[:40]) or "Aucun bannissement."
    await ctx.send(embed=embed)

@bot.command(name="adminlist")
async def adminlist_cmd(ctx):
    admins = [m.mention for m in ctx.guild.members if m.guild_permissions.administrator]
    await ctx.send(embed=make_embed("Administrateurs", "\n".join(admins) or "Aucun administrateur trouvé.", "user"))

@bot.command(name="staff-list")
async def staff_list_cmd(ctx):
    members = [m for m in ctx.guild.members if staff_level(m) > 0]
    description = "\n".join(f"{m.mention} — niveau {staff_level(m)}" for m in members[:50])
    await ctx.send(embed=make_embed("Équipe du staff", description or "Aucun rôle de staff configuré.", "user"))


# ============================================================
# SALONS : VERROUILLAGE
# ============================================================

@bot.command(name="lock")
async def lock_cmd(ctx, salon: Optional[discord.TextChannel] = None):
    if not await staff_check(ctx, "lock"): return
    salon = salon or ctx.channel
    await salon.set_permissions(ctx.guild.default_role, send_messages=False)
    await reply_embed(ctx, "Salon verrouillé", salon.mention, "lock")

@bot.command(name="unlock")
async def unlock_cmd(ctx, salon: Optional[discord.TextChannel] = None):
    if not await staff_check(ctx, "unlock"): return
    salon = salon or ctx.channel
    await salon.set_permissions(ctx.guild.default_role, send_messages=None)
    await reply_embed(ctx, "Salon déverrouillé", salon.mention, "unlock")

@bot.command(name="lockall")
async def lockall_cmd(ctx):
    if not await staff_check(ctx, "lockall"): return
    count = 0
    for channel in ctx.guild.text_channels:
        try:
            await channel.set_permissions(ctx.guild.default_role, send_messages=False)
            count += 1
        except discord.Forbidden:
            continue
    await reply_embed(ctx, "Verrouillage global", f"{count} salons verrouillés.", "lock")

@bot.command(name="unlockall")
async def unlockall_cmd(ctx):
    if not await staff_check(ctx, "unlockall"): return
    count = 0
    for channel in ctx.guild.text_channels:
        try:
            await channel.set_permissions(ctx.guild.default_role, send_messages=None)
            count += 1
        except discord.Forbidden:
            continue
    await reply_embed(ctx, "Déverrouillage global", f"{count} salons déverrouillés.", "unlock")

@bot.command(name="scan")
async def scan_cmd(ctx, membre: Optional[discord.Member] = None):
    membre = membre or ctx.author
    roles = [r.mention for r in membre.roles if r != ctx.guild.default_role]
    embed = make_embed(f"Scan de {membre}", emoji="info")
    embed.add_field(name="Compte créé", value=f"<t:{int(membre.created_at.timestamp())}:F>")
    embed.add_field(name="Arrivée", value=f"<t:{int(membre.joined_at.timestamp())}:F>" if membre.joined_at else "Inconnue")
    embed.add_field(name="Rôles", value=", ".join(roles) or "Aucun", inline=False)
    await ctx.send(embed=embed)


# ============================================================
# TICKETS MULTI-PANELS CONFIGURABLES
# ============================================================

# Les données des tickets sont séparées par serveur dans ticket_panels.
# Chaque panel possède ses options, ses rôles, son salon de publication
# et ses catégories Discord de destination.

class TicketOptionModal(discord.ui.Modal, title="Ajouter une option de ticket"):
    option_name = discord.ui.TextInput(label="Nom de l'option", placeholder="Ex. Direction", max_length=45)
    option_description = discord.ui.TextInput(label="Description", placeholder="Décris brièvement cette demande", max_length=180, required=False)

    def __init__(self, setup_state, setup_layout_view):
        super().__init__(timeout=300)
        self.setup_state = setup_state
        self.setup_layout_view = setup_layout_view

    async def on_submit(self, interaction: discord.Interaction):
        self.setup_state.pending_option = {
            "name": str(self.option_name).strip(),
            "description": str(self.option_description).strip(),
            "role_ids": [],
        }
        await interaction.response.send_message(
            "Choisis maintenant les rôles autorisés pour cette option. Tu peux sélectionner plusieurs rôles.",
            view=TicketRolePickView(self.setup_state, self.setup_layout_view), ephemeral=True)


class TicketRolePickView(discord.ui.View):
    def __init__(self, setup_state, setup_layout_view):
        super().__init__(timeout=300)
        self.setup_state = setup_state
        self.setup_layout_view = setup_layout_view
        self.add_item(discord.ui.RoleSelect(placeholder="Rôles autorisés", min_values=1, max_values=25))
        self.children[0].callback = self.roles_selected

    async def roles_selected(self, interaction: discord.Interaction):
        if not self.setup_state.pending_option:
            return await interaction.response.send_message("Cette option a expiré. Clique à nouveau sur Ajouter une option.", ephemeral=True)
        selected_roles = self.children[0].values
        self.setup_state.pending_option["role_ids"] = [role.id for role in selected_roles]
        self.setup_state.options.append(self.setup_state.pending_option)
        added_name = self.setup_state.pending_option["name"]
        self.setup_state.pending_option = None
        # Components V2 interdit le paramètre `content` dans send_message.
        # On renvoie le panneau V2 lui-même, qui contient déjà le texte et les boutons.
        await interaction.response.send_message(
            view=self.setup_layout_view, ephemeral=True)


class TicketSetupViewState:
    """État du configurateur uniquement : aucun callback discord.ui ici.

    Important : les méthodes décorées par @discord.ui.button deviennent des objets
    Button sur une instance View. Garder l'état dans une classe simple évite de
    tenter d'appeler ces objets comme des fonctions.
    """
    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        self.mode = "buttons"
        self.options = []
        self.pending_option = None
        self.publish_channel_id = None
        self.panel_title = "Centre de support"
        self.panel_description = "Choisis une catégorie ci-dessous pour ouvrir un ticket privé."


class TicketSetupLayoutView(discord.ui.LayoutView):
    """Panneau Components V2 : texte et boutons dans le même conteneur."""
    def __init__(self, guild_id: int):
        super().__init__(timeout=900)
        self.state = TicketSetupViewState(guild_id)
        self.container = discord.ui.Container(
            discord.ui.TextDisplay("## Configuration des tickets\nChoisis le format, ajoute les options, sélectionne les rôles autorisés et publie le panneau dans le salon souhaité."),
            discord.ui.Separator(),
            discord.ui.ActionRow(
                discord.ui.Button(label="Boutons", style=discord.ButtonStyle.primary, custom_id="s42:setup:buttons"),
                discord.ui.Button(label="Menu déroulant", style=discord.ButtonStyle.primary, custom_id="s42:setup:select"),
            ),
            discord.ui.ActionRow(
                discord.ui.Button(label="Ajouter une option", style=discord.ButtonStyle.primary, custom_id="s42:setup:add"),
                discord.ui.Button(label="Choisir le salon et publier", style=discord.ButtonStyle.danger, custom_id="s42:setup:publish"),
            ),
            accent_colour=discord.Colour(0x000000),
        )
        self.add_item(self.container)
        buttons = [item for row in self.container.children if isinstance(row, discord.ui.ActionRow) for item in row.children]
        buttons[0].callback = self.choose_buttons
        buttons[1].callback = self.choose_dropdown
        buttons[2].callback = self.add_option
        buttons[3].callback = self.publish

    async def choose_buttons(self, interaction: discord.Interaction):
        self.state.mode = "buttons"
        await interaction.response.send_message("Format choisi : boutons.", ephemeral=True)

    async def choose_dropdown(self, interaction: discord.Interaction):
        self.state.mode = "select"
        await interaction.response.send_message("Format choisi : menu déroulant.", ephemeral=True)

    async def add_option(self, interaction: discord.Interaction):
        if len(self.state.options) >= 25:
            return await interaction.response.send_message("La limite Discord est de 25 options par menu.", ephemeral=True)
        await interaction.response.send_modal(TicketOptionModal(self.state, self))

    async def publish(self, interaction: discord.Interaction):
        if not self.state.options:
            return await interaction.response.send_message("Ajoute au moins une option avant de publier.", ephemeral=True)
        await interaction.response.send_message("Dans quel salon publier le panel ?", view=TicketPublishChannelView(self.state), ephemeral=True)


class TicketPublishChannelView(discord.ui.View):
    def __init__(self, setup_view):
        super().__init__(timeout=300)
        self.setup_view = setup_view
        self.add_item(discord.ui.ChannelSelect(channel_types=[discord.ChannelType.text], placeholder="Salon de publication", min_values=1, max_values=1))
        self.children[0].callback = self.channel_selected

    async def channel_selected(self, interaction: discord.Interaction):
        # ChannelSelect peut renvoyer un AppCommandChannel et non un TextChannel
        # selon la version de discord.py. Résoudre l'ID via le cache du serveur.
        selected = self.children[0].values[0]
        selected_id = getattr(selected, "id", None)
        channel = interaction.guild.get_channel(selected_id) if interaction.guild and selected_id else None
        if channel is None and selected_id:
            try:
                channel = await interaction.guild.fetch_channel(selected_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                channel = None
        if not isinstance(channel, discord.TextChannel):
            return await interaction.response.send_message(
                "Le salon sélectionné n'est pas un salon textuel accessible. Choisis un salon de texte classique.",
                ephemeral=True,
            )
        data = load_data()
        guild_data = get_guild_data(data, interaction.guild_id)
        panel_id = str(int(time.time() * 1000))
        panel = {
            "id": panel_id, "mode": self.setup_view.mode,
            "title": self.setup_view.panel_title,
            "description": self.setup_view.panel_description,
            "options": self.setup_view.options,
            "publish_channel_id": channel.id,
        }
        guild_data.setdefault("ticket_panels", {})[panel_id] = panel
        save_data(data)
        view = DynamicTicketPanelView(panel, interaction.guild.name)
        try:
            # Components V2 : titre, description et menu/boutons dans le même conteneur.
            message = await channel.send(view=view)
        except discord.Forbidden:
            return await interaction.response.send_message("Je n'ai pas la permission d'envoyer le panel dans ce salon.", ephemeral=True)
        panel["message_id"] = message.id
        save_data(data)
        await interaction.response.send_message(f"Panel publié dans {channel.mention} avec {len(panel['options'])} option(s).", ephemeral=True)


class DynamicTicketPanelView(discord.ui.LayoutView):
    """Panel public de tickets en Components V2 : texte et contrôles regroupés."""
    def __init__(self, panel, server_name=""):
        super().__init__(timeout=None)
        self.panel = panel
        self.server_name = server_name
        children = [
            discord.ui.TextDisplay(f"## {panel['title']} — {server_name}".strip(" —") + f"\n{panel['description']}"),
            discord.ui.Separator(),
        ]
        if panel.get("mode") == "select":
            options = [discord.SelectOption(label=o["name"][:100], description=(o.get("description") or "Ouvrir un ticket")[:100], value=str(i)) for i, o in enumerate(panel["options"][:25])]
            select = discord.ui.Select(placeholder="Choisis le type de ticket", options=options, custom_id=f"s42:ticket:select:{panel['id']}")
            select.callback = self.select_callback
            children.append(discord.ui.ActionRow(select))
        else:
            buttons = []
            for index, option in enumerate(panel["options"][:25]):
                button = discord.ui.Button(label=option["name"][:80], style=discord.ButtonStyle.primary, custom_id=f"s42:ticket:button:{panel['id']}:{index}")
                async def callback(interaction, index=index):
                    await self.create_ticket(interaction, index)
                button.callback = callback
                buttons.append(button)
            for i in range(0, len(buttons), 5):
                children.append(discord.ui.ActionRow(*buttons[i:i+5]))
        self.add_item(discord.ui.Container(*children, accent_colour=discord.Colour(0x000000)))

    async def select_callback(self, interaction: discord.Interaction):
        await self.create_ticket(interaction, int(interaction.data["values"][0]))

    async def create_ticket(self, interaction: discord.Interaction, option_index: int):
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message("Cette action doit être utilisée sur un serveur.", ephemeral=True)
        data = load_data()
        gd = get_guild_data(data, guild.id)
        panel = gd.get("ticket_panels", {}).get(str(self.panel["id"]), self.panel)
        if option_index >= len(panel.get("options", [])):
            return await interaction.response.send_message("Cette option de ticket n'existe plus.", ephemeral=True)
        option = panel["options"][option_index]
        active = gd.setdefault("tickets", {})
        key = f"{interaction.user.id}:{panel['id']}"
        previous = active.get(key)
        if previous and guild.get_channel(int(previous.get("channel_id", 0))):
            return await interaction.response.send_message(f"Tu as déjà un ticket ouvert : <#{previous['channel_id']}>.", ephemeral=True)
        safe_user = re.sub(r"[^a-z0-9-]", "", interaction.user.name.lower().replace(" ", "-"))[:35] or "membre"
        safe_option = re.sub(r"[^a-z0-9-]", "", option["name"].lower().replace(" ", "-"))[:25] or "ticket"
        category_name = option["name"][:90]
        category = discord.utils.get(guild.categories, name=category_name)
        if category is None:
            category = await guild.create_category(category_name, reason=f"Catégorie de tickets {category_name}")
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        }
        bot_member = guild.me
        if bot_member:
            overwrites[bot_member] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True)
        for role_id in option.get("role_ids", []):
            role = guild.get_role(int(role_id))
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        # Le rôle administrateur configuré globalement peut voir tous les tickets.
        owner_role_id = gd.get("owner_role_id")
        owner_role = guild.get_role(int(owner_role_id)) if owner_role_id else None
        if owner_role:
            overwrites[owner_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        channel = await guild.create_text_channel(
            name=f"{safe_option}-{safe_user}"[:95], category=category, overwrites=overwrites,
            topic=f"ticket|panel={panel['id']}|option={option['name']}|owner={interaction.user.id}",
            reason=f"Ticket {option['name']} ouvert par {interaction.user}")
        active[key] = {"channel_id": channel.id, "user_id": interaction.user.id, "panel_id": panel["id"], "option": option["name"], "role_ids": option.get("role_ids", []), "claimed_by": None}
        save_data(data)
        await channel.send(embed=make_embed(f"Ticket — {option['name']}", f"Bonjour {interaction.user.mention}, explique ta demande ici.\n\nUtilise les boutons ci-dessous pour gérer ce ticket.", "ticket"), view=TicketControlView())
        await interaction.response.send_message(f"Ton ticket a été créé : {channel.mention}.", ephemeral=True)


class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    def _ticket_record(self, interaction):
        data = load_data()
        gd = get_guild_data(data, interaction.guild_id)
        for key, ticket in gd.setdefault("tickets", {}).items():
            if int(ticket.get("channel_id", 0)) == interaction.channel_id:
                return data, gd, key, ticket
        return data, gd, None, None

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, custom_id="s42:ticket:close")
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        data, gd, key, ticket = self._ticket_record(interaction)
        if not ticket:
            return await interaction.response.send_message("Ce salon n'est pas un ticket suivi.", ephemeral=True)
        if not can_manage_ticket(interaction.user, ticket):
            return await interaction.response.send_message("Tu n'as pas la permission de fermer ce ticket.", ephemeral=True)
        await interaction.response.send_message("Ticket fermé. Le salon va être supprimé.")
        await log_action(interaction.guild, "Ticket fermé", f"Salon : {interaction.channel.mention}\nOption : {ticket['option']}\nFermé par : {interaction.user.mention}")
        gd["tickets"].pop(key, None)
        save_data(data)
        await interaction.channel.delete(reason=f"Ticket fermé par {interaction.user}")

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.primary, custom_id="s42:ticket:claim")
    async def claim_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        data, gd, key, ticket = self._ticket_record(interaction)
        if not ticket:
            return await interaction.response.send_message("Ce salon n'est pas un ticket suivi.", ephemeral=True)
        if not can_manage_ticket(interaction.user, ticket):
            return await interaction.response.send_message("Seuls les rôles autorisés peuvent claim ce ticket.", ephemeral=True)
        if ticket.get("claimed_by") and ticket["claimed_by"] != interaction.user.id:
            return await interaction.response.send_message(f"Ce ticket est déjà claim par <@{ticket['claimed_by']}>.", ephemeral=True)
        ticket["claimed_by"] = interaction.user.id
        save_data(data)
        # Les rôles configurés pour cette option constituent la liste autorisée (WL).
        # Le membre qui claim est explicitement autorisé à écrire dans le ticket.
        if isinstance(interaction.user, discord.Member):
            await interaction.channel.set_permissions(interaction.user, view_channel=True, send_messages=True, read_message_history=True)
        await interaction.response.send_message(f"Ticket pris en charge par {interaction.user.mention}. Seuls l'auteur, la personne assignée et les personnes autorisées (WL) peuvent écrire.")

    @discord.ui.button(label="Rename", style=discord.ButtonStyle.primary, custom_id="s42:ticket:rename")
    async def rename_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        data, gd, key, ticket = self._ticket_record(interaction)
        if not ticket or not can_manage_ticket(interaction.user, ticket):
            return await interaction.response.send_message("Tu n'as pas la permission de renommer ce ticket.", ephemeral=True)
        await interaction.response.send_modal(TicketRenameModal())


class TicketRenameModal(discord.ui.Modal, title="Renommer le ticket"):
    new_name = discord.ui.TextInput(label="Nouveau nom", max_length=90)
    async def on_submit(self, interaction: discord.Interaction):
        name = re.sub(r"[^a-z0-9-]", "-", str(self.new_name).lower().replace(" ", "-"))[:90].strip("-") or "ticket"
        await interaction.channel.edit(name=name, reason=f"Ticket renommé par {interaction.user}")
        await interaction.response.send_message(f"Ticket renommé en **{name}**.", ephemeral=True)


def can_manage_ticket(member, ticket):
    if not isinstance(member, discord.Member):
        return False
    if member.guild_permissions.administrator or member.guild_permissions.manage_channels:
        return True
    allowed = set(int(x) for x in ticket.get("role_ids", []))
    return any(role.id in allowed for role in member.roles)


@bot.command(name="ticket")
async def ticket_cmd(ctx):
    await ctx.send(view=TicketSetupLayoutView(ctx.guild.id))


@bot.command(name="add")
async def ticket_add(ctx, membre: discord.Member):
    data = load_data(); gd = get_guild_data(data, ctx.guild.id)
    ticket = next((t for t in gd.setdefault("tickets", {}).values() if int(t.get("channel_id", 0)) == ctx.channel.id), None)
    if not ticket:
        return await ctx.send("Cette commande doit être utilisée dans un ticket.")
    if not can_manage_ticket(ctx.author, ticket):
        return await ctx.send("Tu n'as pas la permission de gérer ce ticket.")
    await ctx.channel.set_permissions(membre, view_channel=True, send_messages=True, read_message_history=True)
    await ctx.send(f"{membre.mention} a été ajouté au ticket avec succès.")


@bot.command(name="del")
async def ticket_del(ctx, membre: discord.Member):
    data = load_data(); gd = get_guild_data(data, ctx.guild.id)
    ticket = next((t for t in gd.setdefault("tickets", {}).values() if int(t.get("channel_id", 0)) == ctx.channel.id), None)
    if not ticket:
        return await ctx.send("Cette commande doit être utilisée dans un ticket.")
    if not can_manage_ticket(ctx.author, ticket):
        return await ctx.send("Tu n'as pas la permission de gérer ce ticket.")
    await ctx.channel.set_permissions(membre, overwrite=None)
    await ctx.send(f"{membre.mention} a été retiré du ticket avec succès.")


@bot.command(name="close")
async def ticket_close_cmd(ctx):
    data = load_data(); gd = get_guild_data(data, ctx.guild.id)
    found = next(((key, t) for key, t in gd.setdefault("tickets", {}).items() if int(t.get("channel_id", 0)) == ctx.channel.id), None)
    if not found:
        return await ctx.send("Cette commande doit être utilisée dans un ticket.")
    key, ticket = found
    if not can_manage_ticket(ctx.author, ticket):
        return await ctx.send("Tu n'as pas la permission de fermer ce ticket.")
    await log_action(ctx.guild, "Ticket fermé", f"Salon : #{ctx.channel.name}\nOption : {ticket['option']}\nFermé par : {ctx.author.mention}")
    gd["tickets"].pop(key, None); save_data(data)
    await ctx.send("Ticket fermé. Le salon va être supprimé.")
    await ctx.channel.delete(reason=f"Ticket fermé par {ctx.author}")


@bot.command(name="rename")
async def ticket_rename(ctx, *, nom: str):
    data = load_data(); gd = get_guild_data(data, ctx.guild.id)
    ticket = next((t for t in gd.setdefault("tickets", {}).values() if int(t.get("channel_id", 0)) == ctx.channel.id), None)
    if not ticket:
        return await ctx.send("Cette commande doit être utilisée dans un ticket.")
    if not can_manage_ticket(ctx.author, ticket):
        return await ctx.send("Tu n'as pas la permission de gérer ce ticket.")
    name = re.sub(r"[^a-z0-9-]", "-", nom.lower().replace(" ", "-"))[:90].strip("-") or "ticket"
    await ctx.channel.edit(name=name)
    await ctx.send(f"Ticket renommé en **{name}**.")


@bot.command(name="ticket-stats")
async def ticket_stats(ctx):
    data = load_data(); gd = get_guild_data(data, ctx.guild.id)
    await ctx.send(embed=make_embed("Statistiques tickets", f"Tickets ouverts : **{len(gd.setdefault('tickets', {}))}**\nPanels configurés : **{len(gd.setdefault('ticket_panels', {}))}**", "stats"))


# ============================================================
# GIVEAWAYS AVEC BOUTONS
# ============================================================

class GiveawayJoinView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Participer", style=discord.ButtonStyle.primary,
                       custom_id="s42_giveaway_join")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = load_data()
        giveaway = data["giveaways"].get(str(interaction.message.id))
        if not giveaway or giveaway.get("ended"):
            return await interaction.response.send_message(
                embed=make_embed("Giveaway terminé", "Les participations sont fermées.", "warning"),
                ephemeral=True)
        entries = giveaway.setdefault("entries", [])
        if interaction.user.id in entries:
            entries.remove(interaction.user.id)
            message = "Ta participation a été retirée."
        else:
            entries.append(interaction.user.id)
            message = "Ta participation est enregistrée."
        save_data(data)
        await interaction.response.send_message(embed=make_embed("Participation", message, "giveaway"), ephemeral=True)

@bot.command(name="giveaway")
async def giveaway_cmd(ctx, duree: str, gagnants: int, *, lot: str):
    if not await staff_check(ctx, "giveaway"): return
    seconds = parse_duration(duree)
    if seconds is None or seconds < 10 or gagnants < 1:
        return await reply_embed(ctx, "Paramètres invalides",
                                 "Exemple : `=giveaway 1h 1 Nitro`.", "error")
    ends = time.time() + seconds
    embed = make_embed("Giveaway", f"**Lot :** {lot}\n**Gagnants :** {gagnants}\n"
        f"**Fin :** <t:{int(ends)}:R>\n**Organisé par :** {ctx.author.mention}", "giveaway")
    # Les boutons doivent être envoyés avec l’embed dès le premier envoi.
    view = GiveawayJoinView()
    message = await ctx.send(embed=embed, view=view)
    data = load_data()
    data["giveaways"][str(message.id)] = {
        "channel": ctx.channel.id, "guild": ctx.guild.id, "ends": ends,
        "winners": gagnants, "prize": lot, "entries": [], "ended": False,
        "host": ctx.author.id
    }
    save_data(data)

@tasks.loop(seconds=15)
async def giveaway_watcher():
    data = load_data()
    changed = False
    for message_id, giveaway in list(data["giveaways"].items()):
        if giveaway.get("ended") or time.time() < giveaway.get("ends", 0):
            continue
        guild = bot.get_guild(giveaway["guild"])
        channel = guild.get_channel(giveaway["channel"]) if guild else None
        winners = random.sample(giveaway.get("entries", []),
                                min(giveaway.get("winners", 1), len(giveaway.get("entries", []))))
        if channel:
            mentions = ", ".join(f"<@{uid}>" for uid in winners) if winners else "Aucun participant"
            await channel.send(embed=make_embed("Giveaway terminé",
                f"Lot : **{giveaway['prize']}**\nGagnant(s) : {mentions}", "giveaway"))
            try:
                message = await channel.fetch_message(int(message_id))
                await message.edit(view=None)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        giveaway["ended"] = True
        giveaway["winners_ids"] = winners
        changed = True
    if changed:
        save_data(data)

@bot.command(name="gcancel")
async def giveaway_cancel(ctx, message_id: int):
    if not await staff_check(ctx, "gcancel"): return
    data = load_data()
    giveaway = data["giveaways"].get(str(message_id))
    if not giveaway or giveaway.get("ended"):
        return await reply_embed(ctx, "Giveaway introuvable", "ID invalide ou giveaway déjà terminé.", "error")
    giveaway["ended"] = True
    save_data(data)
    await reply_embed(ctx, "Giveaway annulé", f"ID du message : `{message_id}`", "success")

@bot.command(name="gend")
async def giveaway_end(ctx, message_id: int):
    if not await staff_check(ctx, "gend"): return
    data = load_data()
    giveaway = data["giveaways"].get(str(message_id))
    if not giveaway:
        return await reply_embed(ctx, "Giveaway introuvable", "Vérifie l'ID du message.", "error")
    giveaway["ends"] = time.time()
    giveaway["ended"] = False
    save_data(data)
    await reply_embed(ctx, "Fin demandée", "Le giveaway sera clôturé au prochain passage du vérificateur.", "success")

@bot.command(name="reroll")
async def giveaway_reroll(ctx, message_id: int):
    if not await staff_check(ctx, "reroll"): return
    giveaway = load_data()["giveaways"].get(str(message_id))
    if not giveaway or not giveaway.get("ended"):
        return await reply_embed(ctx, "Impossible", "Ce giveaway n'est pas terminé.", "error")
    entries = giveaway.get("entries", [])
    if not entries:
        return await reply_embed(ctx, "Aucun participant", "Personne n'a participé.", "warning")
    winner = random.choice(entries)
    await reply_embed(ctx, "Nouveau gagnant", f"Gagnant : <@{winner}>\nLot : {giveaway['prize']}", "giveaway")

@bot.command(name="glist")
async def giveaway_list(ctx):
    data = load_data()
    active = [f"`{mid}` — {g['prize']} — fin <t:{int(g['ends'])}:R>"
              for mid, g in data["giveaways"].items() if not g.get("ended")]
    await ctx.send(embed=make_embed("Giveaways actifs", "\n".join(active) or "Aucun giveaway actif.", "giveaway"))


# ============================================================
# MESSAGES / CONFIGURATION
# ============================================================

class WelcomeMessageModal(discord.ui.Modal):
    def __init__(self, kind: str, current: str):
        self.kind = kind
        title = "Modifier le message d'arrivée" if kind == "join" else "Modifier le message de départ"
        super().__init__(title=title, timeout=300)
        self.message_input = discord.ui.TextInput(
            label="Message à envoyer",
            placeholder="Écris librement le message souhaité. Variables : {user}, {server}",
            default=current[:2000],
            max_length=2000,
            style=discord.TextStyle.paragraph,
            required=True,
        )
        self.add_item(self.message_input)

    async def on_submit(self, interaction: discord.Interaction):
        data = load_data()
        gd = get_guild_data(data, interaction.guild_id)
        gd[f"{self.kind}_message"] = str(self.message_input.value)
        save_data(data)
        await interaction.response.send_message("Message enregistré.", ephemeral=True)


class WelcomeChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, kind: str):
        self.kind = kind
        super().__init__(placeholder="Choisir le salon de publication", channel_types=[discord.ChannelType.text], min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        data = load_data()
        gd = get_guild_data(data, interaction.guild_id)
        gd[f"{self.kind}_channel_id"] = self.values[0].id
        save_data(data)
        await interaction.response.edit_message(embed=welcome_panel_embed(interaction.guild, self.kind), view=WelcomeMessagePanel(self.kind, interaction.guild_id))


class WelcomeDelaySelect(discord.ui.Select):
    def __init__(self, kind: str, current: int):
        self.kind = kind
        options = [
            discord.SelectOption(label="Ne jamais supprimer", value="0", description="Le message reste dans le salon"),
            discord.SelectOption(label="10 secondes", value="10"),
            discord.SelectOption(label="30 secondes", value="30"),
            discord.SelectOption(label="1 minute", value="60"),
            discord.SelectOption(label="5 minutes", value="300"),
            discord.SelectOption(label="10 minutes", value="600"),
            discord.SelectOption(label="30 minutes", value="1800"),
            discord.SelectOption(label="1 heure", value="3600"),
        ]
        super().__init__(placeholder="Délai avant suppression automatique", min_values=1, max_values=1, options=options)
        self.default_value = str(current)
        for option in self.options:
            option.default = option.value == self.default_value

    async def callback(self, interaction: discord.Interaction):
        data = load_data()
        gd = get_guild_data(data, interaction.guild_id)
        gd[f"{self.kind}_delete_after"] = int(self.values[0])
        save_data(data)
        await interaction.response.edit_message(embed=welcome_panel_embed(interaction.guild, self.kind), view=WelcomeMessagePanel(self.kind, interaction.guild_id))


class WelcomeMessagePanel(discord.ui.View):
    def __init__(self, kind: str, guild_id: int):
        super().__init__(timeout=900)
        self.kind = kind
        self.guild_id = guild_id
        gd = get_guild_data(load_data(), guild_id)
        self.add_item(WelcomeChannelSelect(kind))
        self.add_item(WelcomeDelaySelect(kind, int(gd.get(f"{kind}_delete_after", 0))))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.administrator and not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("Tu dois être administrateur ou gérer le serveur pour modifier ce panel.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Modifier le message", style=discord.ButtonStyle.primary, row=2)
    async def edit_message_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = load_data()
        gd = get_guild_data(data, interaction.guild_id)
        current = gd.get(f"{self.kind}_message", "Bienvenue {user} sur {server}." if self.kind == "join" else "{user} a quitté {server}.")
        await interaction.response.send_modal(WelcomeMessageModal(self.kind, current))

    @discord.ui.button(label="Activer / désactiver", style=discord.ButtonStyle.danger, row=2)
    async def toggle_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = load_data()
        gd = get_guild_data(data, interaction.guild_id)
        key = f"{self.kind}_enabled"
        gd[key] = not gd.get(key, True)
        save_data(data)
        await interaction.response.edit_message(embed=welcome_panel_embed(interaction.guild, self.kind), view=WelcomeMessagePanel(self.kind, interaction.guild_id))


def welcome_panel_embed(guild: discord.Guild, kind: str) -> discord.Embed:
    data = load_data()
    gd = get_guild_data(data, guild.id)
    is_join = kind == "join"
    title = f"Message d'arrivée de {guild.name}" if is_join else f"Message de départ de {guild.name}"
    message = gd.get(f"{kind}_message", "Bienvenue {user} sur {server}." if is_join else "{user} a quitté {server}.")
    channel_id = gd.get(f"{kind}_channel_id", 0)
    channel = guild.get_channel(int(channel_id)) if channel_id else None
    delay = int(gd.get(f"{kind}_delete_after", 0))
    enabled = gd.get(f"{kind}_enabled", True)
    delay_text = "Jamais" if delay == 0 else format_duration(delay)
    embed = make_embed(title, emoji="user")
    embed.description = (
        f"**État :** {'Activé' if enabled else 'Désactivé'}\n"
        f"**Salon :** {channel.mention if channel else 'Non configuré'}\n"
        f"**Message :** {message}\n"
        f"**Suppression automatique :** {delay_text}\n\n"
        "Le contenu du message est libre : écris le texte que tu veux dans « Modifier le message ». Variables : `{user}` (membre) et `{server}` (serveur). Le délai de suppression se règle séparément."
    )
    return embed


@bot.command(name="joinmessage")
async def joinmessage(ctx):
    data = load_data()
    gd = get_guild_data(data, ctx.guild.id)
    gd.setdefault("join_enabled", True)
    gd.setdefault("join_delete_after", 0)
    gd.setdefault("join_channel_id", 0)
    gd.setdefault("join_message", "Bienvenue {user} sur {server}.")
    save_data(data)
    await ctx.send(embed=welcome_panel_embed(ctx.guild, "join"), view=WelcomeMessagePanel("join", ctx.guild.id))


@bot.command(name="leavemessage")
async def leavemessage(ctx):
    data = load_data()
    gd = get_guild_data(data, ctx.guild.id)
    gd.setdefault("leave_enabled", True)
    gd.setdefault("leave_delete_after", 0)
    gd.setdefault("leave_channel_id", 0)
    gd.setdefault("leave_message", "{user} a quitté {server}.")
    save_data(data)
    await ctx.send(embed=welcome_panel_embed(ctx.guild, "leave"), view=WelcomeMessagePanel("leave", ctx.guild.id))


@bot.event
async def on_member_join(member):
    data = load_data()
    gd = get_guild_data(data, member.guild.id)
    if not gd.get("join_enabled", True):
        return
    channel_id = gd.get("join_channel_id") or gd.get("logs_channel") or data.get("logs_channel") or LOG_CHANNEL_ID
    channel = member.guild.get_channel(int(channel_id)) if channel_id else None
    if channel:
        template = gd.get("join_message", "Bienvenue {user} sur {server}.")
        text = template.replace("{user}", member.mention).replace("{server}", member.guild.name)
        try:
            delay = max(0, int(gd.get("join_delete_after", 0)))
            message = await channel.send(embed=make_embed(f"Arrivée sur {member.guild.name}", text, "user"))
            if delay:
                await message.delete(delay=delay)
        except discord.Forbidden:
            pass


@bot.event
async def on_member_remove(member):
    data = load_data()
    gd = get_guild_data(data, member.guild.id)
    if not gd.get("leave_enabled", True):
        return
    channel_id = gd.get("leave_channel_id") or gd.get("logs_channel") or data.get("logs_channel") or LOG_CHANNEL_ID
    channel = member.guild.get_channel(int(channel_id)) if channel_id else None
    if channel:
        template = gd.get("leave_message", "{user} a quitté {server}.")
        text = template.replace("{user}", str(member)).replace("{server}", member.guild.name)
        try:
            delay = max(0, int(gd.get("leave_delete_after", 0)))
            message = await channel.send(embed=make_embed(f"Départ de {member.guild.name}", text, "user"))
            if delay:
                await message.delete(delay=delay)
        except discord.Forbidden:
            pass

@bot.command(name="say")
async def say_cmd(ctx, *, message: str):
    await ctx.message.delete()
    await ctx.send(embed=make_embed("Message", message, "info"))

@bot.command(name="mp")
async def mp_cmd(ctx, membre: discord.Member, *, message: str):
    await membre.send(f"Message de {ctx.guild.name}\n\n{message}")
    await reply_embed(ctx, "Message privé envoyé", f"Message envoyé à {membre.mention}.", "success")

@bot.command(name="dmall")
async def dmall_cmd(ctx, *, message: str):
    sent = 0
    for member in ctx.guild.members:
        if member.bot:
            continue
        try:
            await member.send(f"Message de {ctx.guild.name}\n\n{message}")
            sent += 1
        except discord.Forbidden:
            pass
    await reply_embed(ctx, "Envoi terminé", f"Message envoyé à {sent} membre(s).", "success")

@bot.command(name="setname")
async def setname_cmd(ctx, *, nom: str):
    await bot.user.edit(username=nom[:32])
    await reply_embed(ctx, "Nom du bot modifié", f"Nouveau nom : **{nom[:32]}**", "success")

@bot.command(name="setpic")
async def setpic_cmd(ctx, url: str):
    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                return await reply_embed(ctx, "Téléchargement impossible", "URL inaccessible.", "error")
            image_bytes = await response.read()
    await bot.user.edit(avatar=image_bytes)
    await reply_embed(ctx, "Avatar du bot modifié", "Modification effectuée.", "success")

@bot.command(name="setbanner")
async def setbanner_cmd(ctx):
    await reply_embed(ctx, "Bannière du bot",
                      "Discord ne permet pas de modifier la bannière du bot via l'API discord.py classique.", "warning")

@bot.command(name="setstatus")
async def setstatus_cmd(ctx, *, texte: str):
    await bot.change_presence(activity=discord.Game(name=texte))
    await reply_embed(ctx, "Statut modifié", texte, "success")

@bot.command(name="online")
async def online_cmd(ctx):
    await bot.change_presence(status=discord.Status.online)
    await reply_embed(ctx, "Statut en ligne", "Le bot est en ligne.", "success")

@bot.command(name="dnd")
async def dnd_cmd(ctx):
    await bot.change_presence(status=discord.Status.dnd)
    await reply_embed(ctx, "Statut Ne pas déranger", "Le bot est en mode Ne pas déranger.", "success")

@bot.command(name="owner")
async def owner_cmd(ctx):
    if not OWNER_USER_ID or ctx.author.id != OWNER_USER_ID:
        return await ctx.send("Commande réservée à l'identifiant OWNER_USER_ID configuré dans Render.")
    await ctx.send(f"Tu es le propriétaire P9 configuré : {ctx.author.mention}.")


# ============================================================
# COMMANDES UTILES
# ============================================================

@bot.command(name="delperm")
async def delperm_cmd(ctx, membre: discord.Member, role: discord.Role):
    await membre.remove_roles(role)
    await reply_embed(ctx, "Permission retirée", f"Rôle {role.mention} retiré à {membre.mention}.", "success")

@bot.command(name="online-status")
async def online_status(ctx):
    await reply_embed(ctx, "État du bot", f"Connecté en tant que {bot.user}.", "bot")


# ============================================================
# DÉMARRAGE
# ============================================================

persistent_views_registered = False

@bot.event
async def on_ready():
    global persistent_views_registered
    if not persistent_views_registered:
        bot.add_view(TicketControlView())
        saved = load_data()
        for guild_id, gd in saved.get("guilds", {}).items():
            for panel in gd.get("ticket_panels", {}).values():
                try:
                    bot.add_view(DynamicTicketPanelView(panel), message_id=int(panel.get("message_id", 0)) or None)
                except (ValueError, discord.HTTPException, TypeError):
                    pass
        for message_id, giveaway in saved.get("giveaways", {}).items():
            if not giveaway.get("ended"):
                try:
                    bot.add_view(GiveawayJoinView(), message_id=int(message_id))
                except (ValueError, discord.HTTPException):
                    pass
        persistent_views_registered = True
    print(f"Bot connecté : {bot.user} (ID: {bot.user.id})")

# Petit endpoint HTTP pour Render Web Service gratuit.
# Le bot Discord reste le processus principal ; Flask écoute sur le port fourni par Render.
web_app = Flask(__name__)

@web_app.get("/")
def health_check():
    return "Bot is running", 200

def run_web_server():
    port = int(os.environ.get("PORT", "10000"))
    web_app.run(host="0.0.0.0", port=port, use_reloader=False, threaded=True)

def main():
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN est absent du fichier .env.")
    Thread(target=run_web_server, daemon=True).start()
    bot.run(TOKEN)

if __name__ == "__main__":
    main()
