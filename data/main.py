
from __future__ import annotations

import json
from html import escape as html_escape
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# =========================================================
# CONFIGURATION
# =========================================================

st.set_page_config(
    page_title="Steam Charts | What players are playing",
    page_icon="🎮",
    layout="wide",
    initial_sidebar_state="expanded",
)

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "steam_history.db"

CHARTS_URL = (
    "https://api.steampowered.com/"
    "ISteamChartsService/GetMostPlayedGames/v1/"
)
DETAILS_URL = "https://store.steampowered.com/api/appdetails"
REVIEWS_URL = "https://api.steampowered.com/IUserReviewsService/GetAppReviews/v1/"

REFRESH_OPTIONS = {
    "1 minute": 60,
    "2 minutes": 120,
    "5 minutes": 300,
    "10 minutes": 600,
}

HISTORY_DAYS = 30
MIN_SNAPSHOT_INTERVAL_SECONDS = 300  # Avoid duplicate records from widget reruns.
MAX_RETRIES = 3

# =========================================================
# THEME
# =========================================================

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&display=swap');

    :root {
        --bg: #171a16;
        --panel: #20261f;
        --panel-soft: #252d24;
        --line: rgba(201, 214, 184, .13);
        --muted: #a5ae9c;
        --text: #f0f0e8;
        --accent: #c7d99a;
        --accent-dark: #7d9660;
        --warm: #e5b27e;
    }

    html, body, [class*="css"], [data-testid="stAppViewContainer"] {
        font-family: 'DM Sans', sans-serif;
    }
    .stApp {
        background:
          radial-gradient(ellipse at 88% 0%, rgba(125, 150, 96, .13), transparent 34%),
          radial-gradient(ellipse at 5% 38%, rgba(178, 126, 78, .07), transparent 32%),
          #171a16;
        color: var(--text);
    }
    [data-testid="stHeader"] { background: rgba(23, 26, 22, .88); }
    [data-testid="stToolbar"] { right: 1rem; }
    .block-container { max-width: 1480px; padding-top: 1.6rem; padding-bottom: 2.6rem; }

    [data-testid="stSidebar"] {
        background: #1b201a;
        border-right: 1px solid rgba(201, 214, 184, .11);
    }
    [data-testid="stSidebar"] > div:first-child { padding-top: 1.2rem; }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { color: #aeb7a5; }
    [data-testid="stSidebar"] hr { border-color: rgba(201, 214, 184, .13); }
    [data-testid="stSidebar"] [role="radiogroup"] { gap: .28rem; }
    [data-testid="stSidebar"] [role="radiogroup"] label {
        border: 1px solid transparent;
        border-radius: 10px;
        padding: .55rem .68rem;
        color: #c4cbbb;
        transition: background .15s ease, border-color .15s ease;
    }
    [data-testid="stSidebar"] [role="radiogroup"] label:hover {
        background: rgba(199, 217, 154, .08);
        border-color: rgba(199, 217, 154, .17);
    }

    .brand-mark {
        display: flex; align-items: center; gap: 10px;
        color: #eff1e8; font-size: 1.06rem; font-weight: 800; letter-spacing: -.035em;
    }
    .brand-icon {
        width: 34px; height: 34px; display: grid; place-items: center;
        border-radius: 11px; background: #303b2b; border: 1px solid #46553a;
        font-size: 1.05rem;
    }
    .sidebar-note { color: #899482; font-size: .78rem; line-height: 1.5; margin-top: 7px; }

    .hero {
        position: relative; overflow: hidden; isolation: isolate;
        padding: 29px 32px; border: 1px solid rgba(201, 214, 184, .15);
        border-radius: 19px; margin-bottom: 22px;
        background: linear-gradient(112deg, #293326 0%, #242b22 57%, #292921 100%);
        box-shadow: 0 12px 34px rgba(0, 0, 0, .15);
    }
    .hero:after {
        content: ''; position: absolute; z-index: -1; width: 290px; height: 290px;
        right: -90px; top: -165px; border-radius: 50%;
        background: radial-gradient(circle, rgba(199, 217, 154, .15), transparent 69%);
    }
    .hero .eyebrow {
        color: #c4d3a5; font-size: .7rem; font-weight: 700;
        letter-spacing: .13em; margin-bottom: 10px; text-transform: uppercase;
    }
    .hero h1 {
        color: #f4f1e8; font-family: 'Fraunces', Georgia, serif;
        font-size: clamp(2rem, 4vw, 2.8rem); line-height: 1.06;
        font-weight: 600; letter-spacing: -.035em; margin: 0;
    }
    .hero p { color: #c2c8b9; font-size: .98rem; margin: 11px 0 0; max-width: 720px; line-height: 1.65; }
    .hero-badges { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 17px; }
    .hero-badge {
        display: inline-flex; align-items: center; gap: 7px; padding: 6px 10px;
        border-radius: 8px; background: rgba(13, 18, 12, .24);
        border: 1px solid rgba(201, 214, 184, .14);
        color: #d9dece; font-size: .72rem; font-weight: 600;
    }
    .hero-dot { width: 7px; height: 7px; display: inline-block; border-radius: 50%; background: #a9c77b; }

    .section-heading {
        display: flex; align-items: center; gap: 10px; color: #eff0e7;
        font-family: 'DM Sans', sans-serif; font-size: 1.05rem; font-weight: 800;
        letter-spacing: -.025em; margin: 27px 0 13px; padding-bottom: 10px;
        border-bottom: 1px solid rgba(201, 214, 184, .12);
    }
    .section-heading:before {
        content: ''; width: 4px; height: 18px; border-radius: 5px;
        background: var(--accent-dark);
    }

    [data-testid="stMetric"] {
        background: #222920; border: 1px solid rgba(201, 214, 184, .13);
        border-radius: 13px; padding: 15px 17px;
        box-shadow: 0 5px 17px rgba(0,0,0,.10); min-height: 106px;
    }
    [data-testid="stMetricLabel"] { color: #aab5a1 !important; font-size: .74rem !important; font-weight: 700 !important; letter-spacing: .025em; }
    [data-testid="stMetricValue"] { color: #f0f0e8 !important; font-family: 'DM Sans', sans-serif; font-size: clamp(1.28rem, 2vw, 1.8rem) !important; font-weight: 800 !important; letter-spacing: -.04em; }
    [data-testid="stMetricDelta"] { font-size: .75rem !important; }

    .leaderboard-row {
        display: flex; align-items: center; gap: 14px; padding: 12px 14px;
        margin: 0 0 8px; border: 1px solid rgba(201, 214, 184, .12);
        border-radius: 13px; background: #20261f;
        transition: background .15s ease, border-color .15s ease;
    }
    .leaderboard-row:hover { background: #252e23; border-color: rgba(199, 217, 154, .28); }
    .rank-badge {
        width: 39px; height: 39px; flex: 0 0 39px; display: grid; place-items: center;
        border-radius: 10px; color: #d8ddce; font-weight: 800; font-size: .95rem;
        background: #2b3328; border: 1px solid rgba(201, 214, 184, .13);
    }
    .rank-badge.top-three { color: #f3d5a9; background: #3b3326; border-color: rgba(229, 178, 126, .25); }
    .leaderboard-cover { width: 108px; height: 50px; flex: 0 0 108px; object-fit: cover; border-radius: 7px; background: #30382d; }
    .leaderboard-info { flex: 1; min-width: 0; }
    .leaderboard-title { color: #f0f0e8; font-size: .96rem; font-weight: 700; line-height: 1.3; }
    .leaderboard-subtitle { color: #9ea995; font-size: .75rem; margin-top: 5px; }
    .leaderboard-score { flex: 0 0 auto; text-align: right; color: #e7ebde; font-weight: 800; font-size: 1rem; }
    .leaderboard-score small { display: block; color: #96a08e; font-size: .66rem; font-weight: 600; margin-top: 2px; }

    .game-card {
        background: #222920; border: 1px solid rgba(201, 214, 184, .13);
        border-radius: 13px; padding: 14px 16px; margin-bottom: 10px;
    }
    .game-title { color: #f0f0e8; font-weight: 700; font-size: 1rem; }
    .game-subtitle { color: #a5ae9c; font-size: .78rem; margin-top: 5px; }
    .small-muted { color: #a5ae9c; font-size: .82rem; }

    .stButton > button, .stDownloadButton > button, .stLinkButton > a {
        border-radius: 9px; font-weight: 700;
        border: 1px solid #63784c; background: #465b38; color: #f4f3e9;
        transition: background .15s ease, border-color .15s ease;
    }
    .stButton > button:hover, .stDownloadButton > button:hover, .stLinkButton > a:hover {
        border-color: #91a873; background: #526b41; color: #fff;
    }
    [data-testid="stSelectbox"], [data-testid="stMultiSelect"] { margin-bottom: .15rem; }
    [data-testid="stSelectbox"] > div > div, [data-testid="stMultiSelect"] > div > div {
        background: #242c22; border-color: rgba(201, 214, 184, .17); border-radius: 9px;
    }
    [data-testid="stDataFrame"] { border: 1px solid rgba(201, 214, 184, .14); border-radius: 11px; overflow: hidden; }
    div[data-testid="stImage"] { border-radius: 11px; overflow: hidden; }
    [data-testid="stAlert"] { border-radius: 11px; }
    .stCaption, [data-testid="stCaptionContainer"] { color: #929d89; }
    hr { border-color: rgba(201, 214, 184, .13); }

    @media (max-width: 720px) {
        .block-container { padding-left: 1rem; padding-right: 1rem; padding-top: 1rem; }
        .hero { padding: 22px 19px; border-radius: 15px; }
        .leaderboard-row { gap: 8px; padding: 9px; }
        .leaderboard-cover { width: 72px; height: 44px; flex-basis: 72px; }
        .rank-badge { width: 32px; height: 32px; flex-basis: 32px; font-size: .85rem; }
        .leaderboard-title { font-size: .85rem; }
        .leaderboard-subtitle { font-size: .66rem; }
        .leaderboard-score { font-size: .85rem; }
        [data-testid="stMetric"] { padding: 12px; min-height: 92px; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# =========================================================
# PERSONAL VISUAL STYLES
# Each visitor gets an independent choice for their own session.
# =========================================================

THEME_PRESETS = {
    "Sage & cozy": {
        "description": "Soft greens, warm neutrals, and a relaxed feel.",
        "bg": "#171a16", "panel": "#20261f", "panel2": "#252d24", "sidebar": "#1b201a",
        "text": "#f0f0e8", "muted": "#a5ae9c", "line": "rgba(201,214,184,.15)",
        "accent": "#c7d99a", "accent_dark": "#7d9660", "warm": "#e5b27e",
        "hero1": "#293326", "hero2": "#292921", "chart_low": "#536b43",
        "good": "#a9c77b", "bad": "#c98f8a", "hover": "#303b2b",
        "chart_colors": ["#c7d99a", "#e5b27e", "#8fb9a8", "#c98f8a", "#9eacd0", "#d1c18a", "#b39acb"],
    },
    "Midnight blue": {
        "description": "Cool navy panels with crisp blue highlights.",
        "bg": "#0c1322", "panel": "#151f33", "panel2": "#1b2940", "sidebar": "#101a2c",
        "text": "#edf4ff", "muted": "#9caec7", "line": "rgba(160,190,230,.17)",
        "accent": "#8cc8ff", "accent_dark": "#3c80b7", "warm": "#c1b8ff",
        "hero1": "#172d4b", "hero2": "#1c2238", "chart_low": "#235b8a",
        "good": "#70d6b0", "bad": "#ff8794", "hover": "#203653",
        "chart_colors": ["#8cc8ff", "#c1b8ff", "#70d6b0", "#ff8794", "#f2c879", "#78d4dd", "#d6a5e8"],
    },
    "Rose garden": {
        "description": "Muted plum surfaces with soft rose accents.",
        "bg": "#1c151d", "panel": "#2a1f2b", "panel2": "#352638", "sidebar": "#241a27",
        "text": "#f8edf5", "muted": "#c0aebd", "line": "rgba(230,190,220,.16)",
        "accent": "#f2b5d0", "accent_dark": "#b5688b", "warm": "#e8c09e",
        "hero1": "#3b2637", "hero2": "#30253b", "chart_low": "#8a496f",
        "good": "#9fd4b1", "bad": "#ff8293", "hover": "#402d40",
        "chart_colors": ["#f2b5d0", "#e8c09e", "#9fd4b1", "#b9a2df", "#ff8293", "#90c9d8", "#e8d28e"],
    },
    "OLED black": {
        "description": "Deep black, quiet surfaces, and sharp contrast.",
        "bg": "#08090c", "panel": "#111318", "panel2": "#181b22", "sidebar": "#0e1015",
        "text": "#f1f3f5", "muted": "#a0a6b2", "line": "rgba(220,230,245,.14)",
        "accent": "#d8e2ee", "accent_dark": "#7c91a8", "warm": "#ffb86b",
        "hero1": "#1b1f28", "hero2": "#171c24", "chart_low": "#505d72",
        "good": "#85d6a7", "bad": "#ff7b85", "hover": "#222733",
        "chart_colors": ["#d8e2ee", "#ffb86b", "#85d6a7", "#ff7b85", "#9db9ff", "#d4a6e8", "#93dce3"],
    },
    "Warm sunset": {
        "description": "Espresso tones with amber and terracotta details.",
        "bg": "#1d1713", "panel": "#2b211a", "panel2": "#38291f", "sidebar": "#241b15",
        "text": "#fbf1e7", "muted": "#c3ae9b", "line": "rgba(240,205,170,.15)",
        "accent": "#f3c28f", "accent_dark": "#c17b45", "warm": "#f6ad74",
        "hero1": "#3a291d", "hero2": "#30231c", "chart_low": "#84532f",
        "good": "#a6cf9b", "bad": "#e7887b", "hover": "#493326",
        "chart_colors": ["#f3c28f", "#f6ad74", "#a6cf9b", "#e7887b", "#a8badc", "#d2a8ca", "#e3d28d"],
    },
}

ACTIVE_THEME = THEME_PRESETS["Sage & cozy"]


def apply_visual_theme(theme):
    """Apply the chosen palette to the app's panels and controls."""
    st.markdown(
        f"""
        <style>
        :root {{
            --app-bg: {theme['bg']}; --app-panel: {theme['panel']};
            --app-panel-2: {theme['panel2']}; --app-sidebar: {theme['sidebar']};
            --app-text: {theme['text']}; --app-muted: {theme['muted']};
            --app-line: {theme['line']}; --app-accent: {theme['accent']};
            --app-accent-dark: {theme['accent_dark']}; --app-warm: {theme['warm']};
        }}
        .stApp {{
            background: radial-gradient(ellipse at 88% 0%, color-mix(in srgb, {theme['accent_dark']} 20%, transparent), transparent 36%),
                        linear-gradient(145deg, {theme['bg']}, {theme['panel']} 58%, {theme['bg']}) !important;
            color: {theme['text']} !important;
        }}
        [data-testid="stHeader"] {{ background: color-mix(in srgb, {theme['bg']} 92%, transparent) !important; }}
        [data-testid="stSidebar"] {{ background: {theme['sidebar']} !important; border-right-color: {theme['line']} !important; }}
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
        .small-muted, .game-subtitle, .sidebar-note {{ color: {theme['muted']} !important; }}
        .hero {{ background: linear-gradient(112deg, {theme['hero1']}, {theme['hero2']}) !important; border-color: {theme['line']} !important; }}
        .hero:after {{ background: radial-gradient(circle, color-mix(in srgb, {theme['accent']} 26%, transparent), transparent 70%) !important; }}
        .hero .eyebrow, .hero-badge {{ color: {theme['accent']} !important; }}
        .hero h1, .section-heading, .leaderboard-title, .game-title {{ color: {theme['text']} !important; }}
        .hero p, .leaderboard-subtitle, .leaderboard-score small {{ color: {theme['muted']} !important; }}
        .hero-badge {{ background: color-mix(in srgb, {theme['bg']} 42%, transparent) !important; border-color: {theme['line']} !important; }}
        .hero-dot {{ background: {theme['accent']} !important; }}
        .section-heading {{ border-bottom-color: {theme['line']} !important; }}
        .section-heading:before {{ background: {theme['accent_dark']} !important; }}
        [data-testid="stMetric"] {{ background: {theme['panel']} !important; border-color: {theme['line']} !important; }}
        [data-testid="stMetricLabel"] {{ color: {theme['muted']} !important; }}
        [data-testid="stMetricValue"] {{ color: {theme['text']} !important; }}
        .leaderboard-row, .game-card {{ background: {theme['panel']} !important; border-color: {theme['line']} !important; }}
        .leaderboard-row:hover {{ background: {theme['panel2']} !important; border-color: {theme['accent_dark']} !important; }}
        .rank-badge {{ background: {theme['panel2']} !important; color: {theme['text']} !important; border-color: {theme['line']} !important; }}
        .rank-badge.top-three {{ background: color-mix(in srgb, {theme['warm']} 17%, {theme['panel']}) !important; color: {theme['warm']} !important; border-color: {theme['warm']} !important; }}
        .leaderboard-score {{ color: {theme['text']} !important; }}
        .brand-mark {{ color: {theme['text']} !important; }}
        .brand-icon {{ background: {theme['panel2']} !important; border-color: {theme['accent_dark']} !important; }}
        .stButton > button, .stDownloadButton > button, .stLinkButton > a {{
            background: {theme['accent_dark']} !important; border-color: {theme['accent_dark']} !important;
            color: #fff !important;
        }}
        .stButton > button:hover, .stDownloadButton > button:hover, .stLinkButton > a:hover {{
            background: {theme['accent']} !important; border-color: {theme['accent']} !important;
            color: {theme['bg']} !important;
        }}
        [data-testid="stSelectbox"] > div > div, [data-testid="stMultiSelect"] > div > div,
        [data-testid="stTextInput"] input, [data-testid="stNumberInput"] input,
        [data-testid="stDateInput"] input, [data-testid="stTextArea"] textarea {{
            background: {theme['panel2']} !important; border-color: {theme['line']} !important;
            color: {theme['text']} !important;
        }}
        [data-testid="stDataFrame"] {{ border-color: {theme['line']} !important; }}
        [data-testid="stAlert"] {{ border-radius: 11px; }}
        [data-testid="stCaptionContainer"], .stCaption {{ color: {theme['muted']} !important; }}
        [data-testid="stSidebar"] hr, hr {{ border-color: {theme['line']} !important; }}
        [data-testid="stSidebar"] [role="radiogroup"] label:hover {{
            background: color-mix(in srgb, {theme['accent']} 10%, transparent) !important;
            border-color: {theme['line']} !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# =========================================================
# DATABASE
# =========================================================

def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_database():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collected_at TEXT NOT NULL,
                appid INTEGER NOT NULL,
                game_name TEXT NOT NULL,
                rank INTEGER NOT NULL,
                chart_value INTEGER NOT NULL
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_snapshots_time
            ON snapshots(collected_at)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_snapshots_appid
            ON snapshots(appid)
        """)


def save_snapshot(games):
    """Store one Top 10 snapshot at most every five minutes."""
    now_dt = datetime.now()
    now = now_dt.isoformat(timespec="seconds")

    rows = [
        (
            now,
            game["appid"],
            game["name"],
            game["rank"],
            game["players"],
        )
        for game in games
    ]

    if not rows:
        return False

    with get_connection() as conn:
        latest = conn.execute(
            "SELECT MAX(collected_at) AS latest FROM snapshots"
        ).fetchone()["latest"]

        if latest:
            try:
                latest_dt = datetime.fromisoformat(latest)
                elapsed = (now_dt - latest_dt).total_seconds()
                if elapsed < MIN_SNAPSHOT_INTERVAL_SECONDS:
                    return False
            except (TypeError, ValueError):
                # If an old/invalid timestamp exists, allow a new clean snapshot.
                pass

        conn.executemany("""
            INSERT INTO snapshots (
                collected_at,
                appid,
                game_name,
                rank,
                chart_value
            )
            VALUES (?, ?, ?, ?, ?)
        """, rows)

    return True


def cleanup_old_history():
    cutoff = (
        datetime.now() - timedelta(days=HISTORY_DAYS + 2)
    ).isoformat(timespec="seconds")

    with get_connection() as conn:
        conn.execute(
            "DELETE FROM snapshots WHERE collected_at < ?",
            (cutoff,),
        )


def load_history(days=30):
    cutoff = (
        datetime.now() - timedelta(days=days)
    ).isoformat(timespec="seconds")

    with get_connection() as conn:
        df = pd.read_sql_query(
            """
            SELECT
                collected_at,
                appid,
                game_name,
                rank,
                chart_value
            FROM snapshots
            WHERE collected_at >= ?
            ORDER BY collected_at
            """,
            conn,
            params=(cutoff,),
        )

    if not df.empty:
        df["collected_at"] = pd.to_datetime(
            df["collected_at"],
            errors="coerce",
        )

    return df


initialize_database()


# =========================================================
# HTTP HELPERS
# =========================================================

@st.cache_resource
def get_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "SteamChartsCommunityDashboard/4.0"
    })
    return session


def request_json(url, params=None, timeout=25):
    """Request JSON with a small retry window for temporary Steam errors."""
    session = get_session()
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            response = session.get(
                url,
                params=params,
                timeout=timeout,
            )
            response.raise_for_status()

            try:
                payload = response.json()
            except ValueError as error:
                raise RuntimeError("Steam returned a non-JSON response.") from error

            if not isinstance(payload, dict):
                raise RuntimeError("Steam returned an unexpected JSON format.")
            return payload

        except (requests.RequestException, RuntimeError) as error:
            last_error = error
            if attempt < MAX_RETRIES - 1:
                retry_after = 0
                response = getattr(error, "response", None)
                if response is not None:
                    try:
                        retry_after = int(response.headers.get("Retry-After", 0))
                    except (TypeError, ValueError):
                        retry_after = 0
                time.sleep(max(retry_after, 1 + attempt))

    raise RuntimeError(f"Steam request failed: {last_error}")


# =========================================================
# STEAM DATA
# =========================================================

@st.cache_data(ttl=60, show_spinner=False)
def fetch_top_games():
    payload = request_json(CHARTS_URL)
    ranks = payload.get("response", {}).get("ranks", [])

    games = []

    for item in ranks:
        appid = item.get("appid")

        if not appid:
            continue

        games.append({
            "appid": int(appid),
            "rank": int(item.get("rank", len(games) + 1)),
            "players": int(item.get("peak_in_game", 0) or 0),
            "last_week_rank": item.get("last_week_rank"),
        })

    games.sort(key=lambda x: x["rank"])
    return games[:10]


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_game_details(appid):
    payload = request_json(
        DETAILS_URL,
        params={
            "appids": appid,
            "cc": "us",
            "l": "english",
        },
    )

    item = payload.get(str(appid), {})

    if not item.get("success"):
        return {}

    return item.get("data", {})


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_reviews(appid):
    """Fetch lifetime review totals using Valve's current IUserReviewsService."""
    input_json = {
        "appid": int(appid),
        "filter": 1,              # Recent sort; summary totals are lifetime totals.
        "languages": ["all"],
        "review_type": 0,         # All reviews, required for positive/negative totals.
        "purchase_type": 1,       # All purchase types.
        "num_per_page": 1,        # One review plus the aggregate summary; small response.
        "cursor": "*",            # First page includes query_summary score totals.
        "display_language": "english",
        "filter_offtopic_activity": True,
    }

    payload = request_json(
        REVIEWS_URL,
        params={
            "input_json": json.dumps(input_json, separators=(",", ":")),
        },
    )

    # Steam Service API responses are wrapped in a top-level "response" object.
    response = payload.get("response", payload)
    summary = response.get("query_summary") if isinstance(response, dict) else None

    required_fields = (
        "total_positive",
        "total_negative",
        "total_reviews",
        "review_score_desc",
    )
    if not isinstance(summary, dict) or not all(
        field in summary for field in required_fields
    ):
        raise RuntimeError(
            "Steam did not include review totals in query_summary. "
            "Check the API response or try again later."
        )

    return {
        "total_positive": int(summary["total_positive"] or 0),
        "total_negative": int(summary["total_negative"] or 0),
        "total_reviews": int(summary["total_reviews"] or 0),
        "review_score_desc": str(summary.get("review_score_desc") or "Unknown"),
        "review_score": summary.get("review_score"),
    }


def enrich_games(rankings):
    result = []

    for index, item in enumerate(rankings):
        appid = item["appid"]

        try:
            details = fetch_game_details(appid)
        except Exception:
            details = {}

        # The anonymous Steam reviews endpoint has a lower rate limit.
        # Cache each app for 30 minutes and space requests slightly apart.
        if index:
            time.sleep(0.15)

        review_error = ""
        try:
            reviews = fetch_reviews(appid)
            reviews_available = True
        except Exception as error:
            reviews = {}
            reviews_available = False
            review_error = str(error)

        release = details.get("release_date") or {}
        developers = details.get("developers") or []
        genres = details.get("genres") or []

        result.append({
            **item,
            "name": details.get("name", f"App {appid}"),
            "image": details.get("header_image", ""),
            "description": details.get("short_description", ""),
            "release_date": release.get("date", "Unknown"),
            "developers": ", ".join(developers[:3]),
            "genres": ", ".join(
                genre.get("description", "")
                for genre in genres[:4]
                if isinstance(genre, dict)
            ),
            # None means the request failed; it is not a genuine zero.
            "reviews_available": reviews_available,
            "review_error": review_error,
            "positive": reviews.get("total_positive"),
            "negative": reviews.get("total_negative"),
            "total_reviews": reviews.get("total_reviews"),
            "review_score": reviews.get("review_score_desc", "Unavailable"),
        })

    return result

# =========================================================
# FORMATTING
# =========================================================

def fmt(value):
    return f"{int(value or 0):,}"


def fmt_optional(value):
    return "Unavailable" if value is None else fmt(value)


def rank_change(game):
    previous = game.get("last_week_rank")

    if not previous:
        return "No rank last week"

    difference = previous - game["rank"]

    if difference > 0:
        return f"↑ Up {difference} places"

    if difference < 0:
        return f"↓ Down {abs(difference)} places"

    return "— Same as last week"


def player_change_text(current, previous):
    if previous is None:
        return "First recorded snapshot"

    difference = current - previous
    sign = "+" if difference > 0 else ""

    return f"{sign}{difference:,} chart value"


def header():
    st.markdown(
        """
        <div class="hero">
            <div class="eyebrow">A LITTLE LOOK AT WHAT'S POPULAR</div>
            <h1>What's everyone playing?</h1>
            <p>Browse the games topping Steam's charts, see what players think, and follow how the list changes over time.</p>
            <div class="hero-badges">
                <span class="hero-badge"><span class="hero-dot"></span> STEAM CHARTS</span>
                <span class="hero-badge">PLAYER REVIEWS</span>
                <span class="hero-badge">RECENT TRENDS</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def heading(title):
    st.markdown(
        f'<div class="section-heading">{html_escape(str(title))}</div>',
        unsafe_allow_html=True,
    )


def dark_chart(fig, height=420):
    theme = ACTIVE_THEME
    fig.update_layout(
        template="plotly_dark",
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=18, r=18, t=34, b=18),
        legend_title_text="",
        colorway=theme["chart_colors"],
        font=dict(family="DM Sans, sans-serif", color=theme["text"], size=12),
        hoverlabel=dict(bgcolor=theme["panel2"], bordercolor=theme["accent_dark"], font=dict(color=theme["text"])),
        xaxis=dict(showgrid=False, zerolinecolor=theme["line"], linecolor=theme["line"]),
        yaxis=dict(gridcolor=theme["line"], zerolinecolor=theme["line"], linecolor=theme["line"]),
    )
    return fig


# =========================================================
# CHART BUILDERS — each section offers several visual styles
# =========================================================

def make_player_chart(df, chart_type):
    """Build a selectable chart for Steam's Top 10 chart values."""
    labels = {"players": "Steam chart figure", "name": "Game"}

    if chart_type == "Horizontal bars":
        fig = px.bar(
            df, x="players", y="name", orientation="h", text="players",
            color="players", color_continuous_scale=[ACTIVE_THEME["chart_low"], ACTIVE_THEME["accent"]], labels=labels,
        )
        fig.update_layout(yaxis={"categoryorder": "total ascending"}, coloraxis_showscale=False)
    elif chart_type == "Vertical bars":
        fig = px.bar(df, x="name", y="players", text="players", color="name", labels=labels)
        fig.update_layout(xaxis_tickangle=-30, showlegend=False)
    elif chart_type == "Line":
        fig = px.line(df, x="name", y="players", markers=True, text="players", labels=labels)
        fig.update_traces(line_width=3, marker_size=9)
        fig.update_layout(xaxis_tickangle=-30)
    elif chart_type == "Area":
        fig = px.area(df, x="name", y="players", labels=labels)
        fig.update_layout(xaxis_tickangle=-30)
    elif chart_type == "Scatter":
        fig = px.scatter(df, x="name", y="players", size="players", color="rank", hover_name="name", labels=labels)
        fig.update_layout(xaxis_tickangle=-30)
    elif chart_type == "Donut":
        fig = px.pie(df, names="name", values="players", hole=0.58, labels=labels)
    else:  # Treemap
        fig = px.treemap(df, path=["name"], values="players", color="players", color_continuous_scale=[ACTIVE_THEME["chart_low"], ACTIVE_THEME["accent"]])
        fig.update_layout(coloraxis_showscale=False)

    return dark_chart(fig, 470)


def make_review_chart(df, chart_type, height=430):
    """Build a selectable comparison of positive and negative review totals."""
    long_df = df.melt(
        id_vars=["name"],
        value_vars=["positive", "negative"],
        var_name="Review type",
        value_name="Reviews",
    )
    long_df["Review type"] = long_df["Review type"].map({
        "positive": "Positive", "negative": "Negative"
    })
    colors = {"Positive": ACTIVE_THEME["good"], "Negative": ACTIVE_THEME["bad"]}

    if chart_type == "Grouped bars":
        fig = px.bar(long_df, x="name", y="Reviews", color="Review type", barmode="group", color_discrete_map=colors)
        fig.update_layout(xaxis_tickangle=-30)
    elif chart_type == "Stacked bars":
        fig = px.bar(long_df, x="name", y="Reviews", color="Review type", barmode="stack", color_discrete_map=colors)
        fig.update_layout(xaxis_tickangle=-30)
    elif chart_type == "Horizontal bars":
        fig = px.bar(long_df, x="Reviews", y="name", color="Review type", barmode="group", orientation="h", color_discrete_map=colors)
        fig.update_layout(yaxis={"categoryorder": "total ascending"})
    elif chart_type == "Line":
        fig = px.line(long_df, x="name", y="Reviews", color="Review type", markers=True, color_discrete_map=colors)
        fig.update_layout(xaxis_tickangle=-30)
    elif chart_type == "Area":
        fig = px.area(long_df, x="name", y="Reviews", color="Review type", color_discrete_map=colors)
        fig.update_layout(xaxis_tickangle=-30)
    else:  # Donut summarizes sentiment across all currently displayed games.
        totals = pd.DataFrame({
            "Review type": ["Positive", "Negative"],
            "Reviews": [int(df["positive"].sum()), int(df["negative"].sum())],
        })
        fig = px.pie(totals, names="Review type", values="Reviews", hole=0.58, color="Review type", color_discrete_map=colors)

    return dark_chart(fig, height)


def make_history_chart(df, chart_type, height=460):
    """Build a selectable time-series view of collected Steam chart values."""
    labels = {
        "collected_at": "Time",
        "chart_value": "Steam chart figure",
        "game_name": "Game",
    }
    if chart_type == "Line":
        fig = px.line(df, x="collected_at", y="chart_value", color="game_name", markers=True, labels=labels)
    elif chart_type == "Area":
        fig = px.area(df, x="collected_at", y="chart_value", color="game_name", labels=labels)
    elif chart_type == "Scatter":
        fig = px.scatter(df, x="collected_at", y="chart_value", color="game_name", symbol="game_name", labels=labels)
    else:  # Bars
        fig = px.bar(df, x="collected_at", y="chart_value", color="game_name", barmode="group", labels=labels)
    return dark_chart(fig, height)


# =========================================================
# SIDEBAR
# =========================================================

# Session-level preferences. Each visitor can customise their own view.
SESSION_DEFAULTS = {
    # App preferences use non-widget keys so they survive navigation between pages.
    "app_visual_style": "Sage & cozy",
    "app_auto_refresh": True,
    "app_refresh_label": "5 minutes",
    "app_default_player_chart": "Horizontal bars",
    "app_default_review_chart": "Grouped bars",
    "app_default_history_chart": "Line",
}
for setting_key, setting_value in SESSION_DEFAULTS.items():
    if setting_key not in st.session_state:
        st.session_state[setting_key] = setting_value

# Keep both the sidebar quick controls and the full Settings page in sync.
PREFERENCE_WIDGETS = {
    "app_visual_style": ["sidebar_visual_style_input", "settings_visual_style_input"],
    "app_auto_refresh": ["sidebar_auto_refresh_input", "settings_auto_refresh_input"],
    "app_refresh_label": ["sidebar_refresh_interval_input", "settings_refresh_interval_input"],
    "app_default_player_chart": ["settings_default_player_chart_input"],
    "app_default_review_chart": ["settings_default_review_chart_input"],
    "app_default_history_chart": ["settings_default_history_chart_input"],
}

for preference_key, widget_keys in PREFERENCE_WIDGETS.items():
    for widget_key in widget_keys:
        if widget_key not in st.session_state:
            st.session_state[widget_key] = st.session_state[preference_key]


def save_setting(widget_key, preference_key):
    """Save a widget selection and mirror it to the matching settings control."""
    value = st.session_state[widget_key]
    st.session_state[preference_key] = value
    for other_widget_key in PREFERENCE_WIDGETS.get(preference_key, []):
        if other_widget_key != widget_key:
            st.session_state[other_widget_key] = value


def save_visual_style():
    save_setting("settings_visual_style_input", "app_visual_style")


def save_sidebar_visual_style():
    save_setting("sidebar_visual_style_input", "app_visual_style")


def save_auto_refresh():
    save_setting("settings_auto_refresh_input", "app_auto_refresh")


def save_sidebar_auto_refresh():
    save_setting("sidebar_auto_refresh_input", "app_auto_refresh")


def save_refresh_interval():
    save_setting("settings_refresh_interval_input", "app_refresh_label")


def save_sidebar_refresh_interval():
    save_setting("sidebar_refresh_interval_input", "app_refresh_label")


def save_default_player_chart():
    save_setting("settings_default_player_chart_input", "app_default_player_chart")


def save_default_review_chart():
    save_setting("settings_default_review_chart_input", "app_default_review_chart")


def save_default_history_chart():
    save_setting("settings_default_history_chart_input", "app_default_history_chart")

with st.sidebar:
    st.markdown("<div class='brand-mark'><span class='brand-icon'>🎮</span> Steam, lately</div>", unsafe_allow_html=True)
    st.markdown("<div class='sidebar-note'>A friendly snapshot of what people are playing.</div>", unsafe_allow_html=True)

    st.divider()
    page = st.radio(
        "EXPLORE",
        [
            "Dashboard",
            "Game Explorer",
            "Game Comparison",
            "Player History",
            "Data & Export",
            "Settings",
            "About",
        ],
        format_func=lambda item: "⚙️  Settings" if item == "Settings" else item,
    )

    st.divider()
    # Compact controls live exactly beneath the navigation, where visitors can
    # reach the most-used preferences without leaving the page they are viewing.
    with st.expander("⚙️  Quick settings", expanded=(page == "Settings")):
        st.caption("A few handy controls for your view.")
        st.selectbox(
            "Visual style",
            list(THEME_PRESETS.keys()),
            key="sidebar_visual_style_input",
            on_change=save_sidebar_visual_style,
        )
        st.toggle(
            "Automatic updates",
            key="sidebar_auto_refresh_input",
            on_change=save_sidebar_auto_refresh,
        )
        st.selectbox(
            "Refresh interval",
            list(REFRESH_OPTIONS.keys()),
            key="sidebar_refresh_interval_input",
            on_change=save_sidebar_refresh_interval,
            disabled=not st.session_state["app_auto_refresh"],
        )
        st.caption("For chart defaults and more options, open the Settings page above.")

    st.divider()
    st.caption("Using public Steam data")
    st.caption("No account connection needed.")

visual_style = st.session_state["app_visual_style"]
auto_refresh = bool(st.session_state["app_auto_refresh"])
refresh_label = st.session_state["app_refresh_label"]
refresh_seconds = REFRESH_OPTIONS.get(refresh_label, 300)

ACTIVE_THEME = THEME_PRESETS[visual_style]
apply_visual_theme(ACTIVE_THEME)

if auto_refresh:
    st_autorefresh(
        interval=refresh_seconds * 1000,
        key="steam_pro_refresh",
    )


# =========================================================
# LOAD DASHBOARD
# =========================================================

header()

if "games" not in st.session_state:
    st.session_state.games = []

if "last_updated" not in st.session_state:
    st.session_state.last_updated = None

try:
    with st.spinner("Connecting to Steam..."):
        rankings = fetch_top_games()

        if not rankings:
            raise RuntimeError("Steam returned no rankings.")

        games = enrich_games(rankings)

        if not games:
            raise RuntimeError("No games could be loaded.")

        st.session_state.games = games
        st.session_state.last_updated = datetime.now()

        # Save only once for each successful dashboard load.
        save_snapshot(games)
        cleanup_old_history()

except Exception as error:
    games = st.session_state.games

    if games:
        st.warning(
            "Steam did not send a fresh update just now, so you are seeing the last version that loaded successfully."
        )
    else:
        st.error(f"Unable to load Steam data: {error}")
        st.info(
            "Check your connection, then try the update button in the sidebar."
        )
        st.stop()

last_updated = st.session_state.last_updated

if last_updated:
    st.caption(
        "Updated "
        + last_updated.strftime("%b %d at %I:%M %p").replace(" 0", " ")
    )

top_game = games[0]
total_chart_value = sum(g["players"] for g in games)
reviewed_games = [g for g in games if g.get("reviews_available")]
review_data_count = len(reviewed_games)
total_reviews = sum(g["total_reviews"] or 0 for g in reviewed_games)

history_30 = load_history(30)


# =========================================================
# DASHBOARD
# =========================================================

if page == "Dashboard":

    heading("A quick look")

    a, b, c, d = st.columns(4)

    with a:
        st.metric(
            "At the top",
            top_game["name"][:24],
            "Currently #1",
        )

    with b:
        st.metric(
            "Steam chart figure",
            fmt(top_game["players"]),
            "Steam-reported figure",
        )

    with c:
        st.metric(
            "Top 10 combined",
            fmt(total_chart_value),
            "Across these 10 games",
        )

    with d:
        st.metric(
            "Reviews counted",
            fmt(total_reviews) if review_data_count else "Unavailable",
            f"Available for {review_data_count} of 10 games",
        )

    heading("The games at the top")

    for game in games:
        rank = int(game["rank"])
        rank_class = "rank-badge top-three" if rank <= 3 else "rank-badge"
        cover_url = game.get("image") or ""
        cover_html = (
            f'<img class="leaderboard-cover" src="{html_escape(cover_url, quote=True)}" alt="">'
            if cover_url.startswith("https://") else
            '<div class="leaderboard-cover" style="display:grid;place-items:center;color:#7390b2;font-size:1.2rem">🎮</div>'
        )
        game_name = html_escape(str(game.get("name", "Unknown game")))
        rating = html_escape(str(game.get("review_score") if game.get("reviews_available") else "Reviews unavailable"))
        movement = html_escape(rank_change(game))
        st.markdown(
            f"""
            <div class="leaderboard-row">
                <div class="{rank_class}">{rank:02d}</div>
                {cover_html}
                <div class="leaderboard-info">
                    <div class="leaderboard-title">{game_name}</div>
                    <div class="leaderboard-subtitle">{rating} &nbsp;·&nbsp; {movement}</div>
                </div>
                <div class="leaderboard-score">{fmt(game['players'])}<small>Steam chart figure</small></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    heading("How the chart compares")

    player_df = pd.DataFrame(games)
    player_chart_options = ["Horizontal bars", "Vertical bars", "Line", "Area", "Scatter", "Donut", "Treemap"]
    player_chart_saved = st.session_state.get("dashboard_player_chart_type", st.session_state["app_default_player_chart"])
    player_chart_index = player_chart_options.index(player_chart_saved) if player_chart_saved in player_chart_options else 0
    player_chart_type = st.selectbox(
        "View this chart as",
        player_chart_options,
        index=player_chart_index,
        key="dashboard_player_chart_type",
    )
    st.plotly_chart(
        make_player_chart(player_df, player_chart_type),
        use_container_width=True,
    )

    heading("What players think")

    review_df = pd.DataFrame(reviewed_games)
    if review_df.empty:
        st.warning(
            "Steam has not shared review totals for these games just now. "
            "The app will retry after the review-data cache expires."
        )
    else:
        review_chart_options = ["Grouped bars", "Stacked bars", "Horizontal bars", "Line", "Area", "Donut"]
        review_chart_saved = st.session_state.get("dashboard_review_chart_type", st.session_state["app_default_review_chart"])
        review_chart_index = review_chart_options.index(review_chart_saved) if review_chart_saved in review_chart_options else 0
        review_chart_type = st.selectbox(
            "View reviews as",
            review_chart_options,
            index=review_chart_index,
            key="dashboard_review_chart_type",
        )
        st.plotly_chart(
            make_review_chart(review_df, review_chart_type, height=430),
            use_container_width=True,
        )
        if review_data_count < len(games):
            st.caption(
                f"Review data loaded for {review_data_count} of {len(games)} games. "
                "Unavailable games are omitted rather than shown as zero."
            )

    heading("How the list has moved")

    if not history_30.empty:
        history_chart_options = ["Line", "Area", "Scatter", "Bars"]
        history_chart_saved = st.session_state.get("dashboard_history_chart_type", st.session_state["app_default_history_chart"])
        history_chart_index = history_chart_options.index(history_chart_saved) if history_chart_saved in history_chart_options else 0
        history_chart_type = st.selectbox(
            "View the history as",
            history_chart_options,
            index=history_chart_index,
            key="dashboard_history_chart_type",
        )
        st.plotly_chart(
            make_history_chart(history_30, history_chart_type, height=390),
            use_container_width=True,
        )

        snapshot_count = history_30["collected_at"].nunique()
        st.caption(
            f"{snapshot_count:,} collection points · "
            f"{len(history_30):,} game records · one snapshot at most every 5 minutes."
        )
    else:
        st.info(
            "Your history will build as the app collects snapshots. "
            "It can take a little while for a useful trend to appear."
        )

# =========================================================
# GAME EXPLORER
# =========================================================

elif page == "Game Explorer":

    heading("Get to know a game")

    names = [game["name"] for game in games]

    selected_name = st.selectbox(
        "Pick a game",
        names,
    )

    game = next(
        g for g in games if g["name"] == selected_name
    )

    left, right = st.columns([1.05, 2.15], gap="large")

    with left:
        if game["image"]:
            st.image(game["image"], use_container_width=True)
        else:
            st.info("No cover image available.")
        st.markdown(
            f"<div class='game-card'><div class='game-title'>#{game['rank']} on Steam Charts</div>"
            f"<div class='game-subtitle'>App ID {game['appid']} · {html_escape(str(game['genres'] or 'Genre unavailable'))}</div></div>",
            unsafe_allow_html=True,
        )

    with right:
        st.title(game["name"])
        st.write(game["description"] or "Steam has not provided a description for this game.")
        m1, m2, m3 = st.columns(3)
        with m1:
            st.metric("Steam chart figure", fmt(game["players"]))
        with m2:
            st.metric("Current rank", f"#{game['rank']}")
        with m3:
            st.metric("Review rating", game["review_score"] if game["reviews_available"] else "Unavailable")
        st.markdown("#### Game information")
        info_left, info_right = st.columns(2)
        with info_left:
            st.write(f"**Release date:** {game['release_date']}")
            st.write(f"**Developer:** {game['developers'] or 'Unknown'}")
        with info_right:
            st.write(f"**Previous weekly rank:** {game['last_week_rank'] or 'Unknown'}")
            st.write(f"**Genres:** {game['genres'] or 'Unknown'}")
        st.link_button(
            "↗  Open on Steam Store",
            f"https://store.steampowered.com/app/{game['appid']}/",
        )

    heading("Player reviews")

    x, y, z = st.columns(3)

    with x:
        st.metric("Positive", fmt_optional(game["positive"]))

    with y:
        st.metric("Negative", fmt_optional(game["negative"]))

    with z:
        st.metric("Total reviews", fmt_optional(game["total_reviews"]))

    if not game["reviews_available"]:
        st.warning(
            "Steam review totals could not be loaded for this game. "
            "The values above are marked unavailable, not zero."
        )
        if game.get("review_error"):
            with st.expander("Technical details"):
                st.code(game["review_error"])
    elif (game["positive"] or 0) + (game["negative"] or 0) > 0:
        review_fig = px.pie(
            names=["Positive", "Negative"],
            values=[game["positive"], game["negative"]],
            hole=0.65,
            color=["Positive", "Negative"],
            color_discrete_map={
                "Positive": ACTIVE_THEME["good"],
                "Negative": ACTIVE_THEME["bad"],
            },
        )
        st.plotly_chart(
            dark_chart(review_fig, 350),
            use_container_width=True,
        )


# =========================================================
# GAME COMPARISON
# =========================================================

elif page == "Game Comparison":

    heading("Put games side by side")

    options = [game["name"] for game in games]

    selected_names = st.multiselect(
        "Which games should we compare?",
        options,
        default=options[:3],
        max_selections=10,
    )

    selected_games = [
        game for game in games
        if game["name"] in selected_names
    ]

    if len(selected_games) < 2:
        st.info("Select at least two games to compare.")
    else:
        compare_df = pd.DataFrame(selected_games)

        st.markdown("#### Chart figures")
        compare_player_options = ["Horizontal bars", "Vertical bars", "Line", "Area", "Scatter", "Donut", "Treemap"]
        compare_player_saved = st.session_state.get("comparison_player_chart_type", st.session_state["app_default_player_chart"])
        compare_player_index = compare_player_options.index(compare_player_saved) if compare_player_saved in compare_player_options else 1
        player_compare_type = st.selectbox(
            "Show the figures as",
            compare_player_options,
            index=compare_player_index,
            key="comparison_player_chart_type",
        )
        st.plotly_chart(
            make_player_chart(compare_df, player_compare_type),
            use_container_width=True,
        )

        st.markdown("#### Review comparison")

        review_compare_df = compare_df[compare_df["reviews_available"]].copy()
        if review_compare_df.empty:
            st.warning("Review statistics are unavailable for the selected games.")
        else:
            compare_review_options = ["Grouped bars", "Stacked bars", "Horizontal bars", "Line", "Area", "Donut"]
            compare_review_saved = st.session_state.get("comparison_review_chart_type", st.session_state["app_default_review_chart"])
            compare_review_index = compare_review_options.index(compare_review_saved) if compare_review_saved in compare_review_options else 0
            review_compare_type = st.selectbox(
                "Show reviews as",
                compare_review_options,
                index=compare_review_index,
                key="comparison_review_chart_type",
            )
            st.plotly_chart(
                make_review_chart(review_compare_df, review_compare_type, height=420),
                use_container_width=True,
            )
            missing_review_games = len(compare_df) - len(review_compare_df)
            if missing_review_games:
                st.caption(
                    f"{missing_review_games} selected game(s) omitted because review data is unavailable."
                )

        st.markdown("#### The details")

        table = compare_df[
            [
                "name",
                "rank",
                "players",
                "review_score",
                "positive",
                "negative",
                "total_reviews",
            ]
        ].copy()
        # Keep numeric review data intact for charts, but build a separate
        # display-safe table. Recent pandas versions (including pandas 3.x)
        # reject assigning strings into int/float columns with .loc.
        review_columns = [
            "review_score", "positive", "negative", "total_reviews"
        ]
        reviews_available = (
            compare_df["reviews_available"]
            .fillna(False)
            .astype(bool)
            .tolist()
        )
        for column in review_columns:
            original_values = table[column].tolist()
            table[column] = [
                value if available else "Unavailable"
                for available, value in zip(reviews_available, original_values)
            ]
        table = table.rename(columns={
            "name": "Game",
            "rank": "Rank",
            "players": "Steam chart figure",
            "review_score": "Rating",
            "positive": "Positive",
            "negative": "Negative",
            "total_reviews": "Total reviews",
        })

        st.dataframe(
            table,
            use_container_width=True,
            hide_index=True,
        )


# =========================================================
# PLAYER HISTORY
# =========================================================

elif page == "Player History":

    heading("The chart over time")

    period = st.selectbox(
        "Look back over",
        ["24 hours", "7 days", "30 days"],
        index=2,
    )

    days = {
        "24 hours": 1,
        "7 days": 7,
        "30 days": 30,
    }[period]

    history = load_history(days)

    if history.empty:
        st.info(
            "No history has been collected for this period yet. "
            "Keep the app open; snapshots are collected when the dashboard successfully refreshes."
        )
    else:
        game_names = sorted(history["game_name"].unique())

        chosen = st.multiselect(
            "Show these games",
            game_names,
            default=game_names[:3],
        )

        filtered = history[
            history["game_name"].isin(chosen)
        ]

        if not filtered.empty:
            history_view_options = ["Line", "Area", "Scatter", "Bars"]
            history_view_saved = st.session_state.get("player_history_chart_type", st.session_state["app_default_history_chart"])
            history_view_index = history_view_options.index(history_view_saved) if history_view_saved in history_view_options else 0
            history_chart_type = st.selectbox(
                "View the timeline as",
                history_view_options,
                index=history_view_index,
                key="player_history_chart_type",
            )
            st.plotly_chart(
                make_history_chart(filtered, history_chart_type, height=480),
                use_container_width=True,
            )

        a, b, c = st.columns(3)

        with a:
            st.metric(
                "Game records",
                fmt(len(history)),
            )

        with b:
            st.metric(
                "Collection points",
                fmt(history["collected_at"].nunique()),
            )

        with c:
            st.metric(
                "Time period",
                period,
            )

        st.markdown("#### Collected snapshots")

        st.dataframe(
            history.sort_values(
                "collected_at",
                ascending=False,
            ),
            use_container_width=True,
            hide_index=True,
        )


# =========================================================
# DATA & EXPORT
# =========================================================

elif page == "Data & Export":

    heading("Your data")

    st.write(
        "Save a copy of the current chart or the history this app has collected."
    )

    current_df = pd.DataFrame(games)

    st.markdown("#### Current top 10")

    st.dataframe(
        current_df,
        use_container_width=True,
        hide_index=True,
    )

    st.download_button(
        "⬇️ Download current Top 10 CSV",
        data=current_df.to_csv(
            index=False
        ).encode("utf-8-sig"),
        file_name="steam_top10.csv",
        mime="text/csv",
        use_container_width=True,
    )

    st.markdown("#### Collected history")

    all_history = load_history(30)

    if all_history.empty:
        st.info("No historical data available yet.")
    else:
        st.metric(
            "Stored game records",
            fmt(len(all_history)),
        )

        st.download_button(
            "⬇️ Download history CSV",
            data=all_history.to_csv(
                index=False
            ).encode("utf-8-sig"),
            file_name="steam_history_30_days.csv",
            mime="text/csv",
            use_container_width=True,
        )

    st.markdown("#### A note about saved history")

    st.caption(f"Database file: {DB_PATH.name}")
    st.caption("History retention: approximately 30 days.")
    st.caption("The app stores at most one collection point every 5 minutes to avoid duplicate records from page interactions.")
    st.caption(
        "This SQLite database is local to the app environment. "
        "For reliable long-term cloud history, connect an external database."
    )


# =========================================================
# SETTINGS
# =========================================================

elif page == "Settings":

    heading("Settings")
    st.write("Make the tracker feel right for you. These preferences apply to your current app session.")

    appearance_tab, updates_tab, charts_tab = st.tabs(["🎨  Appearance", "↻  Updates", "📊  Charts"])

    with appearance_tab:
        st.markdown("#### Choose your look")
        st.caption("Pick a palette. The dashboard colours update automatically after you choose one.")
        style_names = list(THEME_PRESETS.keys())
        visual_style = st.selectbox(
            "Visual style",
            style_names,
            index=style_names.index(st.session_state["app_visual_style"]),
            key="settings_visual_style_input",
            on_change=save_visual_style,
            help="Your choice changes the app panels, buttons and chart palette.",
        )
        selected_theme = THEME_PRESETS[visual_style]
        swatch_cols = st.columns(4)
        swatch_items = [
            ("Background", selected_theme["bg"]),
            ("Cards", selected_theme["panel"]),
            ("Accent", selected_theme["accent"]),
            ("Highlight", selected_theme["warm"]),
        ]
        for swatch_col, (swatch_name, swatch_color) in zip(swatch_cols, swatch_items):
            with swatch_col:
                st.markdown(
                    f"<div style='height:38px;border-radius:10px;background:{swatch_color};border:1px solid {selected_theme['line']}'></div>",
                    unsafe_allow_html=True,
                )
                st.caption(swatch_name)
        st.info(selected_theme["description"])
        st.caption("Theme choices are kept for this browser session; they are not shared between visitors.")

    with updates_tab:
        st.markdown("#### Keep the numbers fresh")
        st.toggle(
            "Check for updates automatically",
            value=bool(st.session_state["app_auto_refresh"]),
            key="settings_auto_refresh_input",
            on_change=save_auto_refresh,
            help="When turned off, the app only updates when you request it.",
        )
        st.selectbox(
            "Refresh interval",
            list(REFRESH_OPTIONS.keys()),
            index=list(REFRESH_OPTIONS.keys()).index(st.session_state["app_refresh_label"]),
            key="settings_refresh_interval_input",
            on_change=save_refresh_interval,
            disabled=not st.session_state["app_auto_refresh"],
        )
        if st.button("↻  Check Steam now", use_container_width=True, key="settings_refresh_now"):
            fetch_top_games.clear()
            fetch_game_details.clear()
            fetch_reviews.clear()
            st.rerun()
        if st.session_state["app_auto_refresh"]:
            st.caption(f"Automatic checks are set for every {st.session_state['app_refresh_label'].lower()}.")
        else:
            st.caption("Automatic checks are paused. Use the button above whenever you want fresh data.")

    with charts_tab:
        st.markdown("#### Pick your usual chart styles")
        st.caption("These become the starting chart styles on the dashboard, comparison and history pages.")
        player_options = ["Horizontal bars", "Vertical bars", "Line", "Area", "Scatter", "Donut", "Treemap"]
        review_options = ["Grouped bars", "Stacked bars", "Horizontal bars", "Line", "Area", "Donut"]
        history_options = ["Line", "Area", "Scatter", "Bars"]
        default_player = st.selectbox(
            "Game popularity chart",
            player_options,
            index=player_options.index(st.session_state["app_default_player_chart"]),
            key="settings_default_player_chart_input",
            on_change=save_default_player_chart,
        )
        default_review = st.selectbox(
            "Review chart",
            review_options,
            index=review_options.index(st.session_state["app_default_review_chart"]),
            key="settings_default_review_chart_input",
            on_change=save_default_review_chart,
        )
        default_history = st.selectbox(
            "History chart",
            history_options,
            index=history_options.index(st.session_state["app_default_history_chart"]),
            key="settings_default_history_chart_input",
            on_change=save_default_history_chart,
        )
        if st.button("Apply chart preferences", use_container_width=True, key="apply_chart_defaults"):
            # These chart widgets are not instantiated on the Settings page.
            for key in ["dashboard_player_chart_type", "comparison_player_chart_type"]:
                st.session_state[key] = default_player
            for key in ["dashboard_review_chart_type", "comparison_review_chart_type"]:
                st.session_state[key] = default_review
            for key in ["dashboard_history_chart_type", "player_history_chart_type"]:
                st.session_state[key] = default_history
            st.success("Your chart preferences have been applied.")

    st.divider()
    st.markdown("#### About these settings")
    st.caption("Settings are saved for your active session and stay in place as you move between pages. They reset when the session expires.")


# =========================================================
# ABOUT
# =========================================================

elif page == "About":

    heading("About this tracker")

    st.markdown(
        """
        Steam Analytics Pro is an unofficial dashboard for exploring
        Steam's most-played games and public review information.

        **Features**

        - Top 10 Steam chart rankings.
        - Steam chart player values.
        - Weekly ranking comparison.
        - Store images and game descriptions.
        - Positive and negative review summaries.
        - Game comparison.
        - 24-hour, 7-day and 30-day history views.
        - SQLite snapshot collection.
        - CSV exports.
        - Automatic refresh.
        - Selectable player, review and history chart styles.

        **Data sources**

        - Steam Charts Service API.
        - Steam Store App Details API.
        - Steamworks IUserReviewsService GetAppReviews API (current reviews endpoint).

        **Important limitations**

        - Steam controls when chart data is updated.
        - The chart value is not guaranteed to be an instantaneous live count.
        - Historical collection begins after deployment.
        - History is collected only when the app successfully loads new data, at most once every five minutes.
        - Streamlit Cloud may pause inactive apps, so history does not collect while the app is asleep.
        - SQLite storage on Streamlit Cloud is not guaranteed to survive
          environment replacement or redeployment.
        - Review summaries are aggregate totals, not historical review data.
        - Review data may be unavailable temporarily due to Steam rate limits; unavailable values are not displayed as zero.
        - Anonymous review API results may be cached by Steam for up to 10 minutes.

        This project is not affiliated with Valve Corporation.
        """
    )

    st.link_button(
        "Official Steam Charts",
        "https://store.steampowered.com/charts/",
    )

    st.link_button(
        "Steam Store",
        "https://store.steampowered.com/",
    )

# =========================================================
# FOOTER
# =========================================================

st.divider()

st.markdown(
    "<div style='text-align:center;padding:12px 0 2px;color:#7186a2;font-size:.72rem;letter-spacing:.08em'>"
    "STEAM, LATELY · VERSION 4.2 · YOUR STEAM, YOUR SETTINGS"
    "</div>",
    unsafe_allow_html=True,
)
