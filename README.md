# <img src="/VJG-main.png" height="30" alt="icon"> Vera

Vera is a public Discord bot built with **discord.py** that runs a perpetual suite of creative mini-games for your server. Games can be individually enabled/disabled per guild, with optional dedicated channels per game.

---

## Features

### 🖼️ Caption & Image Games

| Command Group | Game |
| --- | --- |
| `/caption` | **Rolling Caption Contest** — always-live image, closes at 20 submissions or 48h |
| `/blurb` | **Blurb Battle** — fake synopsis for an obscure title |
| `/wrong` | **Wrong Answers Only** — absurd misidentifications of mundane images |
| `/thumbnail` | **Thumbnail Liar** — fake clickbait titles for screenshots |

### ✍️ Writing & Wordplay Games

| Command Group | Game |
| --- | --- |
| `/pun` | **Pun Championship** — weekly theme, 5-day submission, 48h vote |
| `/oneliner` | **One-liner Tourney** — one sentence enforced, multi-line auto-rejected |
| `/worstidea` | **Worst Idea Competition** — pitch the worst possible solution |
| `/haiku` | **Haiku Smackdown** — syllable-validated (5-7-5), snarky rejections |
| `/thesaurus` | **Thesaurus Thunderdome** — unnecessarily verbose rewrites |
| `/headline` | **Headline Heist** — fill in the blanked noun to make it funnier |

### ⚖️ Judging & Taste Games

| Command Group | Game |
| --- | --- |
| `/hottake` | **Hot Take Tribunal** — community votes Guilty/Not Guilty |
| `/taste` | **Taste Test** — argue for your pick in one sentence, react to vote |
| `/vibe` | **Vibe Court** — is it a real vibe? |
| `/canon` | **Canon or Cringe** — approved entries logged permanently |

### 🏆 Leaderboards

| Command | Board |
| --- | --- |
| `/leaderboard weekly` | Rolling 7-day window |
| `/leaderboard monthly` | Rolling 30-day window |
| `/leaderboard alltime` | Never resets — the legacy hierarchy |
| `/leaderboard streak` | Current and all-time win streaks |
| `/leaderboard voter` | Most engaged judges |
| `/leaderboard underdog` | Wins by bottom-half members only |
| `/leaderboard me` | Your personal stats |

### ⚙️ Admin Commands

| Command | Description |
| --- | --- |
| `/games enable <game>` | Enable a game in this server |
| `/games disable <game>` | Disable a game |
| `/games setchannel <game> <channel>` | Set a dedicated channel for a game |
| `/games clearchannel <game>` | Remove the channel override |
| `/games list` | Show all game states for this server |

---

## Setup

### Prerequisites

- Python 3.11+
- A Discord bot token with the following **Privileged Intents** enabled in the Developer Portal:
  - **Message Content Intent**
  - **Server Members Intent**

### Installation

```bash
git clone https://github.com/augy-studios/vera-judgement-games.git vera
cd vera
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Configuration

Create a `.env` file (never commit this):

```bash
DISCORD_TOKEN=your_bot_token_here
```

Load it before running:

```bash
export $(cat .env | xargs)
```

Or use `python-dotenv` if you prefer to load it in-code (add it to `requirements.txt` and call `load_dotenv()` at the top of `main.py`).

### Running in tmux

```bash
tmux new -s vera
source .venv/bin/activate
export DISCORD_TOKEN=your_token_here
python main.py
```

Detach with `Ctrl+B`, then `D`. Reattach later with:

```bash
tmux attach -t vera
```

---

## Database

Vera uses **SQLite** stored at `data/vera.db`. The file is created automatically on first run. The `data/` directory is gitignored — back it up separately if needed.

Scheduling (round auto-close) is handled via the `scheduler` table polled every 60 seconds. No external job runner required.

---

## Project Structure

```bash
vera/
├── main.py                  # Bot entry point
├── requirements.txt
├── README.md
├── .gitignore
├── cogs/
│   ├── admin.py             # /games commands
│   ├── caption_games.py     # /caption, /blurb, /wrong, /thumbnail
│   ├── writing_games.py     # /pun, /oneliner, /worstidea, /haiku, /thesaurus, /headline
│   ├── judging_games.py     # /hottake, /taste, /vibe, /canon
│   ├── leaderboard.py       # /leaderboard
│   └── scheduler.py         # Background job poller
├── utils/
│   ├── db.py                # SQLite helpers (aiosqlite)
│   └── games.py             # Shared constants, validators, helpers
└── data/                    # Auto-created, gitignored
    └── vera.db
```

---

## Adding the Bot to a Server

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Under **OAuth2 → URL Generator**, select:
   - Scopes: `bot`, `applications.commands`
   - Bot Permissions: `Send Messages`, `Embed Links`, `Read Message History`, `Add Reactions`, `Read Messages/View Channels`
3. Use the generated URL to invite Vera to your server.

After joining, slash commands sync globally on startup (may take up to 1 hour for Discord to propagate globally).

---

## Notes

- All games are **enabled by default** for all guilds. Use `/games disable` to turn off specific games.
- Voting in react-based games (Wrong Answers Only, Thumbnail Liar, Thesaurus Thunderdome, Taste Test) is done by reacting to submitted messages. Use the `/close` command to tally reacts.
- Hot Take Tribunal, Vibe Court, and Canon or Cringe use button-based voting embedded in the post message.
- The haiku syllable counter uses a simple English heuristic and may occasionally miscount unusual words.
