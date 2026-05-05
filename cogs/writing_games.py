import discord
from discord import app_commands
from discord.ext import commands
import time

from utils.db import fetchone, fetchall, execute, lastrowid
from utils.games import (
    is_game_enabled, get_game_channel, get_active_round,
    get_active_submit_round, now_ts, ts_to_discord, ts_full,
    record_win, record_vote, GAME_NAMES,
    validate_haiku, validate_one_sentence
)


class WritingGames(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ─────────────────────────────────────────────
    # PUN CHAMPIONSHIP
    # ─────────────────────────────────────────────
    pun_group = app_commands.Group(name="pun", description="Pun Championship — weekly pun battles.")

    @pun_group.command(name="start", description="[Mod] Start a Pun Championship round.")
    @app_commands.describe(theme="The pun theme for this week")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def pun_start(self, interaction: discord.Interaction, theme: str):
        if not await is_game_enabled(interaction.guild_id, "pun_championship"):
            return await interaction.response.send_message("❌ Game not enabled.", ephemeral=True)
        if await get_active_round(interaction.guild_id, "pun_championship"):
            return await interaction.response.send_message("❌ A round is already active.", ephemeral=True)

        opens = now_ts()
        closes = opens + 5 * 24 * 3600
        vote_ends = closes + 48 * 3600
        ch = await get_game_channel(interaction.guild, "pun_championship") or interaction.channel

        embed = discord.Embed(
            title="🎭 Pun Championship",
            description=(
                f"**This week's theme: *{theme}***\n\n"
                f"Submit your best (worst?) pun on this theme!\n"
                f"One pun per person. Use `/pun submit`.\n"
                f"Submissions close {ts_to_discord(closes)}. Voting runs for 48 hours after."
            ),
            color=discord.Color.purple()
        )
        msg = await ch.send(embed=embed)
        await lastrowid(
            "INSERT INTO rounds (guild_id, game_key, prompt, phase, opens_at, closes_at, vote_ends_at, message_id, channel_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (interaction.guild_id, "pun_championship", theme, "submit", opens, closes, vote_ends, msg.id, ch.id)
        )
        await interaction.response.send_message(f"✅ Pun Championship started in {ch.mention}!", ephemeral=True)

    @pun_group.command(name="submit", description="Submit your pun for this week's theme.")
    @app_commands.describe(pun="Your pun (one per person!)")
    async def pun_submit(self, interaction: discord.Interaction, pun: str):
        if not await is_game_enabled(interaction.guild_id, "pun_championship"):
            return await interaction.response.send_message("❌ Game not enabled.", ephemeral=True)
        rnd = await get_active_submit_round(interaction.guild_id, "pun_championship")
        if not rnd:
            return await interaction.response.send_message("❌ No active round.", ephemeral=True)
        if now_ts() > rnd["closes_at"]:
            return await interaction.response.send_message("❌ Submissions closed.", ephemeral=True)
        if await fetchone("SELECT id FROM submissions WHERE round_id=? AND user_id=?", (rnd["id"], interaction.user.id)):
            return await interaction.response.send_message("❌ One pun per person!", ephemeral=True)

        await execute(
            "INSERT INTO submissions (round_id, user_id, content, submitted_at) VALUES (?,?,?,?)",
            (rnd["id"], interaction.user.id, pun, now_ts())
        )
        await interaction.response.send_message("✅ Pun submitted. Groan-worthy? Only the voters will decide.", ephemeral=True)

    @pun_group.command(name="vote", description="Vote for your favourite pun.")
    async def pun_vote(self, interaction: discord.Interaction):
        await self._generic_vote(interaction, "pun_championship", "pun")

    @pun_group.command(name="close", description="[Mod] Close voting and crown the Pun Champion.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def pun_close(self, interaction: discord.Interaction):
        await self._generic_close(interaction, "pun_championship", "🎭 Pun Championship Results!")

    # ─────────────────────────────────────────────
    # ONE-LINER TOURNEY
    # ─────────────────────────────────────────────
    oneliner_group = app_commands.Group(name="oneliner", description="One-liner Tourney — one sentence, max impact.")

    @oneliner_group.command(name="start", description="[Mod] Start a One-liner Tourney.")
    @app_commands.describe(theme="The theme for one-liners")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def oneliner_start(self, interaction: discord.Interaction, theme: str):
        if not await is_game_enabled(interaction.guild_id, "oneliner_tourney"):
            return await interaction.response.send_message("❌ Game not enabled.", ephemeral=True)
        if await get_active_round(interaction.guild_id, "oneliner_tourney"):
            return await interaction.response.send_message("❌ A round is already active.", ephemeral=True)

        opens = now_ts()
        closes = opens + 5 * 24 * 3600
        vote_ends = closes + 48 * 3600
        ch = await get_game_channel(interaction.guild, "oneliner_tourney") or interaction.channel

        embed = discord.Embed(
            title="💬 One-liner Tourney",
            description=(
                f"**Theme: *{theme}***\n\n"
                f"One sentence. Maximum impact. Multi-line submissions are **auto-rejected**.\n"
                f"Use `/oneliner submit` — closes {ts_to_discord(closes)}."
            ),
            color=discord.Color.blue()
        )
        msg = await ch.send(embed=embed)
        await lastrowid(
            "INSERT INTO rounds (guild_id, game_key, prompt, phase, opens_at, closes_at, vote_ends_at, message_id, channel_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (interaction.guild_id, "oneliner_tourney", theme, "submit", opens, closes, vote_ends, msg.id, ch.id)
        )
        await interaction.response.send_message(f"✅ One-liner Tourney started in {ch.mention}!", ephemeral=True)

    @oneliner_group.command(name="submit", description="Submit your one-liner. One sentence only — or it gets rejected.")
    @app_commands.describe(line="Your one-liner (single sentence only!)")
    async def oneliner_submit(self, interaction: discord.Interaction, line: str):
        if not await is_game_enabled(interaction.guild_id, "oneliner_tourney"):
            return await interaction.response.send_message("❌ Game not enabled.", ephemeral=True)
        rnd = await get_active_submit_round(interaction.guild_id, "oneliner_tourney")
        if not rnd:
            return await interaction.response.send_message("❌ No active round.", ephemeral=True)
        if now_ts() > rnd["closes_at"]:
            return await interaction.response.send_message("❌ Submissions closed.", ephemeral=True)
        if await fetchone("SELECT id FROM submissions WHERE round_id=? AND user_id=?", (rnd["id"], interaction.user.id)):
            return await interaction.response.send_message("❌ You already submitted.", ephemeral=True)

        if not validate_one_sentence(line):
            return await interaction.response.send_message(
                "❌ **Auto-rejected.** That's more than one sentence. One. Line. Try again.", ephemeral=True
            )

        await execute(
            "INSERT INTO submissions (round_id, user_id, content, submitted_at) VALUES (?,?,?,?)",
            (rnd["id"], interaction.user.id, line, now_ts())
        )
        await interaction.response.send_message("✅ One-liner submitted!", ephemeral=True)

    @oneliner_group.command(name="vote", description="Vote for the best one-liner.")
    async def oneliner_vote(self, interaction: discord.Interaction):
        await self._generic_vote(interaction, "oneliner_tourney", "one-liner")

    @oneliner_group.command(name="close", description="[Mod] Close voting and reveal the winner.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def oneliner_close(self, interaction: discord.Interaction):
        await self._generic_close(interaction, "oneliner_tourney", "💬 One-liner Tourney Results!")

    # ─────────────────────────────────────────────
    # WORST IDEA COMPETITION
    # ─────────────────────────────────────────────
    worst_group = app_commands.Group(name="worstidea", description="Worst Idea Competition — be gloriously unhelpful.")

    @worst_group.command(name="start", description="[Mod] Post a problem for the Worst Idea Competition.")
    @app_commands.describe(problem="The real problem members must solve (badly)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def worst_start(self, interaction: discord.Interaction, problem: str):
        if not await is_game_enabled(interaction.guild_id, "worst_idea"):
            return await interaction.response.send_message("❌ Game not enabled.", ephemeral=True)
        if await get_active_round(interaction.guild_id, "worst_idea"):
            return await interaction.response.send_message("❌ A round is already active.", ephemeral=True)

        opens = now_ts()
        closes = opens + 48 * 3600
        vote_ends = closes + 24 * 3600
        ch = await get_game_channel(interaction.guild, "worst_idea") or interaction.channel

        embed = discord.Embed(
            title="💡 Worst Idea Competition",
            description=(
                f"**The Problem:** *{problem}*\n\n"
                f"Pitch the **worst possible solution** you can think of.\n"
                f"Use `/worstidea submit` — closes {ts_to_discord(closes)}."
            ),
            color=discord.Color.dark_orange()
        )
        msg = await ch.send(embed=embed)
        await lastrowid(
            "INSERT INTO rounds (guild_id, game_key, prompt, phase, opens_at, closes_at, vote_ends_at, message_id, channel_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (interaction.guild_id, "worst_idea", problem, "submit", opens, closes, vote_ends, msg.id, ch.id)
        )
        await interaction.response.send_message(f"✅ Worst Idea Competition started in {ch.mention}!", ephemeral=True)

    @worst_group.command(name="submit", description="Submit your worst possible solution.")
    @app_commands.describe(idea="Your spectacularly bad idea")
    async def worst_submit(self, interaction: discord.Interaction, idea: str):
        if not await is_game_enabled(interaction.guild_id, "worst_idea"):
            return await interaction.response.send_message("❌ Game not enabled.", ephemeral=True)
        rnd = await get_active_submit_round(interaction.guild_id, "worst_idea")
        if not rnd:
            return await interaction.response.send_message("❌ No active round.", ephemeral=True)
        if now_ts() > rnd["closes_at"]:
            return await interaction.response.send_message("❌ Submissions closed.", ephemeral=True)
        if await fetchone("SELECT id FROM submissions WHERE round_id=? AND user_id=?", (rnd["id"], interaction.user.id)):
            return await interaction.response.send_message("❌ You already submitted.", ephemeral=True)

        await execute(
            "INSERT INTO submissions (round_id, user_id, content, submitted_at) VALUES (?,?,?,?)",
            (rnd["id"], interaction.user.id, idea, now_ts())
        )
        await interaction.response.send_message("✅ Bad idea logged. You should be proud (and ashamed).", ephemeral=True)

    @worst_group.command(name="vote", description="Vote for the most unhinged idea.")
    async def worst_vote(self, interaction: discord.Interaction):
        await self._generic_vote(interaction, "worst_idea", "terrible idea")

    @worst_group.command(name="close", description="[Mod] Crown the worst idea of the round.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def worst_close(self, interaction: discord.Interaction):
        await self._generic_close(interaction, "worst_idea", "💡 Worst Idea Competition Results!")

    # ─────────────────────────────────────────────
    # HAIKU SMACKDOWN
    # ─────────────────────────────────────────────
    haiku_group = app_commands.Group(name="haiku", description="Haiku Smackdown — syllables or silence.")

    @haiku_group.command(name="start", description="[Mod] Start a Haiku Smackdown round.")
    @app_commands.describe(theme="The haiku theme")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def haiku_start(self, interaction: discord.Interaction, theme: str):
        if not await is_game_enabled(interaction.guild_id, "haiku_smackdown"):
            return await interaction.response.send_message("❌ Game not enabled.", ephemeral=True)
        if await get_active_round(interaction.guild_id, "haiku_smackdown"):
            return await interaction.response.send_message("❌ A round is already active.", ephemeral=True)

        opens = now_ts()
        closes = opens + 5 * 24 * 3600
        vote_ends = closes + 48 * 3600
        ch = await get_game_channel(interaction.guild, "haiku_smackdown") or interaction.channel

        embed = discord.Embed(
            title="🌸 Haiku Smackdown",
            description=(
                f"**Theme: *{theme}***\n\n"
                f"5 — 7 — 5. The bot validates syllables. Invalid haikus are **auto-rejected** with commentary.\n"
                f"Use `/haiku submit` — closes {ts_to_discord(closes)}."
            ),
            color=discord.Color.pink()
        )
        msg = await ch.send(embed=embed)
        await lastrowid(
            "INSERT INTO rounds (guild_id, game_key, prompt, phase, opens_at, closes_at, vote_ends_at, message_id, channel_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (interaction.guild_id, "haiku_smackdown", theme, "submit", opens, closes, vote_ends, msg.id, ch.id)
        )
        await interaction.response.send_message(f"✅ Haiku Smackdown started in {ch.mention}!", ephemeral=True)

    @haiku_group.command(name="submit", description="Submit your haiku (5-7-5 syllables, 3 lines).")
    @app_commands.describe(
        line1="First line (5 syllables)",
        line2="Second line (7 syllables)",
        line3="Third line (5 syllables)"
    )
    async def haiku_submit(self, interaction: discord.Interaction, line1: str, line2: str, line3: str):
        if not await is_game_enabled(interaction.guild_id, "haiku_smackdown"):
            return await interaction.response.send_message("❌ Game not enabled.", ephemeral=True)
        rnd = await get_active_submit_round(interaction.guild_id, "haiku_smackdown")
        if not rnd:
            return await interaction.response.send_message("❌ No active round.", ephemeral=True)
        if now_ts() > rnd["closes_at"]:
            return await interaction.response.send_message("❌ Submissions closed.", ephemeral=True)
        if await fetchone("SELECT id FROM submissions WHERE round_id=? AND user_id=?", (rnd["id"], interaction.user.id)):
            return await interaction.response.send_message("❌ You already submitted.", ephemeral=True)

        full_haiku = f"{line1}\n{line2}\n{line3}"
        valid, err = validate_haiku(full_haiku)
        if not valid:
            snarky = [
                "That's not a haiku, that's a cry for help.",
                "Five-seven-five. It's not that hard. Apparently it is.",
                "The ancient poets weep.",
                "Did you even count? Really?",
                "Zero out of five cherry blossoms.",
            ]
            import random
            return await interaction.response.send_message(
                f"❌ **Haiku rejected!** {err}\n*{random.choice(snarky)}*", ephemeral=True
            )

        await execute(
            "INSERT INTO submissions (round_id, user_id, content, submitted_at) VALUES (?,?,?,?)",
            (rnd["id"], interaction.user.id, full_haiku, now_ts())
        )
        await interaction.response.send_message(
            f"✅ Haiku accepted!\n```\n{full_haiku}\n```", ephemeral=True
        )

    @haiku_group.command(name="vote", description="Vote for your favourite haiku.")
    async def haiku_vote(self, interaction: discord.Interaction):
        await self._generic_vote(interaction, "haiku_smackdown", "haiku")

    @haiku_group.command(name="close", description="[Mod] Close voting and crown the haiku master.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def haiku_close(self, interaction: discord.Interaction):
        await self._generic_close(interaction, "haiku_smackdown", "🌸 Haiku Smackdown Results!")

    # ─────────────────────────────────────────────
    # THESAURUS THUNDERDOME
    # ─────────────────────────────────────────────
    thesaurus_group = app_commands.Group(name="thesaurus", description="Thesaurus Thunderdome — unnecessarily verbose.")

    @thesaurus_group.command(name="start", description="[Mod] Start a Thesaurus Thunderdome round.")
    @app_commands.describe(word="The simple word", sentence="The sentence to rewrite using complex vocabulary")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def thesaurus_start(self, interaction: discord.Interaction, word: str, sentence: str):
        if not await is_game_enabled(interaction.guild_id, "thesaurus_thunderdome"):
            return await interaction.response.send_message("❌ Game not enabled.", ephemeral=True)
        if await get_active_round(interaction.guild_id, "thesaurus_thunderdome"):
            return await interaction.response.send_message("❌ A round is already active.", ephemeral=True)

        opens = now_ts()
        closes = opens + 48 * 3600
        ch = await get_game_channel(interaction.guild, "thesaurus_thunderdome") or interaction.channel
        import json
        meta = json.dumps({"word": word, "sentence": sentence})

        embed = discord.Embed(
            title="📖 Thesaurus Thunderdome",
            description=(
                f"**Simple word:** *{word}*\n"
                f"**Sentence to rewrite:** *{sentence}*\n\n"
                f"Rewrite the sentence using the most **unnecessarily complex vocabulary** possible.\n"
                f"Most reacts wins! Use `/thesaurus submit` — closes {ts_to_discord(closes)}."
            ),
            color=discord.Color.dark_teal()
        )
        msg = await ch.send(embed=embed)
        await lastrowid(
            "INSERT INTO rounds (guild_id, game_key, prompt, phase, opens_at, closes_at, message_id, channel_id, metadata) VALUES (?,?,?,?,?,?,?,?,?)",
            (interaction.guild_id, "thesaurus_thunderdome", sentence, "submit", opens, closes, msg.id, ch.id, meta)
        )
        await interaction.response.send_message(f"✅ Thesaurus Thunderdome started in {ch.mention}!", ephemeral=True)

    @thesaurus_group.command(name="submit", description="Submit your maximally verbose rewrite.")
    @app_commands.describe(rewrite="Your needlessly complex sentence")
    async def thesaurus_submit(self, interaction: discord.Interaction, rewrite: str):
        if not await is_game_enabled(interaction.guild_id, "thesaurus_thunderdome"):
            return await interaction.response.send_message("❌ Game not enabled.", ephemeral=True)
        rnd = await get_active_submit_round(interaction.guild_id, "thesaurus_thunderdome")
        if not rnd:
            return await interaction.response.send_message("❌ No active round.", ephemeral=True)
        if now_ts() > rnd["closes_at"]:
            return await interaction.response.send_message("❌ Round is closed.", ephemeral=True)
        if await fetchone("SELECT id FROM submissions WHERE round_id=? AND user_id=?", (rnd["id"], interaction.user.id)):
            return await interaction.response.send_message("❌ You already submitted.", ephemeral=True)

        ch = interaction.guild.get_channel(rnd["channel_id"]) or interaction.channel
        msg = await ch.send(f"📖 **{interaction.user.display_name}:** *{rewrite}*")
        await execute(
            "INSERT INTO submissions (round_id, user_id, content, message_id, submitted_at) VALUES (?,?,?,?,?)",
            (rnd["id"], interaction.user.id, rewrite, msg.id, now_ts())
        )
        await interaction.response.send_message("✅ Submitted! React to vote for your favourites.", ephemeral=True)

    @thesaurus_group.command(name="close", description="[Mod] Close round and count reacts.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def thesaurus_close(self, interaction: discord.Interaction):
        from cogs.caption_games import CaptionGames
        cog = self.bot.get_cog("CaptionGames")
        if cog:
            await cog._close_react_game(interaction, "thesaurus_thunderdome", "📖 Thesaurus Thunderdome Results!")

    # ─────────────────────────────────────────────
    # HEADLINE HEIST
    # ─────────────────────────────────────────────
    headline_group = app_commands.Group(name="headline", description="Headline Heist — fill in the blank!")

    @headline_group.command(name="start", description="[Mod] Post a headline with a blanked noun.")
    @app_commands.describe(headline="The headline with ___ where the noun should go")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def headline_start(self, interaction: discord.Interaction, headline: str):
        if not await is_game_enabled(interaction.guild_id, "headline_heist"):
            return await interaction.response.send_message("❌ Game not enabled.", ephemeral=True)
        if await get_active_round(interaction.guild_id, "headline_heist"):
            return await interaction.response.send_message("❌ A round is already active.", ephemeral=True)
        if "___" not in headline:
            return await interaction.response.send_message("❌ Use `___` to mark the blanked noun.", ephemeral=True)

        opens = now_ts()
        closes = opens + 48 * 3600
        vote_ends = closes + 24 * 3600
        ch = await get_game_channel(interaction.guild, "headline_heist") or interaction.channel

        embed = discord.Embed(
            title="📰 Headline Heist",
            description=(
                f"**Headline:** *{headline}*\n\n"
                f"Fill in the blank to make it funnier!\n"
                f"Use `/headline submit` — closes {ts_to_discord(closes)}."
            ),
            color=discord.Color.dark_blue()
        )
        msg = await ch.send(embed=embed)
        await lastrowid(
            "INSERT INTO rounds (guild_id, game_key, prompt, phase, opens_at, closes_at, vote_ends_at, message_id, channel_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (interaction.guild_id, "headline_heist", headline, "submit", opens, closes, vote_ends, msg.id, ch.id)
        )
        await interaction.response.send_message(f"✅ Headline Heist started in {ch.mention}!", ephemeral=True)

    @headline_group.command(name="submit", description="Fill in the blank to complete the headline.")
    @app_commands.describe(fill="The word or phrase to fill in the blank")
    async def headline_submit(self, interaction: discord.Interaction, fill: str):
        if not await is_game_enabled(interaction.guild_id, "headline_heist"):
            return await interaction.response.send_message("❌ Game not enabled.", ephemeral=True)
        rnd = await get_active_submit_round(interaction.guild_id, "headline_heist")
        if not rnd:
            return await interaction.response.send_message("❌ No active round.", ephemeral=True)
        if now_ts() > rnd["closes_at"]:
            return await interaction.response.send_message("❌ Submissions closed.", ephemeral=True)
        if await fetchone("SELECT id FROM submissions WHERE round_id=? AND user_id=?", (rnd["id"], interaction.user.id)):
            return await interaction.response.send_message("❌ You already submitted.", ephemeral=True)

        completed = rnd["prompt"].replace("___", f"**{fill}**")
        await execute(
            "INSERT INTO submissions (round_id, user_id, content, submitted_at) VALUES (?,?,?,?)",
            (rnd["id"], interaction.user.id, fill, now_ts())
        )
        await interaction.response.send_message(
            f"✅ Submitted!\n📰 *{completed}*", ephemeral=True
        )

    @headline_group.command(name="vote", description="Vote for the funniest fill-in.")
    async def headline_vote(self, interaction: discord.Interaction):
        if not await is_game_enabled(interaction.guild_id, "headline_heist"):
            return await interaction.response.send_message("❌ Game not enabled.", ephemeral=True)
        rnd = await fetchone(
            "SELECT * FROM rounds WHERE guild_id=? AND game_key='headline_heist' AND phase='vote' ORDER BY id DESC LIMIT 1",
            (interaction.guild_id,)
        )
        if not rnd:
            return await interaction.response.send_message("❌ No voting phase active.", ephemeral=True)

        subs = await fetchall("SELECT * FROM submissions WHERE round_id=? ORDER BY id", (rnd["id"],))
        if not subs:
            return await interaction.response.send_message("❌ No submissions.", ephemeral=True)

        headline = rnd["prompt"]
        options = [
            discord.SelectOption(
                label=f"#{i+1}: {headline.replace('___', sub['content'])[:90]}",
                value=str(sub["id"])
            ) for i, sub in enumerate(subs)
        ]

        class HeadlineVoteView(discord.ui.View):
            def __init__(self, rnd):
                super().__init__(timeout=300)
                self.rnd = rnd

            @discord.ui.select(placeholder="Choose the funniest headline…", options=options)
            async def cb(self, i: discord.Interaction, sel: discord.ui.Select):
                sub_id = int(sel.values[0])
                await execute(
                    "INSERT OR IGNORE INTO votes (round_id, voter_id, sub_id) VALUES (?,?,?)",
                    (self.rnd["id"], i.user.id, sub_id)
                )
                await record_vote(self.rnd["guild_id"], i.user.id)
                await i.response.send_message("✅ Vote cast!", ephemeral=True)
                self.stop()

        await interaction.response.send_message("**Vote for the funniest headline:**", view=HeadlineVoteView(rnd), ephemeral=True)

    @headline_group.command(name="close", description="[Mod] Close voting and reveal the winner.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def headline_close(self, interaction: discord.Interaction):
        await self._generic_close(interaction, "headline_heist", "📰 Headline Heist Results!")

    # ─────────────────────────────────────────────
    # SHARED HELPERS
    # ─────────────────────────────────────────────
    async def _generic_vote(self, interaction, game_key, item_label):
        if not await is_game_enabled(interaction.guild_id, game_key):
            return await interaction.response.send_message("❌ Game not enabled.", ephemeral=True)
        rnd = await fetchone(
            "SELECT * FROM rounds WHERE guild_id=? AND game_key=? AND phase='vote' ORDER BY id DESC LIMIT 1",
            (interaction.guild_id, game_key)
        )
        if not rnd:
            return await interaction.response.send_message("❌ No voting phase active.", ephemeral=True)
        if now_ts() > rnd["vote_ends_at"]:
            return await interaction.response.send_message("❌ Voting has ended.", ephemeral=True)
        if await fetchone("SELECT id FROM votes WHERE round_id=? AND voter_id=?", (rnd["id"], interaction.user.id)):
            return await interaction.response.send_message("❌ You already voted.", ephemeral=True)

        subs = await fetchall("SELECT id, user_id, content FROM submissions WHERE round_id=? ORDER BY id", (rnd["id"],))
        if not subs:
            return await interaction.response.send_message("❌ No submissions.", ephemeral=True)

        options = [
            discord.SelectOption(label=f"#{i+1}: {s['content'][:90]}", value=str(s["id"]))
            for i, s in enumerate(subs)
        ]

        class VV(discord.ui.View):
            def __init__(self, rnd):
                super().__init__(timeout=300)
                self.rnd = rnd

            @discord.ui.select(placeholder=f"Choose the best {item_label}…", options=options)
            async def cb(self, i: discord.Interaction, sel: discord.ui.Select):
                await execute("INSERT OR IGNORE INTO votes (round_id, voter_id, sub_id) VALUES (?,?,?)",
                              (self.rnd["id"], i.user.id, int(sel.values[0])))
                await record_vote(self.rnd["guild_id"], i.user.id)
                await i.response.send_message("✅ Vote cast!", ephemeral=True)
                self.stop()

        await interaction.response.send_message(f"**Vote for the best {item_label}:**", view=VV(rnd), ephemeral=True)

    async def _generic_close(self, interaction, game_key, title):
        rnd = await fetchone(
            "SELECT * FROM rounds WHERE guild_id=? AND game_key=? AND phase='vote' ORDER BY id DESC LIMIT 1",
            (interaction.guild_id, game_key)
        )
        if not rnd:
            rnd = await get_active_submit_round(interaction.guild_id, game_key)
            if rnd:
                vote_ends = now_ts() + 48 * 3600
                await execute("UPDATE rounds SET phase='vote', vote_ends_at=? WHERE id=?", (vote_ends, rnd["id"]))
                ch = interaction.guild.get_channel(rnd["channel_id"]) or interaction.channel
                await ch.send(f"🗳️ Submissions closed! Voting now open for 48 hours. Use the vote command to pick your favourite!")
                return await interaction.response.send_message("✅ Voting opened.", ephemeral=True)
            return await interaction.response.send_message("❌ No active round.", ephemeral=True)

        results = await fetchall(
            "SELECT sub_id, COUNT(*) as votes FROM votes WHERE round_id=? GROUP BY sub_id ORDER BY votes DESC",
            (rnd["id"],)
        )
        await execute("UPDATE rounds SET phase='ended' WHERE id=?", (rnd["id"],))
        ch = interaction.guild.get_channel(rnd["channel_id"]) or interaction.channel

        if not results:
            await ch.send(f"**{title}**\nNo votes were cast. No winner this round!")
            return await interaction.response.send_message("✅ Closed.", ephemeral=True)

        winner = await fetchone("SELECT * FROM submissions WHERE id=?", (results[0]["sub_id"],))
        await record_win(rnd["guild_id"], winner["user_id"], game_key)

        embed = discord.Embed(title=f"🏆 {title}", color=discord.Color.gold())
        embed.add_field(name="🥇 Winner", value=f"<@{winner['user_id']}>\n> {winner['content']}", inline=False)
        await ch.send(embed=embed)
        await interaction.response.send_message("✅ Round closed and winner announced.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(WritingGames(bot))
