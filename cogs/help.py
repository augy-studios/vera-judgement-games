import discord
from discord import app_commands
from discord.ext import commands

TOTAL_PAGES = 6


class HelpView(discord.ui.View):
    def __init__(self, pages: list[discord.Embed]):
        super().__init__(timeout=180)
        self.pages = pages
        self.page = 0
        self._sync_buttons()

    def _sync_buttons(self):
        self.prev_btn.disabled = (self.page == 0)
        self.next_btn.disabled = (self.page == len(self.pages) - 1)

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.pages[self.page], view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.pages[self.page], view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="List all bot commands.")
    async def help_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)
        pages = await self._build_pages(interaction.guild)
        view = HelpView(pages)
        await interaction.followup.send(embed=pages[0], view=view)

    async def _build_pages(self, guild: discord.Guild | None = None) -> list[discord.Embed]:
        fetched = await self.bot.tree.fetch_commands(guild=guild)
        if not fetched:
            fetched = await self.bot.tree.fetch_commands()
        cmd_map = {c.name: c for c in fetched}

        def m(group: str, *subs: str) -> str:
            c = cmd_map.get(group)
            cid = c.id if c else 0
            if subs:
                return f"</{group} {' '.join(subs)}:{cid}>"
            return f"</{group}:{cid}>"

        def make_embed(title: str, desc: str, page_num: int) -> discord.Embed:
            e = discord.Embed(title=title, description=desc, color=discord.Color.blurple())
            e.set_footer(text=f"Page {page_num}/{TOTAL_PAGES}  ·  [Mod] = Manage Channel required")
            return e

        pages = []

        # Page 1: Bot Management
        e = make_embed("⚙️ Bot Management", "Commands to configure games server-wide. Requires **Manage Channel**.", 1)
        e.add_field(name="Game Settings", value=(
            f"{m('games', 'enable')} — Enable a game\n"
            f"{m('games', 'disable')} — Disable a game\n"
            f"{m('games', 'setchannel')} — Set a dedicated channel for a game\n"
            f"{m('games', 'clearchannel')} — Remove the dedicated channel override\n"
            f"{m('games', 'list')} — Show all game states for this server"
        ), inline=False)
        pages.append(e)

        # Page 2: Caption & Image Games
        e = make_embed("🖼️ Caption & Image Games", "Image-based games where players caption or title visuals.", 2)
        e.add_field(name="Caption Contest", value=(
            f"{m('caption', 'start')} — [Mod] Post an image to caption\n"
            f"{m('caption', 'submit')} — Submit your caption\n"
            f"{m('caption', 'vote')} — Vote for your favourite caption\n"
            f"{m('caption', 'close')} — [Mod] Close voting & announce winner"
        ), inline=False)
        e.add_field(name="Blurb Battle", value=(
            f"{m('blurb', 'start')} — [Mod] Post a show/movie for fake synopses\n"
            f"{m('blurb', 'submit')} — Submit your fake synopsis\n"
            f"{m('blurb', 'vote')} — Vote for the most convincing blurb\n"
            f"{m('blurb', 'close')} — [Mod] Close voting & reveal winner"
        ), inline=False)
        e.add_field(name="Wrong Answers Only", value=(
            f"{m('wrong', 'start')} — [Mod] Post an image for wrong answers\n"
            f"{m('wrong', 'submit')} — Submit your absurd wrong answer\n"
            f"{m('wrong', 'close')} — [Mod] Close the round"
        ), inline=False)
        e.add_field(name="Thumbnail Liar", value=(
            f"{m('thumbnail', 'start')} — [Mod] Post a screenshot for fake titles\n"
            f"{m('thumbnail', 'submit')} — Submit your fake clickbait title\n"
            f"{m('thumbnail', 'close')} — [Mod] Close the round"
        ), inline=False)
        pages.append(e)

        # Page 3: Writing & Wordplay Games (1/2)
        e = make_embed("✍️ Writing & Wordplay Games (1/2)", "Creativity-based games — puns, one-liners, bad ideas, haiku.", 3)
        e.add_field(name="Pun Championship", value=(
            f"{m('pun', 'start')} — [Mod] Start a round with a theme\n"
            f"{m('pun', 'submit')} — Submit your pun\n"
            f"{m('pun', 'vote')} — Vote for your favourite pun\n"
            f"{m('pun', 'close')} — [Mod] Crown the Pun Champion"
        ), inline=False)
        e.add_field(name="One-Liner Tourney", value=(
            f"{m('oneliner', 'start')} — [Mod] Start a round\n"
            f"{m('oneliner', 'submit')} — Submit your one-liner (one sentence only)\n"
            f"{m('oneliner', 'vote')} — Vote for the best one-liner\n"
            f"{m('oneliner', 'close')} — [Mod] Reveal the winner"
        ), inline=False)
        e.add_field(name="Worst Idea Competition", value=(
            f"{m('worstidea', 'start')} — [Mod] Post a problem to solve badly\n"
            f"{m('worstidea', 'submit')} — Submit your worst possible solution\n"
            f"{m('worstidea', 'vote')} — Vote for the most unhinged idea\n"
            f"{m('worstidea', 'close')} — [Mod] Crown the worst idea"
        ), inline=False)
        e.add_field(name="Haiku Smackdown", value=(
            f"{m('haiku', 'start')} — [Mod] Start a haiku round\n"
            f"{m('haiku', 'submit')} — Submit your haiku (5-7-5 syllables, 3 lines)\n"
            f"{m('haiku', 'vote')} — Vote for your favourite haiku\n"
            f"{m('haiku', 'close')} — [Mod] Crown the haiku master"
        ), inline=False)
        pages.append(e)

        # Page 4: Writing & Wordplay Games (2/2)
        e = make_embed("✍️ Writing & Wordplay Games (2/2)", "More writing games — thesaurus battles and headline fill-ins.", 4)
        e.add_field(name="Thesaurus Thunderdome", value=(
            f"{m('thesaurus', 'start')} — [Mod] Post a sentence to rewrite as verbosely as possible\n"
            f"{m('thesaurus', 'submit')} — Submit your maximally verbose rewrite\n"
            f"{m('thesaurus', 'close')} — [Mod] Close the round & count reacts"
        ), inline=False)
        e.add_field(name="Headline Heist", value=(
            f"{m('headline', 'start')} — [Mod] Post a headline with a blanked noun\n"
            f"{m('headline', 'submit')} — Fill in the blank to complete the headline\n"
            f"{m('headline', 'vote')} — Vote for the funniest fill-in\n"
            f"{m('headline', 'close')} — [Mod] Close voting & reveal winner"
        ), inline=False)
        pages.append(e)

        # Page 5: Judging & Taste Games
        e = make_embed("⚖️ Judging & Taste Games", "Games where the server votes on takes, vibes, and picks.", 5)
        e.add_field(name="Hot Take Tribunal", value=(
            f"{m('hottake', 'submit')} — Submit a hot take for the jury (instant voting)\n"
            f"{m('hottake', 'close')} — [Mod] Force-close a tribunal & deliver verdict"
        ), inline=False)
        e.add_field(name="Taste Test", value=(
            f"{m('taste', 'start')} — [Mod] Start a Taste Test (A vs B)\n"
            f"{m('taste', 'submit')} — Argue for your pick in one sentence\n"
            f"{m('taste', 'close')} — [Mod] Close and count reacts"
        ), inline=False)
        e.add_field(name="Vibe Court", value=(
            f"{m('vibe', 'submit')} — Submit a vibe for the court to judge (instant voting)\n"
            f"{m('vibe', 'close')} — [Mod] Close a vibe vote & deliver verdict"
        ), inline=False)
        e.add_field(name="Canon Cringe", value=(
            f"{m('canon', 'submit')} — Submit a server in-joke for canon consideration\n"
            f"{m('canon', 'list')} — View all approved server canon entries\n"
            f"{m('canon', 'close')} — [Mod] Force-close a canon vote"
        ), inline=False)
        pages.append(e)

        # Page 6: Leaderboards
        e = make_embed("🏆 Leaderboards", "Track who's winning across all games.", 6)
        e.add_field(name="Standings", value=(
            f"{m('leaderboard', 'weekly')} — Top players in the last 7 days\n"
            f"{m('leaderboard', 'monthly')} — Top players in the last 30 days\n"
            f"{m('leaderboard', 'alltime')} — The all-time legacy board\n"
            f"{m('leaderboard', 'streak')} — Current and all-time win streaks\n"
            f"{m('leaderboard', 'voter')} — Most engaged judges (last 30 days)\n"
            f"{m('leaderboard', 'underdog')} — Wins by bottom-half members only\n"
            f"{m('leaderboard', 'me')} — Your personal stats and rankings"
        ), inline=False)
        pages.append(e)

        return pages


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCog(bot))
