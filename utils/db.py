import aiosqlite
import asyncio
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "vera.db")

CREATE_STATEMENTS = [
    # Guild settings — which games are enabled, channel overrides
    """
    CREATE TABLE IF NOT EXISTS guild_settings (
        guild_id    INTEGER NOT NULL,
        game_key    TEXT    NOT NULL,
        enabled     INTEGER NOT NULL DEFAULT 1,
        channel_id  INTEGER,
        PRIMARY KEY (guild_id, game_key)
    )
    """,

    # Active rounds for all games
    """
    CREATE TABLE IF NOT EXISTS rounds (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id     INTEGER NOT NULL,
        game_key     TEXT    NOT NULL,
        prompt       TEXT,
        image_url    TEXT,
        phase        TEXT    NOT NULL DEFAULT 'submit',
        opens_at     REAL    NOT NULL,
        closes_at    REAL    NOT NULL,
        vote_ends_at REAL,
        message_id   INTEGER,
        channel_id   INTEGER,
        metadata     TEXT
    )
    """,

    # Submissions to a round
    """
    CREATE TABLE IF NOT EXISTS submissions (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        round_id     INTEGER NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
        user_id      INTEGER NOT NULL,
        content      TEXT    NOT NULL,
        message_id   INTEGER,
        react_count  INTEGER NOT NULL DEFAULT 0,
        submitted_at REAL    NOT NULL,
        UNIQUE(round_id, user_id)
    )
    """,

    # Bot-managed votes (for games that use bot-voting rather than raw reacts)
    """
    CREATE TABLE IF NOT EXISTS votes (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        round_id    INTEGER NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
        voter_id    INTEGER NOT NULL,
        sub_id      INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
        UNIQUE(round_id, voter_id)
    )
    """,

    # Leaderboard points
    """
    CREATE TABLE IF NOT EXISTS points (
        guild_id   INTEGER NOT NULL,
        user_id    INTEGER NOT NULL,
        game_key   TEXT    NOT NULL,
        points     INTEGER NOT NULL DEFAULT 0,
        wins       INTEGER NOT NULL DEFAULT 0,
        earned_at  REAL    NOT NULL,
        PRIMARY KEY (guild_id, user_id, game_key, earned_at)
    )
    """,

    # Voter activity log (for voter leaderboard)
    """
    CREATE TABLE IF NOT EXISTS voter_log (
        guild_id  INTEGER NOT NULL,
        user_id   INTEGER NOT NULL,
        voted_at  REAL    NOT NULL
    )
    """,

    # Canon entries (Canon or Cringe)
    """
    CREATE TABLE IF NOT EXISTS canon_log (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id   INTEGER NOT NULL,
        user_id    INTEGER NOT NULL,
        content    TEXT    NOT NULL,
        approved_at REAL   NOT NULL
    )
    """,

    # Hot Take verdicts
    """
    CREATE TABLE IF NOT EXISTS verdicts (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id   INTEGER NOT NULL,
        user_id    INTEGER NOT NULL,
        take       TEXT    NOT NULL,
        guilty     INTEGER NOT NULL,
        votes_g    INTEGER NOT NULL DEFAULT 0,
        votes_ng   INTEGER NOT NULL DEFAULT 0,
        closed_at  REAL    NOT NULL
    )
    """,

    # Scheduler queue
    """
    CREATE TABLE IF NOT EXISTS scheduler (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        job_type    TEXT    NOT NULL,
        run_at      REAL    NOT NULL,
        payload     TEXT    NOT NULL,
        done        INTEGER NOT NULL DEFAULT 0
    )
    """,
]

async def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        for stmt in CREATE_STATEMENTS:
            await db.execute(stmt)
        await db.commit()

async def fetchone(query: str, params=()):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, params) as cur:
            return await cur.fetchone()

async def fetchall(query: str, params=()):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, params) as cur:
            return await cur.fetchall()

async def execute(query: str, params=()):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(query, params)
        await db.commit()

async def executemany(query: str, data):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executemany(query, data)
        await db.commit()

async def lastrowid(query: str, params=()):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(query, params) as cur:
            await db.commit()
            return cur.lastrowid
