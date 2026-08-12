import discord
from discord import app_commands
from discord.ext import commands, tasks
import os
import re
import json
import time
import datetime
from dotenv import load_dotenv

# ============================================================
#                      CONFIGURATION
#   Remplace tous les 0 par tes vrais IDs (mode développeur
#   Discord activé > clic droit sur rôle/salon > Copier l'ID)
# ============================================================

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
    "avertir": 1,
    "sanctions": 1,
    "timeout": 2,
    "expulser": 3,
    "bannir-temp": 3,
    "del-san": 3,
    "add-role": 4,
    "del-role": 4,
    "bannir-perm": 5,
}

# ID de ton serveur, pour que les commandes slash apparaissent instantanément
# dessus pendant les tests (sinon ça peut prendre jusqu'à 1h en sync globale).
# Laisse à 0 pour une synchronisation globale (tous les serveurs, plus lente à jour).
TEST_GUILD_ID = 0

EMBED_COLOR = discord.Colour(0xFFFFFF)  # blanc

DATA_FILE = "data.json"

# ============================================================
#                     STOCKAGE (JSON)
# ============================================================

def load_data():
    if not os.path.exists(DATA_FILE):
        return {"sanctions": {}, "tempbans": {}}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
        data.setdefault("sanctions", {})
        data.setdefault("tempbans", {})
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

bot = commands.Bot(command_prefix=".", intents=intents)


@bot.event
async def on_ready():
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
    await interaction.response.send_message(embed=embed)


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

@bot.command(name="règlement", aliases=["reglement"])
async def reglement(ctx):
    embed = discord.Embed(
        title="📜 Règlement — Fondation SCP, Site-42",
        description="Merci de lire attentivement les règles ci-dessous avant de participer aux activités RH.",
        color=EMBED_COLOR,
    )
    embed.add_field(
        name="1️⃣ Respect",
        value="Aucune insulte, discrimination ou harcèlement envers un autre membre du personnel.",
        inline=False,
    )
    embed.add_field(
        name="2️⃣ Hiérarchie",
        value="Les décisions des Ressources Humaines sont à respecter. Tout désaccord se règle en message privé avec un responsable, jamais publiquement.",
        inline=False,
    )
    embed.add_field(
        name="3️⃣ Sanctions",
        value="Toute sanction (avertissement, timeout, expulsion, bannissement) est justifiée et consignée dans le casier du membre concerné.",
        inline=False,
    )
    embed.add_field(
        name="4️⃣ Confidentialité",
        value="Les informations RH échangées ici ne doivent pas être partagées en dehors du service.",
        inline=False,
    )
    embed.set_footer(text="En restant sur ce serveur, tu acceptes ce règlement.")
    await ctx.send(embed=embed)


bot.run(TOKEN)
