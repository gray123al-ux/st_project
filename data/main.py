
from __future__ import annotations

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
REVIEWS_URL = "https://store.steampowered.com/appreviews/{}"

REFRESH_OPTIONS = {
    "1 minute": 60,
    "2 minutes": 120,
    "5 minutes": 300,
    "10 minutes": 600,
}

HISTORY_DAYS = 30
MAX_RETRIES = 2

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
    now = datetime.now().isoformat(timespec="seconds")

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

    with get_connection() as conn:
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
        "User-Agent": "SteamAnalyticsPro/2.0"
    })
    return session


def request_json(url, params=None, timeout=20):
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
            return response.json()

        except (
            requests.RequestException,
            ValueError,
        ) as error:
            last_error = error
            if attempt < MAX_RETRIES - 1:
                time.sleep(1)

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


@st.cache_data(ttl=900, show_spinner=False)
def fetch_reviews(appid):
    payload = request_json(
        REVIEWS_URL.format(appid),
        params={
            "json": 1,
            "filter": "summary",
            "language": "all",
            "num_per_page": 0,
        },
    )

    return payload.get("query_summary", {})


def enrich_games(rankings):
    result = []

    for item in rankings:
        appid = item["appid"]

        try:
            details = fetch_game_details(appid)
        except Exception:
            details = {}

        try:
            reviews = fetch_reviews(appid)
        except Exception:
            reviews = {}

        release = details.get("release_date", {})

        result.append({
            **item,
            "name": details.get("name", f"App {appid}"),
            "image": details.get("header_image", ""),
            "description": details.get(
                "short_description",
                "",
            ),
            "release_date": release.get("date", "Unknown"),
            "developers": ", ".join(
                details.get("developers", [])[:3]
            ),
            "genres": ", ".join(
                genre.get("description", "")
                for genre in details.get("genres", [])[:4]
            ),
            "positive": int(
                reviews.get("total_positive", 0) or 0
            ),
            "negative": int(
                reviews.get("total_negative", 0) or 0
            ),
            "total_reviews": int(
                reviews.get("total_reviews", 0) or 0
            ),
            "review_score": reviews.get(
                "review_score_desc",
                "Unknown",
            ),
        })

    return result


# =========================================================
# FORMATTING
# =========================================================

def fmt(value):
    return f"{int(value or 0):,}"


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
    st.caption("Version 2.0 · Analytics Pro")

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
total_reviews = sum(g["total_reviews"] for g in games)

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
            fmt(total_reviews),
            "Top 10 combined",
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
                        {game['review_score']} ·
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

    review_df = pd.DataFrame(games)

    fig = px.bar(
        review_df,
        x="name",
        y=["positive", "negative"],
        barmode="group",
        labels={
            "name": "Game",
            "value": "Reviews",
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

    heading("📈 RECENT HISTORY")

    if not history_30.empty:
        latest = history_30.sort_values(
            "collected_at"
        ).groupby("appid").tail(1)

        fig = px.line(
            history_30,
            x="collected_at",
            y="chart_value",
            color="game_name",
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

        st.caption(
            f"{len(history_30):,} historical records collected."
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
        st.write(f"**Review rating:** {game['review_score']}")
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
        st.metric("Positive", fmt(game["positive"]))

    with y:
        st.metric("Negative", fmt(game["negative"]))

    with z:
        st.metric("Total reviews", fmt(game["total_reviews"]))

    if game["positive"] + game["negative"] > 0:
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

        fig = px.bar(
            compare_df,
            x="name",
            y=["positive", "negative"],
            barmode="group",
            labels={
                "name": "Game",
                "value": "Reviews",
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
        ].rename(columns={
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
            "Leave the app running to collect snapshots."
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
                "Records",
                fmt(len(history)),
            )

        with b:
            st.metric(
                "Games tracked",
                fmt(history["appid"].nunique()),
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
            "Stored snapshots",
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
        - Steam Store Reviews API.

        **Important limitations**

        - Steam controls when chart data is updated.
        - The chart value is not guaranteed to be an instantaneous live count.
        - Historical collection begins after deployment.
        - History is collected only when the app successfully loads new data.
        - SQLite storage on Streamlit Cloud is not guaranteed to survive
          environment replacement or redeployment.
        - Review summaries are aggregate totals, not historical review data.

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
    "STEAM ANALYTICS PRO · VERSION 2.0 · "
    "PYTHON + STREAMLIT · UNOFFICIAL STEAM DASHBOARD"
)
