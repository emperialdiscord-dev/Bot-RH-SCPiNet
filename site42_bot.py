# -*- coding: utf-8 -*-
"""
SITE42 BOT — script complet de base
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

# Flask / keep-alive est facultatif. Si tu utilises un hébergeur qui le nécessite,
# ajoute ton propre keep_alive.py. Le bot fonctionne sans ce module.
try:
    from keep_alive import keep_alive
except ImportError:
    def keep_alive():
        return None


# ============================================================
# CONFIGURATION
# ============================================================

PREFIX = "="
DATA_FILE = "site42_data.json"
EMBED_COLOR = discord.Colour(0xFFFFFF)

# Remplace chaque valeur par TON emoji personnalisé.
# Format statique : <:nom:ID> | animé : <a:nom:ID>
EMOJIS = {
    "success": "EMOJI_SUCCES",
    "error": "EMOJI_ERREUR",
    "warning": "EMOJI_AVERTISSEMENT",
    "info": "EMOJI_INFO",
    "moderation": "EMOJI_MODERATION",
    "ticket": "EMOJI_TICKET",
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


# Mets ici les IDs des rôles qui correspondent aux niveaux du staff.
ROLE_LEVELS = {
    1: 0,
    2: 0,
    3: 0,
    4: 0,
    5: 0,
}

# Niveaux minimums par commande (administrateurs Discord passent automatiquement).
COMMAND_LEVELS = {
    "warn": 2, "sanction": 2, "tempmute": 2, "mute": 2,
    "ban": 3, "tempban": 3, "kick": 3, "unban": 3,
    "add-role": 3, "del-role": 3, "del-sanction": 3,
    "rank": 4, "derank": 4, "owner": 5,
    "lock": 2, "unlock": 2, "lockall": 4, "unlockall": 4,
}

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
    embed = discord.Embed(
        title=f"{em(emoji)} {title}",
        description=description,
        color=color or EMBED_COLOR,
        timestamp=discord.utils.utcnow(),
    )
    embed.set_footer(text="Site42")
    return embed

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
    if member.guild_permissions.administrator:
        return 999
    ids = {role.id for role in member.roles}
    return max((level for level, role_id in ROLE_LEVELS.items()
                if role_id and role_id in ids), default=0)

def has_level(member: discord.Member, command_name: str) -> bool:
    return staff_level(member) >= COMMAND_LEVELS.get(command_name, 1)

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
    channel_id = data.get("logs_channel") or LOG_CHANNEL_ID
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
                      f"Niveau requis : **{COMMAND_LEVELS.get(command_name, 1)}**.\n"
                      f"Ton niveau : **{staff_level(ctx.author)}**.", "error")
    return False

async def send_dm(member: discord.Member, title: str, description: str):
    try:
        await member.send(embed=make_embed(title, description, "moderation"))
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
async def on_ready():
    print(f"Site42 connecté : {bot.user} | préfixe {PREFIX}")
    if not giveaway_watcher.is_running():
        giveaway_watcher.start()


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


# ============================================================
# AIDE / INFOS
# ============================================================

@bot.command(name="help", aliases=["aide"])
async def help_command(ctx):
    embed = make_embed("Commandes Site42", emoji="bot")
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

@bot.command(name="stats-logs")
async def stats_logs(ctx):
    data = load_data()
    await reply_embed(ctx, "Statistiques des logs",
                      f"Sanctions enregistrées : **{sum(map(len, data['sanctions'].values()))}**\n"
                      f"Tickets suivis : **{len(data['tickets'])}**\n"
                      f"Giveaways suivis : **{len(data['giveaways'])}**", "stats")

@bot.command(name="logs-global")
@commands.has_permissions(administrator=True)
async def logs_global(ctx):
    data = load_data()
    data["logs_channel"] = ctx.channel.id
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
    await reply_embed(ctx, "Avertissement ajouté",
                      f"Membre : {membre.mention}\nModérateur : {ctx.author.mention}\nRaison : {raison}", "warning")
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
    await reply_embed(ctx, "Sanction supprimée",
                      f"{removed['type']} retirée pour {membre.mention}.", "success")

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
    await reply_embed(ctx, "Timeout appliqué",
                      f"Membre : {membre.mention}\nDurée : {duree}\nRaison : {raison}", "moderation")

@bot.command(name="mute")
async def mute_cmd(ctx, membre: discord.Member, *, raison="Aucune raison précisée"):
    if not await staff_check(ctx, "mute"): return
    await membre.timeout(discord.utils.utcnow() + datetime.timedelta(days=28), reason=raison)
    await reply_embed(ctx, "Membre réduit au silence",
                      f"{membre.mention}\nDurée maximale Discord : 28 jours.\nRaison : {raison}", "moderation")

@bot.command(name="unmute")
async def unmute_cmd(ctx, membre: discord.Member):
    if not await staff_check(ctx, "mute"): return
    await membre.timeout(None, reason=f"Unmute par {ctx.author}")
    await reply_embed(ctx, "Timeout retiré", f"{membre.mention} peut de nouveau parler.", "success")

@bot.command(name="ban")
async def ban_cmd(ctx, membre: discord.Member, *, raison="Aucune raison précisée"):
    if not await staff_check(ctx, "ban"): return
    await send_dm(membre, "Bannissement", f"Serveur : {ctx.guild.name}\nRaison : {raison}")
    await membre.ban(reason=raison)
    await reply_embed(ctx, "Membre banni", f"{membre} — {raison}", "moderation")
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
    await reply_embed(ctx, "Bannissement temporaire",
                      f"{membre} — durée : {duree}\nRaison : {raison}", "moderation")

@bot.command(name="unban")
async def unban_cmd(ctx, user_id: int, *, raison="Levée du bannissement"):
    if not await staff_check(ctx, "unban"): return
    await ctx.guild.unban(discord.Object(id=user_id), reason=raison)
    await reply_embed(ctx, "Bannissement levé", f"ID : `{user_id}`\nRaison : {raison}", "success")

@bot.command(name="kick")
async def kick_cmd(ctx, membre: discord.Member, *, raison="Aucune raison précisée"):
    if not await staff_check(ctx, "kick"): return
    await send_dm(membre, "Expulsion", f"Raison : {raison}")
    await membre.kick(reason=raison)
    await reply_embed(ctx, "Membre expulsé", f"{membre} — {raison}", "moderation")

@bot.command(name="rank")
async def rank_cmd(ctx, membre: discord.Member, niveau: int):
    if not await staff_check(ctx, "rank"): return
    if niveau not in ROLE_LEVELS or not ROLE_LEVELS[niveau]:
        return await reply_embed(ctx, "Niveau non configuré", "Configure les IDs dans ROLE_LEVELS.", "error")
    role = ctx.guild.get_role(ROLE_LEVELS[niveau])
    if not role:
        return await reply_embed(ctx, "Rôle introuvable", "Vérifie ROLE_LEVELS.", "error")
    await membre.add_roles(role)
    await reply_embed(ctx, "Niveau attribué", f"{role.mention} ajouté à {membre.mention}.", "success")

@bot.command(name="derank")
async def derank_cmd(ctx, membre: discord.Member, niveau: int):
    if not await staff_check(ctx, "derank"): return
    role_id = ROLE_LEVELS.get(niveau)
    role = ctx.guild.get_role(role_id) if role_id else None
    if not role:
        return await reply_embed(ctx, "Rôle introuvable", "Configure ROLE_LEVELS.", "error")
    await membre.remove_roles(role)
    await reply_embed(ctx, "Niveau retiré", f"{role.mention} retiré à {membre.mention}.", "success")

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
# TICKETS AVEC BOUTONS
# ============================================================

class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Créer un ticket", style=discord.ButtonStyle.primary,
                       custom_id="site42_ticket_create")
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        data = load_data()
        existing = data["tickets"].get(str(interaction.user.id))
        if existing and guild.get_channel(existing):
            return await interaction.response.send_message(
                embed=make_embed("Ticket déjà ouvert", f"Ton ticket : <#{existing}>", "warning"),
                ephemeral=True)
        category = guild.get_channel(TICKET_CATEGORY_ID) if TICKET_CATEGORY_ID else None
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        if TICKET_STAFF_ROLE_ID:
            staff_role = guild.get_role(TICKET_STAFF_ROLE_ID)
            if staff_role:
                overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        channel = await guild.create_text_channel(
            name=f"ticket-{interaction.user.name}".lower().replace(" ", "-")[:90],
            category=category if isinstance(category, discord.CategoryChannel) else None,
            overwrites=overwrites,
            reason=f"Ticket ouvert par {interaction.user}")
        data["tickets"][str(interaction.user.id)] = channel.id
        save_data(data)
        await channel.send(embed=make_embed("Ticket ouvert",
            f"Bonjour {interaction.user.mention}, explique ta demande.\nLe staff peut utiliser les boutons ci-dessous.",
            "ticket"), view=TicketControlView())
        await interaction.response.send_message(
            embed=make_embed("Ticket créé", f"Ton ticket est {channel.mention}.", "success"),
            ephemeral=True)

class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Fermer", style=discord.ButtonStyle.danger,
                       custom_id="site42_ticket_close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not (interaction.user.guild_permissions.manage_channels or
                (TICKET_STAFF_ROLE_ID and any(r.id == TICKET_STAFF_ROLE_ID for r in interaction.user.roles))):
            return await interaction.response.send_message(
                embed=make_embed("Accès refusé", "Seul le staff peut fermer ce ticket.", "error"),
                ephemeral=True)
        data = load_data()
        for owner_id, channel_id in list(data["tickets"].items()):
            if channel_id == interaction.channel.id:
                del data["tickets"][owner_id]
        save_data(data)
        await interaction.response.send_message(embed=make_embed("Ticket fermé", "Ce salon sera supprimé dans quelques secondes.", "ticket"))
        await interaction.channel.delete(reason=f"Ticket fermé par {interaction.user}")

@bot.command(name="ticket")
async def ticket_cmd(ctx):
    await ctx.send(embed=make_embed("Support Site42",
        "Clique sur le bouton ci-dessous pour ouvrir un ticket privé.", "ticket"),
        view=TicketPanelView())

@bot.command(name="add")
async def ticket_add(ctx, membre: discord.Member):
    if not ctx.channel.name.startswith("ticket-"):
        return await reply_embed(ctx, "Commande indisponible", "Utilise cette commande dans un ticket.", "warning")
    await ctx.channel.set_permissions(membre, view_channel=True, send_messages=True, read_message_history=True)
    await reply_embed(ctx, "Membre ajouté", f"{membre.mention} peut maintenant voir ce ticket.", "success")

@bot.command(name="del")
async def ticket_del(ctx, membre: discord.Member):
    if not ctx.channel.name.startswith("ticket-"):
        return await reply_embed(ctx, "Commande indisponible", "Utilise cette commande dans un ticket.", "warning")
    await ctx.channel.set_permissions(membre, overwrite=None)
    await reply_embed(ctx, "Membre retiré", f"{membre.mention} ne voit plus ce ticket.", "success")

@bot.command(name="close")
async def ticket_close_cmd(ctx):
    if not ctx.channel.name.startswith("ticket-"):
        return await reply_embed(ctx, "Commande indisponible", "Utilise cette commande dans un ticket.", "warning")
    await reply_embed(ctx, "Ticket fermé", "Le salon va être supprimé.", "ticket")
    await ctx.channel.delete(reason=f"Ticket fermé par {ctx.author}")

@bot.command(name="rename")
async def ticket_rename(ctx, *, nom: str):
    if not ctx.channel.name.startswith("ticket-"):
        return await reply_embed(ctx, "Commande indisponible", "Utilise cette commande dans un ticket.", "warning")
    await ctx.channel.edit(name=re.sub(r"[^a-z0-9-]", "-", nom.lower())[:90])
    await reply_embed(ctx, "Ticket renommé", f"Nouveau nom : **{nom}**", "success")

@bot.command(name="ticket-stats")
async def ticket_stats(ctx):
    data = load_data()
    await reply_embed(ctx, "Statistiques tickets", f"Tickets actuellement suivis : **{len(data['tickets'])}**", "stats")


# ============================================================
# GIVEAWAYS AVEC BOUTONS
# ============================================================

class GiveawayJoinView(discord.ui.View):
    def __init__(self, message_id: int):
        super().__init__(timeout=None)
        self.message_id = message_id

    @discord.ui.button(label="Participer", style=discord.ButtonStyle.success,
                       custom_id="site42_giveaway_join")
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
    if not await staff_check(ctx, "rank"): return
    seconds = parse_duration(duree)
    if seconds is None or seconds < 10 or gagnants < 1:
        return await reply_embed(ctx, "Paramètres invalides",
                                 "Exemple : `=giveaway 1h 1 Nitro`.", "error")
    ends = time.time() + seconds
    embed = make_embed("Giveaway", f"**Lot :** {lot}\n**Gagnants :** {gagnants}\n"
        f"**Fin :** <t:{int(ends)}:R>\n**Organisé par :** {ctx.author.mention}", "giveaway")
    message = await ctx.send(embed=embed, view=discord.ui.View(timeout=None))
    view = GiveawayJoinView(message.id)
    await message.edit(view=view)
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
    if not await staff_check(ctx, "rank"): return
    data = load_data()
    giveaway = data["giveaways"].get(str(message_id))
    if not giveaway or giveaway.get("ended"):
        return await reply_embed(ctx, "Giveaway introuvable", "ID invalide ou giveaway déjà terminé.", "error")
    giveaway["ended"] = True
    save_data(data)
    await reply_embed(ctx, "Giveaway annulé", f"ID du message : `{message_id}`", "success")

@bot.command(name="gend")
async def giveaway_end(ctx, message_id: int):
    if not await staff_check(ctx, "rank"): return
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
    if not await staff_check(ctx, "rank"): return
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

@bot.command(name="joinmessage")
@commands.has_permissions(administrator=True)
async def joinmessage(ctx, *, message: str):
    data = load_data()
    data["join_message"] = message
    save_data(data)
    await reply_embed(ctx, "Message d'arrivée configuré",
                      "Variables disponibles : `{user}` et `{server}`.", "success")

@bot.command(name="leavemessage")
@commands.has_permissions(administrator=True)
async def leavemessage(ctx, *, message: str):
    data = load_data()
    data["leave_message"] = message
    save_data(data)
    await reply_embed(ctx, "Message de départ configuré",
                      "Variables disponibles : `{user}` et `{server}`.", "success")

@bot.event
async def on_member_join(member):
    data = load_data()
    channel_id = data.get("logs_channel") or LOG_CHANNEL_ID
    channel = member.guild.get_channel(int(channel_id)) if channel_id else None
    if channel:
        text = data["join_message"].format(user=member.mention, server=member.guild.name)
        await channel.send(embed=make_embed("Arrivée d'un membre", text, "user"))

@bot.event
async def on_member_remove(member):
    data = load_data()
    channel_id = data.get("logs_channel") or LOG_CHANNEL_ID
    channel = member.guild.get_channel(int(channel_id)) if channel_id else None
    if channel:
        text = data["leave_message"].format(user=str(member), server=member.guild.name)
        await channel.send(embed=make_embed("Départ d'un membre", text, "user"))

@bot.command(name="say")
@commands.has_permissions(manage_messages=True)
async def say_cmd(ctx, *, message: str):
    await ctx.message.delete()
    await ctx.send(embed=make_embed("Message", message, "info"))

@bot.command(name="mp")
@commands.has_permissions(administrator=True)
async def mp_cmd(ctx, membre: discord.Member, *, message: str):
    await membre.send(embed=make_embed(f"Message de {ctx.guild.name}", message, "info"))
    await reply_embed(ctx, "Message privé envoyé", f"Message envoyé à {membre.mention}.", "success")

@bot.command(name="dmall")
@commands.has_permissions(administrator=True)
async def dmall_cmd(ctx, *, message: str):
    sent = 0
    for member in ctx.guild.members:
        if member.bot:
            continue
        try:
            await member.send(embed=make_embed(f"Message de {ctx.guild.name}", message, "info"))
            sent += 1
        except discord.Forbidden:
            pass
    await reply_embed(ctx, "Envoi terminé", f"Message envoyé à {sent} membre(s).", "success")

@bot.command(name="setname")
@commands.is_owner()
async def setname_cmd(ctx, *, nom: str):
    await bot.user.edit(username=nom[:32])
    await reply_embed(ctx, "Nom du bot modifié", f"Nouveau nom : **{nom[:32]}**", "success")

@bot.command(name="setpic")
@commands.is_owner()
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
@commands.is_owner()
async def setbanner_cmd(ctx):
    await reply_embed(ctx, "Bannière du bot",
                      "Discord ne permet pas de modifier la bannière du bot via l'API discord.py classique.", "warning")

@bot.command(name="setstatus")
@commands.is_owner()
async def setstatus_cmd(ctx, *, texte: str):
    await bot.change_presence(activity=discord.Game(name=texte))
    await reply_embed(ctx, "Statut modifié", texte, "success")

@bot.command(name="online")
@commands.is_owner()
async def online_cmd(ctx):
    await bot.change_presence(status=discord.Status.online)
    await reply_embed(ctx, "Statut en ligne", "Le bot est en ligne.", "success")

@bot.command(name="dnd")
@commands.is_owner()
async def dnd_cmd(ctx):
    await bot.change_presence(status=discord.Status.dnd)
    await reply_embed(ctx, "Statut Ne pas déranger", "Le bot est en mode Ne pas déranger.", "success")

@bot.command(name="owner")
@commands.is_owner()
async def owner_cmd(ctx):
    app_info = await bot.application_info()
    await reply_embed(ctx, "Propriétaire du bot", f"Propriétaire : {app_info.owner.mention if hasattr(app_info.owner, 'mention') else app_info.owner}", "user")


# ============================================================
# COMMANDES UTILES
# ============================================================

@bot.command(name="delperm")
@commands.has_permissions(administrator=True)
async def delperm_cmd(ctx, membre: discord.Member, role: discord.Role):
    await membre.remove_roles(role)
    await reply_embed(ctx, "Permission retirée", f"Rôle {role.mention} retiré à {membre.mention}.", "success")

@bot.command(name="server-invite")
async def server_invite_alias(ctx):
    invite = await ctx.channel.create_invite(max_age=86400, max_uses=0)
    await reply_embed(ctx, "Invitation du serveur", invite.url, "link")

@bot.command(name="online-status")
async def online_status(ctx):
    await reply_embed(ctx, "État du bot", f"Connecté en tant que {bot.user}.", "bot")


# ============================================================
# DÉMARRAGE
# ============================================================

async def restore_persistent_views():
    bot.add_view(TicketPanelView())
    bot.add_view(TicketControlView())

@bot.event
async def setup_hook():
    await restore_persistent_views()

def main():
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN est absent du fichier .env.")
    keep_alive()
    bot.run(TOKEN)

if __name__ == "__main__":
    main()
