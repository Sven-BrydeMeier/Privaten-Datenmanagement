"""
Theme-Verwaltung für Dark Mode
"""
import streamlit as st


def init_theme():
    """Initialisiert Theme-Einstellungen"""
    if "theme" not in st.session_state:
        st.session_state.theme = "light"


def get_theme() -> str:
    """Gibt aktuelles Theme zurück"""
    init_theme()
    return st.session_state.theme


def set_theme(theme: str):
    """Setzt Theme"""
    st.session_state.theme = theme


def toggle_theme():
    """Wechselt zwischen Light und Dark Mode"""
    init_theme()
    if st.session_state.theme == "light":
        st.session_state.theme = "dark"
    else:
        st.session_state.theme = "light"


def get_theme_css() -> str:
    """Gibt CSS für aktuelles Theme zurück"""
    theme = get_theme()

    if theme == "dark":
        return """
        <style>
        /* Dark Mode CSS */
        :root {
            --background-color: #1a1a2e;
            --secondary-bg: #16213e;
            --text-color: #eaeaea;
            --accent-color: #0f3460;
            --primary-color: #e94560;
            --border-color: #2a2a4a;
            --success-color: #00bf63;
            --warning-color: #ff9f1c;
            --error-color: #ef476f;
        }

        .stApp {
            background-color: var(--background-color);
            color: var(--text-color);
        }

        .stSidebar {
            background-color: var(--secondary-bg);
        }

        .stButton > button {
            background-color: var(--accent-color);
            color: var(--text-color);
            border: 1px solid var(--border-color);
        }

        .stButton > button:hover {
            background-color: var(--primary-color);
            border-color: var(--primary-color);
        }

        .stTextInput > div > div > input,
        .stTextArea > div > div > textarea,
        .stSelectbox > div > div > select {
            background-color: var(--secondary-bg);
            color: var(--text-color);
            border-color: var(--border-color);
        }

        .stExpander {
            background-color: var(--secondary-bg);
            border-color: var(--border-color);
        }

        div[data-testid="stMetricValue"] {
            color: var(--text-color);
        }

        .stDataFrame {
            background-color: var(--secondary-bg);
        }

        .stAlert {
            background-color: var(--secondary-bg);
        }

        /* Tabs */
        .stTabs [data-baseweb="tab-list"] {
            background-color: var(--secondary-bg);
        }

        .stTabs [data-baseweb="tab"] {
            color: var(--text-color);
        }

        /* Cards/Container */
        div[data-testid="stVerticalBlock"] > div {
            background-color: transparent;
        }

        /* Tables */
        .stTable {
            background-color: var(--secondary-bg);
        }

        /* Markdown */
        .stMarkdown {
            color: var(--text-color);
        }

        /* Form */
        .stForm {
            background-color: var(--secondary-bg);
            border-color: var(--border-color);
        }
        </style>
        """
    else:
        return """
        <style>
        /* Light Mode CSS (default) */
        :root {
            --background-color: #ffffff;
            --secondary-bg: #f8f9fa;
            --text-color: #333333;
            --accent-color: #1976d2;
            --primary-color: #2196f3;
            --border-color: #e0e0e0;
            --success-color: #4caf50;
            --warning-color: #ff9800;
            --error-color: #f44336;
        }
        </style>
        """


def apply_theme():
    """Wendet aktuelles Theme an"""
    st.markdown(get_theme_css(), unsafe_allow_html=True)


def render_theme_toggle():
    """Rendert Theme-Toggle Button"""
    init_theme()

    col1, col2 = st.columns([1, 10])

    with col1:
        if st.session_state.theme == "light":
            if st.button("🌙", help="Dark Mode aktivieren"):
                toggle_theme()
                st.rerun()
        else:
            if st.button("☀️", help="Light Mode aktivieren"):
                toggle_theme()
                st.rerun()


def render_theme_selector():
    """Rendert Theme-Auswahl"""
    init_theme()

    theme = st.selectbox(
        "Theme",
        options=["light", "dark"],
        index=0 if st.session_state.theme == "light" else 1,
        format_func=lambda x: "Hell" if x == "light" else "Dunkel"
    )

    if theme != st.session_state.theme:
        set_theme(theme)
        st.rerun()


# Farbpaletten für Diagramme
CHART_COLORS = {
    "light": [
        "#1976d2", "#2196f3", "#64b5f6", "#90caf9",
        "#4caf50", "#8bc34a", "#cddc39",
        "#ff9800", "#ffc107", "#ffeb3b",
        "#f44336", "#e91e63", "#9c27b0"
    ],
    "dark": [
        "#64b5f6", "#90caf9", "#bbdefb", "#e3f2fd",
        "#81c784", "#a5d6a7", "#c5e1a5",
        "#ffb74d", "#ffd54f", "#fff176",
        "#ef5350", "#f06292", "#ba68c8"
    ]
}


def get_chart_colors() -> list:
    """Gibt Farbpalette für aktuelles Theme zurück"""
    theme = get_theme()
    return CHART_COLORS.get(theme, CHART_COLORS["light"])
