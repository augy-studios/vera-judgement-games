import discord
from discord.ext import commands
import asyncio
import os
import time
import logging
from dotenv import load_dotenv

load_dotenv()
from utils.db import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("vera.log"),
    ]
)
log = logging.getLogger("vera")

TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN environment variable not set.")

COGS = [
    "cogs.admin",
    "cogs.caption_games",
    "cogs.writing_games",
    "cogs.judging_games",
    "cogs.leaderboard",
    "cogs.scheduler",
    "cogs.help",
    "cogs.botinfo",
]

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

async def _update_presence():
    guild_count = len(bot.guilds)
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name=f"{guild_count} guilds judge each other",
        )
    )

@bot.event
async def on_ready():
    bot.start_time = time.time()
    log.info(f"Logged in as {bot.user} ({bot.user.id})")
    await bot.tree.sync()
    log.info("Slash commands synced globally.")
    await _update_presence()

@bot.event
async def on_guild_join(guild):
    await _update_presence()

@bot.event
async def on_guild_remove(guild):
    await _update_presence()

async def main():
    await init_db()
    async with bot:
        for cog in COGS:
            try:
                await bot.load_extension(cog)
                log.info(f"Loaded cog: {cog}")
            except Exception as e:
                log.error(f"Failed to load cog {cog}: {e}")
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
