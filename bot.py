import discord
from discord.ext import commands, tasks
from discord.ui import View, Button, Select, Modal, TextInput
import json 
import asyncio
import re
import aiosqlite
import datetime
from discord import app_commands
from collections import defaultdict, deque
from datetime import datetime, timezone
from presence import PresenceManager

# Intents nécessaires
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True
intents.messages = True
intents.reactions = True
intents.voice_states = True
intents.presences = True
intents.guild_messages = True
intents.guild_reactions = True
intents.bans = True

# --- Gestion dynamique du préfixe par serveur ---

def get_prefix(bot, message):
    try:
        with open("prefixes.json", "r") as f:
            prefixes = json.load(f)
    except FileNotFoundError:
        prefixes = {}

    return prefixes.get(str(message.guild.id), "+")  # "+" par défaut

bot = commands.Bot(command_prefix=get_prefix, intents=intents, help_command=None)

# --- Check admin simple ---

def is_admin():
    async def predicate(ctx):
        return ctx.author.guild_permissions.administrator
    return commands.check(predicate)

# --- Variables globales ---

LOG_CHANNEL_NAME = "logs-bot"
SERVER_LOG_CHANNEL_NAME = "server-log"

# --- Stockage settings join (simplifié, en mémoire) ---

security_settings = {}

def save_config():
    # Tu peux étendre ici pour sauvegarder security_settings sur disque si besoin
    pass

def get_button_style(color_name):
    return {
        "bleu": discord.ButtonStyle.blurple,
        "gris": discord.ButtonStyle.secondary,
        "rouge": discord.ButtonStyle.danger,
        "vert": discord.ButtonStyle.success,
    }.get(color_name.lower(), discord.ButtonStyle.secondary)


# --- Events ---

presence_manager = PresenceManager(bot)

@bot.event
async def on_ready():
    print(f"Connecté en tant que {bot.user}")

    # Statut fixe en streaming
    await bot.change_presence(activity=discord.Streaming(name="QUATRO PROTECT", url="https://twitch.tv/quatro_protect"))

# --- Commandes préfixe ---

@bot.command()
@is_admin()
async def setprefix(ctx, new_prefix):
    try:
        with open("prefixes.json", "r") as f:
            prefixes = json.load(f)
    except FileNotFoundError:
        prefixes = {}

    prefixes[str(ctx.guild.id)] = new_prefix

    with open("prefixes.json", "w") as f:
        json.dump(prefixes, f, indent=4)

    await ctx.send(f"✅ Préfixe mis à jour pour ce serveur : `{new_prefix}`")

@bot.command()
async def prefix(ctx):
    await ctx.send(f"Le préfixe actuel est `{ctx.prefix}`")

# --- Commande setupserverlog ---

@bot.command(name="setupserverlog")
@is_admin()
async def setup_server_log(ctx):
    guild = ctx.guild
    log_channel_name = SERVER_LOG_CHANNEL_NAME

    existing_channel = discord.utils.get(guild.text_channels, name=log_channel_name)
    if existing_channel:
        await ctx.send("🔍 Le salon `server-log` existe déjà.")
        return

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
    }

    for role in guild.roles:
        if role.permissions.administrator:
            overwrites[role] = discord.PermissionOverwrite(read_messages=True)

    log_channel = await guild.create_text_channel(log_channel_name, overwrites=overwrites)
    await ctx.send(f"✅ Salon `#{log_channel_name}` créé et réservé aux admins.")

# --- Fonction utilitaire pour récupérer salon server-log ---

async def get_server_log_channel(guild):
    return discord.utils.get(guild.text_channels, name=SERVER_LOG_CHANNEL_NAME)

# --- Commandes join (configuration sécurité) ---

@bot.group(name="join", invoke_without_command=True)
async def join(ctx):
    await ctx.send(f"Utilisez {ctx.prefix}join settings pour commencer la configuration.")

@join.command(name="settings")
async def join_settings(ctx):
    view = View()

    btn_captcha = Button(label="Sécurité Captcha", style=discord.ButtonStyle.primary)
    btn_button = Button(label="Vérification par Bouton", style=discord.ButtonStyle.success)

    async def captcha_callback(interaction):
        guild_id = str(ctx.guild.id)
        security_settings[guild_id] = {
            "type": "captcha"
        }
        save_config()
        await interaction.response.edit_message(content="Méthode Sécurité Captcha sélectionnée.", view=None)

    async def button_callback(interaction):
        guild_id = str(ctx.guild.id)
        security_settings[guild_id] = {
            "type": "button",
            "button_text": "Valider",
            "button_emoji": None,
            "button_color": "gris"
        }
        save_config()
        await interaction.response.edit_message(content="Méthode Vérification par Bouton sélectionnée.", view=None)

    btn_captcha.callback = captcha_callback
    btn_button.callback = button_callback

    view.add_item(btn_captcha)
    view.add_item(btn_button)

    await ctx.send("Choisissez le type de sécurité à activer :", view=view)

@join.command(name="setchannel")
async def join_setchannel(ctx, channel: discord.TextChannel):
    guild_id = str(ctx.guild.id)
    if guild_id not in security_settings:
        return await ctx.send(f"Configurez d'abord la méthode avec {ctx.prefix}join settings.")

    security_settings[guild_id]["channel_id"] = channel.id

    method = security_settings[guild_id].get("type")
    if not method:
        return await ctx.send(f"Configurez d'abord la méthode avec {ctx.prefix}join settings.")

    old_msg_id = security_settings[guild_id].get("message_id")
    if old_msg_id:
        try:
            old_msg = await channel.fetch_message(old_msg_id)
            await old_msg.delete()
        except:
            pass

    if method == "button":
        text = security_settings[guild_id].get("button_text", "Valider")
        emoji = security_settings[guild_id].get("button_emoji")
        color = security_settings[guild_id].get("button_color", "gris")
        style = get_button_style(color)
        view = View()
        btn = Button(label=text, emoji=emoji if emoji else None, style=style)

        async def dummy_callback(interaction):
            await interaction.response.send_message("Message de vérification, cliquez quand un membre rejoint.", ephemeral=True)
        btn.callback = dummy_callback

        view.add_item(btn)

        msg = await channel.send("Message de vérification : lorsqu'un membre rejoint, un message personnalisé avec bouton lui sera envoyé en DM.", view=view)
        security_settings[guild_id]["message_id"] = msg.id
        save_config()
        await ctx.send(f"Salon de vérification défini sur {channel.mention} et message créé automatiquement.")

    elif method == "captcha":
        msg = await channel.send("Message de vérification : lorsqu'un membre rejoint, un captcha lui sera envoyé en DM.")
        security_settings[guild_id]["message_id"] = msg.id
        save_config()
        await ctx.send(f"Salon de vérification défini sur {channel.mention} et message créé automatiquement.")

    else:
        await ctx.send("Méthode inconnue, impossible de créer le message.")

@join.command(name="setmessage")
async def join_setmessage(ctx, message_id: int):
    guild_id = str(ctx.guild.id)
    if guild_id not in security_settings:
        return await ctx.send(f"Configurez d'abord la méthode avec {ctx.prefix}join settings.")

    security_settings[guild_id]["message_id"] = message_id
    save_config()
    await ctx.send(f"Message de vérification défini sur ID {message_id}.")

@join.command(name="setbutton")
async def join_setbutton(ctx, text: str, emoji: str = None, color: str = "gris"):
    guild_id = str(ctx.guild.id)
    if guild_id not in security_settings or security_settings[guild_id].get("type") != "button":
        return await ctx.send("La méthode Vérification par Bouton n'est pas activée.")

    security_settings[guild_id]["button_text"] = text
    security_settings[guild_id]["button_emoji"] = emoji
    security_settings[guild_id]["button_color"] = color
    save_config()
    await ctx.send("Paramètres du bouton modifiés.")

# Config auto-moderation par guild_id
automod_config = {}

def get_automod_config(guild_id):
    if guild_id not in automod_config:
        automod_config[guild_id] = {
            "antispam": False,
            "antispam_limit": (4, 5),  # messages, secondes
            "antilink": False,
            "antilink_type": "all",  # "invite" ou "all"
            "antibadword": False,
            "badwords": set(),
            "antimassmention": False,
            "mass_mention_limit": 5,
            "punishments": {},  # id : {strikes, duration, sanction, extra_duration}
            "strikes": defaultdict(int),  # user_id : nb_strikes
            "strike_duration": {},  # user_id : datetime expiration strike
        }
    return automod_config[guild_id]

# --- COMMANDES ---

@bot.command()
@commands.has_permissions(administrator=True)
async def antispam(ctx, option=None):
    config = get_automod_config(ctx.guild.id)
    if option is None:
        config["antispam"] = not config["antispam"]
        await ctx.send(f"AntiSpam {'activé' if config['antispam'] else 'désactivé'}.")
    else:
        # config format: messages/seconde (ex: 4/5)
        match = re.match(r"(\d+)\/(\d+)", option)
        if match:
            messages, secondes = int(match[1]), int(match[2])
            config["antispam_limit"] = (messages, secondes)
            config["antispam"] = True
            await ctx.send(f"AntiSpam configuré : {messages} messages en {secondes} secondes.")
        else:
            await ctx.send("Usage: !antispam <messages>/<secondes> (ex: 4/5)")

@bot.command()
@commands.has_permissions(administrator=True)
async def antilink(ctx, option=None):
    config = get_automod_config(ctx.guild.id)
    if option is None:
        config["antilink"] = not config["antilink"]
        await ctx.send(f"AntiLink {'activé' if config['antilink'] else 'désactivé'}.")
    elif option.lower() in ("invite", "all"):
        config["antilink"] = True
        config["antilink_type"] = option.lower()
        await ctx.send(f"AntiLink activé pour le type : {option.lower()}.")
    else:
        await ctx.send("Usage: !antilink invite|all")

@bot.group()
@commands.has_permissions(administrator=True)
async def badword(ctx):
    config = get_automod_config(ctx.guild.id)
    if ctx.invoked_subcommand is None:
        await ctx.send("Usage : !badword add <mot> / del <mot> / list")

@badword.command(name="add")
async def badword_add(ctx, *, word):
    config = get_automod_config(ctx.guild.id)
    config["badwords"].add(word.lower())
    await ctx.send(f"Mot interdit ajouté : `{word}`")

@badword.command(name="del")
async def badword_del(ctx, *, word):
    config = get_automod_config(ctx.guild.id)
    if word.lower() in config["badwords"]:
        config["badwords"].remove(word.lower())
        await ctx.send(f"Mot interdit supprimé : `{word}`")
    else:
        await ctx.send(f"Mot `{word}` non trouvé.")

@badword.command(name="list")
async def badword_list(ctx):
    config = get_automod_config(ctx.guild.id)
    if not config["badwords"]:
        await ctx.send("Aucun mot interdit configuré.")
    else:
        await ctx.send("Mots interdits : " + ", ".join(f"`{w}`" for w in config["badwords"]))

@bot.command()
@commands.has_permissions(administrator=True)
async def antimassmention(ctx, option=None):
    config = get_automod_config(ctx.guild.id)
    if option is None:
        config["antimassmention"] = not config["antimassmention"]
        await ctx.send(f"AntiMassMention {'activé' if config['antimassmention'] else 'désactivé'}.")
    else:
        try:
            limit = int(option)
            config["antimassmention"] = True
            config["mass_mention_limit"] = limit
            await ctx.send(f"AntiMassMention activé avec une limite de {limit} mentions.")
        except:
            await ctx.send("Usage : !antimassmention <nombre>")

# --- Système simple de strikes & punishments ---

@bot.group()
@commands.has_permissions(administrator=True)
async def punish(ctx):
    config = get_automod_config(ctx.guild.id)
    if ctx.invoked_subcommand is None:
        if not config["punishments"]:
            await ctx.send("Aucune sanction configurée.")
        else:
            msg = "Sanctions configurées:\n"
            for id_, p in config["punishments"].items():
                msg += f"ID {id_} : {p['strikes']} strikes => {p['sanction']} durant {p['duration']} secondes\n"
            await ctx.send(msg)

@punish.command(name="add")
async def punish_add(ctx, strikes: int, duration: int, sanction: str, extra_duration: int = 0):
    config = get_automod_config(ctx.guild.id)
    new_id = max(config["punishments"].keys(), default=0) + 1
    config["punishments"][new_id] = {
        "strikes": strikes,
        "duration": duration,
        "sanction": sanction,
        "extra_duration": extra_duration,
    }
    await ctx.send(f"Sanction ajoutée (ID {new_id}): {strikes} strikes => {sanction} pendant {duration}s")

@punish.command(name="del")
async def punish_del(ctx, id_: int):
    config = get_automod_config(ctx.guild.id)
    if id_ in config["punishments"]:
        del config["punishments"][id_]
        await ctx.send(f"Sanction ID {id_} supprimée.")
    else:
        await ctx.send(f"Sanction ID {id_} non trouvée.")

# --- Gestion anti-spam (exemple simple) ---

user_message_times = defaultdict(lambda: deque())

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return await bot.process_commands(message)

    config = get_automod_config(message.guild.id)

    # AntiSpam
    if config["antispam"]:
        limit_messages, limit_seconds = config["antispam_limit"]
        times = user_message_times[(message.guild.id, message.author.id)]
        now = datetime.datetime.utcnow()
        times.append(now)

        # Retirer timestamps vieux
        while times and (now - times[0]).total_seconds() > limit_seconds:
            times.popleft()

        if len(times) > limit_messages:
            # Appliquer sanction ici (kick, mute, strike, etc.)
            await message.channel.send(f"{message.author.mention}, stop le spam !")
            # Exemple: supprimer le message
            try:
                await message.delete()
            except:
                pass
            # Ajouter strike ici (à compléter selon ta logique)
    
    # AntiLink
    if config["antilink"]:
        content = message.content.lower()
        if config["antilink_type"] == "invite":
            if "discord.gg/" in content or "discord.com/invite" in content:
                await message.delete()
                await message.channel.send(f"{message.author.mention}, les liens d'invitation sont interdits.")
        elif config["antilink_type"] == "all":
            # supprimer tous les liens basiques (http/https)
            if re.search(r"https?://", content):
                await message.delete()
                await message.channel.send(f"{message.author.mention}, les liens sont interdits.")

    # AntiBadWord
    if config["antibadword"]:
        if any(badword in message.content.lower() for badword in config["badwords"]):
            await message.delete()
            await message.channel.send(f"{message.author.mention}, mot interdit détecté.")

    # AntiMassMention
    if config["antimassmention"]:
        if len(message.mentions) > config["mass_mention_limit"]:
            await message.delete()
            await message.channel.send(f"{message.author.mention}, trop de mentions dans ce message.")

    await bot.process_commands(message)

    # Stockage config anti-raid par serveur
anti_raid_configs = {}

def get_anti_raid_config(guild_id):
    if guild_id not in anti_raid_configs:
        anti_raid_configs[guild_id] = {
            "antiban": False,
            "antibot": False,
            "antichannel": False,
            "antideco": False,
            "antieveryone": False,
            "antirole": False,
            "antitoken": False,
            "antiunban": False,
            "antiupdate": False,
            "antiwebhook": False,
            "blacklistrank": set(),
            "creationlimit_days": 0,
        }
    return anti_raid_configs[guild_id]

# Commande générique d’activation/désactivation
@bot.command()
@commands.has_permissions(administrator=True)
async def antiban(ctx, option: str):
    config = get_anti_raid_config(ctx.guild.id)
    if option.lower() in ("enable", "on"):
        config["antiban"] = True
        await ctx.send("🛡️ AntiBan activé.")
    elif option.lower() in ("disable", "off"):
        config["antiban"] = False
        await ctx.send("🛡️ AntiBan désactivé.")
    else:
        await ctx.send("Usage: !antiban enable|disable")

@bot.command()
@commands.has_permissions(administrator=True)
async def antibot(ctx, option: str):
    config = get_anti_raid_config(ctx.guild.id)
    if option.lower() in ("enable", "on"):
        config["antibot"] = True
        await ctx.send("🛡️ AntiBot activé.")
    elif option.lower() in ("disable", "off"):
        config["antibot"] = False
        await ctx.send("🛡️ AntiBot désactivé.")
    else:
        await ctx.send("Usage: !antibot enable|disable")

@bot.command()
@commands.has_permissions(administrator=True)
async def antichannel(ctx, option: str):
    config = get_anti_raid_config(ctx.guild.id)
    if option.lower() in ("enable", "on"):
        config["antichannel"] = True
        await ctx.send("🛡️ AntiChannel activé.")
    elif option.lower() in ("disable", "off"):
        config["antichannel"] = False
        await ctx.send("🛡️ AntiChannel désactivé.")
    else:
        await ctx.send("Usage: !antichannel enable|disable")

@bot.command()
@commands.has_permissions(administrator=True)
async def antideco(ctx, option: str):
    config = get_anti_raid_config(ctx.guild.id)
    if option.lower() in ("enable", "on"):
        config["antideco"] = True
        await ctx.send("🛡️ AntiDéco activé.")
    elif option.lower() in ("disable", "off"):
        config["antideco"] = False
        await ctx.send("🛡️ AntiDéco désactivé.")
    else:
        await ctx.send("Usage: !antideco enable|disable")

@bot.command()
@commands.has_permissions(administrator=True)
async def antieveryone(ctx, option: str):
    config = get_anti_raid_config(ctx.guild.id)
    if option.lower() in ("enable", "on"):
        config["antieveryone"] = True
        await ctx.send("🛡️ AntiEveryone activé.")
    elif option.lower() in ("disable", "off"):
        config["antieveryone"] = False
        await ctx.send("🛡️ AntiEveryone désactivé.")
    else:
        await ctx.send("Usage: !antieveryone enable|disable")

@bot.command()
@commands.has_permissions(administrator=True)
async def antirole(ctx, option: str):
    config = get_anti_raid_config(ctx.guild.id)
    if option.lower() in ("enable", "on"):
        config["antirole"] = True
        await ctx.send("🛡️ AntiRole activé.")
    elif option.lower() in ("disable", "off"):
        config["antirole"] = False
        await ctx.send("🛡️ AntiRole désactivé.")
    else:
        await ctx.send("Usage: !antirole enable|disable")

@bot.command()
@commands.has_permissions(administrator=True)
async def antitoken(ctx, option: str):
    config = get_anti_raid_config(ctx.guild.id)
    if option.lower() in ("enable", "on"):
        config["antitoken"] = True
        await ctx.send("🛡️ AntiToken activé.")
    elif option.lower() in ("disable", "off"):
        config["antitoken"] = False
        await ctx.send("🛡️ AntiToken désactivé.")
    else:
        await ctx.send("Usage: !antitoken enable|disable")

@bot.command()
@commands.has_permissions(administrator=True)
async def antiunban(ctx, option: str):
    config = get_anti_raid_config(ctx.guild.id)
    if option.lower() in ("enable", "on"):
        config["antiunban"] = True
        await ctx.send("🛡️ AntiUnban activé.")
    elif option.lower() in ("disable", "off"):
        config["antiunban"] = False
        await ctx.send("🛡️ AntiUnban désactivé.")
    else:
        await ctx.send("Usage: !antiunban enable|disable")

@bot.command()
@commands.has_permissions(administrator=True)
async def antiupdate(ctx, option: str):
    config = get_anti_raid_config(ctx.guild.id)
    if option.lower() in ("enable", "on"):
        config["antiupdate"] = True
        await ctx.send("🛡️ AntiUpdate activé.")
    elif option.lower() in ("disable", "off"):
        config["antiupdate"] = False
        await ctx.send("🛡️ AntiUpdate désactivé.")
    else:
        await ctx.send("Usage: !antiupdate enable|disable")

@bot.command()
@commands.has_permissions(administrator=True)
async def antiwebhook(ctx, option: str):
    config = get_anti_raid_config(ctx.guild.id)
    if option.lower() in ("enable", "on"):
        config["antiwebhook"] = True
        await ctx.send("🛡️ AntiWebhook activé.")
    elif option.lower() in ("disable", "off"):
        config["antiwebhook"] = False
        await ctx.send("🛡️ AntiWebhook désactivé.")
    else:
        await ctx.send("Usage: !antiwebhook enable|disable")

# Blacklist Rank : add/remove @membre
@bot.group()
@commands.has_permissions(administrator=True)
async def blacklistrank(ctx):
    if ctx.invoked_subcommand is None:
        await ctx.send("Usage: !blacklistrank add|remove @membre")

@blacklistrank.command(name="add")
async def blacklistrank_add(ctx, member: discord.Member):
    config = get_anti_raid_config(ctx.guild.id)
    config["blacklistrank"].add(member.id)
    await ctx.send(f"✅ {member.mention} ajouté à la blacklist de rangs.")

@blacklistrank.command(name="remove")
async def blacklistrank_remove(ctx, member: discord.Member):
    config = get_anti_raid_config(ctx.guild.id)
    if member.id in config["blacklistrank"]:
        config["blacklistrank"].remove(member.id)
        await ctx.send(f"✅ {member.mention} retiré de la blacklist de rangs.")
    else:
        await ctx.send(f"{member.mention} n'est pas dans la blacklist.")

@bot.command()
@commands.has_permissions(administrator=True)
async def creationlimit(ctx, action: str, jours: int = None):
    config = get_anti_raid_config(ctx.guild.id)
    if action.lower() == "set":
        if jours is None or jours < 0:
            return await ctx.send("Usage: !creationlimit set <nombre_de_jours>")
        config["creationlimit_days"] = jours
        await ctx.send(f"Limite d'âge des comptes fixée à {jours} jours.")
    else:
        await ctx.send("Usage: !creationlimit set <nombre_de_jours>")

# Exemple simple de gestion : bloquer l’ajout de bots si antibot activé
@bot.event
async def on_member_join(member):
    config = get_anti_raid_config(member.guild.id)
    if config["antibot"] and member.bot:
        try:
            await member.kick(reason="AntiBot activé")
            chan = member.guild.system_channel
            if chan:
                await chan.send(f"🤖 Bot {member.name} expulsé automatiquement (AntiBot).")
        except Exception as e:
            print(f"Erreur antibot kick: {e}")

# --- PROTECTIONS PANEL ---

automod_config = {}
anti_raid_configs = {}
user_message_times = defaultdict(lambda: deque())

def get_automod_config(guild_id):
    if guild_id not in automod_config:
        automod_config[guild_id] = {
            "antispam": False,
            "antispam_limit": (4, 5),
            "antilink": False,
            "antilink_type": "all",
            "antibadword": False,
            "badwords": set(),
            "antimassmention": False,
            "mass_mention_limit": 5,
        }
    return automod_config[guild_id]

def get_anti_raid_config(guild_id):
    if guild_id not in anti_raid_configs:
        anti_raid_configs[guild_id] = {
            "antiban": False,
            "antibot": False,
            "antichannel": False,
            "antideco": False,
            "antieveryone": False,
            "antirole": False,
            "antitoken": False,
            "antiunban": False,
            "antiupdate": False,
            "antiwebhook": False,
        }
    return anti_raid_configs[guild_id]

class ProtectionView(View):
    def __init__(self, guild_id):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.refresh_buttons()

    def refresh_buttons(self):
        self.clear_items()
        config = {**get_automod_config(self.guild_id), **get_anti_raid_config(self.guild_id)}
        for key, value in config.items():
            if isinstance(value, bool):
                self.add_item(ToggleButton(label=key, enabled=value, guild_id=self.guild_id))

class ToggleButton(Button):
    def __init__(self, label, enabled, guild_id):
        style = discord.ButtonStyle.success if enabled else discord.ButtonStyle.danger
        super().__init__(label=label, style=style)
        self.enabled = enabled
        self.setting = label
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        if self.setting in get_automod_config(self.guild_id):
            config = get_automod_config(self.guild_id)
        else:
            config = get_anti_raid_config(self.guild_id)

        config[self.setting] = not config[self.setting]
        status = "✅ Activé" if config[self.setting] else "❌ Désactivé"

        embed = generate_protection_embed(self.guild_id)
        view = ProtectionView(self.guild_id)

        await interaction.response.edit_message(embed=embed, view=view)

def generate_protection_embed(guild_id):
    automod = get_automod_config(guild_id)
    antiraid = get_anti_raid_config(guild_id)

    desc = ""
    for k, v in automod.items():
        if isinstance(v, bool):
            desc += f"🔹 `{k}` : {'✅' if v else '❌'}\n"
    for k, v in antiraid.items():
        if isinstance(v, bool):
            desc += f"🛡️ `{k}` : {'✅' if v else '❌'}\n"

    return discord.Embed(title="Configuration AutoMod & Anti-Raid", description=desc, color=0x2b2d31)

@bot.command()
@commands.has_permissions(administrator=True)
async def protections(ctx):
    embed = generate_protection_embed(ctx.guild.id)
    view = ProtectionView(ctx.guild.id)
    await ctx.send(embed=embed, view=view)

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return await bot.process_commands(message)

    config = get_automod_config(message.guild.id)
    now = datetime.datetime.utcnow()

    # AntiSpam
    if config["antispam"]:
        msgs, secs = config["antispam_limit"]
        times = user_message_times[(message.guild.id, message.author.id)]
        times.append(now)
        while times and (now - times[0]).total_seconds() > secs:
            times.popleft()
        if len(times) > msgs:
            try: await message.delete()
            except: pass
            await message.channel.send(f"{message.author.mention}, stop le spam !")

    # AntiLink
    if config["antilink"]:
        content = message.content.lower()
        if config["antilink_type"] == "invite" and ("discord.gg/" in content or "discord.com/invite" in content):
            await message.delete()
            await message.channel.send(f"{message.author.mention}, lien d'invitation interdit.")
        elif config["antilink_type"] == "all" and re.search(r"https?://", content):
            await message.delete()
            await message.channel.send(f"{message.author.mention}, les liens sont interdits.")

    # AntiBadWord
    if config["antibadword"]:
        if any(bad in message.content.lower() for bad in config["badwords"]):
            await message.delete()
            await message.channel.send(f"{message.author.mention}, mot interdit détecté.")

    # AntiMassMention
    if config["antimassmention"]:
        if len(message.mentions) > config["mass_mention_limit"]:
            await message.delete()
            await message.channel.send(f"{message.author.mention}, trop de mentions dans ce message.")

    await bot.process_commands(message)

@bot.event
async def on_member_join(member):
    config = get_anti_raid_config(member.guild.id)
    if config["antibot"] and member.bot:
        try:
            await member.kick(reason="AntiBot activé")
            if member.guild.system_channel:
                await member.guild.system_channel.send(f"🤖 Bot {member.name} expulsé automatiquement (AntiBot).")
        except Exception as e:
            print(f"Erreur antibot kick: {e}")

# --- COMMANDES TICKET ---

# --- Configuration ---
MAX_TICKETS_PER_USER = 3
TICKET_CATEGORY_NAME = "Tickets"
MODERATOR_ROLE_NAME = "c:/Acces/Perm"

active_tickets = {}  # Structure: {guild_id: {user_id: [channel_ids]}}

# Fonctions utilitaires
async def get_category_by_name(guild, name):
    for category in guild.categories:
        if category.name == name:
            return category
    return None

async def get_role_by_name(guild, name):
    for role in guild.roles:
        if role.name == name:
            return role
    return None

# Vue pour créer un ticket
class TicketCreateView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📩 Ouvrir un ticket", style=discord.ButtonStyle.green, custom_id="open_ticket")
    async def open_ticket(self, interaction: discord.Interaction, button: Button):
        guild = interaction.guild
        member = interaction.user

        # Vérifie le nombre max de tickets
        user_tickets = active_tickets.get(guild.id, {}).get(member.id, [])
        if MAX_TICKETS_PER_USER != 0 and len(user_tickets) >= MAX_TICKETS_PER_USER:
            await interaction.response.send_message(
                f"❌ Tu as déjà atteint le maximum de {MAX_TICKETS_PER_USER} tickets ouverts.",
                ephemeral=True
            )
            return

        # Trouve ou crée la catégorie
        category = await get_category_by_name(guild, TICKET_CATEGORY_NAME)
        if not category:
            category = await guild.create_category(TICKET_CATEGORY_NAME)

        # Permissions pour le channel ticket
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        }
        mod_role = await get_role_by_name(guild, MODERATOR_ROLE_NAME)
        if mod_role:
            overwrites[mod_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        # Nom unique pour le channel
        base_name = f"ticket-{member.name}".lower()
        existing = discord.utils.get(category.channels, name=base_name)
        channel_name = base_name
        if existing:
            channel_name = f"{base_name}-{member.discriminator}"

        ticket_channel = await guild.create_text_channel(channel_name, category=category, overwrites=overwrites, topic=f"Ticket de {member} ({member.id})")

        # Enregistre le ticket en mémoire
        if guild.id not in active_tickets:
            active_tickets[guild.id] = {}
        if member.id not in active_tickets[guild.id]:
            active_tickets[guild.id][member.id] = []
        active_tickets[guild.id][member.id].append(ticket_channel.id)

        # Message dans le ticket avec vue de gestion
        embed = discord.Embed(
            title="🎫 Ticket ouvert",
            description=f"{member.mention} Merci de décrire ton problème. Un modérateur arrivera bientôt.",
            color=discord.Color.green()
        )
        view = TicketManageView(member, ticket_channel)
        await ticket_channel.send(embed=embed, view=view)

        await interaction.response.send_message(f"✅ Ton ticket a été créé: {ticket_channel.mention}", ephemeral=True)

# Vue pour gérer les tickets (claim & close)
class TicketManageView(View):
    def __init__(self, user, channel):
        super().__init__(timeout=None)
        self.user = user
        self.channel = channel

    @discord.ui.button(label="🛡️ Claim", style=discord.ButtonStyle.primary, custom_id="claim_ticket")
    async def claim(self, interaction: discord.Interaction, button: Button):
        mod_role = await get_role_by_name(interaction.guild, MODERATOR_ROLE_NAME)
        if mod_role not in interaction.user.roles:
            await interaction.response.send_message("❌ Tu n'as pas la permission de claim ce ticket.", ephemeral=True)
            return

        overwrites = self.channel.overwrites
        for target in list(overwrites):
            if target != self.user and target != interaction.user:
                overwrites[target].view_channel = False
        overwrites[self.user].view_channel = True
        overwrites[interaction.user] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        await self.channel.edit(overwrites=overwrites)
        await interaction.response.send_message(f"🛡️ Ticket claimé par {interaction.user.mention}", ephemeral=True)

    @discord.ui.button(label="❌ Close", style=discord.ButtonStyle.danger, custom_id="close_ticket")
    async def close(self, interaction: discord.Interaction, button: Button):
        mod_role = await get_role_by_name(interaction.guild, MODERATOR_ROLE_NAME)
        if mod_role not in interaction.user.roles:
            await interaction.response.send_message("❌ Tu n'as pas la permission de fermer ce ticket.", ephemeral=True)
            return
        await interaction.response.send_modal(CloseTicketModal(self.user, self.channel))

# Modal pour la fermeture de ticket
class CloseTicketModal(Modal, title="Fermeture du ticket"):
    reason = TextInput(label="Raison de la fermeture", style=discord.TextStyle.paragraph, required=False, max_length=200)

    def __init__(self, user, channel):
        super().__init__()
        self.user = user
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        messages = [msg async for msg in self.channel.history(limit=100)]
        transcript = "\n".join(f"{msg.author}: {msg.content}" for msg in reversed(messages))

        try:
            await self.user.send(f"📄 Voici la transcription de ton ticket fermé dans {self.channel.guild.name}.\nRaison: {self.reason.value}\n\n{transcript}")
        except:
            pass

        await self.channel.delete()

        guild_id = self.channel.guild.id
        if guild_id in active_tickets:
            for user_id, chans in active_tickets[guild_id].items():
                if self.channel.id in chans:
                    chans.remove(self.channel.id)
                    break

        await interaction.response.send_message(f"🗑️ Ticket fermé pour la raison: {self.reason.value}", ephemeral=True)

# Commande pour poster le panneau de ticket (uniquement admin)
@bot.command()
@commands.has_permissions(administrator=True)
async def ticketpanel(ctx):
    embed = discord.Embed(title="🎫 Ouvrir un ticket", description="Clique sur le bouton pour créer un ticket.", color=discord.Color.blue())
    await ctx.send(embed=embed, view=TicketCreateView())

# --- Commandes salons ---

@bot.command(name="addchannel")
@is_admin()
async def add_channel(ctx, channel_name):
    guild = ctx.guild
    existing = discord.utils.get(guild.channels, name=channel_name)
    if existing:
        await ctx.send("Ce salon existe déjà.")
    else:
        await guild.create_text_channel(channel_name)
        await ctx.send(f"Salon {channel_name} créé !")

@bot.command(name="removechannel")
@is_admin()
async def remove_channel(ctx, channel_name):
    guild = ctx.guild
    channel = discord.utils.get(guild.channels, name=channel_name)
    if channel:
        await channel.delete()
        await ctx.send(f"Salon {channel_name} supprimé.")
    else:
        await ctx.send("Salon introuvable.")

@bot.command(name="lockchannel")
@is_admin()
async def lock_channel(ctx):
    overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
    overwrite.send_messages = False
    await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
    await ctx.send("Salon verrouillé.")

@bot.command(name="unlockchannel")
@is_admin()
async def unlock_channel(ctx):
    overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
    overwrite.send_messages = True
    await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
    await ctx.send("Salon déverrouillé.")

# --- Commande see ---

class SeeUserView(View):
    def __init__(self, member: discord.Member):
        super().__init__(timeout=120)
        self.member = member

    @discord.ui.button(label="🔨 Bannir", style=discord.ButtonStyle.danger)
    async def ban(self, interaction: discord.Interaction, button: Button):
        if not interaction.user.guild_permissions.ban_members:
            await interaction.response.send_message("❌ Vous n'avez pas la permission de bannir.", ephemeral=True)
            return
        await self.member.ban(reason=f"Banni par {interaction.user}")
        await interaction.response.send_message(f"✅ {self.member.mention} a été **banni**.", ephemeral=True)
        self.stop()

    @discord.ui.button(label="🦶 Exclure", style=discord.ButtonStyle.secondary)
    async def kick(self, interaction: discord.Interaction, button: Button):
        if not interaction.user.guild_permissions.kick_members:
            await interaction.response.send_message("❌ Vous n'avez pas la permission d'exclure.", ephemeral=True)
            return
        await self.member.kick(reason=f"Expulsé par {interaction.user}")
        await interaction.response.send_message(f"✅ {self.member.mention} a été **exclu**.", ephemeral=True)
        self.stop()

    @discord.ui.button(label="🔇 Mute", style=discord.ButtonStyle.primary)
    async def mute(self, interaction: discord.Interaction, button: Button):
        if not interaction.user.guild_permissions.moderate_members:
            await interaction.response.send_message("❌ Vous n'avez pas la permission de mute.", ephemeral=True)
            return
        await self.member.edit(timed_out_until=discord.utils.utcnow() + discord.timedelta(minutes=10), reason="Mute temporaire (10 min)")
        await interaction.response.send_message(f"🔇 {self.member.mention} a été **muté pour 10 minutes**.", ephemeral=True)
        self.stop()

    @discord.ui.button(label="❌ Fermer", style=discord.ButtonStyle.grey)
    async def close(self, interaction: discord.Interaction, button: Button):
        await interaction.message.delete()
        self.stop()


@bot.command(name="see")
@commands.has_permissions(administrator=True)
async def see(ctx, user: discord.User = None):
    user = user or ctx.author
    guild = ctx.guild
    member = guild.get_member(user.id)

    server_log = await get_server_log_channel(guild)
    if server_log is None:
        await ctx.send("⚠️ Le salon `server-log` n'existe pas. Utilisez `setupserverlog` pour le créer.")
        return

    embed = discord.Embed(title=f"Informations sur {user}", color=discord.Color.blurple())
    embed.set_thumbnail(url=user.avatar.url if user.avatar else discord.Embed.Empty)

    embed.add_field(name="Nom d'utilisateur", value=f"{user.name}#{user.discriminator}", inline=True)
    embed.add_field(name="ID", value=user.id, inline=True)
    embed.add_field(name="Bot ?", value="✅" if user.bot else "❌", inline=True)

    embed.add_field(name="Compte créé le", value=user.created_at.strftime('%d/%m/%Y %H:%M:%S'), inline=False)

    if member:
        embed.add_field(name="Surnom", value=member.nick or "Aucun", inline=True)
        embed.add_field(name="Statut", value=str(member.status).title(), inline=True)
        embed.add_field(name="Activité", value=member.activity.name if member.activity else "Aucune", inline=True)
        embed.add_field(name="Rejoint le serveur", value=member.joined_at.strftime('%d/%m/%Y %H:%M:%S'), inline=False)

        roles = [role.mention for role in member.roles if role != guild.default_role]
        embed.add_field(name="Rôles", value=", ".join(roles) if roles else "Aucun", inline=False)

        if member.premium_since:
            embed.add_field(name="Booste depuis", value=member.premium_since.strftime('%d/%m/%Y %H:%M:%S'), inline=True)

        if member.timed_out_until:
            embed.add_field(name="Mute jusqu’à", value=member.timed_out_until.strftime('%d/%m/%Y %H:%M:%S'), inline=True)
    else:
        embed.set_footer(text="Utilisateur non présent sur ce serveur.")

    view = SeeUserView(member) if member else None

    await server_log.send(embed=embed)
    await ctx.send(f"📬 Infos sur {user.mention} envoyées dans {server_log.mention}", view=view)

# --- MSGALL ---

# Modal pour saisir le message
class MsgAllModal(Modal, title="Message à envoyer à tous les membres"):
    message = TextInput(label="Ton message", style=discord.TextStyle.paragraph, required=True, max_length=1000)

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        sent = 0
        failed = 0

        for member in self.ctx.guild.members:
            if member.bot:
                continue
            try:
                await member.send(self.message.value)
                sent += 1
            except:
                failed += 1

        await interaction.followup.send(
            f"📨 Message envoyé à {sent} membres.\n❌ Échecs : {failed}", ephemeral=True
        )

# Vue avec boutons Envoyer / Annuler
class MsgAllConfirmView(View):
    def __init__(self, ctx):
        super().__init__(timeout=60)
        self.ctx = ctx

    @discord.ui.button(label="✉️ Écrire et envoyer", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(MsgAllModal(self.ctx))
        self.stop()

    @discord.ui.button(label="❌ Annuler", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("❌ Envoi annulé.", ephemeral=True)
        self.stop()

# Commande msgall
@bot.command()
@commands.has_permissions(administrator=True)
async def msgall(ctx):
    view = MsgAllConfirmView(ctx)
    await ctx.send("Tu veux envoyer un message à **tous les membres** en privé ?", view=view)

# --- COMMANDE CLEAR ---

@bot.command(name="clear")
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int):
    if amount < 1:
        await ctx.send("Tu dois spécifier un nombre de messages à supprimer supérieur à 0.")
        return
    deleted = await ctx.channel.purge(limit=amount + 1)
    await ctx.send(f"✅ {len(deleted)-1} messages supprimés.", delete_after=5)

# --- COMMANDES ROLES ---

@bot.command(name="giverole")
@is_admin()
async def give_role(ctx, member: discord.Member, role_name):
    role = discord.utils.get(ctx.guild.roles, name=role_name)
    if role:
        await member.add_roles(role)
        await ctx.send(f"Le rôle {role_name} a été donné à {member.display_name}")
    else:
        await ctx.send("Rôle introuvable.")

@bot.command(name="removerole")
@is_admin()
async def remove_role(ctx, member: discord.Member, role_name):
    role = discord.utils.get(ctx.guild.roles, name=role_name)
    if role:
        await member.remove_roles(role)
        await ctx.send(f"Le rôle {role_name} a été retiré à {member.display_name}")
    else:
        await ctx.send("Rôle introuvable.")

@bot.command(name="createrole")
@is_admin()
async def create_role(ctx, role_name, color: discord.Colour = discord.Colour.default()):
    guild = ctx.guild
    existing = discord.utils.get(guild.roles, name=role_name)
    if existing:
        await ctx.send("Ce rôle existe déjà.")
    else:
        role = await guild.create_role(name=role_name, colour=color)
        await ctx.send(f"Rôle {role_name} créé.")

# --- COMMANDE DE REINITIALISATION DU SERVEUR ---   
 
@bot.command(name="resetserver")
@commands.guild_only()
async def reset_server(ctx):
    if ctx.author != ctx.guild.owner:
        await ctx.send("❌ Seul le **propriétaire du serveur** peut utiliser cette commande.")
        return

    confirmation = await ctx.send("⚠️ Cette commande va **supprimer tous les salons et tous les rôles** (sauf @everyone). Tape `CONFIRMER` dans les 30 secondes pour continuer.")

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel and m.content == "CONFIRMER"

    try:
        await bot.wait_for("message", check=check, timeout=30.0)
    except asyncio.TimeoutError:
        await ctx.send("⏱️ Temps écoulé. Réinitialisation annulée.")
        return

    # Suppression des salons
    for channel in ctx.guild.channels:
        try:
            await channel.delete()
        except Exception as e:
            print(f"Erreur suppression salon : {e}")

    # Suppression des rôles sauf @everyone
    for role in ctx.guild.roles:
        if role.name != "@everyone":
            try:
                await role.delete()
            except Exception as e:
                print(f"Erreur suppression rôle : {e}")

    # Création d’un salon avec le nom du bot
    try:
        new_channel = await ctx.guild.create_text_channel(str(bot.user.name))
        await new_channel.send("✅ Serveur réinitialisé avec succès.")
    except Exception as e:
        print(f"Erreur création nouveau salon : {e}")
     
# --- BAN / KICK / MUTE ---

@bot.command(name="ban")
@is_admin()
async def ban_member(ctx, member: discord.Member, *, reason=None):
    await member.ban(reason=reason)
    await ctx.send(f"🚫 {member.display_name} a été banni. Raison: {reason}")

    server_log = await get_server_log_channel(ctx.guild)
    if server_log:
        await server_log.send(f"🚫 **{member}** banni par **{ctx.author}**. Raison: {reason}")

@bot.command(name="kick")
@is_admin()
async def kick_member(ctx, member: discord.Member, *, reason=None):
    await member.kick(reason=reason)
    await ctx.send(f"👢 {member.display_name} a été expulsé. Raison: {reason}")

    server_log = await get_server_log_channel(ctx.guild)
    if server_log:
        await server_log.send(f"👢 **{member}** expulsé par **{ctx.author}**. Raison: {reason}")

@bot.command(name="mute")
@is_admin()
async def mute_member(ctx, member: discord.Member, *, reason=None):
    guild = ctx.guild
    mute_role = discord.utils.get(guild.roles, name="Muted")
    if mute_role is None:
        mute_role = await guild.create_role(name="Muted")
        for channel in guild.channels:
            await channel.set_permissions(mute_role, speak=False, send_messages=False, read_message_history=True, read_messages=False)
    await member.add_roles(mute_role)
    await ctx.send(f"🔇 {member.display_name} a été mute. Raison: {reason}")

    server_log = await get_server_log_channel(ctx.guild)
    if server_log:
        await server_log.send(f"🔇 **{member}** mute par **{ctx.author}**. Raison: {reason}")

@bot.command(name="unmute")
@is_admin()
async def unmute_member(ctx, member: discord.Member):
    guild = ctx.guild
    mute_role = discord.utils.get(guild.roles, name="Muted")
    if mute_role in member.roles:
        await member.remove_roles(mute_role)
        await ctx.send(f"🔊 {member.display_name} a été unmute.")

        server_log = await get_server_log_channel(ctx.guild)
        if server_log:
            await server_log.send(f"🔊 **{member}** unmute par **{ctx.author}**.")
    else:
        await ctx.send(f"{member.display_name} n'est pas mute.")

# --- BACKUP SIMPLE DU SERVEUR ---

@bot.command(name="backupserver")
@is_admin()
async def backup_server(ctx):
    guild = ctx.guild

    data = {
        "guild_name": guild.name,
        "guild_id": guild.id,
        "roles": [],
        "channels": [],
        "members": [],
    }

    for role in guild.roles:
        data["roles"].append({
            "name": role.name,
            "id": role.id,
            "color": role.color.value,
            "permissions": role.permissions.value,
            "hoist": role.hoist,
            "mentionable": role.mentionable,
            "position": role.position,
        })

    for channel in guild.channels:
        data["channels"].append({
            "name": channel.name,
            "id": channel.id,
            "type": str(channel.type),
            "position": channel.position,
            "category": channel.category.name if channel.category else None,
            "nsfw": getattr(channel, "nsfw", False),
        })

    for member in guild.members:
        data["members"].append({
            "id": member.id,
            "name": member.name,
            "discriminator": member.discriminator,
            "roles": [role.name for role in member.roles if role.name != "@everyone"]
        })

    filename = f"backup_{guild.id}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    await ctx.send(f"📦 Backup du serveur sauvegardé dans `{filename}`")

# --- SYSTÈME DE LOGS (ancien) ---

async def get_log_channel(guild):
    channel = discord.utils.get(guild.channels, name=LOG_CHANNEL_NAME)
    if channel is None:
        channel = await guild.create_text_channel(LOG_CHANNEL_NAME)
    return channel

@bot.event
async def on_guild_channel_create(channel):
    guild = channel.guild
    log_channel = await get_log_channel(guild)

    author = None
    try:
        entry = await guild.audit_logs(action=discord.AuditLogAction.channel_create, limit=1).find(lambda e: e.target.id == channel.id)
        author = entry.user if entry else None
    except:
        author = None

    if author:
        now = asyncio.get_event_loop().time()
        times = channel_create_times.get(author.id, [])
        times = [t for t in times if now - t < 60]
        times.append(now)
        channel_create_times[author.id] = times
        if len(times) > 3:
            try:
                await guild.kick(author, reason="Suspicion d'attaque raid (création trop rapide de salons)")
                await log_channel.send(f"⚠️ {author} expulsé pour suspicion de raid (trop de salons créés).")
            except Exception as e:
                print(f"Erreur anti-raid : {e}")

    await log_channel.send(f"📢 Nouveau salon créé : {channel.name}")

@bot.event
async def on_guild_channel_delete(channel):
    log_channel = await get_log_channel(channel.guild)
    await log_channel.send(f"🗑️ Salon supprimé : {channel.name}")

# --- NOUVEAUX LOGS DANS SERVER-LOG ---

@bot.event
async def on_member_join(member):
    server_log = await get_server_log_channel(member.guild)
    if server_log:
        await server_log.send(f"✅ **{member}** a rejoint le serveur.")

@bot.event
async def on_member_remove(member):
    server_log = await get_server_log_channel(member.guild)
    if server_log:
        await server_log.send(f"❌ **{member}** a quitté ou a été expulsé du serveur.")

        from collections import defaultdict
import time

# ==========================
# ⚙️ Commande auto-config log
# ==========================
@bot.command(name="autoconfiglog")
@commands.has_permissions(administrator=True)
async def autoconfiglog(ctx):
    guild = ctx.guild
    category_name = "📝 Logs"
    log_channels = [
        "log-messages", "log-vocal", "log-modération",
        "log-boost", "log-rôles", "log-raid"
    ]

    category = discord.utils.get(guild.categories, name=category_name)
    if not category:
        category = await guild.create_category(category_name)

    created_channels = []
    for name in log_channels:
        existing = discord.utils.get(category.text_channels, name=name)
        if not existing:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False)
            }
            channel = await guild.create_text_channel(name, category=category, overwrites=overwrites)
            created_channels.append(channel.name)

    await ctx.send(f"✅ Catégorie de logs créée avec les salons : {', '.join(created_channels)}")

# =======================
# 📝 Logs de messages
# =======================
@bot.event
async def on_message_delete(message):
    if message.guild and not message.author.bot:
        channel = discord.utils.get(message.guild.text_channels, name="log-messages")
        if channel:
            await channel.send(f"🗑️ **Message supprimé** de {message.author.mention} dans {message.channel.mention} :\n```{message.content}```")

@bot.event
async def on_message_edit(before, after):
    if before.guild and not before.author.bot and before.content != after.content:
        channel = discord.utils.get(before.guild.text_channels, name="log-messages")
        if channel:
            await channel.send(
                f"✏️ **Message modifié** par {before.author.mention} dans {before.channel.mention} :\n"
                f"Avant : ```{before.content}```\nAprès : ```{after.content}```"
            )

# =======================
# 🔊 Logs vocaux
# =======================
@bot.event
async def on_voice_state_update(member, before, after):
    channel = discord.utils.get(member.guild.text_channels, name="log-vocal")
    if not channel:
        return

    if not before.channel and after.channel:
        await channel.send(f"🔊 {member.mention} s'est **connecté** à {after.channel.name}")
    elif before.channel and not after.channel:
        await channel.send(f"🔇 {member.mention} s'est **déconnecté** de {before.channel.name}")
    elif before.channel != after.channel:
        await channel.send(f"🔁 {member.mention} est passé de {before.channel.name} à {after.channel.name}")

    if not before.self_stream and after.self_stream:
        await channel.send(f"📺 {member.mention} a **démarré un partage d'écran**.")
    if before.self_stream and not after.self_stream:
        await channel.send(f"📺 {member.mention} a **arrêté son partage d'écran**.")
    if not before.self_video and after.self_video:
        await channel.send(f"📷 {member.mention} a **activé sa caméra**.")
    if before.self_video and not after.self_video:
        await channel.send(f"📷 {member.mention} a **désactivé sa caméra**.")

# =======================
# 🚀 Logs de boost
# =======================
@bot.event
async def on_member_update(before, after):
    if before.premium_since != after.premium_since:
        boost_channel = discord.utils.get(after.guild.text_channels, name="log-boost")
        if boost_channel and after.premium_since:
            await boost_channel.send(f"🚀 {after.mention} a **boosté** le serveur ! Merci ❤️")

# =======================
# 🎭 Logs rôles
# =======================
@bot.event
async def on_member_update(before, after):
    if before.roles != after.roles:
        role_channel = discord.utils.get(after.guild.text_channels, name="log-rôles")
        if not role_channel:
            return

        before_roles = set(before.roles)
        after_roles = set(after.roles)

        added = after_roles - before_roles
        removed = before_roles - after_roles

        for role in added:
            await role_channel.send(f"➕ {after.mention} a reçu le rôle **{role.name}**")
        for role in removed:
            await role_channel.send(f"➖ {after.mention} a perdu le rôle **{role.name}**")

# =======================
# 🔐 Logs Anti-Raid (exemple générique)
# =======================
async def log_antiraid_action(guild, message: str):
    channel = discord.utils.get(guild.text_channels, name="log-raid")
    if channel:
        await channel.send(f"🚨 {message}")


# --- LOG V2 ---

# Configuration des logs en mémoire: 
# guild_id -> {log_type: channel_id, ... , "nolog": set(salon_ids)}
log_config = {}

def get_guild_config(guild_id):
    if guild_id not in log_config:
        log_config[guild_id] = {
            "modlog": None,
            "messagelog": None,
            "voicelog": None,
            "boostlog": None,
            "rolelog": None,
            "raidlog": None,
            "nolog": set()
        }
    return log_config[guild_id]

# --- Commandes pour activer/désactiver logs ---

def create_log_toggle_command(log_type):
    @bot.group(name=log_type + "log", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def log_toggle(ctx, toggle=None, channel: discord.TextChannel = None):
        guild_id = ctx.guild.id
        cfg = get_guild_config(guild_id)

        if toggle is None:
            current_id = cfg.get(log_type)
            if current_id:
                ch = ctx.guild.get_channel(current_id)
                await ctx.send(f"Le log `{log_type}` est activé dans {ch.mention}")
            else:
                await ctx.send(f"Le log `{log_type}` est désactivé.")
            return

        toggle = toggle.lower()
        if toggle == "on":
            if channel is None:
                await ctx.send(f"Merci de préciser un salon. Exemple: `+{log_type}log on #salon`")
                return
            cfg[log_type] = channel.id
            await ctx.send(f"Logs `{log_type}` activés dans {channel.mention}")
        elif toggle == "off":
            cfg[log_type] = None
            await ctx.send(f"Logs `{log_type}` désactivés.")
        else:
            await ctx.send(f"Usage : `+{log_type}log on [salon]` ou `+{log_type}log off`")

    return log_toggle

modlog = create_log_toggle_command("mod")
messagelog = create_log_toggle_command("message")
voicelog = create_log_toggle_command("voice")
boostlog = create_log_toggle_command("boost")
rolelog = create_log_toggle_command("role")
raidlog = create_log_toggle_command("raid")

# --- Commande pour gérer les exceptions (nolog) ---

@bot.group(name="nolog", invoke_without_command=True)
@commands.has_permissions(administrator=True)
async def nolog(ctx, action=None, channel: discord.TextChannel=None):
    if action is None or channel is None:
        await ctx.send("Usage : `+nolog add [salon]` ou `+nolog del [salon]`")
        return

    guild_id = ctx.guild.id
    cfg = get_guild_config(guild_id)

    action = action.lower()
    if action == "add":
        cfg["nolog"].add(channel.id)
        await ctx.send(f"Salon {channel.mention} ajouté aux exceptions (logs désactivés).")
    elif action == "del":
        cfg["nolog"].discard(channel.id)
        await ctx.send(f"Salon {channel.mention} retiré des exceptions (logs activés).")
    else:
        await ctx.send("Utilise `add` ou `del` uniquement.")

# --- Commande autoconfiglog qui crée catégorie + salons ---

@commands.has_permissions(administrator=True)
async def autoconfiglog(ctx):
    guild = ctx.guild
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        guild.me: discord.PermissionOverwrite(read_messages=True)
    }
    category = await guild.create_category("Logs", overwrites=overwrites)
    
    async def create_log_channel(name):
        channel = await guild.create_text_channel(name, category=category)
        return guild.get_channel(channel.id)

    logs = {}
    logs["modlog"] = await guild.create_text_channel("mod-logs", category=category)
    logs["messagelog"] = await guild.create_text_channel("message-logs", category=category)
    logs["voicelog"] = await guild.create_text_channel("voice-logs", category=category)
    logs["boostlog"] = await guild.create_text_channel("boost-logs", category=category)
    logs["rolelog"] = await guild.create_text_channel("role-logs", category=category)
    logs["raidlog"] = await guild.create_text_channel("raid-logs", category=category)

    cfg = get_guild_config(guild.id)
    for key in logs:
        cfg[key] = logs[key].id

    await ctx.send("Logs configurés automatiquement avec une catégorie et salons dédiés.")

# --- EVENTS LOG ---

# Modération logs : bannissements, kicks, etc.
@bot.event
async def on_member_ban(guild, user):
    cfg = get_guild_config(guild.id)
    channel_id = cfg.get("modlog")
    if not channel_id:
        return
    if channel_id in cfg["nolog"]:
        return
    channel = guild.get_channel(channel_id)
    if channel:
        embed = discord.Embed(title="Membre banni", color=discord.Color.red())
        embed.add_field(name="Utilisateur", value=f"{user} ({user.id})", inline=False)
        await channel.send(embed=embed)

@bot.event
async def on_member_unban(guild, user):
    cfg = get_guild_config(guild.id)
    channel_id = cfg.get("modlog")
    if not channel_id:
        return
    if channel_id in cfg["nolog"]:
        return
    channel = guild.get_channel(channel_id)
    if channel:
        embed = discord.Embed(title="Membre débanni", color=discord.Color.green())
        embed.add_field(name="Utilisateur", value=f"{user} ({user.id})", inline=False)
        await channel.send(embed=embed)

# Message logs : suppression et édition
@bot.event
async def on_message_delete(message):
    if message.guild is None:
        return
    cfg = get_guild_config(message.guild.id)
    channel_id = cfg.get("messagelog")
    if not channel_id or message.channel.id in cfg["nolog"]:
        return
    channel = message.guild.get_channel(channel_id)
    if channel:
        embed = discord.Embed(title="Message supprimé", color=discord.Color.orange())
        embed.add_field(name="Auteur", value=f"{message.author} ({message.author.id})", inline=False)
        embed.add_field(name="Salon", value=message.channel.mention, inline=False)
        embed.add_field(name="Contenu", value=message.content or "*aucun contenu*", inline=False)
        await channel.send(embed=embed)

@bot.event
async def on_message_edit(before, after):
    if before.guild is None:
        return
    cfg = get_guild_config(before.guild.id)
    channel_id = cfg.get("messagelog")
    if not channel_id or before.channel.id in cfg["nolog"]:
        return
    if before.content == after.content:
        return
    channel = before.guild.get_channel(channel_id)
    if channel:
        embed = discord.Embed(title="Message édité", color=discord.Color.blue())
        embed.add_field(name="Auteur", value=f"{before.author} ({before.author.id})", inline=False)
        embed.add_field(name="Salon", value=before.channel.mention, inline=False)
        embed.add_field(name="Avant", value=before.content or "*aucun contenu*", inline=False)
        embed.add_field(name="Après", value=after.content or "*aucun contenu*", inline=False)
        await channel.send(embed=embed)

# Voice logs : join, leave, mute, deaf, etc.
@bot.event
async def on_voice_state_update(member, before, after):
    guild = member.guild
    cfg = get_guild_config(guild.id)
    channel_id = cfg.get("voicelog")
    if not channel_id:
        return
    if before.channel and before.channel.id in cfg["nolog"]:
        return
    if after.channel and after.channel.id in cfg["nolog"]:
        return
    channel = guild.get_channel(channel_id)
    if not channel:
        return

    if before.channel != after.channel:
        if before.channel is None and after.channel is not None:
            await channel.send(f"🔊 {member.mention} est entré dans {after.channel.mention}")
        elif before.channel is not None and after.channel is None:
            await channel.send(f"🔈 {member.mention} est sorti de {before.channel.mention}")
        else:
            await channel.send(f"🔄 {member.mention} a changé de salon vocal : {before.channel.mention} → {after.channel.mention}")

    # Screen share / caméra détectée par flags (simplifié)
    if before.self_stream != after.self_stream:
        status = "a démarré un partage d'écran" if after.self_stream else "a arrêté un partage d'écran"
        await channel.send(f"📽️ {member.mention} {status}")
    if before.self_video != after.self_video:
        status = "a allumé sa caméra" if after.self_video else "a éteint sa caméra"
        await channel.send(f"🎥 {member.mention} {status}")

    # Mute / Deafen
    if before.self_mute != after.self_mute:
        status = "s'est mute" if after.self_mute else "s'est unmute"
        await channel.send(f"🔇 {member.mention} {status}")
    if before.self_deaf != after.self_deaf:
        status = "s'est deaf" if after.self_deaf else "s'est undeaf"
        await channel.send(f"🔈 {member.mention} {status}")

# Boost logs : lorsqu'un membre boost le serveur
@bot.event
async def on_member_update(before, after):
    guild = after.guild
    cfg = get_guild_config(guild.id)
    channel_id = cfg.get("boostlog")
    if not channel_id:
        return
    channel = guild.get_channel(channel_id)
    if not channel:
        return
    if after.premium_since and (before.premium_since is None):
        await channel.send(f"🚀 {after.mention} a boosté le serveur ! Merci à toi !")

# Role logs : ajout et suppression de rôles
@bot.event
async def on_member_update(before, after):
    guild = after.guild
    cfg = get_guild_config(guild.id)
    channel_id = cfg.get("rolelog")
    if not channel_id:
        return
    channel = guild.get_channel(channel_id)
    if not channel:
        return

    before_roles = set(before.roles)
    after_roles = set(after.roles)

    added = after_roles - before_roles
    removed = before_roles - after_roles

    if added:
        for role in added:
            if role.is_default():
                continue
            await channel.send(f"✅ {after.mention} a reçu le rôle {role.name}")
    if removed:
        for role in removed:
            if role.is_default():
                continue
            await channel.send(f"❌ {after.mention} a perdu le rôle {role.name}")

# --- Commande logstatus pour voir la config actuelle ---

@bot.command(name="logstatus")
@commands.has_permissions(administrator=True)
async def logstatus(ctx):
    cfg = get_guild_config(ctx.guild.id)
    lines = []
    for key in ["modlog", "messagelog", "voicelog", "boostlog", "rolelog", "raidlog"]:
        cid = cfg.get(key)
        ch = ctx.guild.get_channel(cid) if cid else None
        lines.append(f"**{key}** : {ch.mention if ch else 'désactivé'}")
    if cfg["nolog"]:
        excepts = [ctx.guild.get_channel(c) for c in cfg["nolog"] if ctx.guild.get_channel(c)]
        lines.append(f"**Exceptions (nolog)** : {', '.join([ch.mention for ch in excepts])}")
    else:
        lines.append("**Exceptions (nolog)** : aucune")
    await ctx.send("\n".join(lines))

# --- VARIABLES ANTI-RAID ---

ban_times = defaultdict(list)
unban_times = defaultdict(list)
role_add_times = defaultdict(list)
channel_edit_times = defaultdict(list)
webhook_create_times = defaultdict(list)
everyone_ping_times = defaultdict(list)
member_join_times = []
deco_voice_times = defaultdict(list)

MAX_BANS = 3
BAN_TIME_FRAME = 60  # secondes

MAX_UNBANS = 2
UNBAN_TIME_FRAME = 60

MAX_ROLE_ADDS = 5
ROLE_ADD_TIME_FRAME = 60

MAX_CHANNEL_EDITS = 3
CHANNEL_EDIT_TIME_FRAME = 60

MAX_WEBHOOK_CREATES = 3
WEBHOOK_CREATE_TIME_FRAME = 60

MAX_EVERYONE_PINGS = 3
EVERYONE_PING_TIME_FRAME = 120

MAX_JOINS_SIMULTANEOUS = 5
JOIN_TIME_FRAME = 30

ACCOUNT_AGE_LIMIT = 7 * 24 * 3600  # 7 jours en secondes

blacklist_role_names = ["bannedrole"]  # à adapter, rôles blacklistés


# --- FONCTION POUR SANCTIONNER ---

async def sanction_user(guild, user, reason):
    try:
        await guild.kick(user, reason=reason)
        server_log = await get_server_log_channel(guild)
        if server_log:
            await server_log.send(f"⚠️ {user} expulsé automatiquement pour : {reason}")
    except Exception as e:
        print(f"Erreur sanction anti-raid: {e}")


# --- ANTI BAN ---

@bot.event
async def on_member_ban(guild, user):
    try:
        entry = await guild.audit_logs(action=discord.AuditLogAction.ban, limit=1).get()
        if entry is None:
            return
        mod = entry.user
        now = time.time()
        times = ban_times[mod.id]
        times = [t for t in times if now - t < BAN_TIME_FRAME]
        times.append(now)
        ban_times[mod.id] = times
        if len(times) > MAX_BANS:
            await sanction_user(guild, mod, "AntiBan: bannissements trop rapides")
    except Exception as e:
        print(f"Erreur AntiBan : {e}")


# --- ANTI UNBAN ---

@bot.event
async def on_member_unban(guild, user):
    try:
        entry = await guild.audit_logs(action=discord.AuditLogAction.unban, limit=1).get()
        if entry is None:
            return
        mod = entry.user
        now = time.time()
        times = unban_times[mod.id]
        times = [t for t in times if now - t < UNBAN_TIME_FRAME]
        times.append(now)
        unban_times[mod.id] = times
        if len(times) > MAX_UNBANS:
            await sanction_user(guild, mod, "AntiUnban: débannissements trop rapides")
    except Exception as e:
        print(f"Erreur AntiUnban : {e}")


# --- ANTI BOT ADD ---

@bot.event
async def on_member_join(member):
    # Limite compte trop récent (Creation Limit)
    now = time.time()
    account_age = now - member.created_at.timestamp()
    if account_age < ACCOUNT_AGE_LIMIT:
        try:
            await member.kick(reason="Compte trop récent - anti raid")
            server_log = await get_server_log_channel(member.guild)
            if server_log:
                await server_log.send(f"⚠️ {member} a été kick car compte créé il y a moins de 7 jours.")
        except Exception as e:
            print(f"Erreur anti creation limit: {e}")
        return

    # Limite nombre membres rejoignant en même temps (AntiToken)
    member_join_times.append(now)
    member_join_times[:] = [t for t in member_join_times if now - t < JOIN_TIME_FRAME]
    if len(member_join_times) > MAX_JOINS_SIMULTANEOUS:
        # Trouver le plus récent à kick (ou tous)
        try:
            await member.kick(reason="AntiToken: trop de membres rejoignent en même temps")
            server_log = await get_server_log_channel(member.guild)
            if server_log:
                await server_log.send(f"⚠️ {member} kické pour anti token (trop de joins simultanés).")
        except Exception as e:
            print(f"Erreur anti token: {e}")

    # AntiBot
    if member.bot:
        try:
            await member.kick(reason="AntiBot: bot non autorisé")
            server_log = await get_server_log_channel(member.guild)
            if server_log:
                await server_log.send(f"⚠️ Bot {member} kické automatiquement.")
        except Exception as e:
            print(f"Erreur anti bot: {e}")


# --- ANTI CHANNEL (création, modification, suppression) ---

@bot.event
async def on_guild_channel_create(channel):
    guild = channel.guild
    now = time.time()
    entry = None
    try:
        entry = await guild.audit_logs(action=discord.AuditLogAction.channel_create, limit=1).get()
    except:
        pass
    if entry:
        mod = entry.user
        times = channel_edit_times[mod.id]
        times = [t for t in times if now - t < CHANNEL_EDIT_TIME_FRAME]
        times.append(now)
        channel_edit_times[mod.id] = times
        if len(times) > MAX_CHANNEL_EDITS:
            await sanction_user(guild, mod, "AntiChannel: créations trop rapides")

@bot.event
async def on_guild_channel_delete(channel):
    guild = channel.guild
    now = time.time()
    entry = None
    try:
        entry = await guild.audit_logs(action=discord.AuditLogAction.channel_delete, limit=1).get()
    except:
        pass
    if entry:
        mod = entry.user
        times = channel_edit_times[mod.id]
        times = [t for t in times if now - t < CHANNEL_EDIT_TIME_FRAME]
        times.append(now)
        channel_edit_times[mod.id] = times
        if len(times) > MAX_CHANNEL_EDITS:
            await sanction_user(guild, mod, "AntiChannel: suppressions trop rapides")

@bot.event
async def on_guild_channel_update(before, after):
    guild = after.guild
    now = time.time()
    entry = None
    try:
        entry = await guild.audit_logs(action=discord.AuditLogAction.channel_update, limit=1).get()
    except:
        pass
    if entry:
        mod = entry.user
        times = channel_edit_times[mod.id]
        times = [t for t in times if now - t < CHANNEL_EDIT_TIME_FRAME]
        times.append(now)
        channel_edit_times[mod.id] = times
        if len(times) > MAX_CHANNEL_EDITS:
            await sanction_user(guild, mod, "AntiChannel: modifications trop rapides")


# --- ANTI WEBHOOK CREATION ---

@bot.event
async def on_webhooks_update(channel):
    guild = channel.guild
    now = time.time()
    entry = None
    try:
        entry = await guild.audit_logs(action=discord.AuditLogAction.webhook_create, limit=1).get()
    except:
        pass
    if entry:
        mod = entry.user
        times = webhook_create_times[mod.id]
        times = [t for t in times if now - t < WEBHOOK_CREATE_TIME_FRAME]
        times.append(now)
        webhook_create_times[mod.id] = times
        if len(times) > MAX_WEBHOOK_CREATES:
            await sanction_user(guild, mod, "AntiWebhook: créations trop rapides")


# --- ANTI EVERYONE/HERE PING ---

@bot.event
async def on_message(message):
    if message.author.bot:
        return await bot.process_commands(message)

    now = time.time()
    if ("@everyone" in message.content or "@here" in message.content):
        times = everyone_ping_times[message.author.id]
        times = [t for t in times if now - t < EVERYONE_PING_TIME_FRAME]
        times.append(now)
        everyone_ping_times[message.author.id] = times
        if len(times) > MAX_EVERYONE_PINGS:
            try:
                await message.delete()
                await sanction_user(message.guild, message.author, "AntiEveryone: spam @everyone/@here")
            except Exception as e:
                print(f"Erreur anti everyone: {e}")

    await bot.process_commands(message)


# --- ANTI ROLE ADD/DON ---

@bot.event
async def on_guild_role_create(role):
    guild = role.guild
    now = time.time()
    # Ici on peut logger ou limiter si création rôle trop rapide (optionnel)

@bot.event
async def on_guild_role_update(before, after):
    guild = after.guild
    now = time.time()
    # idem création/modif rôle

@bot.event
async def on_guild_role_delete(role):
    guild = role.guild
    now = time.time()
    # idem suppression rôle

@bot.event
async def on_member_update(before, after):
    guild = after.guild
    now = time.time()
    try:
        # Check si un rôle a été ajouté
        added_roles = [r for r in after.roles if r not in before.roles]
        if not added_roles:
            return
        entry = await guild.audit_logs(action=discord.AuditLogAction.member_role_update, limit=1).get()
        if entry is None:
            return
        mod = entry.user
        # Blacklist Rank Check
        for role in added_roles:
            if role.name.lower() in blacklist_role_names:
                # Sanctionne mod qui a donné un rôle blacklisté
                await sanction_user(guild, mod, f"BlacklistRank: a donné le rôle blacklisté {role.name}")
                # Retire le rôle donné
                await after.remove_roles(role)
                server_log = await get_server_log_channel(guild)
                if server_log:
                    await server_log.send(f"⚠️ {mod} a donné le rôle blacklisté {role.name} à {after}, rôle retiré.")
                return

        # AntiRole Add frequency
        times = role_add_times[mod.id]
        times = [t for t in times if now - t < ROLE_ADD_TIME_FRAME]
        times.append(now)
        role_add_times[mod.id] = times
        if len(times) > MAX_ROLE_ADDS:
            await sanction_user(guild, mod, "AntiRole: ajout de rôles trop rapide")

    except Exception as e:
        print(f"Erreur AntiRole: {e}")


# --- ANTI DECO (abus déconnexions vocales répétées) ---

@bot.event
async def on_voice_state_update(member, before, after):
    if before.channel is not None and after.channel is None:
        now = time.time()
        times = deco_voice_times[member.id]
        times = [t for t in times if now - t < 30]  # 30 secondes pour exemple
        times.append(now)
        deco_voice_times[member.id] = times
        if len(times) > 3:
            try:
                await member.send("⚠️ Vous déconnectez trop souvent du vocal, veuillez arrêter.")
                server_log = await get_server_log_channel(member.guild)
                if server_log:
                    await server_log.send(f"⚠️ {member} abuse des déconnexions vocales répétées.")
            except Exception as e:
                print(f"Erreur AntiDeco: {e}")

# --- ANTI UPDATE (modification serveur) ---

@bot.event
async def on_guild_update(before, after):
    guild = after
    try:
        entry = await guild.audit_logs(action=discord.AuditLogAction.guild_update, limit=1).get()
        if entry is None:
            return
        mod = entry.user
        # Ici on peut vérifier précisément ce qui a changé, exemple :
        changes = []
        if before.name != after.name:
            changes.append("nom du serveur")
        if before.icon != after.icon:
            changes.append("icone du serveur")
        if before.banner != after.banner:
            changes.append("bannière du serveur")
        if changes:
            await sanction_user(guild, mod, f"AntiUpdate: modifications serveur ({', '.join(changes)})")
    except Exception as e:
        print(f"Erreur AntiUpdate : {e}")

# --- COMMANDE HELP ---

import discord
from discord.ext import commands
from discord.ui import View, Button

class HelpView(View):
    def __init__(self, embeds, author):
        super().__init__(timeout=120)  # 2 minutes d'inactivité max
        self.embeds = embeds
        self.author = author
        self.current = 0

        self.previous_button = Button(label="⬅️", style=discord.ButtonStyle.gray)
        self.next_button = Button(label="➡️", style=discord.ButtonStyle.gray)
        self.close_button = Button(label="❌ Fermer", style=discord.ButtonStyle.red)

        self.previous_button.callback = self.previous
        self.next_button.callback = self.next
        self.close_button.callback = self.close

        self.add_item(self.previous_button)
        self.add_item(self.next_button)
        self.add_item(self.close_button)

    async def previous(self, interaction: discord.Interaction):
        if interaction.user != self.author:
            await interaction.response.send_message("Seul l'auteur de la commande peut naviguer.", ephemeral=True)
            return
        if self.current > 0:
            self.current -= 1
            await interaction.response.edit_message(embed=self.embeds[self.current], view=self)

    async def next(self, interaction: discord.Interaction):
        if interaction.user != self.author:
            await interaction.response.send_message("Seul l'auteur de la commande peut naviguer.", ephemeral=True)
            return
        if self.current < len(self.embeds) - 1:
            self.current += 1
            await interaction.response.edit_message(embed=self.embeds[self.current], view=self)

    async def close(self, interaction: discord.Interaction):
        if interaction.user != self.author:
            await interaction.response.send_message("Seul l'auteur peut fermer ce message.", ephemeral=True)
            return
        await interaction.message.delete()

bot.remove_command("help")

@bot.command(name="help")
async def help_command(ctx):
    prefix_used = ctx.prefix  # Assure-toi que 'prefix' est défini globalement

    embed1 = discord.Embed(
        title="📘 Commandes Générales",
        description=f"""
🔹 `{prefix_used}setprefix <nouveau_prefix>` — Change le préfixe  
🔹 `{prefix_used}lockchannel` — Verrouille le salon  
🔹 `{prefix_used}unlockchannel` — Déverrouille le salon  
🔹 `{prefix_used}addchannel <nom>` — Crée un salon  
🔹 `{prefix_used}removechannel <nom>` — Supprime un salon  
🔹 `{prefix_used}giverole @membre <rôle>` — Donne un rôle  
🔹 `{prefix_used}removerole @membre <rôle>` — Retire un rôle  
🔹 `{prefix_used}createrole <nom>` — Crée un rôle  
🔹 `{prefix_used}ban @membre` — Bannit un membre  
🔹 `{prefix_used}kick @membre` — Expulse un membre  
🔹 `{prefix_used}mute @membre` — Mute un membre  
🔹 `{prefix_used}unmute @membre` — Unmute un membre  
🔹 `{prefix_used}backupserver` — Sauvegarde le serveur  
🔹 `{prefix_used}setupserverlog` — Crée le salon `#server-log`  
🔹 `{prefix_used}clear <nombre>` — Supprime un nombre de messages  
🔹 `{prefix_used}resetserver` — Réinitialise le serveur  
""",
        color=discord.Color.dark_theme()
    )
    embed1.set_footer(text="Page 1/6")

    embed2 = discord.Embed(
        title="🛡️ Commandes Anti-Raid",
        description=f"""
🔹 `{prefix_used}antiban enable|disable`  
🔹 `{prefix_used}antibot enable|disable`  
🔹 `{prefix_used}antichannel enable|disable`  
🔹 `{prefix_used}antideco enable|disable`  
🔹 `{prefix_used}antieveryone enable|disable`  
🔹 `{prefix_used}antirole enable|disable`  
🔹 `{prefix_used}antitoken enable|disable`  
🔹 `{prefix_used}antiunban enable|disable`  
🔹 `{prefix_used}antiupdate enable|disable`  
🔹 `{prefix_used}antiwebhook enable|disable`  
🔹 `{prefix_used}blacklistrank add|remove @membre`  
🔹 `{prefix_used}creationlimit set <jours>`  
""",
        color=discord.Color.dark_theme()
    )
    embed2.set_footer(text="Page 2/6")

    embed3 = discord.Embed(
        title="🔧 Utilitaires",
        description=f"""
🔹 `{prefix_used}help` — Affiche ce message d’aide  
🔹 `{prefix_used}logstatus` — Affiche l’état des logs 
🔹 `{prefix_used}protections` — Affiche le panel D'automod / AntiRaid 
🔹 `{prefix_used}ticketpanel` — Affiche le panel des tickets 
🔹 `{prefix_used}autoconfiglog` — Configure automatiquement les salons de logs  
🔹 `{prefix_used}see <user_id>` — Affiche les informations détaillées d'un utilisateur  
🔹 Plus de commandes à venir... ✨  
""",
        color=discord.Color.dark_theme()
    )
    embed3.set_footer(text="Page 3/6")

    embed4 = discord.Embed(
        title="🧱 Automodération",
        description=f"""
**Activation rapide :**  
🔹 `{prefix_used}antispam on`  
🔹 `{prefix_used}antilink on`  
🔹 `{prefix_used}antibadword on`  
🔹 `{prefix_used}antimassmention on`  

**Configuration :**  
🔹 `{prefix_used}antispam <messages>/<secondes>` — Ex : `4/5`  
🔹 `{prefix_used}antilink invite|all`  
🔹 `{prefix_used}badword add <mot>` / `del <mot>` / `list`  
🔹 `{prefix_used}antimassmention <nombre>`  

**Sanctions & Strikes :**  
🔹 `{prefix_used}punish add <strikes> <durée> <sanction> [durée]`  
🔹 `{prefix_used}punish del <id>`  
🔹 `{prefix_used}punish` — Voir la liste  
🔹 `{prefix_used}punish setup` — Config auto  

**Strikes personnalisés :**  
🔹 `{prefix_used}strike <action> <valeur> [ancien|nouveau]`  
🔹 `{prefix_used}ancien <durée>` — Ex : `1h`, `2j`  
🔹 `{prefix_used}settings` — Voir la config actuelle  
""",
        color=discord.Color.dark_theme()
    )
    embed4.set_footer(text="Page 4/6")

    embed5 = discord.Embed(
        title="⭐ Système de Niveau (EN MAINTENANCE)",
        description=f"""
🔹 `{prefix_used}lvlmessage on [#salon]` — Active l’envoi des messages de niveau dans un salon  
🔹 `{prefix_used}lvlmessage set <message>` — Définit le message d’annonce de niveau (ex: Bravo {{MemberMention}}, tu as passé un niveau)  
🔹 `{prefix_used}role level add <@rôle> <niveau>` — Ajoute un rôle à un niveau  
🔹 `{prefix_used}role level cumul <on/off>` — Choisit d’attribuer un seul rôle ou plusieurs rôles cumulés  
🔹 `{prefix_used}role level del <@rôle>` — Supprime un rôle de niveau  
🔹 `{prefix_used}role level list` — Liste les rôles de niveau  
🔹 `{prefix_used}rate message <rate> [#salon]` — Configure le gain d’XP par message global ou par salon  
🔹 `{prefix_used}rate voc <rate> [#salon]` — Configure le gain d’XP vocal global ou par salon  
🔹 `{prefix_used}rate mute <pourcentage> [#salon]` — Réduit l’XP gagné en vocal quand muet  
🔹 `{prefix_used}rate list` — Affiche la liste des salons avec leurs rates personnalisés  
🔹 `{prefix_used}settings level` — Affiche les paramètres globaux du leveling  
🔹 `{prefix_used}rate level <niveau>` — Affiche l’activité nécessaire pour atteindre un niveau donné  
🔹 `{prefix_used}cooldown <temps>` — Définit le cooldown minimum entre messages pour gagner de l’XP  
🔹 `{prefix_used}xp add <nombre> [@membre]` — Ajoute de l’XP à un membre  
🔹 `{prefix_used}xp remove <nombre> [@membre]` — Retire de l’XP à un membre  
🔹 `{prefix_used}xp reset <@membre>` — Réinitialise l’XP d’un membre  
🔹 `{prefix_used}xp resetall` — Réinitialise l’XP de tous les membres  
🔹 `{prefix_used}leaderboard level` — Affiche le classement des membres par niveau
""",
        color=discord.Color.dark_theme()
    )
    embed5.set_footer(text="Page 5/6")

    embed6 = discord.Embed(
        title="🔐 Système de Sécurité & Bienvenue",
        description=f"""
**Sécurité Captcha & Vérification par bouton**  
🔹 `{prefix_used}join settings` — Configure la sécurité (choix Captcha ou bouton)  
🔹 `{prefix_used}set captcha_message_id <id>` — ID du message du système captcha  
🔹 `{prefix_used}set captcha_channel <id|nom>` — Salon où la sécurité est affichée  
🔹 `{prefix_used}set captcha_button_text <texte>` — Texte du bouton captcha  
🔹 `{prefix_used}set captcha_button_emoji <emoji>` — Emoji du bouton captcha  
🔹 `{prefix_used}set captcha_button_color <bleu|gris|rouge|vert>` — Couleur du bouton captcha  

**Durée & Logs de vérification**  
🔹 `{prefix_used}set verification_duration <minutes>` — Durée max pour valider (0 pour désactiver)  
🔹 `{prefix_used}set verification_log_channel <id|nom>` — Salon des logs de vérification  

**Rôle membre et permissions**  
🔹 `{prefix_used}set verified_role <id|nom>` — Rôle attribué après validation  
🔹 `{prefix_used}sync permissions` — Synchronise les permissions du serveur  

**Messages de bienvenue**  
🔹 `{prefix_used}set welcome_channel <id|nom>` — Salon des messages de bienvenue  
🔹 `{prefix_used}set welcome_message <texte>` — Message de bienvenue personnalisé  
🔹 `{prefix_used}set welcome_autodelete <secondes>` — Suppression auto du message (0 pour désactiver)  
🔹 `{prefix_used}set welcome_after_verification <on|off>` — Afficher message après validation  

**Messages privés (MP)**  
🔹 `{prefix_used}set welcome_dm <texte>` — Message privé aux nouveaux membres  
🔹 `{prefix_used}remove welcome_dm` — Supprime le message privé (irréversible)
""",
        color=discord.Color.dark_theme()
    )
    embed6.set_footer(text="Page 6/6")

    embeds = [embed1, embed2, embed3, embed4, embed5, embed6]

    view = HelpView(embeds, ctx.author)
    await ctx.send(embed=embed1, view=view)

# --- Lancement du bot ---
# Remplace 'TON_TOKEN_ICI' par ton token réel
bot.run('token de ton bot')
