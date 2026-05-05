import platform
import socket
import time
import discord
from discord import app_commands
from discord.ext import commands
import psutil


class BotInfoCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._process = psutil.Process()

    @app_commands.command(name="botinfo", description="Show technical information about the bot.")
    async def botinfo(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)

        os_info = f"{platform.system()} {platform.release()}"
        hostname = socket.gethostname()
        arch = platform.machine()
        cpu_cores = psutil.cpu_count(logical=False) or psutil.cpu_count()
        cpu_usage = psutil.cpu_percent(interval=0.2)

        mem = psutil.virtual_memory()
        mem_used_mb = mem.used / (1024 ** 2)
        mem_total_gb = mem.total / (1024 ** 3)

        py_version = platform.python_version()
        dpy_version = discord.__version__

        guild_count = len(self.bot.guilds)
        channel_count = sum(len(g.channels) for g in self.bot.guilds)
        user_count = sum(g.member_count or 0 for g in self.bot.guilds)

        cmds = await self.bot.tree.fetch_commands()
        total_commands = len(cmds)

        start_time = getattr(self.bot, "start_time", None)
        if start_time:
            elapsed = int(time.time() - start_time)
            hours, rem = divmod(elapsed, 3600)
            minutes, seconds = divmod(rem, 60)
            uptime_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            uptime_str = "N/A"

        lines = [
            f"**Bot Information:**",
            f"",
            f"• **Operating System**: {os_info}",
            f"• **Uptime**: {uptime_str}",
            f"• **Hostname**: {hostname}",
            f"• **CPU Architecture**: {arch} ({cpu_cores} cores)",
            f"• **CPU Usage**: {cpu_usage:.0f}%",
            f"• **Memory Usage**: {mem_used_mb:.2f}MB / {mem_total_gb:.2f}GB",
            f"• **Python Version**: v{py_version}",
            f"• **discord.py Version**: {dpy_version}",
            f"• **Connected to** {guild_count} guilds, {channel_count} channels, and {user_count} users",
            f"• **Total Commands**: {total_commands}",
        ]

        await interaction.followup.send("\n".join(lines))


async def setup(bot: commands.Bot):
    await bot.add_cog(BotInfoCog(bot))
