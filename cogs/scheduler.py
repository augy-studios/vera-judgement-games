"""
Scheduler cog.
Polls the SQLite `scheduler` table every 60 seconds for due jobs.
Jobs are inserted by game cogs (or externally) and processed here.

Supported job_types:
  - close_submit:<round_id>  → moves a round from submit → vote phase
  - close_vote:<round_id>    → calls the game-specific close handler
  - close_vibe:<round_id>
  - close_canon:<round_id>
  - close_tribunal:<round_id>
"""
import asyncio
import json
import logging

import discord
from discord.ext import commands, tasks

from utils.db import fetchall, execute, fetchone
from utils.games import now_ts, ts_to_discord

log = logging.getLogger("vera.scheduler")


class Scheduler(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.poll_jobs.start()

    def cog_unload(self):
        self.poll_jobs.cancel()

    @tasks.loop(seconds=60)
    async def poll_jobs(self):
        due = await fetchall(
            "SELECT * FROM scheduler WHERE done=0 AND run_at <= ? ORDER BY run_at",
            (now_ts(),)
        )
        for job in due:
            try:
                await self._dispatch(job)
            except Exception as e:
                log.error(f"Scheduler job {job['id']} ({job['job_type']}) failed: {e}")
            await execute("UPDATE scheduler SET done=1 WHERE id=?", (job["id"],))

    @poll_jobs.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()

    async def _dispatch(self, job):
        jtype = job["job_type"]
        payload = json.loads(job["payload"])
        round_id = payload.get("round_id")

        if not round_id:
            return

        rnd = await fetchone("SELECT * FROM rounds WHERE id=?", (round_id,))
        if not rnd or rnd["phase"] == "ended":
            return

        guild = self.bot.get_guild(rnd["guild_id"])
        if not guild:
            return

        ch = guild.get_channel(rnd["channel_id"])

        if jtype == "close_submit":
            # Move to vote phase and announce
            vote_ends = rnd["vote_ends_at"] or (now_ts() + 24 * 3600)
            await execute(
                "UPDATE rounds SET phase='vote', vote_ends_at=? WHERE id=?",
                (vote_ends, round_id)
            )
            game_name = rnd["game_key"].replace("_", " ").title()
            if ch:
                await ch.send(
                    f"🗳️ **{game_name}** — submissions are closed! Voting is now open until {ts_to_discord(vote_ends)}. "
                    f"Use the `/vote` command for this game to cast your pick!"
                )
            # Schedule vote close
            await _queue_job("close_vote", round_id, vote_ends)

        elif jtype == "close_vote":
            game_key = rnd["game_key"]
            if game_key in ("hot_take",):
                cog = self.bot.get_cog("JudgingGames")
                if cog:
                    await cog._deliver_verdict(rnd)
            elif game_key == "vibe_court":
                cog = self.bot.get_cog("JudgingGames")
                if cog:
                    await cog._close_vibe(rnd)
            elif game_key == "canon_cringe":
                cog = self.bot.get_cog("JudgingGames")
                if cog:
                    await cog._close_canon(rnd)
            elif game_key == "rolling_caption":
                cog = self.bot.get_cog("CaptionGames")
                if cog:
                    await cog._close_caption_round(rnd)
            else:
                # Generic vote close for all writing/caption games
                await _generic_close_vote(self.bot, rnd)

        log.info(f"Processed job {job['id']}: {jtype} for round {round_id}")


async def _queue_job(job_type: str, round_id: int, run_at: float):
    payload = json.dumps({"round_id": round_id})
    await execute(
        "INSERT INTO scheduler (job_type, run_at, payload, done) VALUES (?,?,?,0)",
        (job_type, run_at, payload)
    )


async def _generic_close_vote(bot, rnd):
    """Generic vote close — finds winner by vote count and announces."""
    from utils.db import fetchall as fa, execute as ex
    from utils.games import record_win, GAME_NAMES

    results = await fa(
        "SELECT sub_id, COUNT(*) as votes FROM votes WHERE round_id=? GROUP BY sub_id ORDER BY votes DESC",
        (rnd["id"],)
    )
    await ex("UPDATE rounds SET phase='ended' WHERE id=?", (rnd["id"],))

    guild = bot.get_guild(rnd["guild_id"])
    if not guild:
        return
    ch = guild.get_channel(rnd["channel_id"])
    if not ch:
        return

    game_name = GAME_NAMES.get(rnd["game_key"], rnd["game_key"])

    if not results:
        await ch.send(f"**{game_name}** — voting closed. No votes were cast. No winner this round!")
        return

    from utils.db import fetchone as fo
    winner_sub = await fo("SELECT * FROM submissions WHERE id=?", (results[0]["sub_id"],))
    if not winner_sub:
        return

    await record_win(rnd["guild_id"], winner_sub["user_id"], rnd["game_key"])

    embed = discord.Embed(
        title=f"🏆 {game_name} — Results!",
        color=discord.Color.gold()
    )
    embed.add_field(
        name="🥇 Winner",
        value=f"<@{winner_sub['user_id']}>\n> {winner_sub['content']}",
        inline=False
    )
    if rnd.get("image_url"):
        embed.set_image(url=rnd["image_url"])
    await ch.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Scheduler(bot))
