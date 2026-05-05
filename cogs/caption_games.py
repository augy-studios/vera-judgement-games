import discord
from discord import app_commands
from discord.ext import commands
import json
import time

from utils.db import fetchone, fetchall, execute, lastrowid
from utils.games import (
    is_game_enabled, get_game_channel, get_active_round,
    get_active_submit_round, now_ts, ts_to_discord, ts_full,
    record_win, record_vote, GAME_NAMES
)


def enabled_check(game_key: str):
    async def predicate(interaction: discord.Interaction):
        if not await is_game_enabled(interaction.guild_id, game_key):
            await interaction.response.send_message(
                f"❌ **{GAME_NAMES[game_key]}** is not enabled in this server.", ephemeral=True
            )
            return False
        return True
    return predicate


class CaptionGames(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ─────────────────────────────────────────────
    # ROLLING CAPTION CONTEST
    # ─────────────────────────────────────────────
    caption_group = app_commands.Group(
        name="caption", description="Rolling Caption Contest — caption the image!"
    )

    @caption_group.command(name="start", description="[Mod] Start a new caption round with an image.")
    @app_commands.describe(image_url="Direct URL to the image for this round")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def caption_start(self, interaction: discord.Interaction, image_url: str):
        if not await is_game_enabled(interaction.guild_id, "rolling_caption"):
            return await interaction.response.send_message("❌ Game not enabled.", ephemeral=True)

        existing = await get_active_round(interaction.guild_id, "rolling_caption")
        if existing:
            return await interaction.response.send_message(
                "❌ A caption round is already active. Wait for it to close.", ephemeral=True
            )

        opens = now_ts()
        closes = opens + 48 * 3600
        vote_ends = closes + 24 * 3600

        ch = await get_game_channel(interaction.guild, "rolling_caption") or interaction.channel

        embed = discord.Embed(
            title="📸 Rolling Caption Contest",
            description=(
                f"**Caption this image!**\n\n"
                f"Use `/caption submit` to enter your caption.\n"
                f"Round closes {ts_to_discord(closes)} or at 20 submissions — whichever comes first.\n"
                f"Voting opens after submissions close."
            ),
            color=discord.Color.gold()
        )
        embed.set_image(url=image_url)
        embed.set_footer(text=f"Closes: {ts_full(closes)}")

        msg = await ch.send(embed=embed)

        round_id = await lastrowid(
            "INSERT INTO rounds (guild_id, game_key, image_url, phase, opens_at, closes_at, vote_ends_at, message_id, channel_id) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (interaction.guild_id, "rolling_caption", image_url, "submit", opens, closes, vote_ends, msg.id, ch.id)
        )
        await interaction.response.send_message(f"✅ Caption round started in {ch.mention}!", ephemeral=True)

    @caption_group.command(name="submit", description="Submit your caption for the current round.")
    @app_commands.describe(caption="Your caption for the image")
    async def caption_submit(self, interaction: discord.Interaction, caption: str):
        if not await is_game_enabled(interaction.guild_id, "rolling_caption"):
            return await interaction.response.send_message("❌ Game not enabled.", ephemeral=True)

        rnd = await get_active_submit_round(interaction.guild_id, "rolling_caption")
        if not rnd:
            return await interaction.response.send_message("❌ No active caption round right now.", ephemeral=True)
        if now_ts() > rnd["closes_at"]:
            return await interaction.response.send_message("❌ Submissions are closed.", ephemeral=True)

        existing_sub = await fetchone(
            "SELECT id FROM submissions WHERE round_id=? AND user_id=?",
            (rnd["id"], interaction.user.id)
        )
        if existing_sub:
            return await interaction.response.send_message("❌ You already submitted a caption.", ephemeral=True)

        sub_count = await fetchone("SELECT COUNT(*) as c FROM submissions WHERE round_id=?", (rnd["id"],))
        if sub_count["c"] >= 20:
            return await interaction.response.send_message("❌ Max submissions reached (20). Voting phase coming soon!", ephemeral=True)

        await execute(
            "INSERT INTO submissions (round_id, user_id, content, submitted_at) VALUES (?,?,?,?)",
            (rnd["id"], interaction.user.id, caption, now_ts())
        )

        count_now = sub_count["c"] + 1
        await interaction.response.send_message(
            f"✅ Caption submitted! ({count_now}/20)", ephemeral=True
        )

        # Auto-close at 20
        if count_now >= 20:
            await self._open_caption_voting(rnd)

    @caption_group.command(name="vote", description="Vote for your favourite caption.")
    async def caption_vote(self, interaction: discord.Interaction):
        if not await is_game_enabled(interaction.guild_id, "rolling_caption"):
            return await interaction.response.send_message("❌ Game not enabled.", ephemeral=True)

        rnd = await fetchone(
            "SELECT * FROM rounds WHERE guild_id=? AND game_key='rolling_caption' AND phase='vote' ORDER BY id DESC LIMIT 1",
            (interaction.guild_id,)
        )
        if not rnd:
            return await interaction.response.send_message("❌ No voting phase active right now.", ephemeral=True)
        if now_ts() > rnd["vote_ends_at"]:
            return await interaction.response.send_message("❌ Voting has ended.", ephemeral=True)

        existing = await fetchone(
            "SELECT id FROM votes WHERE round_id=? AND voter_id=?",
            (rnd["id"], interaction.user.id)
        )
        if existing:
            return await interaction.response.send_message("❌ You already voted.", ephemeral=True)

        subs = await fetchall(
            "SELECT id, user_id, content FROM submissions WHERE round_id=? ORDER BY id",
            (rnd["id"],)
        )
        if not subs:
            return await interaction.response.send_message("❌ No submissions to vote on.", ephemeral=True)

        options = [
            discord.SelectOption(
                label=f"#{i+1}: {sub['content'][:90]}",
                value=str(sub["id"]),
                description=f"By <@{sub['user_id']}>"
            )
            for i, sub in enumerate(subs)
        ]

        class VoteView(discord.ui.View):
            def __init__(self, cog):
                super().__init__(timeout=300)
                self.cog = cog

            @discord.ui.select(placeholder="Choose your favourite caption…", options=options)
            async def select_cb(self, i: discord.Interaction, select: discord.ui.Select):
                sub_id = int(select.values[0])
                sub = next((s for s in subs if s["id"] == sub_id), None)
                await execute(
                    "INSERT OR IGNORE INTO votes (round_id, voter_id, sub_id) VALUES (?,?,?)",
                    (rnd["id"], i.user.id, sub_id)
                )
                await record_vote(rnd["guild_id"], i.user.id)
                await i.response.send_message(
                    f"✅ Vote cast for caption #{subs.index(sub)+1}!", ephemeral=True
                )
                self.stop()

        await interaction.response.send_message(
            "**Vote for the best caption:**", view=VoteView(self), ephemeral=True
        )

    async def _open_caption_voting(self, rnd):
        await execute(
            "UPDATE rounds SET phase='vote' WHERE id=?", (rnd["id"],)
        )
        guild = self.bot.get_guild(rnd["guild_id"])
        if not guild:
            return
        ch = guild.get_channel(rnd["channel_id"])
        if ch:
            await ch.send(
                f"🗳️ **Caption submissions are closed!** Voting is now open for 24 hours. "
                f"Use `/caption vote` to pick your favourite! Closes {ts_to_discord(rnd['vote_ends_at'])}"
            )

    @caption_group.command(name="close", description="[Mod] Manually close voting and announce the winner.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def caption_close(self, interaction: discord.Interaction):
        rnd = await fetchone(
            "SELECT * FROM rounds WHERE guild_id=? AND game_key='rolling_caption' AND phase='vote' ORDER BY id DESC LIMIT 1",
            (interaction.guild_id,)
        )
        if not rnd:
            return await interaction.response.send_message("❌ No active voting round.", ephemeral=True)

        await self._close_caption_round(rnd)
        await interaction.response.send_message("✅ Round closed and winner announced.", ephemeral=True)

    async def _close_caption_round(self, rnd):
        # Count votes
        results = await fetchall(
            "SELECT sub_id, COUNT(*) as votes FROM votes WHERE round_id=? GROUP BY sub_id ORDER BY votes DESC",
            (rnd["id"],)
        )
        await execute("UPDATE rounds SET phase='ended' WHERE id=?", (rnd["id"],))

        guild = self.bot.get_guild(rnd["guild_id"])
        if not guild:
            return
        ch = guild.get_channel(rnd["channel_id"])
        if not ch:
            return

        if not results:
            await ch.send("📸 **Caption Contest ended** — no votes were cast. No winner this round!")
            return

        winner_sub_id = results[0]["sub_id"]
        winner_sub = await fetchone("SELECT * FROM submissions WHERE id=?", (winner_sub_id,))

        await record_win(rnd["guild_id"], winner_sub["user_id"], "rolling_caption")

        embed = discord.Embed(
            title="🏆 Caption Contest Results!",
            color=discord.Color.gold()
        )
        embed.set_image(url=rnd["image_url"])
        embed.add_field(
            name="🥇 Winner",
            value=f"<@{winner_sub['user_id']}>\n> {winner_sub['content']}",
            inline=False
        )
        if len(results) > 1:
            runners = []
            for r in results[1:3]:
                s = await fetchone("SELECT * FROM submissions WHERE id=?", (r["sub_id"],))
                runners.append(f"<@{s['user_id']}> — {s['content'][:60]}")
            embed.add_field(name="Runners Up", value="\n".join(runners), inline=False)

        await ch.send(embed=embed)

    # ─────────────────────────────────────────────
    # BLURB BATTLE
    # ─────────────────────────────────────────────
    blurb_group = app_commands.Group(
        name="blurb", description="Blurb Battle — write the fakest synopsis!"
    )

    @blurb_group.command(name="start", description="[Mod] Start a Blurb Battle round.")
    @app_commands.describe(title="The obscure book/movie/game title to blurb")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def blurb_start(self, interaction: discord.Interaction, title: str):
        if not await is_game_enabled(interaction.guild_id, "blurb_battle"):
            return await interaction.response.send_message("❌ Game not enabled.", ephemeral=True)
        if await get_active_round(interaction.guild_id, "blurb_battle"):
            return await interaction.response.send_message("❌ A Blurb Battle is already active.", ephemeral=True)

        opens = now_ts()
        closes = opens + 48 * 3600
        vote_ends = closes + 24 * 3600
        ch = await get_game_channel(interaction.guild, "blurb_battle") or interaction.channel

        embed = discord.Embed(
            title="📚 Blurb Battle",
            description=(
                f"**Title: *{title}***\n\n"
                f"Nobody's heard of it. Write the most convincing fake synopsis!\n"
                f"Use `/blurb submit` — submissions close {ts_to_discord(closes)}."
            ),
            color=discord.Color.teal()
        )
        msg = await ch.send(embed=embed)
        await lastrowid(
            "INSERT INTO rounds (guild_id, game_key, prompt, phase, opens_at, closes_at, vote_ends_at, message_id, channel_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (interaction.guild_id, "blurb_battle", title, "submit", opens, closes, vote_ends, msg.id, ch.id)
        )
        await interaction.response.send_message(f"✅ Blurb Battle started in {ch.mention}!", ephemeral=True)

    @blurb_group.command(name="submit", description="Submit your fake synopsis.")
    @app_commands.describe(synopsis="Your fake synopsis (be convincing!)")
    async def blurb_submit(self, interaction: discord.Interaction, synopsis: str):
        if not await is_game_enabled(interaction.guild_id, "blurb_battle"):
            return await interaction.response.send_message("❌ Game not enabled.", ephemeral=True)
        rnd = await get_active_submit_round(interaction.guild_id, "blurb_battle")
        if not rnd:
            return await interaction.response.send_message("❌ No active Blurb Battle round.", ephemeral=True)
        if now_ts() > rnd["closes_at"]:
            return await interaction.response.send_message("❌ Submissions are closed.", ephemeral=True)
        if await fetchone("SELECT id FROM submissions WHERE round_id=? AND user_id=?", (rnd["id"], interaction.user.id)):
            return await interaction.response.send_message("❌ You already submitted.", ephemeral=True)

        await execute(
            "INSERT INTO submissions (round_id, user_id, content, submitted_at) VALUES (?,?,?,?)",
            (rnd["id"], interaction.user.id, synopsis, now_ts())
        )
        await interaction.response.send_message("✅ Blurb submitted! Good luck being convincing.", ephemeral=True)

    @blurb_group.command(name="vote", description="Vote for the most convincing synopsis.")
    async def blurb_vote(self, interaction: discord.Interaction):
        await self._generic_vote(interaction, "blurb_battle", "synopsis")

    @blurb_group.command(name="close", description="[Mod] Close voting and reveal the winner.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def blurb_close(self, interaction: discord.Interaction):
        await self._generic_close(interaction, "blurb_battle", "📚 Blurb Battle Results!")

    # ─────────────────────────────────────────────
    # WRONG ANSWERS ONLY
    # ─────────────────────────────────────────────
    wrong_group = app_commands.Group(
        name="wrong", description="Wrong Answers Only — what is this image?"
    )

    @wrong_group.command(name="start", description="[Mod] Post a new image for Wrong Answers Only.")
    @app_commands.describe(image_url="URL of the mundane image")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def wrong_start(self, interaction: discord.Interaction, image_url: str):
        if not await is_game_enabled(interaction.guild_id, "wrong_answers"):
            return await interaction.response.send_message("❌ Game not enabled.", ephemeral=True)
        if await get_active_round(interaction.guild_id, "wrong_answers"):
            return await interaction.response.send_message("❌ A round is already active.", ephemeral=True)

        opens = now_ts()
        closes = opens + 48 * 3600
        ch = await get_game_channel(interaction.guild, "wrong_answers") or interaction.channel

        embed = discord.Embed(
            title="🤔 Wrong Answers Only",
            description=(
                "What is this image? Give us your **most absurd wrong answer!**\n"
                f"Use `/wrong submit` — most reacts wins! Closes {ts_to_discord(closes)}."
            ),
            color=discord.Color.orange()
        )
        embed.set_image(url=image_url)
        msg = await ch.send(embed=embed)
        await lastrowid(
            "INSERT INTO rounds (guild_id, game_key, image_url, phase, opens_at, closes_at, message_id, channel_id) VALUES (?,?,?,?,?,?,?,?)",
            (interaction.guild_id, "wrong_answers", image_url, "submit", opens, closes, msg.id, ch.id)
        )
        await interaction.response.send_message(f"✅ Wrong Answers Only started in {ch.mention}!", ephemeral=True)

    @wrong_group.command(name="submit", description="Submit your absurd wrong answer.")
    @app_commands.describe(answer="Your gloriously wrong identification")
    async def wrong_submit(self, interaction: discord.Interaction, answer: str):
        if not await is_game_enabled(interaction.guild_id, "wrong_answers"):
            return await interaction.response.send_message("❌ Game not enabled.", ephemeral=True)
        rnd = await get_active_submit_round(interaction.guild_id, "wrong_answers")
        if not rnd:
            return await interaction.response.send_message("❌ No active round.", ephemeral=True)
        if now_ts() > rnd["closes_at"]:
            return await interaction.response.send_message("❌ Round is closed.", ephemeral=True)
        if await fetchone("SELECT id FROM submissions WHERE round_id=? AND user_id=?", (rnd["id"], interaction.user.id)):
            return await interaction.response.send_message("❌ You already submitted.", ephemeral=True)

        ch = interaction.guild.get_channel(rnd["channel_id"]) or interaction.channel
        msg = await ch.send(f"❓ **{interaction.user.display_name}** says: *{answer}*")

        await execute(
            "INSERT INTO submissions (round_id, user_id, content, message_id, submitted_at) VALUES (?,?,?,?,?)",
            (rnd["id"], interaction.user.id, answer, msg.id, now_ts())
        )
        await interaction.response.send_message("✅ Wrong answer posted! React to vote for your favourites.", ephemeral=True)

    @wrong_group.command(name="close", description="[Mod] Close round and count reacts.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def wrong_close(self, interaction: discord.Interaction):
        await self._close_react_game(interaction, "wrong_answers", "🤔 Wrong Answers Only — Results!")

    # ─────────────────────────────────────────────
    # THUMBNAIL LIAR
    # ─────────────────────────────────────────────
    thumb_group = app_commands.Group(
        name="thumbnail", description="Thumbnail Liar — fake clickbait titles!"
    )

    @thumb_group.command(name="start", description="[Mod] Post a screenshot for Thumbnail Liar.")
    @app_commands.describe(image_url="URL of the screenshot")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def thumb_start(self, interaction: discord.Interaction, image_url: str):
        if not await is_game_enabled(interaction.guild_id, "thumbnail_liar"):
            return await interaction.response.send_message("❌ Game not enabled.", ephemeral=True)
        if await get_active_round(interaction.guild_id, "thumbnail_liar"):
            return await interaction.response.send_message("❌ A round is already active.", ephemeral=True)

        opens = now_ts()
        closes = opens + 48 * 3600
        ch = await get_game_channel(interaction.guild, "thumbnail_liar") or interaction.channel

        embed = discord.Embed(
            title="🎬 Thumbnail Liar",
            description=(
                "Give this screenshot the most clickbait fake title you can!\n"
                f"Use `/thumbnail submit` — most reacts wins! Closes {ts_to_discord(closes)}."
            ),
            color=discord.Color.red()
        )
        embed.set_image(url=image_url)
        msg = await ch.send(embed=embed)
        await lastrowid(
            "INSERT INTO rounds (guild_id, game_key, image_url, phase, opens_at, closes_at, message_id, channel_id) VALUES (?,?,?,?,?,?,?,?)",
            (interaction.guild_id, "thumbnail_liar", image_url, "submit", opens, closes, msg.id, ch.id)
        )
        await interaction.response.send_message(f"✅ Thumbnail Liar started in {ch.mention}!", ephemeral=True)

    @thumb_group.command(name="submit", description="Submit your fake clickbait title.")
    @app_commands.describe(title="Your fake thumbnail title")
    async def thumb_submit(self, interaction: discord.Interaction, title: str):
        if not await is_game_enabled(interaction.guild_id, "thumbnail_liar"):
            return await interaction.response.send_message("❌ Game not enabled.", ephemeral=True)
        rnd = await get_active_submit_round(interaction.guild_id, "thumbnail_liar")
        if not rnd:
            return await interaction.response.send_message("❌ No active round.", ephemeral=True)
        if now_ts() > rnd["closes_at"]:
            return await interaction.response.send_message("❌ Round is closed.", ephemeral=True)
        if await fetchone("SELECT id FROM submissions WHERE round_id=? AND user_id=?", (rnd["id"], interaction.user.id)):
            return await interaction.response.send_message("❌ You already submitted.", ephemeral=True)

        ch = interaction.guild.get_channel(rnd["channel_id"]) or interaction.channel
        msg = await ch.send(f"🎬 **{interaction.user.display_name}:** *{title}*")
        await execute(
            "INSERT INTO submissions (round_id, user_id, content, message_id, submitted_at) VALUES (?,?,?,?,?)",
            (rnd["id"], interaction.user.id, title, msg.id, now_ts())
        )
        await interaction.response.send_message("✅ Title submitted! React to vote for your favourites.", ephemeral=True)

    @thumb_group.command(name="close", description="[Mod] Close round and count reacts.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def thumb_close(self, interaction: discord.Interaction):
        await self._close_react_game(interaction, "thumbnail_liar", "🎬 Thumbnail Liar — Results!")

    # ─────────────────────────────────────────────
    # SHARED HELPERS
    # ─────────────────────────────────────────────
    async def _generic_vote(self, interaction: discord.Interaction, game_key: str, item_label: str):
        if not await is_game_enabled(interaction.guild_id, game_key):
            return await interaction.response.send_message("❌ Game not enabled.", ephemeral=True)
        rnd = await fetchone(
            "SELECT * FROM rounds WHERE guild_id=? AND game_key=? AND phase='vote' ORDER BY id DESC LIMIT 1",
            (interaction.guild_id, game_key)
        )
        if not rnd:
            return await interaction.response.send_message("❌ No voting round active.", ephemeral=True)
        if now_ts() > rnd["vote_ends_at"]:
            return await interaction.response.send_message("❌ Voting has ended.", ephemeral=True)
        if await fetchone("SELECT id FROM votes WHERE round_id=? AND voter_id=?", (rnd["id"], interaction.user.id)):
            return await interaction.response.send_message("❌ You already voted.", ephemeral=True)

        subs = await fetchall(
            "SELECT id, user_id, content FROM submissions WHERE round_id=? ORDER BY id",
            (rnd["id"],)
        )
        if not subs:
            return await interaction.response.send_message("❌ No submissions.", ephemeral=True)

        options = [
            discord.SelectOption(
                label=f"#{i+1}: {sub['content'][:90]}",
                value=str(sub["id"])
            ) for i, sub in enumerate(subs)
        ]

        class VoteView(discord.ui.View):
            def __init__(self, cog, subs, rnd):
                super().__init__(timeout=300)
                self.cog = cog
                self.subs = subs
                self.rnd = rnd

            @discord.ui.select(placeholder=f"Choose the best {item_label}…", options=options)
            async def cb(self, i: discord.Interaction, sel: discord.ui.Select):
                sub_id = int(sel.values[0])
                await execute(
                    "INSERT OR IGNORE INTO votes (round_id, voter_id, sub_id) VALUES (?,?,?)",
                    (self.rnd["id"], i.user.id, sub_id)
                )
                await record_vote(self.rnd["guild_id"], i.user.id)
                await i.response.send_message("✅ Vote cast!", ephemeral=True)
                self.stop()

        await interaction.response.send_message(
            f"**Vote for the best {item_label}:**", view=VoteView(self, subs, rnd), ephemeral=True
        )

    async def _generic_close(self, interaction: discord.Interaction, game_key: str, title: str):
        rnd = await fetchone(
            "SELECT * FROM rounds WHERE guild_id=? AND game_key=? AND phase='vote' ORDER BY id DESC LIMIT 1",
            (interaction.guild_id, game_key)
        )
        if not rnd:
            # Try closing a submit round
            rnd = await get_active_submit_round(interaction.guild_id, game_key)
            if rnd:
                await execute("UPDATE rounds SET phase='vote' WHERE id=?", (rnd["id"],))
                return await interaction.response.send_message("✅ Submissions closed. Voting opened.", ephemeral=True)
            return await interaction.response.send_message("❌ No active round found.", ephemeral=True)

        results = await fetchall(
            "SELECT sub_id, COUNT(*) as votes FROM votes WHERE round_id=? GROUP BY sub_id ORDER BY votes DESC",
            (rnd["id"],)
        )
        await execute("UPDATE rounds SET phase='ended' WHERE id=?", (rnd["id"],))
        ch = interaction.guild.get_channel(rnd["channel_id"]) or interaction.channel

        if not results:
            await ch.send(f"**{title}**\nNo votes cast. No winner this round!")
            return await interaction.response.send_message("✅ Round closed.", ephemeral=True)

        winner = await fetchone("SELECT * FROM submissions WHERE id=?", (results[0]["sub_id"],))
        await record_win(rnd["guild_id"], winner["user_id"], game_key)

        embed = discord.Embed(title=f"🏆 {title}", color=discord.Color.gold())
        embed.add_field(name="🥇 Winner", value=f"<@{winner['user_id']}>\n> {winner['content']}", inline=False)
        await ch.send(embed=embed)
        await interaction.response.send_message("✅ Round closed and winner announced.", ephemeral=True)

    async def _close_react_game(self, interaction: discord.Interaction, game_key: str, title: str):
        rnd = await get_active_submit_round(interaction.guild_id, game_key)
        if not rnd:
            rnd = await fetchone(
                "SELECT * FROM rounds WHERE guild_id=? AND game_key=? AND phase NOT IN ('ended') ORDER BY id DESC LIMIT 1",
                (interaction.guild_id, game_key)
            )
        if not rnd:
            return await interaction.response.send_message("❌ No active round found.", ephemeral=True)

        subs = await fetchall("SELECT * FROM submissions WHERE round_id=?", (rnd["id"],))
        ch = interaction.guild.get_channel(rnd["channel_id"]) or interaction.channel

        # Fetch react counts from Discord
        best = None
        best_count = -1
        for sub in subs:
            if sub["message_id"]:
                try:
                    msg = await ch.fetch_message(sub["message_id"])
                    react_count = sum(r.count for r in msg.reactions if str(r.emoji) not in ["❌"])
                    await execute("UPDATE submissions SET react_count=? WHERE id=?", (react_count, sub["id"]))
                    if react_count > best_count:
                        best_count = react_count
                        best = sub
                except Exception:
                    pass

        await execute("UPDATE rounds SET phase='ended' WHERE id=?", (rnd["id"],))

        if not best:
            await ch.send(f"**{title}**\nNo reactions counted. No winner!")
            return await interaction.response.send_message("✅ Round closed.", ephemeral=True)

        await record_win(rnd["guild_id"], best["user_id"], game_key)
        embed = discord.Embed(title=f"🏆 {title}", color=discord.Color.gold())
        embed.add_field(
            name=f"🥇 Winner ({best_count} reacts)",
            value=f"<@{best['user_id']}>\n> {best['content']}",
            inline=False
        )
        if rnd.get("image_url"):
            embed.set_image(url=rnd["image_url"])
        await ch.send(embed=embed)
        await interaction.response.send_message("✅ Round closed and winner announced.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(CaptionGames(bot))
