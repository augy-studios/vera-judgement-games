import discord
from discord import app_commands
from discord.ext import commands
import time

from utils.db import fetchall, fetchone
from utils.games import is_game_enabled, GAME_NAMES, ALL_GAMES, now_ts


BOARD_DESCRIPTIONS = {
    "weekly":   ("🗓️ Weekly Board", "Rolling 7-day window — resets individually per member."),
    "monthly":  ("📅 Monthly Board", "Rolling 30-day window — consistent performers shine here."),
    "alltime":  ("🏛️ All-Time Legacy Board", "Never resets. The eternal server hierarchy."),
    "streak":   ("🔥 Streak Board", "Current and all-time personal records, side by side."),
    "voter":    ("🗳️ Voter Board", "The most engaged judges — not winners, but essential."),
    "underdog": ("🐣 Underdog Board", "Wins by bottom-half members only. Always visible."),
}


class Leaderboard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    lb_group = app_commands.Group(name="leaderboard", description="View server leaderboards.")

    @lb_group.command(name="weekly", description="Top players in the last 7 days.")
    @app_commands.describe(game="Filter by a specific game (optional)")
    @app_commands.choices(game=[app_commands.Choice(name=GAME_NAMES[k], value=k) for k in ALL_GAMES])
    async def weekly(self, interaction: discord.Interaction, game: str = None):
        since = now_ts() - 7 * 86400
        await self._send_board(interaction, "weekly", since, game)

    @lb_group.command(name="monthly", description="Top players in the last 30 days.")
    @app_commands.describe(game="Filter by a specific game (optional)")
    @app_commands.choices(game=[app_commands.Choice(name=GAME_NAMES[k], value=k) for k in ALL_GAMES])
    async def monthly(self, interaction: discord.Interaction, game: str = None):
        since = now_ts() - 30 * 86400
        await self._send_board(interaction, "monthly", since, game)

    @lb_group.command(name="alltime", description="The all-time legacy board — never resets.")
    @app_commands.describe(game="Filter by a specific game (optional)")
    @app_commands.choices(game=[app_commands.Choice(name=GAME_NAMES[k], value=k) for k in ALL_GAMES])
    async def alltime(self, interaction: discord.Interaction, game: str = None):
        await self._send_board(interaction, "alltime", 0, game)

    @lb_group.command(name="streak", description="Current and all-time win streaks.")
    async def streak(self, interaction: discord.Interaction):
        await interaction.response.defer()

        # Get all wins ordered by user and time for streak calculation
        wins = await fetchall(
            "SELECT user_id, game_key, earned_at FROM points WHERE guild_id=? AND wins > 0 ORDER BY user_id, earned_at",
            (interaction.guild_id,)
        )

        # Calculate streaks per user (a win within 7 days of the previous counts as a streak)
        streaks = {}
        for w in wins:
            uid = w["user_id"]
            if uid not in streaks:
                streaks[uid] = {"current": 0, "best": 0, "_last": None}
            last = streaks[uid]["_last"]
            if last is None or (w["earned_at"] - last) <= 7 * 86400:
                streaks[uid]["current"] += 1
            else:
                streaks[uid]["current"] = 1
            streaks[uid]["best"] = max(streaks[uid]["best"], streaks[uid]["current"])
            streaks[uid]["_last"] = w["earned_at"]

        if not streaks:
            return await interaction.followup.send("No streak data yet — start winning!", ephemeral=False)

        sorted_by_current = sorted(streaks.items(), key=lambda x: x[1]["current"], reverse=True)[:10]

        title, desc = BOARD_DESCRIPTIONS["streak"]
        embed = discord.Embed(title=title, description=desc, color=discord.Color.orange())

        lines = []
        for i, (uid, data) in enumerate(sorted_by_current):
            medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"**{i+1}.**"
            lines.append(
                f"{medal} <@{uid}> — 🔥 Current: **{data['current']}** | 🏆 Best: **{data['best']}**"
            )

        embed.add_field(name="Top Streaks", value="\n".join(lines) or "No data.", inline=False)
        embed.set_footer(text="Streak = wins within 7 days of each other")
        await interaction.followup.send(embed=embed)

    @lb_group.command(name="voter", description="The most engaged judges on this server.")
    async def voter(self, interaction: discord.Interaction):
        await interaction.response.defer()

        since = now_ts() - 30 * 86400
        rows = await fetchall(
            "SELECT user_id, COUNT(*) as votes FROM voter_log WHERE guild_id=? AND voted_at > ? GROUP BY user_id ORDER BY votes DESC LIMIT 10",
            (interaction.guild_id, since)
        )

        title, desc = BOARD_DESCRIPTIONS["voter"]
        embed = discord.Embed(title=title, description=f"{desc}\n*(Last 30 days)*", color=discord.Color.blurple())

        if not rows:
            embed.description += "\n\nNo voting activity yet."
        else:
            lines = []
            for i, r in enumerate(rows):
                medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"**{i+1}.**"
                lines.append(f"{medal} <@{r['user_id']}> — **{r['votes']}** votes cast")
            embed.add_field(name="Top Voters", value="\n".join(lines), inline=False)

        await interaction.followup.send(embed=embed)

    @lb_group.command(name="underdog", description="Wins by bottom-half members only.")
    async def underdog(self, interaction: discord.Interaction):
        await interaction.response.defer()

        # Get all-time win counts
        all_wins = await fetchall(
            "SELECT user_id, SUM(wins) as total FROM points WHERE guild_id=? GROUP BY user_id ORDER BY total DESC",
            (interaction.guild_id,)
        )
        if not all_wins:
            return await interaction.followup.send("No win data yet.")

        total_players = len(all_wins)
        cutoff = total_players // 2
        bottom_half_ids = {r["user_id"] for r in all_wins[cutoff:]}

        underdogs = [r for r in all_wins if r["user_id"] in bottom_half_ids]
        underdogs.sort(key=lambda x: x["total"], reverse=True)
        underdogs = underdogs[:10]

        title, desc = BOARD_DESCRIPTIONS["underdog"]
        embed = discord.Embed(title=title, description=desc, color=discord.Color.green())

        if not underdogs:
            embed.add_field(name="No underdog data yet.", value="Keep playing!", inline=False)
        else:
            lines = []
            for i, r in enumerate(underdogs):
                medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"**{i+1}.**"
                lines.append(f"{medal} <@{r['user_id']}> — **{r['total']}** win(s)")
            embed.add_field(name="Underdog Champions", value="\n".join(lines), inline=False)

        embed.set_footer(text=f"Bottom half of {total_players} players tracked")
        await interaction.followup.send(embed=embed)

    @lb_group.command(name="me", description="View your own stats and rankings.")
    async def me(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid = interaction.user.id
        gid = interaction.guild_id

        total_wins = await fetchone(
            "SELECT SUM(wins) as w, SUM(points) as p FROM points WHERE guild_id=? AND user_id=?",
            (gid, uid)
        )
        votes_cast = await fetchone(
            "SELECT COUNT(*) as c FROM voter_log WHERE guild_id=? AND user_id=?",
            (gid, uid)
        )
        by_game = await fetchall(
            "SELECT game_key, SUM(wins) as w FROM points WHERE guild_id=? AND user_id=? GROUP BY game_key ORDER BY w DESC",
            (gid, uid)
        )
        # Weekly rank
        since_week = now_ts() - 7 * 86400
        weekly_rank = await fetchall(
            "SELECT user_id, SUM(points) as p FROM points WHERE guild_id=? AND earned_at > ? GROUP BY user_id ORDER BY p DESC",
            (gid, since_week)
        )
        rank_w = next((i+1 for i, r in enumerate(weekly_rank) if r["user_id"] == uid), None)

        embed = discord.Embed(
            title=f"📊 Stats for {interaction.user.display_name}",
            color=discord.Color.blurple()
        )
        embed.add_field(name="🏆 Total Wins", value=str(total_wins["w"] or 0), inline=True)
        embed.add_field(name="⭐ Total Points", value=str(total_wins["p"] or 0), inline=True)
        embed.add_field(name="🗳️ Votes Cast", value=str(votes_cast["c"] or 0), inline=True)
        if rank_w:
            embed.add_field(name="🗓️ Weekly Rank", value=f"#{rank_w}", inline=True)

        if by_game:
            game_lines = "\n".join(
                f"• {GAME_NAMES.get(r['game_key'], r['game_key'])}: **{r['w']}** win(s)"
                for r in by_game[:5]
            )
            embed.add_field(name="Top Games", value=game_lines, inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ─────────────────────────────────────────────
    # SHARED BOARD HELPER
    # ─────────────────────────────────────────────
    async def _send_board(self, interaction: discord.Interaction, board_type: str, since: float, game: str = None):
        await interaction.response.defer()

        if game:
            rows = await fetchall(
                "SELECT user_id, SUM(points) as p, SUM(wins) as w FROM points "
                "WHERE guild_id=? AND game_key=? AND earned_at > ? GROUP BY user_id ORDER BY p DESC LIMIT 10",
                (interaction.guild_id, game, since)
            )
        else:
            rows = await fetchall(
                "SELECT user_id, SUM(points) as p, SUM(wins) as w FROM points "
                "WHERE guild_id=? AND earned_at > ? GROUP BY user_id ORDER BY p DESC LIMIT 10",
                (interaction.guild_id, since)
            )

        title, desc = BOARD_DESCRIPTIONS[board_type]
        if game:
            title += f" — {GAME_NAMES.get(game, game)}"

        embed = discord.Embed(title=title, description=desc, color=discord.Color.gold())

        if not rows:
            embed.add_field(name="No data yet.", value="Play some games to get on the board!", inline=False)
        else:
            lines = []
            for i, r in enumerate(rows):
                medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"**{i+1}.**"
                lines.append(f"{medal} <@{r['user_id']}> — **{r['p']}** pts, **{r['w']}** win(s)")
            embed.add_field(name="Rankings", value="\n".join(lines), inline=False)

        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Leaderboard(bot))
