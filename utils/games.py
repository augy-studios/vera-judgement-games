import time
import discord
from utils.db import fetchone, execute

# All registered game keys
ALL_GAMES = [
    "rolling_caption",
    "blurb_battle",
    "wrong_answers",
    "thumbnail_liar",
    "pun_championship",
    "oneliner_tourney",
    "worst_idea",
    "haiku_smackdown",
    "thesaurus_thunderdome",
    "headline_heist",
    "hot_take",
    "taste_test",
    "vibe_court",
    "canon_cringe",
]

GAME_NAMES = {
    "rolling_caption":      "Rolling Caption Contest",
    "blurb_battle":         "Blurb Battle",
    "wrong_answers":        "Wrong Answers Only",
    "thumbnail_liar":       "Thumbnail Liar",
    "pun_championship":     "Pun Championship",
    "oneliner_tourney":     "One-liner Tourney",
    "worst_idea":           "Worst Idea Competition",
    "haiku_smackdown":      "Haiku Smackdown",
    "thesaurus_thunderdome":"Thesaurus Thunderdome",
    "headline_heist":       "Headline Heist",
    "hot_take":             "Hot Take Tribunal",
    "taste_test":           "Taste Test",
    "vibe_court":           "Vibe Court",
    "canon_cringe":         "Canon or Cringe",
}


async def is_game_enabled(guild_id: int, game_key: str) -> bool:
    row = await fetchone(
        "SELECT enabled FROM guild_settings WHERE guild_id=? AND game_key=?",
        (guild_id, game_key)
    )
    # Default enabled if no row
    return (row["enabled"] == 1) if row else True


async def get_game_channel(guild: discord.Guild, game_key: str) -> discord.TextChannel | None:
    row = await fetchone(
        "SELECT channel_id FROM guild_settings WHERE guild_id=? AND game_key=?",
        (guild.id, game_key)
    )
    if row and row["channel_id"]:
        return guild.get_channel(row["channel_id"])
    return None


async def get_active_round(guild_id: int, game_key: str):
    return await fetchone(
        "SELECT * FROM rounds WHERE guild_id=? AND game_key=? AND phase NOT IN ('ended') ORDER BY id DESC LIMIT 1",
        (guild_id, game_key)
    )


async def get_active_submit_round(guild_id: int, game_key: str):
    return await fetchone(
        "SELECT * FROM rounds WHERE guild_id=? AND game_key=? AND phase='submit' ORDER BY id DESC LIMIT 1",
        (guild_id, game_key)
    )


def now_ts() -> float:
    return time.time()


def ts_to_discord(ts: float) -> str:
    return f"<t:{int(ts)}:R>"


def ts_full(ts: float) -> str:
    return f"<t:{int(ts)}:F>"


async def record_win(guild_id: int, user_id: int, game_key: str, points: int = 1):
    await execute(
        "INSERT INTO points (guild_id, user_id, game_key, points, wins, earned_at) VALUES (?,?,?,?,1,?)",
        (guild_id, user_id, game_key, points, now_ts())
    )


async def record_vote(guild_id: int, user_id: int):
    await execute(
        "INSERT INTO voter_log (guild_id, user_id, voted_at) VALUES (?,?,?)",
        (guild_id, user_id, now_ts())
    )


# Haiku syllable counter (simple English heuristic)
def count_syllables(word: str) -> int:
    word = word.lower().strip(".,!?;:'\"")
    if not word:
        return 0
    vowels = "aeiouy"
    count = 0
    prev_vowel = False
    for ch in word:
        is_vowel = ch in vowels
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel
    if word.endswith("e") and count > 1:
        count -= 1
    return max(1, count)


def validate_haiku(text: str):
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    if len(lines) != 3:
        return False, "A haiku must have exactly 3 lines."
    expected = [5, 7, 5]
    for i, (line, exp) in enumerate(zip(lines, expected)):
        words = line.split()
        total = sum(count_syllables(w) for w in words)
        if total != exp:
            return False, (
                f"Line {i+1} has ~{total} syllable(s), but needs {exp}. "
                f"*('{line}')*"
            )
    return True, None


def validate_one_sentence(text: str):
    stripped = text.strip()
    if "\n" in stripped:
        return False
    # Allow one terminal punctuation mark at end
    sentences = [s for s in stripped.replace("!", ".").replace("?", ".").split(".") if s.strip()]
    return len(sentences) <= 1
