import discord
from discord import app_commands
from discord.ext import commands
import json
import random

from utils.db import fetchone, fetchall, execute, lastrowid
from utils.games import (
    is_game_enabled, get_game_channel, get_active_round,
    get_active_submit_round, now_ts, ts_to_discord, ts_full,
    record_win, record_vote, GAME_NAMES
)

GUILTY_VERDICTS = [
    "⚖️ **GUILTY.** The tribunal has spoken. That take is cooked.",
    "⚖️ **GUILTY.** Your take has been convicted of crimes against common sense.",
    "⚖️ **GUILTY.** The evidence was overwhelming. Contemplate your life choices.",
    "⚖️ **GUILTY.** The court finds you terminally incorrect.",
]

NOT_GUILTY_VERDICTS = [
    "⚖️ **NOT GUILTY.** The hot take walks free. This time.",
    "⚖️ **NOT GUILTY.** The tribunal, with some reluctance, accepts the take.",
    "⚖️ **NOT GUILTY.** Bold. Controversial. Correct? Apparently.",
    "⚖️ **NOT GUILTY.** The take stands. The court is adjourned.",
]


class JudgingGames(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ─────────────────────────────────────────────
    # HOT TAKE TRIBUNAL
    # ─────────────────────────────────────────────
    hottake_group = app_commands.Group(name="hottake", description="Hot Take Tribunal — guilty or not guilty?")

    @hottake_group.command(name="submit", description="Submit a hot take for the tribunal.")
    @app_commands.describe(take="Your controversial hot take")
    async def hottake_submit(self, interaction: discord.Interaction, take: str):
        if not await is_game_enabled(interaction.guild_id, "hot_take"):
            return await interaction.response.send_message("❌ Game not enabled.", ephemeral=True)

        opens = now_ts()
        closes = opens + 48 * 3600
        ch = await get_game_channel(interaction.guild, "hot_take") or interaction.channel

        embed = discord.Embed(
            title="🔥 Hot Take Tribunal",
            description=(
                f"**The Take:** *{take}*\n"
                f"**Submitted by:** {interaction.user.mention}\n\n"
                f"Vote below — Guilty or Not Guilty?\n"
                f"Closes {ts_to_discord(closes)}."
            ),
            color=discord.Color.red()
        )

        round_id = await lastrowid(
            "INSERT INTO rounds (guild_id, game_key, prompt, phase, opens_at, closes_at, vote_ends_at, channel_id) VALUES (?,?,?,?,?,?,?,?)",
            (interaction.guild_id, "hot_take", take, "vote", opens, closes, closes, ch.id)
        )
        await execute(
            "INSERT INTO submissions (round_id, user_id, content, submitted_at) VALUES (?,?,?,?)",
            (round_id, interaction.user.id, take, now_ts())
        )

        view = TribunalView(round_id, interaction.guild_id, interaction.user.id, closes)
        msg = await ch.send(embed=embed, view=view)
        await execute("UPDATE rounds SET message_id=? WHERE id=?", (msg.id, round_id))
        await interaction.response.send_message(f"✅ Hot take submitted to {ch.mention}!", ephemeral=True)

    @hottake_group.command(name="close", description="[Mod] Force-close a tribunal and deliver the verdict.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def hottake_close(self, interaction: discord.Interaction):
        rnd = await fetchone(
            "SELECT * FROM rounds WHERE guild_id=? AND game_key='hot_take' AND phase='vote' ORDER BY id DESC LIMIT 1",
            (interaction.guild_id,)
        )
        if not rnd:
            return await interaction.response.send_message("❌ No active tribunal.", ephemeral=True)
        await self._deliver_verdict(rnd)
        await interaction.response.send_message("✅ Verdict delivered.", ephemeral=True)

    async def _deliver_verdict(self, rnd):
        votes = await fetchall(
            "SELECT sub_id, COUNT(*) as cnt FROM votes WHERE round_id=? GROUP BY sub_id",
            (rnd["id"],)
        )
        # In tribunal, sub_id is reused as 1=guilty, 0=not_guilty via metadata in voter_log
        guilty = await fetchone(
            "SELECT COUNT(*) as c FROM voter_log WHERE guild_id=? AND user_id < 0 AND voted_at > ?",
            (rnd["guild_id"], rnd["opens_at"])
        )
        # Simpler: count from votes table with a marker scheme
        # We stored guilty votes with sub_id = round_id (truthy), not-guilty with sub_id = 0
        g_votes = sum(v["cnt"] for v in votes if v["sub_id"] == rnd["id"])
        ng_votes = sum(v["cnt"] for v in votes if v["sub_id"] == 0)

        await execute("UPDATE rounds SET phase='ended' WHERE id=?", (rnd["id"],))
        sub = await fetchone("SELECT * FROM submissions WHERE round_id=?", (rnd["id"],))
        if not sub:
            return

        is_guilty = g_votes >= ng_votes
        verdict_text = random.choice(GUILTY_VERDICTS if is_guilty else NOT_GUILTY_VERDICTS)

        guild = self.bot.get_guild(rnd["guild_id"])
        if not guild:
            return
        ch = guild.get_channel(rnd["channel_id"])
        if not ch:
            return

        await execute(
            "INSERT INTO verdicts (guild_id, user_id, take, guilty, votes_g, votes_ng, closed_at) VALUES (?,?,?,?,?,?,?)",
            (rnd["guild_id"], sub["user_id"], sub["content"], 1 if is_guilty else 0, g_votes, ng_votes, now_ts())
        )

        if is_guilty:
            await record_win(rnd["guild_id"], sub["user_id"], "hot_take")

        embed = discord.Embed(
            title="⚖️ Tribunal — Verdict Delivered",
            description=(
                f"**Take:** *{sub['content']}*\n"
                f"**By:** <@{sub['user_id']}>\n\n"
                f"🔴 Guilty: **{g_votes}** | 🟢 Not Guilty: **{ng_votes}**\n\n"
                f"{verdict_text}"
            ),
            color=discord.Color.dark_red() if is_guilty else discord.Color.green()
        )
        await ch.send(embed=embed)

    # ─────────────────────────────────────────────
    # TASTE TEST
    # ─────────────────────────────────────────────
    taste_group = app_commands.Group(name="taste", description="Taste Test — argue for your pick.")

    @taste_group.command(name="start", description="[Mod] Start a Taste Test round.")
    @app_commands.describe(option_a="First option", option_b="Second option", category="Category (e.g. films, foods, songs)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def taste_start(self, interaction: discord.Interaction, option_a: str, option_b: str, category: str = "options"):
        if not await is_game_enabled(interaction.guild_id, "taste_test"):
            return await interaction.response.send_message("❌ Game not enabled.", ephemeral=True)
        if await get_active_round(interaction.guild_id, "taste_test"):
            return await interaction.response.send_message("❌ A round is already active.", ephemeral=True)

        opens = now_ts()
        closes = opens + 48 * 3600
        ch = await get_game_channel(interaction.guild, "taste_test") or interaction.channel
        meta = json.dumps({"a": option_a, "b": option_b, "category": category})

        embed = discord.Embed(
            title="👅 Taste Test",
            description=(
                f"**{option_a}** vs **{option_b}** *(category: {category})*\n\n"
                f"Pick your side and argue for it in one sentence!\n"
                f"Use `/taste submit` — most convincing argument by react vote wins.\n"
                f"Closes {ts_to_discord(closes)}."
            ),
            color=discord.Color.magenta()
        )
        msg = await ch.send(embed=embed)
        await lastrowid(
            "INSERT INTO rounds (guild_id, game_key, prompt, phase, opens_at, closes_at, message_id, channel_id, metadata) VALUES (?,?,?,?,?,?,?,?,?)",
            (interaction.guild_id, "taste_test", f"{option_a} vs {option_b}", "submit", opens, closes, msg.id, ch.id, meta)
        )
        await interaction.response.send_message(f"✅ Taste Test started in {ch.mention}!", ephemeral=True)

    @taste_group.command(name="submit", description="Argue for your pick in one sentence.")
    @app_commands.describe(pick="Which option are you defending?", argument="Your one-sentence argument")
    async def taste_submit(self, interaction: discord.Interaction, pick: str, argument: str):
        if not await is_game_enabled(interaction.guild_id, "taste_test"):
            return await interaction.response.send_message("❌ Game not enabled.", ephemeral=True)
        rnd = await get_active_submit_round(interaction.guild_id, "taste_test")
        if not rnd:
            return await interaction.response.send_message("❌ No active round.", ephemeral=True)
        if now_ts() > rnd["closes_at"]:
            return await interaction.response.send_message("❌ Round is closed.", ephemeral=True)
        if await fetchone("SELECT id FROM submissions WHERE round_id=? AND user_id=?", (rnd["id"], interaction.user.id)):
            return await interaction.response.send_message("❌ You already submitted.", ephemeral=True)

        from utils.games import validate_one_sentence
        if not validate_one_sentence(argument):
            return await interaction.response.send_message("❌ One sentence only! Edit it down.", ephemeral=True)

        ch = interaction.guild.get_channel(rnd["channel_id"]) or interaction.channel
        msg = await ch.send(
            f"👅 **{interaction.user.display_name}** defends **{pick}**: *{argument}*"
        )
        await execute(
            "INSERT INTO submissions (round_id, user_id, content, message_id, submitted_at) VALUES (?,?,?,?,?)",
            (rnd["id"], interaction.user.id, f"[{pick}] {argument}", msg.id, now_ts())
        )
        await interaction.response.send_message("✅ Argument submitted! React to vote.", ephemeral=True)

    @taste_group.command(name="close", description="[Mod] Close and count reacts.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def taste_close(self, interaction: discord.Interaction):
        from cogs.caption_games import CaptionGames
        cog = self.bot.get_cog("CaptionGames")
        if cog:
            await cog._close_react_game(interaction, "taste_test", "👅 Taste Test Results!")

    # ─────────────────────────────────────────────
    # VIBE COURT
    # ─────────────────────────────────────────────
    vibe_group = app_commands.Group(name="vibe", description="Vibe Court — is it a real vibe?")

    @vibe_group.command(name="submit", description="Submit a vibe for the court to judge.")
    @app_commands.describe(vibe="Describe your vibe in a few words")
    async def vibe_submit(self, interaction: discord.Interaction, vibe: str):
        if not await is_game_enabled(interaction.guild_id, "vibe_court"):
            return await interaction.response.send_message("❌ Game not enabled.", ephemeral=True)

        opens = now_ts()
        closes = opens + 48 * 3600
        ch = await get_game_channel(interaction.guild, "vibe_court") or interaction.channel

        round_id = await lastrowid(
            "INSERT INTO rounds (guild_id, game_key, prompt, phase, opens_at, closes_at, vote_ends_at, channel_id) VALUES (?,?,?,?,?,?,?,?)",
            (interaction.guild_id, "vibe_court", vibe, "vote", opens, closes, closes, ch.id)
        )
        await execute(
            "INSERT INTO submissions (round_id, user_id, content, submitted_at) VALUES (?,?,?,?)",
            (round_id, interaction.user.id, vibe, now_ts())
        )

        embed = discord.Embed(
            title="✨ Vibe Court",
            description=(
                f"**Submitted by:** {interaction.user.mention}\n"
                f"**The Vibe:** *{vibe}*\n\n"
                f"Is this a **real vibe**? Vote below!\n"
                f"Closes {ts_to_discord(closes)}."
            ),
            color=discord.Color.from_rgb(180, 100, 255)
        )

        view = VibeCourtView(round_id, interaction.guild_id, interaction.user.id, closes)
        msg = await ch.send(embed=embed, view=view)
        await execute("UPDATE rounds SET message_id=? WHERE id=?", (msg.id, round_id))
        await interaction.response.send_message(f"✅ Vibe submitted to {ch.mention}!", ephemeral=True)

    @vibe_group.command(name="close", description="[Mod] Close a vibe vote and deliver the verdict.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def vibe_close(self, interaction: discord.Interaction):
        rnd = await fetchone(
            "SELECT * FROM rounds WHERE guild_id=? AND game_key='vibe_court' AND phase='vote' ORDER BY id DESC LIMIT 1",
            (interaction.guild_id,)
        )
        if not rnd:
            return await interaction.response.send_message("❌ No active vibe vote.", ephemeral=True)
        await self._close_vibe(rnd)
        await interaction.response.send_message("✅ Vibe verdict delivered.", ephemeral=True)

    async def _close_vibe(self, rnd):
        votes = await fetchall(
            "SELECT sub_id, COUNT(*) as cnt FROM votes WHERE round_id=? GROUP BY sub_id",
            (rnd["id"],)
        )
        yes_votes = sum(v["cnt"] for v in votes if v["sub_id"] == rnd["id"])
        no_votes = sum(v["cnt"] for v in votes if v["sub_id"] == 0)

        await execute("UPDATE rounds SET phase='ended' WHERE id=?", (rnd["id"],))
        sub = await fetchone("SELECT * FROM submissions WHERE round_id=?", (rnd["id"],))
        if not sub:
            return

        validated = yes_votes > no_votes
        if validated:
            await record_win(rnd["guild_id"], sub["user_id"], "vibe_court")

        guild = self.bot.get_guild(rnd["guild_id"])
        if not guild:
            return
        ch = guild.get_channel(rnd["channel_id"])
        if not ch:
            return

        if validated:
            result_text = f"✅ **VALIDATED.** The court agrees — `{sub['content']}` is a real vibe."
        else:
            result_text = f"❌ **REJECTED.** The court has spoken — `{sub['content']}` is not a vibe."

        embed = discord.Embed(
            title="✨ Vibe Court — Verdict",
            description=(
                f"**The Vibe:** *{sub['content']}*\n"
                f"**By:** <@{sub['user_id']}>\n\n"
                f"✅ Yes: **{yes_votes}** | ❌ No: **{no_votes}**\n\n"
                f"{result_text}"
            ),
            color=discord.Color.green() if validated else discord.Color.dark_gray()
        )
        await ch.send(embed=embed)

    # ─────────────────────────────────────────────
    # CANON OR CRINGE
    # ─────────────────────────────────────────────
    canon_group = app_commands.Group(name="canon", description="Canon or Cringe — earn your place in server history.")

    @canon_group.command(name="submit", description="Submit a server in-joke or moment for canon consideration.")
    @app_commands.describe(entry="The moment, in-joke, or reference you want canonised")
    async def canon_submit(self, interaction: discord.Interaction, entry: str):
        if not await is_game_enabled(interaction.guild_id, "canon_cringe"):
            return await interaction.response.send_message("❌ Game not enabled.", ephemeral=True)

        opens = now_ts()
        closes = opens + 48 * 3600
        ch = await get_game_channel(interaction.guild, "canon_cringe") or interaction.channel

        round_id = await lastrowid(
            "INSERT INTO rounds (guild_id, game_key, prompt, phase, opens_at, closes_at, vote_ends_at, channel_id) VALUES (?,?,?,?,?,?,?,?)",
            (interaction.guild_id, "canon_cringe", entry, "vote", opens, closes, closes, ch.id)
        )
        await execute(
            "INSERT INTO submissions (round_id, user_id, content, submitted_at) VALUES (?,?,?,?)",
            (round_id, interaction.user.id, entry, now_ts())
        )

        embed = discord.Embed(
            title="📜 Canon or Cringe?",
            description=(
                f"**Submitted by:** {interaction.user.mention}\n"
                f"**The Entry:** *{entry}*\n\n"
                f"Does this deserve to be **official server canon**?\n"
                f"Vote below! Closes {ts_to_discord(closes)}."
            ),
            color=discord.Color.gold()
        )

        view = CanonCringeView(round_id, interaction.guild_id, interaction.user.id, closes)
        msg = await ch.send(embed=embed, view=view)
        await execute("UPDATE rounds SET message_id=? WHERE id=?", (msg.id, round_id))
        await interaction.response.send_message(f"✅ Submitted for canon consideration in {ch.mention}!", ephemeral=True)

    @canon_group.command(name="list", description="View all approved server canon entries.")
    async def canon_list(self, interaction: discord.Interaction):
        entries = await fetchall(
            "SELECT * FROM canon_log WHERE guild_id=? ORDER BY approved_at DESC LIMIT 20",
            (interaction.guild_id,)
        )
        if not entries:
            return await interaction.response.send_message("📜 No canon entries yet. Be the first!", ephemeral=True)

        lines = []
        for e in entries:
            import datetime
            dt = datetime.datetime.fromtimestamp(e["approved_at"]).strftime("%d %b %Y")
            lines.append(f"• *{e['content']}* — <@{e['user_id']}> ({dt})")

        embed = discord.Embed(
            title=f"📜 {interaction.guild.name} — Official Server Canon",
            description="\n".join(lines),
            color=discord.Color.gold()
        )
        await interaction.response.send_message(embed=embed)

    @canon_group.command(name="close", description="[Mod] Force-close a canon vote.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def canon_close(self, interaction: discord.Interaction):
        rnd = await fetchone(
            "SELECT * FROM rounds WHERE guild_id=? AND game_key='canon_cringe' AND phase='vote' ORDER BY id DESC LIMIT 1",
            (interaction.guild_id,)
        )
        if not rnd:
            return await interaction.response.send_message("❌ No active canon vote.", ephemeral=True)
        await self._close_canon(rnd)
        await interaction.response.send_message("✅ Canon vote closed.", ephemeral=True)

    async def _close_canon(self, rnd):
        votes = await fetchall(
            "SELECT sub_id, COUNT(*) as cnt FROM votes WHERE round_id=? GROUP BY sub_id",
            (rnd["id"],)
        )
        yes = sum(v["cnt"] for v in votes if v["sub_id"] == rnd["id"])
        no = sum(v["cnt"] for v in votes if v["sub_id"] == 0)

        await execute("UPDATE rounds SET phase='ended' WHERE id=?", (rnd["id"],))
        sub = await fetchone("SELECT * FROM submissions WHERE round_id=?", (rnd["id"],))
        if not sub:
            return

        approved = yes > no
        guild = self.bot.get_guild(rnd["guild_id"])
        if not guild:
            return
        ch = guild.get_channel(rnd["channel_id"])
        if not ch:
            return

        if approved:
            await execute(
                "INSERT INTO canon_log (guild_id, user_id, content, approved_at) VALUES (?,?,?,?)",
                (rnd["guild_id"], sub["user_id"], sub["content"], now_ts())
            )
            await record_win(rnd["guild_id"], sub["user_id"], "canon_cringe")
            embed = discord.Embed(
                title="📜 CANON APPROVED",
                description=(
                    f"*{sub['content']}*\n\n"
                    f"✅ Yes: **{yes}** | ❌ No: **{no}**\n\n"
                    f"This moment has been immortalised in server history. Congratulations, <@{sub['user_id']}>."
                ),
                color=discord.Color.gold()
            )
        else:
            embed = discord.Embed(
                title="🗑️ CRINGE — Rejected",
                description=(
                    f"*{sub['content']}*\n\n"
                    f"✅ Yes: **{yes}** | ❌ No: **{no}**\n\n"
                    f"The server has spoken. This stays in the shadow realm."
                ),
                color=discord.Color.dark_gray()
            )
        await ch.send(embed=embed)


# ─────────────────────────────────────────────
# UI VIEWS FOR BUTTON-BASED VOTING
# ─────────────────────────────────────────────

class TribunalView(discord.ui.View):
    def __init__(self, round_id, guild_id, submitter_id, closes_at):
        super().__init__(timeout=None)
        self.round_id = round_id
        self.guild_id = guild_id
        self.submitter_id = submitter_id
        self.closes_at = closes_at

    @discord.ui.button(label="🔴 GUILTY", style=discord.ButtonStyle.danger, custom_id="tribunal_guilty")
    async def guilty(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._vote(interaction, guilty=True)

    @discord.ui.button(label="🟢 NOT GUILTY", style=discord.ButtonStyle.success, custom_id="tribunal_not_guilty")
    async def not_guilty(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._vote(interaction, guilty=False)

    async def _vote(self, interaction: discord.Interaction, guilty: bool):
        if interaction.user.id == self.submitter_id:
            return await interaction.response.send_message("❌ You can't vote on your own take!", ephemeral=True)
        if now_ts() > self.closes_at:
            return await interaction.response.send_message("❌ This tribunal is closed.", ephemeral=True)

        existing = await fetchone(
            "SELECT id FROM votes WHERE round_id=? AND voter_id=?",
            (self.round_id, interaction.user.id)
        )
        if existing:
            return await interaction.response.send_message("❌ You already voted.", ephemeral=True)

        # sub_id = round_id means guilty, sub_id = 0 means not guilty
        sub_id = self.round_id if guilty else 0
        await execute(
            "INSERT INTO votes (round_id, voter_id, sub_id) VALUES (?,?,?)",
            (self.round_id, interaction.user.id, sub_id)
        )
        await record_vote(self.guild_id, interaction.user.id)
        label = "GUILTY" if guilty else "NOT GUILTY"
        await interaction.response.send_message(f"⚖️ Vote cast: **{label}**", ephemeral=True)


class VibeCourtView(discord.ui.View):
    def __init__(self, round_id, guild_id, submitter_id, closes_at):
        super().__init__(timeout=None)
        self.round_id = round_id
        self.guild_id = guild_id
        self.submitter_id = submitter_id
        self.closes_at = closes_at

    @discord.ui.button(label="✅ Real Vibe", style=discord.ButtonStyle.success, custom_id="vibe_yes")
    async def vibe_yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._vote(interaction, yes=True)

    @discord.ui.button(label="❌ Not a Vibe", style=discord.ButtonStyle.secondary, custom_id="vibe_no")
    async def vibe_no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._vote(interaction, yes=False)

    async def _vote(self, interaction: discord.Interaction, yes: bool):
        if interaction.user.id == self.submitter_id:
            return await interaction.response.send_message("❌ You can't vote on your own vibe!", ephemeral=True)
        if now_ts() > self.closes_at:
            return await interaction.response.send_message("❌ This vibe vote is closed.", ephemeral=True)
        if await fetchone("SELECT id FROM votes WHERE round_id=? AND voter_id=?", (self.round_id, interaction.user.id)):
            return await interaction.response.send_message("❌ You already voted.", ephemeral=True)

        sub_id = self.round_id if yes else 0
        await execute("INSERT INTO votes (round_id, voter_id, sub_id) VALUES (?,?,?)",
                      (self.round_id, interaction.user.id, sub_id))
        await record_vote(self.guild_id, interaction.user.id)
        await interaction.response.send_message("✅ Vote cast!", ephemeral=True)


class CanonCringeView(discord.ui.View):
    def __init__(self, round_id, guild_id, submitter_id, closes_at):
        super().__init__(timeout=None)
        self.round_id = round_id
        self.guild_id = guild_id
        self.submitter_id = submitter_id
        self.closes_at = closes_at

    @discord.ui.button(label="📜 CANON", style=discord.ButtonStyle.success, custom_id="canon_yes")
    async def canon_yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._vote(interaction, yes=True)

    @discord.ui.button(label="🗑️ CRINGE", style=discord.ButtonStyle.danger, custom_id="canon_no")
    async def canon_no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._vote(interaction, yes=False)

    async def _vote(self, interaction: discord.Interaction, yes: bool):
        if interaction.user.id == self.submitter_id:
            return await interaction.response.send_message("❌ You can't vote on your own submission!", ephemeral=True)
        if now_ts() > self.closes_at:
            return await interaction.response.send_message("❌ This vote is closed.", ephemeral=True)
        if await fetchone("SELECT id FROM votes WHERE round_id=? AND voter_id=?", (self.round_id, interaction.user.id)):
            return await interaction.response.send_message("❌ You already voted.", ephemeral=True)

        sub_id = self.round_id if yes else 0
        await execute("INSERT INTO votes (round_id, voter_id, sub_id) VALUES (?,?,?)",
                      (self.round_id, interaction.user.id, sub_id))
        await record_vote(self.guild_id, interaction.user.id)
        await interaction.response.send_message("✅ Vote cast!", ephemeral=True)


async def setup(bot):
    await bot.add_cog(JudgingGames(bot))
