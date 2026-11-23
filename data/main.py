
from __future__ import annotations

import json
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
    page_title="Steam Analytics Pro",
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
    @import url(
      'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap'
    );

    html, body, [class*="css"] {
        font-family: Inter, sans-serif;
    }

    .stApp {
        background:
          radial-gradient(circle at 90% 0%, #172554 0%, transparent 28%),
          linear-gradient(145deg, #080d19, #101827 55%, #080d19);
        color: #f1f5f9;
    }

    [data-testid="stSidebar"] {
        background: #0b1220;
        border-right: 1px solid #25344b;
    }

    .hero {
        padding: 30px;
        border: 1px solid #334155;
        border-radius: 20px;
        background: linear-gradient(115deg, #172554, #111827 70%);
        margin-bottom: 22px;
    }

    .hero h1 {
        color: white;
        font-size: 2.35rem;
        font-weight: 900;
        margin: 0;
    }

    .hero p {
        color: #a5b4fc;
        margin: 8px 0 0;
    }

    .eyebrow {
        color: #60a5fa;
        font-weight: 800;
        font-size: .75rem;
        letter-spacing: 2px;
        margin-bottom: 8px;
    }

    .section-heading {
        color: #f8fafc;
        font-size: 1.25rem;
        font-weight: 800;
        margin: 22px 0 12px;
    }

    .game-card {
        background: linear-gradient(145deg, #172338, #111827);
        border: 1px solid #293a52;
        border-radius: 15px;
        padding: 15px;
        margin-bottom: 10px;
    }

    .game-title {
        color: white;
        font-weight: 800;
        font-size: 1rem;
    }

    .game-subtitle {
        color: #94a3b8;
        font-size: .8rem;
        margin-top: 5px;
    }

    .small-muted {
        color: #94a3b8;
        font-size: .82rem;
    }

    .stButton > button,
    .stDownloadButton > button,
    .stLinkButton > a {
        border-radius: 10px;
        font-weight: 700;
    }

    [data-testid="stMetric"] {
        background: #142136;
        border: 1px solid #293a52;
        border-radius: 13px;
        padding: 14px;
    }

    div[data-testid="stImage"] {
        border-radius: 12px;
        overflow: hidden;
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
        "User-Agent": "SteamAnalyticsPro/3.0 (Streamlit dashboard)"
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
            <div class="eyebrow">MNEURIX // GAMING INTELLIGENCE</div>
            <h1>🎮 STEAM ANALYTICS PRO</h1>
            <p>
                Your gaming statistics command center.
                Rankings, comparisons and historical trends.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def heading(title):
    st.markdown(
        f'<div class="section-heading">{title}</div>',
        unsafe_allow_html=True,
    )


def dark_chart(fig, height=420):
    fig.update_layout(
        template="plotly_dark",
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=12, r=12, t=30, b=12),
        legend_title_text="",
    )
    return fig


# =========================================================
# SIDEBAR
# =========================================================

with st.sidebar:
    st.markdown("## 🎮 STEAM ANALYTICS")
    st.caption("Version 3.0 · Analytics Pro")

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
        left, middle, right = st.columns([1, 5, 2])

        with left:
            st.markdown(f"## #{game['rank']}")

        with middle:
            st.markdown(
                f"""
                <div class="game-card">
                    <div class="game-title">{game['name']}</div>
                    <div class="game-subtitle">
                        {game['review_score'] if game['reviews_available'] else 'Reviews unavailable'} ·
                        {rank_change(game)} ·
                        App ID {game['appid']}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with right:
            st.metric(
                "Chart value",
                fmt(game["players"]),
            )

    heading("📊 PLAYER COMPARISON")

    player_df = pd.DataFrame(games)

    fig = px.bar(
        player_df,
        x="players",
        y="name",
        orientation="h",
        text="players",
        color="players",
        color_continuous_scale=[
            "#1e3a8a",
            "#2563eb",
            "#38bdf8",
        ],
        labels={
            "players": "Steam chart value",
            "name": "Game",
        },
    )

    fig.update_layout(
        yaxis={"categoryorder": "total ascending"},
        coloraxis_showscale=False,
    )

    st.plotly_chart(
        dark_chart(fig, 470),
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
        fig = px.bar(
            review_df,
            x="name",
            y=["positive", "negative"],
            barmode="group",
            labels={
                "name": "Game",
                "value": "Lifetime reviews",
                "variable": "Review type",
            },
            color_discrete_map={
                "positive": "#22c55e",
                "negative": "#ef4444",
            },
        )
        fig.update_layout(xaxis_tickangle=-30)
        st.plotly_chart(
            dark_chart(fig, 430),
            use_container_width=True,
        )
        if review_data_count < len(games):
            st.caption(
                f"Review data loaded for {review_data_count} of {len(games)} games. "
                "Unavailable games are omitted rather than shown as zero."
            )

    heading("📈 RECENT HISTORY")

    if not history_30.empty:
        fig = px.line(
            history_30,
            x="collected_at",
            y="chart_value",
            color="game_name",
            markers=True,
            labels={
                "collected_at": "Time",
                "chart_value": "Chart value",
                "game_name": "Game",
            },
        )

        st.plotly_chart(
            dark_chart(fig, 380),
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

    left, right = st.columns([1, 2])

    with left:
        if game["image"]:
            st.image(
                game["image"],
                use_container_width=True,
            )
        else:
            st.info("No cover image available.")

    with right:
        st.markdown(f"## {game['name']}")
        st.write(game["description"] or "No description available.")

        st.metric(
            "Steam chart value",
            fmt(game["players"]),
        )

        st.write(f"**Current chart rank:** #{game['rank']}")
        st.write(f"**Previous weekly rank:** {game['last_week_rank'] or 'Unknown'}")
        rating_text = game["review_score"] if game["reviews_available"] else "Unavailable"
        st.write(f"**Review rating:** {rating_text}")
        st.write(f"**Release date:** {game['release_date']}")
        st.write(f"**Developers:** {game['developers'] or 'Unknown'}")
        st.write(f"**Genres:** {game['genres'] or 'Unknown'}")
        st.write(f"**Steam App ID:** {game['appid']}")

        st.link_button(
            "Open Steam Store",
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

        fig = px.bar(
            compare_df,
            x="name",
            y="players",
            text="players",
            color="name",
            labels={
                "name": "Game",
                "players": "Chart value",
            },
        )

        st.plotly_chart(
            dark_chart(fig, 400),
            use_container_width=True,
        )

        st.markdown("### Review comparison")

        review_compare_df = compare_df[compare_df["reviews_available"]]
        if review_compare_df.empty:
            st.warning("Review statistics are unavailable for the selected games.")
        else:
            fig = px.bar(
                review_compare_df,
                x="name",
                y=["positive", "negative"],
                barmode="group",
                labels={
                    "name": "Game",
                    "value": "Lifetime reviews",
                    "variable": "Review type",
                },
                color_discrete_map={
                    "positive": "#22c55e",
                    "negative": "#ef4444",
                },
            )
            st.plotly_chart(
                dark_chart(fig, 400),
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
        table.loc[~compare_df["reviews_available"], [
            "review_score", "positive", "negative", "total_reviews"
        ]] = "Unavailable"
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
            fig = px.line(
                filtered,
                x="collected_at",
                y="chart_value",
                color="game_name",
                markers=True,
                labels={
                    "collected_at": "Time",
                    "chart_value": "Chart value",
                    "game_name": "Game",
                },
            )

            st.plotly_chart(
                dark_chart(fig, 480),
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

st.caption(
    "STEAM ANALYTICS PRO · VERSION 3.0 · "
    "PYTHON + STREAMLIT · UNOFFICIAL STEAM DASHBOARD"
)
