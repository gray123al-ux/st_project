import time
from datetime import datetime

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------

st.set_page_config(
    page_title="Steam Top 10 Tracker",
    page_icon="🎮",
    layout="wide",
    initial_sidebar_state="expanded",
)

CHARTS_API = (
    "https://api.steampowered.com/"
    "ISteamChartsService/GetMostPlayedGames/v1/"
)
REVIEWS_API = "https://store.steampowered.com/appreviews/{}"
DETAILS_API = "https://store.steampowered.com/api/appdetails"

REFRESH_SECONDS = 300
HISTORY_LIMIT = 500

# ---------------------------------------------------------
# DESIGN
# ---------------------------------------------------------

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    .stApp {
        background:
            radial-gradient(circle at 85% 0%, #172554 0%, transparent 30%),
            linear-gradient(145deg, #080d19, #101827 55%, #0b1220);
        color: #f1f5f9;
    }

    [data-testid="stSidebar"] {
        background: #0b1220;
        border-right: 1px solid #263449;
    }

    .hero {
        padding: 28px 30px;
        border: 1px solid #334155;
        border-radius: 20px;
        background: linear-gradient(120deg, #172554, #111827 65%);
        margin-bottom: 22px;
    }

    .hero h1 {
        font-size: 2.3rem;
        font-weight: 800;
        margin: 0;
        color: #ffffff;
    }

    .hero p {
        color: #a5b4fc;
        margin: 8px 0 0 0;
    }

    .metric-card {
        background: linear-gradient(145deg, #172338, #111827);
        border: 1px solid #334155;
        border-radius: 16px;
        padding: 18px;
        min-height: 112px;
    }

    .metric-label {
        color: #94a3b8;
        font-size: 0.85rem;
        font-weight: 600;
    }

    .metric-value {
        color: #ffffff;
        font-size: 1.8rem;
        font-weight: 800;
        margin-top: 7px;
    }

    .metric-note {
        color: #64748b;
        font-size: 0.75rem;
        margin-top: 4px;
    }

    .section-title {
        font-size: 1.25rem;
        font-weight: 750;
        margin: 22px 0 12px 0;
        color: #f8fafc;
    }

    .game-card {
        background: #131f32;
        border: 1px solid #293a52;
        border-radius: 13px;
        padding: 13px;
        margin-bottom: 9px;
    }

    .game-name {
        font-weight: 700;
        font-size: 0.98rem;
        color: #f8fafc;
    }

    .game-sub {
        color: #94a3b8;
        font-size: 0.8rem;
        margin-top: 5px;
    }

    div.stButton > button {
        border-radius: 10px;
        font-weight: 650;
    }

    [data-testid="stMetric"] {
        background: #142136;
        border: 1px solid #293a52;
        border-radius: 13px;
        padding: 14px;
    }

    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------
# SESSION STATE
# ---------------------------------------------------------

if "history" not in st.session_state:
    st.session_state.history = []

if "last_success" not in st.session_state:
    st.session_state.last_success = None

if "selected_game" not in st.session_state:
    st.session_state.selected_game = None

if "last_data" not in st.session_state:
    st.session_state.last_data = []

if "last_error" not in st.session_state:
    st.session_state.last_error = None


# ---------------------------------------------------------
# STEAM API
# ---------------------------------------------------------

@st.cache_data(ttl=60, show_spinner=False)
def get_top_games():
    """Retrieve the current most-played Steam games."""
    response = requests.get(
        CHARTS_API,
        timeout=20,
        headers={"User-Agent": "SteamTop10Tracker/1.0"},
    )
    response.raise_for_status()

    payload = response.json()
    ranks = payload.get("response", {}).get("ranks", [])

    games = []

    for item in ranks:
        appid = item.get("appid")
        players = item.get("peak_in_game", 0)

        if not appid:
            continue

        games.append(
            {
                "appid": int(appid),
                "rank": int(item.get("rank", len(games) + 1)),
                "players": int(players or 0),
                "last_week_rank": item.get("last_week_rank"),
            }
        )

    games.sort(key=lambda game: game["rank"])
    return games[:10]


@st.cache_data(ttl=3600, show_spinner=False)
def get_game_details(appid):
    """Retrieve game name, image and store information."""
    response = requests.get(
        DETAILS_API,
        params={"appids": appid, "cc": "us", "l": "english"},
        timeout=15,
    )
    response.raise_for_status()

    data = response.json().get(str(appid), {})
    if not data.get("success"):
        return {}

    return data.get("data", {})


@st.cache_data(ttl=900, show_spinner=False)
def get_reviews(appid):
    """Retrieve Steam review summary."""
    response = requests.get(
        REVIEWS_API.format(appid),
        params={
            "json": 1,
            "filter": "summary",
            "language": "all",
            "num_per_page": 0,
        },
        timeout=15,
    )
    response.raise_for_status()

    return response.json().get("query_summary", {})


def load_dashboard_data():
    """Load rankings and enrich them with game and review details."""
    rankings = get_top_games()
    enriched = []

    for game in rankings:
        appid = game["appid"]

        try:
            details = get_game_details(appid)
        except requests.RequestException:
            details = {}

        try:
            reviews = get_reviews(appid)
        except (requests.RequestException, ValueError):
            reviews = {}

        enriched.append(
            {
                **game,
                "name": details.get("name", f"Steam App {appid}"),
                "image": details.get("header_image", ""),
                "description": details.get("short_description", ""),
                "release_date": details.get("release_date", {}).get(
                    "date", "Unknown"
                ),
                "developers": ", ".join(
                    details.get("developers", [])[:2]
                ),
                "positive": int(reviews.get("total_positive", 0) or 0),
                "negative": int(reviews.get("total_negative", 0) or 0),
                "total_reviews": int(
                    reviews.get("total_reviews", 0) or 0
                ),
                "review_score": reviews.get("review_score_desc", "Unknown"),
            }
        )

    return enriched


# ---------------------------------------------------------
# HISTORY
# ---------------------------------------------------------

def record_history(games):
    """Record the current Top 10 snapshot in this app session."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for game in games:
        st.session_state.history.append(
            {
                "time": now,
                "appid": game["appid"],
                "game": game["name"],
                "rank": game["rank"],
                "players": game["players"],
            }
        )

    st.session_state.history = st.session_state.history[-HISTORY_LIMIT:]


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def number(value):
    return f"{int(value or 0):,}"


def metric_card(label, value, note=""):
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
            <div class="metric-note">{note}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def format_change(current, previous):
    if not previous or previous <= 0:
        return "New / unavailable"
    difference = current - previous
    sign = "+" if difference > 0 else ""
    return f"{sign}{difference:,} players"


# ---------------------------------------------------------
# SIDEBAR
# ---------------------------------------------------------

with st.sidebar:
    st.markdown("## 🎮 STEAM TRACKER")
    st.caption("Live gaming statistics")

    st.divider()

    page = st.radio(
        "NAVIGATION",
        [
            "Dashboard",
            "Game Explorer",
            "Player History",
            "About",
        ],
    )

    st.divider()

    st.markdown("### Settings")
    auto_refresh = st.toggle("Auto refresh", value=True)

    refresh_rate = st.selectbox(
        "Refresh interval",
        [60, 120, 300, 600],
        index=2,
        format_func=lambda x: f"{x // 60} minute(s)" if x >= 60 else f"{x} seconds",
    )

    if st.button("🔄 Refresh now", use_container_width=True):
        get_top_games.clear()
        get_game_details.clear()
        get_reviews.clear()
        st.rerun()

    st.divider()
    st.caption("Data source: Steam public endpoints")
    st.caption("No Steam API key required.")


if auto_refresh:
    st_autorefresh(
        interval=refresh_rate * 1000,
        key="steam_auto_refresh",
    )


# ---------------------------------------------------------
# LOAD DATA
# ---------------------------------------------------------

with st.spinner("Loading Steam statistics..."):
    try:
        games = load_dashboard_data()
        st.session_state.last_data = games
        st.session_state.last_success = datetime.now()
        st.session_state.last_error = None

        if games:
            record_history(games)

    except (requests.RequestException, ValueError) as error:
        games = st.session_state.last_data
        st.session_state.last_error = str(error)


# ---------------------------------------------------------
# HEADER
# ---------------------------------------------------------

st.markdown(
    """
    <div class="hero">
        <h1>🎮 Steam Top 10 Tracker</h1>
        <p>Explore the most-played games, player counts and review statistics.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

if st.session_state.last_error:
    st.warning(
        "Steam data could not be refreshed. "
        "Showing the last successfully loaded data, if available."
    )

if not games:
    st.error(
        "No Steam rankings are available right now. "
        "Please check your connection and try again."
    )
    st.stop()

last_update = st.session_state.last_success
if last_update:
    st.caption(
        f"Last successful update: {last_update.strftime('%Y-%m-%d %H:%M:%S')}"
    )


# ---------------------------------------------------------
# DASHBOARD
# ---------------------------------------------------------

if page == "Dashboard":

    total_players = sum(game["players"] for game in games)
    top_game = games[0]
    total_reviews = sum(game["total_reviews"] for game in games)

    st.markdown('<div class="section-title">LIVE OVERVIEW</div>',
                unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        metric_card("TOP GAME", top_game["name"][:22], "Rank #1")

    with c2:
        metric_card("TOP GAME PLAYERS", number(top_game["players"]),
                    "Current chart value")

    with c3:
        metric_card("TOP 10 PLAYERS", number(total_players),
                    "Combined chart values")

    with c4:
        metric_card("TOTAL REVIEWS", number(total_reviews),
                    "Across the Top 10")

    st.markdown('<div class="section-title">🏆 TOP 10 MOST-PLAYED GAMES</div>',
                unsafe_allow_html=True)

    for game in games:
        col1, col2, col3 = st.columns([1, 5, 2])

        with col1:
            st.markdown(f"### #{game['rank']}")

        with col2:
            st.markdown(
                f"""
                <div class="game-card">
                    <div class="game-name">{game['name']}</div>
                    <div class="game-sub">
                        App ID: {game['appid']} · {game['review_score']}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with col3:
            st.metric("Players", number(game["players"]))

    st.markdown('<div class="section-title">📊 PLAYER COMPARISON</div>',
                unsafe_allow_html=True)

    chart_df = pd.DataFrame(games)

    fig = px.bar(
        chart_df,
        x="players",
        y="name",
        orientation="h",
        text="players",
        color="players",
        color_continuous_scale=["#334155", "#2563eb", "#38bdf8"],
        labels={
            "players": "Players",
            "name": "Game",
        },
    )

    fig.update_layout(
        template="plotly_dark",
        height=480,
        yaxis={"categoryorder": "total ascending"},
        coloraxis_showscale=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=20, b=10),
    )

    st.plotly_chart(fig, use_container_width=True)

    st.markdown('<div class="section-title">⭐ REVIEW SUMMARY</div>',
                unsafe_allow_html=True)

    review_df = pd.DataFrame(games)

    review_fig = px.bar(
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

    review_fig.update_layout(
        template="plotly_dark",
        height=400,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis_tickangle=-30,
    )

    st.plotly_chart(review_fig, use_container_width=True)

    export_df = pd.DataFrame(games)
    csv = export_df.to_csv(index=False).encode("utf-8-sig")

    st.download_button(
        "📥 Download Top 10 CSV",
        data=csv,
        file_name="steam_top10.csv",
        mime="text/csv",
    )


# ---------------------------------------------------------
# GAME EXPLORER
# ---------------------------------------------------------

elif page == "Game Explorer":

    st.markdown("## 🔎 Game Explorer")
    st.write("Search and inspect games currently appearing in the Top 10.")

    names = [game["name"] for game in games]

    selected_name = st.selectbox("Select a game", names)

    selected = next(
        game for game in games if game["name"] == selected_name
    )

    if selected["image"]:
        st.image(selected["image"], use_container_width=True)

    st.markdown(f"### {selected['name']}")
    st.write(selected["description"] or "No description available.")

    a, b, c = st.columns(3)

    with a:
        st.metric("Current chart value", number(selected["players"]))

    with b:
        st.metric("Positive reviews", number(selected["positive"]))

    with c:
        st.metric("Negative reviews", number(selected["negative"]))

    st.markdown("### Game information")

    st.write(f"**Rank:** #{selected['rank']}")
    st.write(f"**Steam App ID:** {selected['appid']}")
    st.write(f"**Review rating:** {selected['review_score']}")
    st.write(f"**Total reviews:** {number(selected['total_reviews'])}")
    st.write(f"**Developers:** {selected['developers'] or 'Unknown'}")
    st.write(f"**Release date:** {selected['release_date']}")

    st.link_button(
        "Open on Steam",
        f"https://store.steampowered.com/app/{selected['appid']}/",
    )


# ---------------------------------------------------------
# PLAYER HISTORY
# ---------------------------------------------------------

elif page == "Player History":

    st.markdown("## 📈 Player History")
    st.write(
        "This chart records snapshots collected while this app session is running. "
        "It does not contain historical Steam data from before collection started."
    )

    history = pd.DataFrame(st.session_state.history)

    if history.empty:
        st.info("History will appear after the first successful data collection.")
    else:
        history["time"] = pd.to_datetime(history["time"])

        available_games = sorted(history["game"].unique())

        selected_history_games = st.multiselect(
            "Choose games",
            available_games,
            default=available_games[:3],
        )

        filtered = history[
            history["game"].isin(selected_history_games)
        ]

        if not filtered.empty:
            history_fig = px.line(
                filtered,
                x="time",
                y="players",
                color="game",
                markers=True,
                labels={
                    "time": "Collection time",
                    "players": "Players",
                    "game": "Game",
                },
            )

            history_fig.update_layout(
                template="plotly_dark",
                height=480,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
            )

            st.plotly_chart(history_fig, use_container_width=True)

        st.metric("Collected snapshots", number(len(history)))
        st.metric("Unique games tracked", number(history["game"].nunique()))

        st.download_button(
            "📥 Export player history",
            data=history.to_csv(index=False).encode("utf-8-sig"),
            file_name="steam_player_history.csv",
            mime="text/csv",
        )

        if st.button("Clear session history"):
            st.session_state.history = []
            st.rerun()


# ---------------------------------------------------------
# ABOUT
# ---------------------------------------------------------

elif page == "About":

    st.markdown("## ℹ️ About Steam Tracker")

    st.write(
        """
        Steam Top 10 Tracker is a dashboard for exploring the most-played
        games on Steam.

        **Features**
        - Top 10 game rankings.
        - Current chart player values.
        - Daily chart peak data when provided by Steam.
        - Positive and negative review summaries.
        - Game search and Steam Store links.
        - Player comparison charts.
        - Session-based player history.
        - CSV exports and automatic refresh.

        **Data sources**
        - Steam Charts Service API.
        - Steam Store App Details API.
        - Steam Store Reviews API.

        **Important limitations**
        - Steam controls when its chart data updates.
        - Review summaries are aggregate totals, not a historical review graph.
        - Player history begins when this app session starts.
        - Session history can disappear when the app restarts.
        - The chart's peak field is not necessarily the current live player count.
        """
    )

    st.markdown("### Useful links")

    st.link_button(
        "Official Steam Charts",
        "https://store.steampowered.com/charts/",
    )

    st.link_button(
        "Steam Store",
        "https://store.steampowered.com/",
    )

# ---------------------------------------------------------
# FOOTER
# ---------------------------------------------------------

st.divider()

st.caption(
    "STEAM TOP 10 TRACKER · Built with Python + Streamlit · "
    "Unofficial community dashboard. Not affiliated with Valve."
)
