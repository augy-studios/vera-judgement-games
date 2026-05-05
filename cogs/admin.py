import discord
from discord import app_commands
from discord.ext import commands
from utils.db import fetchone, execute, fetchall
from utils.games import ALL_GAMES, GAME_NAMES


def is_admin():
    async def predicate(interaction: discord.Interaction):
        return interaction.user.guild_permissions.administrator
    return app_commands.check(predicate)


class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    admin_group = app_commands.Group(name="games", description="Manage games for this server.")

    @admin_group.command(name="enable", description="Enable a game in this server.")
    @app_commands.describe(game="The game to enable")
    @app_commands.choices(game=[app_commands.Choice(name=GAME_NAMES[k], value=k) for k in ALL_GAMES])
    @is_admin()
    async def enable_game(self, interaction: discord.Interaction, game: str):
        await execute(
            "INSERT INTO guild_settings (guild_id, game_key, enabled) VALUES (?,?,1) "
            "ON CONFLICT(guild_id, game_key) DO UPDATE SET enabled=1",
            (interaction.guild_id, game)
        )
        await interaction.response.send_message(
            f"✅ **{GAME_NAMES[game]}** has been **enabled** in this server.", ephemeral=True
        )

    @admin_group.command(name="disable", description="Disable a game in this server.")
    @app_commands.describe(game="The game to disable")
    @app_commands.choices(game=[app_commands.Choice(name=GAME_NAMES[k], value=k) for k in ALL_GAMES])
    @is_admin()
    async def disable_game(self, interaction: discord.Interaction, game: str):
        await execute(
            "INSERT INTO guild_settings (guild_id, game_key, enabled) VALUES (?,?,0) "
            "ON CONFLICT(guild_id, game_key) DO UPDATE SET enabled=0",
            (interaction.guild_id, game)
        )
        await interaction.response.send_message(
            f"🚫 **{GAME_NAMES[game]}** has been **disabled** in this server.", ephemeral=True
        )

    @admin_group.command(name="setchannel", description="Set a dedicated channel for a game.")
    @app_commands.describe(game="The game", channel="The channel to use")
    @app_commands.choices(game=[app_commands.Choice(name=GAME_NAMES[k], value=k) for k in ALL_GAMES])
    @is_admin()
    async def set_channel(self, interaction: discord.Interaction, game: str, channel: discord.TextChannel):
        await execute(
            "INSERT INTO guild_settings (guild_id, game_key, enabled, channel_id) VALUES (?,?,1,?) "
            "ON CONFLICT(guild_id, game_key) DO UPDATE SET channel_id=?",
            (interaction.guild_id, game, channel.id, channel.id)
        )
        await interaction.response.send_message(
            f"📌 **{GAME_NAMES[game]}** will now post in {channel.mention}.", ephemeral=True
        )

    @admin_group.command(name="clearchannel", description="Remove the dedicated channel for a game (uses current channel).")
    @app_commands.describe(game="The game")
    @app_commands.choices(game=[app_commands.Choice(name=GAME_NAMES[k], value=k) for k in ALL_GAMES])
    @is_admin()
    async def clear_channel(self, interaction: discord.Interaction, game: str):
        await execute(
            "UPDATE guild_settings SET channel_id=NULL WHERE guild_id=? AND game_key=?",
            (interaction.guild_id, game)
        )
        await interaction.response.send_message(
            f"🗑️ Cleared dedicated channel for **{GAME_NAMES[game]}**.", ephemeral=True
        )

    @admin_group.command(name="list", description="Show the status of all games in this server.")
    @is_admin()
    async def list_games(self, interaction: discord.Interaction):
        rows = await fetchall(
            "SELECT game_key, enabled, channel_id FROM guild_settings WHERE guild_id=?",
            (interaction.guild_id,)
        )
        settings = {r["game_key"]: r for r in rows}

        lines = []
        for key in ALL_GAMES:
            row = settings.get(key)
            enabled = row["enabled"] if row else 1
            ch_id = row["channel_id"] if row else None
            status = "✅" if enabled else "🚫"
            ch_str = f" → <#{ch_id}>" if ch_id else ""
            lines.append(f"{status} **{GAME_NAMES[key]}**{ch_str}")

        embed = discord.Embed(
            title="Game Settings",
            description="\n".join(lines),
            color=discord.Color.blurple()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # Error handler for permission checks
    async def cog_app_command_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.CheckFailure):
            await interaction.response.send_message(
                "❌ You need **Administrator** permission to use this command.", ephemeral=True
            )
        else:
            raise error


async def setup(bot):
    await bot.add_cog(AdminCog(bot))
