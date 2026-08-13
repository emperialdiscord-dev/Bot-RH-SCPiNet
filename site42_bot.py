import discord
from discord import app_commands
from discord.ext import commands, tasks
import os
import re
import json
import time
import datetime
from dotenv import load_dotenv
from keep_alive import keep_alive

# ============================================================
#                      CONFIGURATION
#   Remplace tous les 0 par tes vrais IDs (mode développeur
#   Discord activé > clic droit sur rôle/salon > Copier l'ID)
# ============================================================

# Niveau de permission associé à chaque rôle (1 = le plus bas, 5 = le plus haut)
# Niveau de permission associé à chaque rôle (1 = le plus bas, 5 = le plus haut)
ROLE_LEVELS = {
    1: 1504065271365767282,  # rôle donnant le niveau 1
    2: 1526705153078591628,
    3: 1526705012628258966,
    4: 1468707330085621904,
    5: 1526704780087656640,
}

# Niveau minimum requis pour chaque commande (modifiable directement ici)
COMMAND_LEVELS = {
    "avertir": 2,
    "sanctions": 2,
    "timeout": 2,
    "expulser": 3,
    "bannir-temp": 3,
    "del-san": 3,
    "add-role": 4,
    "del-role": 4,
    "bannir-perm": 5,
    "blacklist": 1,
    "unblacklist": 1,
}

# ID du rôle "Blacklist X" à donner/retirer pour chaque département
DEPARTMENT_ROLES = {
    "Administratif": 1536924662846455899,
    "ASIA": 1536924762352390214,
    "Médical": 1536924806035804310,
    "DSI": 1536924899694608484,
    "DJI": 1536924932208857088,
    "FIM": 1536925062689718323,
    "Scientifique": 1536925021560373329,
    "Logistique": 1536925452113940570,
    "DI&ST": 1536925405112574104,
    "CE": 1536924867629289492,
    "Sécuritaire": 1536924731331313734,
}

# ID du rôle "BLACKLISTS" qui regroupe tout le monde ayant au moins une blacklist.
# Ajouté automatiquement au premier /blacklist, jamais retiré par /unblacklist.
BLACKLIST_GROUP_ROLE_ID = 1536922110612611092

# ID du rôle donné automatiquement quand un membre clique sur "J'accepte le règlement"
RULES_ACCEPT_ROLE_ID = 1537590169752834108

# ID du salon FORUM où seront créés les posts "Rapport de Service de X"
SERVICE_FORUM_CHANNEL_ID = 1537586598051586069

# ID de ton serveur, pour que les commandes slash apparaissent instantanément
# dessus pendant les tests (sinon ça peut prendre jusqu'à 1h en sync globale).
# Laisse à 0 pour une synchronisation globale (tous les serveurs, plus lente à jour).
TEST_GUILD_ID = 1468687370160312474

EMBED_COLOR = discord.Colour(0xFFFFFF)  # blanc

DATA_FILE = "data.json"

# ============================================================
#                     STOCKAGE (JSON)
# ============================================================

def load_data():
    if not os.path.exists(DATA_FILE):
        return {"sanctions": {}, "tempbans": {}, "logs_channel": 0, "services": {"active": {}, "history": {}, "panel": {"channel_id": 0, "message_id": 0}}}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
        data.setdefault("sanctions", {})
        data.setdefault("tempbans", {})
        data.setdefault("logs_channel", 0)
        data.setdefault("services", {"active": {}, "history": {}, "panel": {"channel_id": 0, "message_id": 0}})
        data["services"].setdefault("active", {})
        data["services"].setdefault("history", {})
        data["services"].setdefault("panel", {"channel_id": 0, "message_id": 0})
        return data


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def add_sanction(member_id, sanction_type, reason, moderator_id):
    data = load_data()
    member_id = str(member_id)
    data["sanctions"].setdefault(member_id, [])
    data["sanctions"][member_id].append({
        "type": sanction_type, "reason": reason, "moderator": moderator_id, "timestamp": time.time()
    })
    save_data(data)


def get_sanctions(member_id):
    return load_data()["sanctions"].get(str(member_id), [])


def delete_sanction(member_id, index):
    data = load_data()
    member_id = str(member_id)
    histo = data["sanctions"].get(member_id, [])
    if index < 1 or index > len(histo):
        return None
    removed = histo.pop(index - 1)
    data["sanctions"][member_id] = histo
    save_data(data)
    return removed

# ============================================================
#                      OUTILS
# ============================================================

def parse_duration(duration_str):
    match = re.match(r"^(\d+)([smhjd])$", duration_str.lower())
    if not match:
        return None
    value, unit = match.groups()
    multipliers = {"s": 1, "m": 60, "h": 3600, "j": 86400, "d": 86400}
    return int(value) * multipliers[unit]


def format_duration(seconds):
    seconds = int(seconds)
    jours, reste = divmod(seconds, 86400)
    heures, reste = divmod(reste, 3600)
    minutes, _ = divmod(reste, 60)
    parts = []
    if jours:
        parts.append(f"{jours}j")
    if heures:
        parts.append(f"{heures}h")
    parts.append(f"{minutes}min")
    return " ".join(parts)


def get_total_service_time(member_id, data):
    member_id = str(member_id)
    total = sum(s["duration"] for s in data["services"]["history"].get(member_id, []))
    active = data["services"]["active"].get(member_id)
    if active:
        elapsed = time.time() - active["start"] - active.get("total_pause", 0)
        if active.get("pause_start"):
            elapsed -= (time.time() - active["pause_start"])
        total += max(0, elapsed)
    return total


def find_active_by_channel(data, channel_id):
    for member_id, info in data["services"]["active"].items():
        if info.get("channel_id") == channel_id:
            return member_id, info
    return None, None


def get_level(member: discord.Member):
    ids = [role.id for role in member.roles]
    if member.guild_permissions.administrator:
        return 999
    highest = 0
    for level, role_id in ROLE_LEVELS.items():
        if role_id in ids:
            highest = max(highest, level)
    return highest


def require_level(command_name):
    async def predicate(interaction: discord.Interaction):
        level = get_level(interaction.user)
        required = COMMAND_LEVELS.get(command_name, 1)
        if level < required:
            await interaction.response.send_message(
                f"❌ Il te faut le niveau **{required}** minimum pour utiliser cette commande (tu as le niveau {level}).",
                ephemeral=True,
            )
            return False
        return True
    return app_commands.check(predicate)


async def notify_member(member: discord.Member, sanction_label: str, reason: str, guild_name: str):
    try:
        await member.send(f"Tu as reçu une sanction sur **{guild_name}**.\n**Type :** {sanction_label}\n**Raison :** {reason}")
    except discord.Forbidden:
        pass

# ============================================================
#                    BOT & INTENTS
# ============================================================

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

async def log_command_usage(interaction: discord.Interaction):
    if interaction.guild is None or interaction.command is None:
        return
    data = load_data()
    channel_id = data.get("logs_channel", 0)
    if not channel_id:
        return
    channel = interaction.guild.get_channel(channel_id)
    if not channel:
        return

    try:
        options = vars(interaction.namespace)
    except Exception:
        options = {}
    details = ", ".join(f"**{k}** : {v}" for k, v in options.items()) if options else "Aucun argument"

    embed = discord.Embed(title="📝 Commande slash utilisée", color=EMBED_COLOR)
    embed.add_field(name="Commande", value=f"`/{interaction.command.qualified_name}`", inline=False)
    embed.add_field(name="Arguments", value=details, inline=False)
    embed.add_field(name="Auteur", value=interaction.user.mention)
    embed.add_field(name="Salon", value=interaction.channel.mention if interaction.channel else "N/A")
    embed.timestamp = datetime.datetime.utcnow()
    await channel.send(embed=embed)


class LoggingCommandTree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.type == discord.InteractionType.application_command:
            await log_command_usage(interaction)
        return True


bot = commands.Bot(command_prefix=".", intents=intents, tree_cls=LoggingCommandTree)


@bot.command(name="logs")
@commands.has_permissions(administrator=True)
async def logs_cmd(ctx):
    data = load_data()
    data["logs_channel"] = ctx.channel.id
    save_data(data)
    await ctx.send(f"✅ Ce salon ({ctx.channel.mention}) est maintenant configuré comme salon des logs. Chaque commande `/` y sera enregistrée.")


@bot.event
async def on_ready():
    bot.add_view(RulesAcceptView())
    bot.add_view(ServiceStartView())
    bot.add_view(ServiceReportView())
    if TEST_GUILD_ID:
        guild = discord.Object(id=TEST_GUILD_ID)
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
    else:
        await bot.tree.sync()
    if not check_tempbans.is_running():
        check_tempbans.start()
    print(f"{bot.user} (Site-42) est connecté et prêt !")


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        return  # message déjà envoyé par le predicate
    if not interaction.response.is_done():
        await interaction.response.send_message(f"❌ Une erreur est survenue : `{error}`", ephemeral=True)
    else:
        await interaction.followup.send(f"❌ Une erreur est survenue : `{error}`", ephemeral=True)
    raise error

# ============================================================
#                 COMMANDES SLASH — SANCTIONS
# ============================================================

@bot.tree.command(name="avertir", description="Avertir un membre")
@require_level("avertir")
async def avertir(interaction: discord.Interaction, membre: discord.Member, raison: str):
    add_sanction(membre.id, "Avertissement", raison, interaction.user.id)
    embed = discord.Embed(title="⚠️ Avertissement", color=EMBED_COLOR)
    embed.add_field(name="Membre", value=membre.mention)
    embed.add_field(name="Modérateur", value=interaction.user.mention)
    embed.add_field(name="Raison", value=raison, inline=False)
    await interaction.response.send_message(embed=embed)
    await notify_member(membre, "Avertissement", raison, interaction.guild.name)


@bot.tree.command(name="timeout", description="Exclure temporairement un membre du chat")
@app_commands.describe(temps="Ex : 10m, 2h, 3j")
@require_level("timeout")
async def timeout_cmd(interaction: discord.Interaction, membre: discord.Member, raison: str, temps: str):
    seconds = parse_duration(temps)
    if seconds is None:
        return await interaction.response.send_message("❌ Durée invalide. Utilise `10m`, `2h`, `3j`.", ephemeral=True)
    if seconds > 28 * 86400:
        return await interaction.response.send_message("❌ Discord limite les timeouts à 28 jours maximum.", ephemeral=True)
    until = discord.utils.utcnow() + datetime.timedelta(seconds=seconds)
    await membre.timeout(until, reason=raison)
    add_sanction(membre.id, f"Timeout ({temps})", raison, interaction.user.id)
    embed = discord.Embed(title="🔇 Timeout", color=EMBED_COLOR)
    embed.add_field(name="Membre", value=membre.mention)
    embed.add_field(name="Durée", value=temps)
    embed.add_field(name="Modérateur", value=interaction.user.mention)
    embed.add_field(name="Raison", value=raison, inline=False)
    await interaction.response.send_message(embed=embed)
    await notify_member(membre, f"Timeout ({temps})", raison, interaction.guild.name)


@bot.tree.command(name="expulser", description="Expulser un membre du serveur")
@require_level("expulser")
async def expulser(interaction: discord.Interaction, membre: discord.Member, raison: str):
    add_sanction(membre.id, "Expulsion", raison, interaction.user.id)
    await notify_member(membre, "Expulsion", raison, interaction.guild.name)
    await membre.kick(reason=raison)
    embed = discord.Embed(title="👢 Expulsion", color=EMBED_COLOR)
    embed.add_field(name="Membre", value=str(membre))
    embed.add_field(name="Modérateur", value=interaction.user.mention)
    embed.add_field(name="Raison", value=raison, inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="bannir-temp", description="Bannir un membre temporairement")
@app_commands.describe(temps="Ex : 10m, 2h, 3j")
@require_level("bannir-temp")
async def bannir_temp(interaction: discord.Interaction, membre: discord.Member, raison: str, temps: str):
    seconds = parse_duration(temps)
    if seconds is None:
        return await interaction.response.send_message("❌ Durée invalide. Utilise `10m`, `2h`, `3j`.", ephemeral=True)
    data = load_data()
    data["tempbans"][str(membre.id)] = {"unban_at": time.time() + seconds, "guild_id": interaction.guild.id}
    save_data(data)
    add_sanction(membre.id, f"Ban temporaire ({temps})", raison, interaction.user.id)
    await notify_member(membre, f"Bannissement temporaire ({temps})", raison, interaction.guild.name)
    await membre.ban(reason=raison)
    embed = discord.Embed(title="🔨 Bannissement temporaire", color=EMBED_COLOR)
    embed.add_field(name="Membre", value=str(membre))
    embed.add_field(name="Durée", value=temps)
    embed.add_field(name="Modérateur", value=interaction.user.mention)
    embed.add_field(name="Raison", value=raison, inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="bannir-perm", description="Bannir un membre définitivement")
@require_level("bannir-perm")
async def bannir_perm(interaction: discord.Interaction, membre: discord.Member, raison: str):
    add_sanction(membre.id, "Ban permanent", raison, interaction.user.id)
    await notify_member(membre, "Bannissement permanent", raison, interaction.guild.name)
    await membre.ban(reason=raison)
    embed = discord.Embed(title="🔨 Bannissement permanent", color=EMBED_COLOR)
    embed.add_field(name="Membre", value=str(membre))
    embed.add_field(name="Modérateur", value=interaction.user.mention)
    embed.add_field(name="Raison", value=raison, inline=False)
    await interaction.response.send_message(embed=embed)


@tasks.loop(seconds=60)
async def check_tempbans():
    data = load_data()
    tempbans = data.get("tempbans", {})
    now = time.time()
    to_remove = []
    for user_id, info in tempbans.items():
        if now >= info["unban_at"]:
            guild = bot.get_guild(info["guild_id"])
            if guild:
                try:
                    await guild.unban(discord.Object(id=int(user_id)), reason="Fin du ban temporaire")
                except discord.NotFound:
                    pass
            to_remove.append(user_id)
    for uid in to_remove:
        del tempbans[uid]
    data["tempbans"] = tempbans
    save_data(data)

# ============================================================
#                 COMMANDES SLASH — RÔLES
# ============================================================

@bot.tree.command(name="add-role", description="Ajouter un rôle à un membre")
@require_level("add-role")
async def add_role(interaction: discord.Interaction, membre: discord.Member, role: discord.Role):
    await membre.add_roles(role)
    await interaction.response.send_message(f"✅ Rôle {role.mention} ajouté à {membre.mention}.")


@bot.tree.command(name="del-role", description="Retirer un rôle à un membre")
@require_level("del-role")
async def del_role(interaction: discord.Interaction, membre: discord.Member, role: discord.Role):
    await membre.remove_roles(role)
    await interaction.response.send_message(f"✅ Rôle {role.mention} retiré à {membre.mention}.")


@bot.tree.command(name="blacklist", description="Blacklister un membre d'un département")
@app_commands.choices(departement=[
    app_commands.Choice(name=nom, value=nom) for nom in DEPARTMENT_ROLES
])
@require_level("blacklist")
async def blacklist(interaction: discord.Interaction, membre: discord.Member, departement: app_commands.Choice[str]):
    role = interaction.guild.get_role(DEPARTMENT_ROLES.get(departement.value, 0))
    if role is None:
        return await interaction.response.send_message(
            "❌ Ce rôle de blacklist n'est pas encore configuré, préviens un admin.", ephemeral=True
        )
    if role in membre.roles:
        return await interaction.response.send_message(
            f"❌ {membre.mention} est déjà blacklist **{departement.value}**.", ephemeral=True
        )
    await membre.add_roles(role)

    groupe = interaction.guild.get_role(BLACKLIST_GROUP_ROLE_ID)
    if groupe and groupe not in membre.roles:
        await membre.add_roles(groupe)

    embed = discord.Embed(title="🚫 Blacklist ajoutée", color=EMBED_COLOR)
    embed.add_field(name="Membre", value=membre.mention)
    embed.add_field(name="Département", value=departement.value)
    embed.add_field(name="Par", value=interaction.user.mention)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="unblacklist", description="Retirer un membre de la blacklist d'un département")
@app_commands.choices(departement=[
    app_commands.Choice(name=nom, value=nom) for nom in DEPARTMENT_ROLES
])
@require_level("unblacklist")
async def unblacklist(interaction: discord.Interaction, membre: discord.Member, departement: app_commands.Choice[str]):
    role = interaction.guild.get_role(DEPARTMENT_ROLES.get(departement.value, 0))
    if role is None:
        return await interaction.response.send_message(
            "❌ Ce rôle de blacklist n'est pas encore configuré, préviens un admin.", ephemeral=True
        )
    if role not in membre.roles:
        return await interaction.response.send_message(
            f"❌ {membre.mention} n'est pas blacklist **{departement.value}**.", ephemeral=True
        )
    await membre.remove_roles(role)
    # Le rôle groupe BLACKLISTS n'est jamais retiré ici, même si c'était la dernière blacklist du membre.
    embed = discord.Embed(title="✅ Blacklist retirée", color=EMBED_COLOR)
    embed.add_field(name="Membre", value=membre.mention)
    embed.add_field(name="Département", value=departement.value)
    embed.add_field(name="Par", value=interaction.user.mention)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ============================================================
#              COMMANDES SLASH — PERMISSIONS & CASIER
# ============================================================

@bot.tree.command(name="perms", description="Voir tes permissions et les commandes que tu peux utiliser")
async def perms(interaction: discord.Interaction):
    level = get_level(interaction.user)
    commandes = [name for name, req in COMMAND_LEVELS.items() if level >= req]
    embed = discord.Embed(title=f"🔑 Tes permissions (niveau {level})", color=EMBED_COLOR)
    embed.add_field(
        name="Commandes disponibles",
        value=", ".join(f"`/{c}`" for c in commandes) if commandes else "Aucune",
        inline=False,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="sanctions", description="Voir le casier de sanctions d'un membre")
@require_level("sanctions")
async def sanctions_cmd(interaction: discord.Interaction, membre: discord.Member):
    histo = get_sanctions(membre.id)
    if not histo:
        return await interaction.response.send_message(f"{membre.mention} n'a aucune sanction.", ephemeral=True)
    embed = discord.Embed(title=f"📋 Casier de {membre}", color=EMBED_COLOR)
    debut = max(0, len(histo) - 15)
    for i, s in enumerate(histo[debut:], start=debut + 1):
        mod = interaction.guild.get_member(s["moderator"])
        embed.add_field(
            name=f"#S.{i} — {s['type']}",
            value=f"Raison : {s['reason']}\nPar : {mod.mention if mod else s['moderator']}",
            inline=False,
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="del-san", description="Supprimer une sanction du casier d'un membre")
@app_commands.describe(numero="Ex : S.1 ou 1")
@require_level("del-san")
async def del_san(interaction: discord.Interaction, membre: discord.Member, numero: str):
    numero_clean = numero.upper().replace("#", "").replace("S.", "").strip()
    try:
        index = int(numero_clean)
    except ValueError:
        return await interaction.response.send_message("❌ Format invalide. Utilise par exemple `S.1`.", ephemeral=True)

    removed = delete_sanction(membre.id, index)
    if removed is None:
        return await interaction.response.send_message(
            f"❌ Aucune sanction #S.{index} trouvée pour {membre.mention}.", ephemeral=True
        )

    embed = discord.Embed(title="🗑️ Sanction supprimée", color=EMBED_COLOR)
    embed.add_field(name="Membre", value=membre.mention)
    embed.add_field(name="Sanction retirée", value=f"#S.{index} — {removed['type']} : {removed['reason']}", inline=False)
    embed.add_field(name="Retirée par", value=interaction.user.mention)
    await interaction.response.send_message(embed=embed)

# ============================================================
#              COMMANDES PRÉFIXE "." — RÈGLEMENT
# ============================================================

class RulesAcceptView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="J'accepte le règlement", style=discord.ButtonStyle.success, emoji="✅", custom_id="accept_rules")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        role = interaction.guild.get_role(RULES_ACCEPT_ROLE_ID)
        if role is None:
            return await interaction.response.send_message(
                "❌ Le rôle n'est pas encore configuré, préviens un admin.", ephemeral=True
            )
        if role in interaction.user.roles:
            return await interaction.response.send_message("Tu as déjà accepté le règlement ✅", ephemeral=True)
        await interaction.user.add_roles(role)
        await interaction.response.send_message("✅ Règlement accepté, accès débloqué !", ephemeral=True)


@bot.command(name="règlement", aliases=["reglement"])
async def reglement(ctx):
    embed1 = discord.Embed(color=EMBED_COLOR, description=(
        "⚠️ __**COMPORTEMENT GÉNÉRAL**__\n\n"
        "1️⃣ **RESPECT ABSOLU:**\n"
        "<a:4572bluearrowright:1112740907465326722> Toute forme d'insulte, attaque personnelle, provocation, harcèlement, moquerie ou discrimination est formellement interdite. Les membres doivent se traiter avec **respect et courtoisie**, sans exception.\n\n"
        "2️⃣ **LANGUAGE :**\n"
        "<a:4572bluearrowright:1112740907465326722> Le serveur est **100 % francophone**. Toute communication doit être rédigée en **français correct**, avec des phrases complètes et compréhensibles.\n\n"
        "3️⃣ **RESPECT DES DEFUNTS:**\n"
        "<a:4572bluearrowright:1112740907465326722> Toute remarque irrespectueuse, moquerie ou provocation envers une personne décédée est **strictement prohibée**, sans justification possible.\n\n"
        "4️⃣ **DEBATS POLITIQUES :**\n"
        "<a:4572bluearrowright:1112740907465326722> Les débats sont autorisés **dans la mesure où ils restent constructifs, argumentés et respectueux**. Les attaques personnelles et les comportements agressifs sont interdits.\n\n"
        "5️⃣ **TENSIONS:**\n"
        "<a:4572bluearrowright:1112740907465326722> La politique est un sujet sensible : **gardez votre sang-froid** et évitez toute escalade conflictuelle. Le calme et la maturité sont de rigueur.\n\n"
        "6️⃣ **CONTOURNEMENT DU RÈGLEMENT:**\n"
        "<a:4572bluearrowright:1112740907465326722> Toute tentative de contournement du présent règlement, notamment par la création de salons, de fils de discussion (topics), ou de tout autre moyen visant à ignorer, subvertir ou délibérément enfreindre les règles établies pour le bon fonctionnement du serveur, sera considérée comme une infraction grave et entraînera des sanctions immédiates.\n\n"
        "🗨️ __**CONTENU AUTORISÉ ET INTERDIT**__\n\n"
        "1️⃣ **THEMATIQUE POLITIQUE:**\n"
        "<a:4572bluearrowright:1112740907465326722> Les discussions doivent impérativement **rester centrées sur la politique**. Les hors-sujets prolongés seront modérés.\n\n"
        "2️⃣ **CONTENU OFFENSANT:**\n"
        "<a:4572bluearrowright:1112740907465326722> Tout propos **raciste, sexiste, homophobe, discriminatoire, haineux ou diffamatoire** est strictement interdit.\n\n"
        "3️⃣ **RELIGION:**\n"
        "<a:4572bluearrowright:1112740907465326722> **Les citations religieuses** (Bible, Coran, Tanakh, etc.) sont **interdites**, même dans un but argumentatif.\n\n"
        "4️⃣ **PROPAGANDE, VIOLENCE:**\n"
        "<a:4572bluearrowright:1112740907465326722> **La propagande extrémiste**, l'apologie du terrorisme, l'incitation à la haine ou à la violence **ne seront jamais tolérées**.\n\n"
        "📚 __**PARTAGE D'INFORMATION**__\n\n"
        "1️⃣ **FAKE NEWS & THÉORIES DU COMPLOT:**\n"
        "<a:4572bluearrowright:1112740907465326722> La diffusion de **fausses informations ou de théories complotistes** est strictement interdite.\n\n"
        "2️⃣ **CONTENU ILLÉGAL OU INAPPROPRIÉ:**\n"
        "<a:4572bluearrowright:1112740907465326722> Le partage de contenu pornographique, choquant, violent ou illégal est interdit et pourra entraîner un bannissement immédiat."
    ))

    embed2 = discord.Embed(color=EMBED_COLOR, description=(
        "🚫 __**PUBLICITÉ ET PROMOTION**__\n\n"
        "1️⃣ **AUCUNE PUBLICITÉ SANS AUTORISATION :**\n"
        "<a:4572bluearrowright:1112740907465326722> La promotion de **serveurs, produits, services ou liens affiliés** est interdite sans l'autorisation explicite de l'équipe de modération.\n\n"
        "2️⃣ **PARTAGE DE CONTENU PERSONNEL :**\n"
        "<a:4572bluearrowright:1112740907465326722> Si vous souhaitez partager votre contenu (vidéo, article, etc.), **faites-le uniquement dans les canaux dédiés**, sans spam ni interférer avec les discussions en cours.\n\n"
        "👤 __**IDENTITÉ VISUELLE (PSEUDO & AVATAR)**__\n\n"
        "1️⃣ **CONFORMITÉ OBLIGATOIRE :**\n"
        "<a:4572bluearrowright:1112740907465326722> Tous les pseudos et photos de profil doivent respecter les **Conditions d'utilisation de Discord** et les règles du serveur.\n\n"
        "2️⃣ **PSEUDOS INACCEPTABLES :**\n"
        "<a:4572bluearrowright:1112740907465326722> Interdiction d'utiliser un pseudo contenant :\n"
        "● Des propos offensants, haineux ou discriminatoires.\n"
        "● Du spam, des caractères spéciaux illisibles ou des émojis excessifs.\n"
        "● Des informations personnelles (nom complet, numéro de téléphone, e-mail, etc.).\n\n"
        "3️⃣ **PHOTOS DE PROFIL :**\n"
        "<a:4572bluearrowright:1112740907465326722> Les avatars ne doivent pas :\n"
        "● Contenir de contenu offensant, choquant ou à caractère sexuel.\n"
        "● Représenter des célébrités, personnalités politiques ou logos sans droit.\n"
        "● Induire les autres en erreur sur votre identité.\n\n"
        "4️⃣ **USURPATION & CONFUSION :**\n"
        "<a:4572bluearrowright:1112740907465326722> L'usage de pseudos ou d'avatars similaires à ceux d'autres membres ou personnalités publiques est **strictement interdit**.\n"
        "● Choisir un rôle politique qui ne correspond pas à ses idées pour se faire passer pour quelqu'un d'autre est interdit.\n"
        "Soyez honnêtes avec vous-mêmes et avec les autres.\n\n"
        "5️⃣ **DOUBLES COMPTES :**\n"
        "<a:4572bluearrowright:1112740907465326722> La possession de **plus d'un compte Discord actif sur le serveur est interdite**.\n\n"
        "**L'équipe de modération**\n\n"
        "Les sanctions décidées par la modération ne doivent en aucun cas être contestées sur le Discord.\n"
        "Toute demande de contestation ou explication doit être faite uniquement via le système de ticket dans le canal dédié.\n\n"
        "Contester une sanction à la place de quelqu'un d'autre n'est pas autorisé.\n\n"
        "Il est strictement interdit de contacter la modération en message privé pour discuter d'une sanction ou de toute autre décision.\n\n"
        "Toute discussion publique à ce sujet pourra entraîner une sanction.\n\n"
        "**Ignorer ce règlement ne constitue pas une excuse.\n"
        "En rejoignant ce serveur, vous acceptez l'ensemble de ces règles.**"
    ))

    await ctx.send(embeds=[embed1, embed2], view=RulesAcceptView())

# ============================================================
#                  SYSTÈME DE SERVICE
# ============================================================

async def refresh_service_panel(guild):
    data = load_data()
    panel = data["services"]["panel"]
    if not panel.get("channel_id") or not panel.get("message_id"):
        return
    channel = guild.get_channel(panel["channel_id"])
    if not channel:
        return
    try:
        message = await channel.fetch_message(panel["message_id"])
    except (discord.NotFound, discord.Forbidden):
        return

    actifs = data["services"]["active"]
    embed = discord.Embed(
        title=f"🔎 Utilisateurs en service - ({len(actifs)})",
        color=EMBED_COLOR,
    )
    if not actifs:
        embed.description = "Aucun utilisateur n'est en service... :("
    else:
        lignes = []
        for member_id, info in actifs.items():
            membre = guild.get_member(int(member_id))
            statut = "⏸️ En pause" if info.get("pause_start") else "🟢 En service"
            lignes.append(f"{membre.mention if membre else member_id} — {statut}")
        embed.description = "\n".join(lignes)
    embed.set_footer(text="Si le bot ne répond pas, cela peut signifier qu'il redémarre.")
    await message.edit(embed=embed)


class ServiceStartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Démarrer son service", style=discord.ButtonStyle.success, emoji="📤", custom_id="start_service")
    async def start_service(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = load_data()
        member_id = str(interaction.user.id)
        if member_id in data["services"]["active"]:
            return await interaction.response.send_message("❌ Tu es déjà en service.", ephemeral=True)

        forum = interaction.guild.get_channel(SERVICE_FORUM_CHANNEL_ID)
        if not isinstance(forum, discord.ForumChannel):
            return await interaction.response.send_message(
                "❌ SERVICE_FORUM_CHANNEL_ID ne pointe pas vers un salon Forum valide, préviens un admin.", ephemeral=True
            )

        embed = discord.Embed(
            title=f"Rapports de Service de {interaction.user.display_name}",
            description="Service démarré ! Utilise les boutons ci-dessous pour gérer ta pause ou terminer ton service.",
            color=EMBED_COLOR,
        )
        thread_with_message = await forum.create_thread(
            name=f"Rapport de Service de {interaction.user.display_name}",
            content=interaction.user.mention,
            embed=embed,
            view=ServiceReportView(),
        )
        salon = thread_with_message.thread

        data["services"]["active"][member_id] = {
            "start": time.time(),
            "pause_start": None,
            "total_pause": 0,
            "channel_id": salon.id,
        }
        save_data(data)

        await interaction.response.send_message(f"✅ Ton service a démarré : {salon.mention}", ephemeral=True)
        await refresh_service_panel(interaction.guild)


class ServiceReportView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Prendre / Terminer sa pause", style=discord.ButtonStyle.primary, emoji="⏸️", custom_id="pause_service")
    async def pause_service(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = load_data()
        member_id, info = find_active_by_channel(data, interaction.channel.id)
        if member_id is None:
            return await interaction.response.send_message("❌ Aucun service actif trouvé pour ce salon.", ephemeral=True)
        if interaction.user.id != int(member_id):
            return await interaction.response.send_message("❌ Seul le titulaire de ce service peut faire ça.", ephemeral=True)

        if info.get("pause_start"):
            pause_duree = time.time() - info["pause_start"]
            info["total_pause"] = info.get("total_pause", 0) + pause_duree
            info["pause_start"] = None
            save_data(data)
            await interaction.response.send_message(f"▶️ Pause terminée ({format_duration(pause_duree)}). Bon retour !")
        else:
            info["pause_start"] = time.time()
            save_data(data)
            await interaction.response.send_message("⏸️ Pause commencée. Prends ton temps !")
        await refresh_service_panel(interaction.guild)

    @discord.ui.button(label="Terminer son service", style=discord.ButtonStyle.danger, emoji="📥", custom_id="end_service")
    async def end_service(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = load_data()
        member_id, info = find_active_by_channel(data, interaction.channel.id)
        if member_id is None:
            return await interaction.response.send_message("❌ Aucun service actif trouvé pour ce salon.", ephemeral=True)
        if interaction.user.id != int(member_id):
            return await interaction.response.send_message("❌ Seul le titulaire de ce service peut faire ça.", ephemeral=True)

        total_pause = info.get("total_pause", 0)
        if info.get("pause_start"):
            total_pause += time.time() - info["pause_start"]

        duree = time.time() - info["start"] - total_pause
        data["services"]["history"].setdefault(member_id, [])
        data["services"]["history"][member_id].append({
            "start": info["start"], "end": time.time(), "duration": duree
        })
        del data["services"]["active"][member_id]
        save_data(data)

        embed = discord.Embed(title="🌙 Service terminé", color=EMBED_COLOR)
        embed.add_field(name="Durée totale", value=format_duration(duree))
        embed.add_field(name="Temps de pause", value=format_duration(total_pause))
        await interaction.response.send_message(embed=embed)

        await interaction.channel.edit(name=f"Terminé — Rapport de {interaction.user.display_name}", locked=True, archived=True)
        await refresh_service_panel(interaction.guild)


@bot.command(name="servicepanel")
@commands.has_permissions(administrator=True)
async def servicepanel(ctx):
    data = load_data()
    embed = discord.Embed(title="🔎 Utilisateurs en service - (0)", description="Aucun utilisateur n'est en service... :(", color=EMBED_COLOR)
    embed.set_footer(text="Si le bot ne répond pas, cela peut signifier qu'il redémarre.")
    message = await ctx.send(embed=embed, view=ServiceStartView())
    data["services"]["panel"] = {"channel_id": ctx.channel.id, "message_id": message.id}
    save_data(data)


def build_classement(data):
    membres_ids = set(data["services"]["history"].keys()) | set(data["services"]["active"].keys())
    return sorted(
        ((mid, get_total_service_time(mid, data)) for mid in membres_ids),
        key=lambda x: x[1], reverse=True
    )


@bot.tree.command(name="topservice", description="Voir le classement du temps de service")
async def topservice(interaction: discord.Interaction):
    data = load_data()
    classement = build_classement(data)
    if not classement:
        return await interaction.response.send_message("Personne n'a encore effectué de service.", ephemeral=True)
    embed = discord.Embed(title="🏆 Classement du temps de service", color=EMBED_COLOR)
    for i, (member_id, total) in enumerate(classement[:15], start=1):
        membre = interaction.guild.get_member(int(member_id))
        embed.add_field(name=f"#{i} — {membre.display_name if membre else member_id}", value=format_duration(total), inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="monservice", description="Voir ton temps de service total et ta position au classement")
async def monservice(interaction: discord.Interaction):
    data = load_data()
    classement = build_classement(data)
    member_id = str(interaction.user.id)
    total = get_total_service_time(member_id, data)

    if total == 0:
        return await interaction.response.send_message("Tu n'as encore jamais effectué de service.", ephemeral=True)

    rang = next((i for i, (mid, _) in enumerate(classement, start=1) if mid == member_id), None)
    en_service = member_id in data["services"]["active"]

    embed = discord.Embed(title=f"🕒 Ton service — {interaction.user.display_name}", color=EMBED_COLOR)
    embed.add_field(name="Temps total", value=format_duration(total))
    embed.add_field(name="Classement", value=f"#{rang} / {len(classement)}")
    embed.add_field(name="Statut actuel", value="🟢 En service" if en_service else "⚪ Hors service", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


keep_alive()
bot.run(TOKEN)
