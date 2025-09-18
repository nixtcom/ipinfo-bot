import asyncio
import logging
import os
from pathlib import Path

import aiohttp
import discord
import yaml
from discord.ext import commands

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("ipinfo-bot")


BASE_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = BASE_DIR / "data" / "settings" / "config.yml"

config = {}
if SETTINGS_PATH.exists():
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning("Failed to parse config.yml: %s", e)
else:
    logger.info("Config file not found at %s — will fall back to environment variables", SETTINGS_PATH)

bot_token = (
    config.get("BOT_CONFIG", {}).get("TOKEN")
    or os.getenv("BOT_TOKEN")
    or os.getenv("DISCORD_TOKEN")
)
prefix = (
    config.get("BOT_CONFIG", {}).get("PREFIX")
    or os.getenv("BOT_PREFIX")
    or "!"
)
ipinfo_token = (
    config.get("BOT_CONFIG", {}).get("IPINFO_TOKEN")
    or os.getenv("IPINFO_TOKEN")
    or os.getenv("IPINFO_IO_TOKEN")
)

if not bot_token:
    logger.error("No Discord bot token found. Set it in data/settings/config.yml or in BOT_TOKEN env var.")
    raise SystemExit(1)

if not ipinfo_token:
    logger.warning("No ipinfo.io token provided. Some endpoints may be rate-limited or restricted.")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=prefix, intents=intents, help_command=None)


async def fetch_ipinfo(session: aiohttp.ClientSession, ip_or_host: str) -> dict:
    """Fetch JSON from ipinfo.io for the provided IP or hostname."""
    base_url = f"https://ipinfo.io/{ip_or_host}/json"
    params = {}
    if ipinfo_token:
        params["token"] = ipinfo_token

    timeout = aiohttp.ClientTimeout(total=10)
    async with session.get(base_url, params=params, timeout=timeout) as resp:
        text = await resp.text()
        if resp.status != 200:
            raise ValueError(f"ipinfo returned status {resp.status}: {text}")
        data = await resp.json()
        return data


def make_embed_from_data(ip_or_host: str, data: dict) -> discord.Embed:
    title = f"IP info — {ip_or_host}"
    embed = discord.Embed(title=title, color=discord.Color.blurple())

    fields = [
        ("IP", data.get("ip")),
        ("Hostname", data.get("hostname")),
        ("City", data.get("city")),
        ("Region", data.get("region")),
        ("Country", data.get("country")),
        ("Location (lat,long)", data.get("loc")),
        ("Organization", data.get("org")),
        ("Postal", data.get("postal")),
        ("Timezone", data.get("timezone")),
    ]

    for name, val in fields:
        if val:
            embed.add_field(name=name, value=str(val), inline=True)

    loc = data.get("loc")
    if loc:
        try:
            lat, lon = loc.split(",")
            map_link = f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=8/{lat}/{lon}"
            google = f"https://www.google.com/maps?q={lat},{lon}"
            embed.add_field(name="Map", value=f"[OpenStreetMap]({map_link}) | [Google Maps]({google})", inline=False)
        except Exception:
            pass

    import json

    pretty = json.dumps(data, indent=2, ensure_ascii=False)
    if len(pretty) < 1024:
        embed.add_field(name="Raw JSON", value=f"```json\n{pretty}\n```", inline=False)

    embed.set_footer(text="Data provided by ipinfo.io")
    return embed

@bot.command(name="help")
async def help_cmd(ctx: commands.Context):
    help_text = (
        f"`{prefix}ipinfo <ip_or_hostname>` — Busca información pública de una IP/host en ipinfo.io\n"
        "Ejemplo: `!ipinfo 8.8.8.8` o `!ipinfo example.com`"
    )
    await ctx.send(help_text)


@bot.command(name="ipinfo")
@commands.cooldown(1, 3, commands.BucketType.user)
async def ipinfo_cmd(ctx: commands.Context, target: str):
    """Obtener información de IP/hostname desde ipinfo.io"""
    await ctx.trigger_typing()

    if not target:
        await ctx.send("Debes indicar una IP o hostname. Ejemplo: `!ipinfo 8.8.8.8`")
        return

    async with aiohttp.ClientSession() as session:
        try:
            data = await fetch_ipinfo(session, target)
        except aiohttp.ClientError as e:
            logger.exception("Network error fetching ipinfo")
            await ctx.send(f"Error de red al consultar ipinfo: {e}")
            return
        except ValueError as e:
            await ctx.send(f"Error al obtener datos: {e}")
            return
        except Exception as e:
            logger.exception("Unexpected error")
            await ctx.send(f"Error inesperado: {e}")
            return

    if data.get("bogon"):
        await ctx.send("La IP consultada es un bogon/reservada y no tiene información pública.")
        return
    if data.get("error"):
        await ctx.send(f"ipinfo error: {data.get('error')}")
        return

    embed = make_embed_from_data(target, data)
    if len(embed) > 6000:  # safety
        embed = make_embed_from_data(target, {k: data[k] for k in data if k != "raw"})

    await ctx.send(embed=embed)

@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (id: {bot.user.id})")
    logger.info("Bot is ready.")

def main():
    try:
        bot.run(bot_token)
    except KeyboardInterrupt:
        logger.info("Shutting down.")


if __name__ == "__main__":
    main()
