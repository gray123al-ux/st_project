
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
    page_title="Steam Analytics Pro | Command Center",
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
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;600;700&display=swap');

    :root {
        --bg: #080d18;
        --panel: #111c2e;
        --panel-2: #15243a;
        --line: rgba(148, 163, 184, .16);
        --muted: #91a2ba;
        --text: #eef4ff;
        --blue: #69a7ff;
        --cyan: #59d2e8;
    }

    html, body, [class*="css"], [data-testid="stAppViewContainer"] {
        font-family: 'DM Sans', sans-serif;
    }

    .stApp {
        background:
          radial-gradient(ellipse at 82% -8%, rgba(37, 99, 235, .22), transparent 34%),
          radial-gradient(ellipse at 6% 18%, rgba(8, 145, 178, .09), transparent 30%),
          linear-gradient(145deg, #080d18 0%, #0b1423 52%, #080d18 100%);
        color: var(--text);
    }

    [data-testid="stHeader"] { background: rgba(8, 13, 24, .72); }
    [data-testid="stToolbar"] { right: 1rem; }
    .block-container { max-width: 1540px; padding-top: 1.7rem; padding-bottom: 2.5rem; }

    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0d1728 0%, #09111e 100%);
        border-right: 1px solid rgba(148, 163, 184, .13);
    }
    [data-testid="stSidebar"] > div:first-child { padding-top: 1.3rem; }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { color: #9fb0c7; }
    [data-testid="stSidebar"] hr { border-color: rgba(148, 163, 184, .14); }
    [data-testid="stSidebar"] [role="radiogroup"] { gap: .35rem; }
    [data-testid="stSidebar"] [role="radiogroup"] label {
        border: 1px solid transparent; border-radius: 11px; padding: .58rem .72rem;
        transition: all .18s ease; color: #bdc9da;
    }
    [data-testid="stSidebar"] [role="radiogroup"] label:hover {
        background: rgba(96, 165, 250, .09); border-color: rgba(96, 165, 250, .2);
    }

    .hero {
        position: relative; overflow: hidden; isolation: isolate;
        padding: 30px 34px; border: 1px solid rgba(125, 170, 230, .25);
        border-radius: 22px; margin-bottom: 24px;
        background: linear-gradient(112deg, rgba(24, 50, 91, .96), rgba(17, 31, 52, .96) 56%, rgba(14, 26, 43, .98));
        box-shadow: 0 18px 55px rgba(0, 0, 0, .22), inset 0 1px 0 rgba(255,255,255,.06);
    }
    .hero:after {
        content: ''; position: absolute; z-index: -1; width: 330px; height: 330px;
        right: -95px; top: -175px; border-radius: 50%;
        background: radial-gradient(circle, rgba(69, 155, 255, .28), transparent 68%);
    }
    .hero .eyebrow { color: #83c5ff; font-size: .72rem; font-weight: 800; letter-spacing: .19em; margin-bottom: 10px; }
    .hero h1 {
        color: #fff; font-family: 'Space Grotesk', sans-serif; font-size: clamp(1.8rem, 4vw, 2.65rem);
        line-height: 1.08; font-weight: 700; letter-spacing: -.045em; margin: 0;
    }
    .hero p { color: #b6c8e2; font-size: .98rem; margin: 11px 0 0; max-width: 690px; }
    .hero-badges { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 19px; }
    .hero-badge {
        display: inline-flex; align-items: center; gap: 7px; padding: 6px 11px;
        border-radius: 999px; background: rgba(8, 17, 31, .42); border: 1px solid rgba(173, 203, 245, .18);
        color: #d7e7fb; font-size: .72rem; font-weight: 700;
    }
    .hero-dot { width: 7px; height: 7px; display: inline-block; border-radius: 50%; background: #42d392; box-shadow: 0 0 12px rgba(66,211,146,.7); }

    .section-heading {
        display: flex; align-items: center; gap: 11px; color: #f3f7ff;
        font-family: 'Space Grotesk', sans-serif; font-size: 1.15rem; font-weight: 700;
        letter-spacing: -.02em; margin: 28px 0 13px; padding-bottom: 10px;
        border-bottom: 1px solid rgba(148, 163, 184, .13);
    }
    .section-heading:before { content: ''; width: 4px; height: 21px; border-radius: 5px; background: linear-gradient(180deg, #66b7ff, #35d0d5); }

    [data-testid="stMetric"] {
        background: linear-gradient(145deg, rgba(23, 39, 62, .96), rgba(16, 28, 45, .96));
        border: 1px solid rgba(127, 163, 207, .2); border-radius: 16px;
        padding: 17px 18px; box-shadow: 0 8px 26px rgba(0,0,0,.12);
        min-height: 112px;
    }
    [data-testid="stMetricLabel"] { color: #a9bbd3 !important; font-size: .76rem !important; font-weight: 700 !important; letter-spacing: .045em; text-transform: uppercase; }
    [data-testid="stMetricValue"] { color: #f3f7ff !important; font-family: 'Space Grotesk', sans-serif; font-size: clamp(1.35rem, 2vw, 1.9rem) !important; font-weight: 700 !important; }
    [data-testid="stMetricDelta"] { font-size: .76rem !important; }

    .leaderboard-row {
        display: flex; align-items: center; gap: 15px; padding: 12px 15px;
        margin: 0 0 9px; border: 1px solid rgba(121, 155, 197, .17);
        border-radius: 15px; background: linear-gradient(110deg, rgba(22, 37, 59, .96), rgba(15, 27, 44, .96));
        box-shadow: 0 5px 18px rgba(0,0,0,.11); transition: transform .18s ease, border-color .18s ease;
    }
    .leaderboard-row:hover { transform: translateY(-2px); border-color: rgba(96, 165, 250, .42); }
    .rank-badge {
        width: 42px; height: 42px; flex: 0 0 42px; display: grid; place-items: center;
        border-radius: 12px; color: #d7eaff; font-family: 'Space Grotesk', sans-serif;
        font-weight: 700; font-size: 1.02rem; background: rgba(59, 130, 246, .15);
        border: 1px solid rgba(96, 165, 250, .25);
    }
    .rank-badge.top-three { color: #ffe5a6; background: rgba(217, 164, 65, .13); border-color: rgba(245, 190, 85, .27); }
    .leaderboard-cover { width: 112px; height: 52px; flex: 0 0 112px; object-fit: cover; border-radius: 9px; background: #1d2c42; }
    .leaderboard-info { flex: 1; min-width: 0; }
    .leaderboard-title { color: #f4f7ff; font-size: .98rem; font-weight: 800; line-height: 1.3; }
    .leaderboard-subtitle { color: #8ea2bd; font-size: .76rem; margin-top: 5px; }
    .leaderboard-score { flex: 0 0 auto; text-align: right; color: #eaf4ff; font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 1.07rem; }
    .leaderboard-score small { display: block; color: #8298b4; font-family: 'DM Sans', sans-serif; font-size: .66rem; font-weight: 600; text-transform: uppercase; letter-spacing: .08em; margin-top: 2px; }

    .game-card {
        background: linear-gradient(145deg, rgba(22, 38, 61, .98), rgba(14, 26, 43, .98));
        border: 1px solid rgba(127, 163, 207, .2); border-radius: 15px;
        padding: 15px 17px; margin-bottom: 10px;
    }
    .game-title { color: #f6f9ff; font-weight: 800; font-size: 1rem; }
    .game-subtitle { color: #91a5c0; font-size: .78rem; margin-top: 5px; }
    .small-muted { color: #91a5c0; font-size: .82rem; }

    .stButton > button, .stDownloadButton > button, .stLinkButton > a {
        border-radius: 11px; font-weight: 700; border: 1px solid rgba(113, 161, 222, .28);
        background: linear-gradient(115deg, #1e4d85, #176c91); color: #f8fbff;
        transition: transform .16s ease, filter .16s ease, box-shadow .16s ease;
    }
    .stButton > button:hover, .stDownloadButton > button:hover, .stLinkButton > a:hover {
        border-color: rgba(125, 190, 255, .7); filter: brightness(1.12); transform: translateY(-1px);
        box-shadow: 0 7px 18px rgba(18, 103, 170, .2);
    }
    [data-testid="stSelectbox"], [data-testid="stMultiSelect"] { margin-bottom: .15rem; }
    [data-testid="stSelectbox"] > div > div, [data-testid="stMultiSelect"] > div > div {
        background: rgba(18, 32, 52, .9); border-color: rgba(127, 163, 207, .25); border-radius: 11px;
    }
    [data-testid="stDataFrame"] { border: 1px solid rgba(127, 163, 207, .18); border-radius: 13px; overflow: hidden; }
    div[data-testid="stImage"] { border-radius: 13px; overflow: hidden; }
    [data-testid="stAlert"] { border-radius: 12px; }
    .stCaption, [data-testid="stCaptionContainer"] { color: #8296b1; }
    hr { border-color: rgba(148, 163, 184, .14); }

    @media (max-width: 720px) {
        .block-container { padding-left: 1rem; padding-right: 1rem; padding-top: 1rem; }
        .hero { padding: 22px 20px; border-radius: 17px; }
        .leaderboard-row { gap: 9px; padding: 10px; }
        .leaderboard-cover { width: 76px; height: 46px; flex-basis: 76px; }
        .rank-badge { width: 34px; height: 34px; flex-basis: 34px; font-size: .9rem; }
        .leaderboard-title { font-size: .86rem; }
        .leaderboard-subtitle { font-size: .68rem; }
        .leaderboard-score { font-size: .88rem; }
        [data-testid="stMetric"] { padding: 13px; min-height: 96px; }
    }
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
        "User-Agent": "SteamAnalyticsPro/3.2 (Streamlit dashboard)"
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
        return "No previous rank"

    difference = previous - game["rank"]

    if difference > 0:
        return f"▲ Up {difference}"

    if difference < 0:
        return f"▼ Down {abs(difference)}"

    return "— No change"


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
            <div class="eyebrow">STEAM CHARTS  /  GAMING INTELLIGENCE</div>
            <h1>STEAM ANALYTICS PRO</h1>
            <p>Your command center for the games people are playing, community sentiment, and trends over time.</p>
            <div class="hero-badges">
                <span class="hero-badge"><span class="hero-dot"></span> LIVE DATA CONNECTION</span>
                <span class="hero-badge">TOP 10 RANKINGS</span>
                <span class="hero-badge">REVIEW INSIGHTS</span>
                <span class="hero-badge">HISTORICAL TRENDS</span>
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
    fig.update_layout(
        template="plotly_dark",
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=18, r=18, t=34, b=18),
        legend_title_text="",
        font=dict(family="DM Sans, sans-serif", color="#c7d5e8", size=12),
        hoverlabel=dict(bgcolor="#14243a", bordercolor="#385579", font=dict(color="#f4f8ff")),
        xaxis=dict(showgrid=False, zerolinecolor="rgba(148,163,184,.15)", linecolor="rgba(148,163,184,.18)"),
        yaxis=dict(gridcolor="rgba(148,163,184,.12)", zerolinecolor="rgba(148,163,184,.15)", linecolor="rgba(148,163,184,.12)"),
    )
    return fig


# =========================================================
# CHART BUILDERS — each section offers several visual styles
# =========================================================

def make_player_chart(df, chart_type):
    """Build a selectable chart for Steam's Top 10 chart values."""
    labels = {"players": "Steam chart value", "name": "Game"}

    if chart_type == "Horizontal bars":
        fig = px.bar(
            df, x="players", y="name", orientation="h", text="players",
            color="players", color_continuous_scale="Blues", labels=labels,
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
        fig = px.treemap(df, path=["name"], values="players", color="players", color_continuous_scale="Blues")
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
    colors = {"Positive": "#22c55e", "Negative": "#ef4444"}

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
        "chart_value": "Steam chart value",
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

with st.sidebar:
    st.markdown("## 🎮 STEAM ANALYTICS")
    st.caption("YOUR GAMING COMMAND CENTER")
    st.markdown("<div class='hero-badge'><span class='hero-dot'></span> SYSTEM READY</div>", unsafe_allow_html=True)

    st.divider()

    page = st.radio(
        "NAVIGATION",
        [
            "Dashboard",
            "Game Explorer",
            "Game Comparison",
            "Player History",
            "Data & Export",
            "About",
        ],
    )

    st.divider()

    st.markdown("### Refresh settings")

    auto_refresh = st.toggle(
        "Automatic refresh",
        value=True,
    )

    refresh_label = st.selectbox(
        "Refresh interval",
        list(REFRESH_OPTIONS.keys()),
        index=2,
    )

    refresh_seconds = REFRESH_OPTIONS[refresh_label]

    if st.button(
        "🔄 Refresh now",
        use_container_width=True,
    ):
        fetch_top_games.clear()
        fetch_game_details.clear()
        fetch_reviews.clear()
        st.rerun()

    st.divider()

    st.caption("Steam public data")
    st.caption("No Steam API key required.")


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
            "Could not refresh Steam data. "
            "Showing the last successfully loaded rankings."
        )
    else:
        st.error(f"Unable to load Steam data: {error}")
        st.info(
            "Check your internet connection and refresh the app."
        )
        st.stop()

last_updated = st.session_state.last_updated

if last_updated:
    st.caption(
        "Last successful update: "
        + last_updated.strftime("%Y-%m-%d %H:%M:%S")
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

    heading("LIVE OVERVIEW")

    a, b, c, d = st.columns(4)

    with a:
        st.metric(
            "TOP GAME",
            top_game["name"][:24],
            "Rank #1",
        )

    with b:
        st.metric(
            "TOP GAME CHART VALUE",
            fmt(top_game["players"]),
            "Steam chart field",
        )

    with c:
        st.metric(
            "TOP 10 TOTAL",
            fmt(total_chart_value),
            "Combined chart values",
        )

    with d:
        st.metric(
            "TOTAL REVIEWS",
            fmt(total_reviews) if review_data_count else "Unavailable",
            f"Data available for {review_data_count}/10 games",
        )

    heading("🏆 TOP 10 LEADERBOARD")

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
                    <div class="leaderboard-subtitle">{rating} &nbsp;·&nbsp; {movement} &nbsp;·&nbsp; App ID {int(game['appid'])}</div>
                </div>
                <div class="leaderboard-score">{fmt(game['players'])}<small>Chart value</small></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    heading("📊 PLAYER COMPARISON")

    player_df = pd.DataFrame(games)
    player_chart_type = st.selectbox(
        "Choose player chart style",
        ["Horizontal bars", "Vertical bars", "Line", "Area", "Scatter", "Donut", "Treemap"],
        index=0,
        key="dashboard_player_chart_type",
    )
    st.plotly_chart(
        make_player_chart(player_df, player_chart_type),
        use_container_width=True,
    )

    heading("⭐ REVIEW ANALYTICS")

    review_df = pd.DataFrame(reviewed_games)
    if review_df.empty:
        st.warning(
            "Review data is currently unavailable from Steam. "
            "The app will retry after the review-data cache expires."
        )
    else:
        review_chart_type = st.selectbox(
            "Choose review chart style",
            ["Grouped bars", "Stacked bars", "Horizontal bars", "Line", "Area", "Donut"],
            index=0,
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

    heading("📈 RECENT HISTORY")

    if not history_30.empty:
        history_chart_type = st.selectbox(
            "Choose history chart style",
            ["Line", "Area", "Scatter", "Bars"],
            index=0,
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
            "Your history graph will appear after statistics "
            "have been collected."
        )

# =========================================================
# GAME EXPLORER
# =========================================================

elif page == "Game Explorer":

    heading("🔎 GAME EXPLORER")

    names = [game["name"] for game in games]

    selected_name = st.selectbox(
        "Choose a game",
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
        st.markdown(f"## {game['name']}")
        st.write(game["description"] or "No description available.")
        m1, m2, m3 = st.columns(3)
        with m1:
            st.metric("Chart value", fmt(game["players"]))
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

    heading("REVIEW DETAILS")

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
                "Positive": "#22c55e",
                "Negative": "#ef4444",
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

    heading("⚔️ GAME COMPARISON")

    options = [game["name"] for game in games]

    selected_names = st.multiselect(
        "Select games to compare",
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

        st.markdown("### Player chart values")
        player_compare_type = st.selectbox(
            "Player comparison chart style",
            ["Horizontal bars", "Vertical bars", "Line", "Area", "Scatter", "Donut", "Treemap"],
            index=1,
            key="comparison_player_chart_type",
        )
        st.plotly_chart(
            make_player_chart(compare_df, player_compare_type),
            use_container_width=True,
        )

        st.markdown("### Review comparison")

        review_compare_df = compare_df[compare_df["reviews_available"]].copy()
        if review_compare_df.empty:
            st.warning("Review statistics are unavailable for the selected games.")
        else:
            review_compare_type = st.selectbox(
                "Review comparison chart style",
                ["Grouped bars", "Stacked bars", "Horizontal bars", "Line", "Area", "Donut"],
                index=0,
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

        st.markdown("### Comparison table")

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
            "players": "Chart value",
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

    heading("📈 HISTORICAL ANALYTICS")

    period = st.selectbox(
        "History period",
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
            "Choose games",
            game_names,
            default=game_names[:3],
        )

        filtered = history[
            history["game_name"].isin(chosen)
        ]

        if not filtered.empty:
            history_chart_type = st.selectbox(
                "History chart style",
                ["Line", "Area", "Scatter", "Bars"],
                index=0,
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

        st.markdown("### History table")

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

    heading("📥 DATA CENTER")

    st.write(
        "Download the current rankings or your collected historical records."
    )

    current_df = pd.DataFrame(games)

    st.markdown("### Current Top 10")

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

    st.markdown("### Historical data")

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

    st.markdown("### Database information")

    st.caption(f"Database file: {DB_PATH.name}")
    st.caption("History retention: approximately 30 days.")
    st.caption("The app stores at most one collection point every 5 minutes to avoid duplicate records from page interactions.")
    st.caption(
        "This SQLite database is local to the app environment. "
        "For reliable long-term cloud history, connect an external database."
    )


# =========================================================
# ABOUT
# =========================================================

elif page == "About":

    heading("ℹ️ ABOUT STEAM ANALYTICS PRO")

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
    "STEAM ANALYTICS PRO · VERSION 3.2 · BUILT WITH PYTHON + STREAMLIT · UNOFFICIAL STEAM DASHBOARD"
    "</div>",
    unsafe_allow_html=True,
)
