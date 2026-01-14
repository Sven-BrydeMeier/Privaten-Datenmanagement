"""
Neue UI-Komponenten:
- Top-Menü mit globaler Suchleiste
- Baum-Navigation ohne sichtbare Buttons (nur Text)
"""
import streamlit as st
from pathlib import Path
import sys
from typing import Optional, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))


# Navigationsstruktur
TREE_NAVIGATION = {
    "Dokumente": {
        "Aufnahme": "pages/2_📄_Dokumentenaufnahme.py",
        "Verwaltung": "pages/3_📁_Dokumente.py",
        "Intelligente Ordner": "pages/4_🔍_Intelligente_Ordner.py",
        "Dokument-Chat": "pages/11_💬_Dokument_Chat.py",
    },
    "Finanzen": {
        "Übersicht": "pages/7_💰_Finanzen.py",
        "Dashboard": "pages/13_📈_Finanz_Dashboard.py",
        "Steuer-Report": "pages/21_📊_Steuer_Report.py",
        "Abonnements": "pages/17_💳_Abonnements.py",
    },
    "Verträge": {
        "Vertragsübersicht": "pages/10_📑_Vertraege.py",
        "Versicherungen": "pages/16_🏥_Versicherungen.py",
        "Garantien": "pages/15_🛡️_Garantien.py",
    },
    "Objekte": {
        "Immobilien": "pages/23_🏘️_Immobilien.py",
        "Entitäten": "pages/24_👥_Entitäten.py",
        "Inventar": "pages/18_🏠_Inventar.py",
        "Kilometerlogbuch": "pages/20_🚗_Kilometerlogbuch.py",
    },
    "Organisation": {
        "Kalender": "pages/5_📅_Kalender.py",
        "E-Mail": "pages/6_📧_E-Mail.py",
        "Vorlagen": "pages/19_📝_Vorlagen.py",
    },
    "Tools": {
        "Diktierfunktion": "pages/9_🎤_Diktierfunktion.py",
        "Automatisierung": "pages/12_🤖_Automatisierung.py",
        "Backup": "pages/22_💾_Backup.py",
    },
    "System": {
        "Einstellungen": "pages/8_⚙️_Einstellungen.py",
        "Diagnose": "pages/50_🔧_Diagnose.py",
    },
}


def apply_sidebar_style():
    """
    Wendet das CSS für die Sidebar-Navigation an.
    Entfernt Button-Rahmen und macht sie wie Text-Links aussehen.
    """
    st.markdown("""
    <style>
        /* ========== STANDARD-NAVIGATION AUSBLENDEN ========== */
        [data-testid="stSidebarNav"] {
            display: none !important;
        }

        /* ========== SIDEBAR BREITE ========== */
        section[data-testid="stSidebar"] {
            width: 260px !important;
            min-width: 260px !important;
        }

        section[data-testid="stSidebar"] > div {
            width: 260px !important;
        }

        /* ========== ALLE SIDEBAR BUTTONS ALS TEXT-LINKS ========== */
        section[data-testid="stSidebar"] button {
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
            color: #374151 !important;
            font-weight: 400 !important;
            padding: 0.25rem 0.5rem !important;
            margin: 0 !important;
            text-align: left !important;
            justify-content: flex-start !important;
        }

        section[data-testid="stSidebar"] button:hover {
            background: transparent !important;
            color: #2563eb !important;
            border: none !important;
        }

        section[data-testid="stSidebar"] button:focus {
            box-shadow: none !important;
            outline: none !important;
            border: none !important;
        }

        section[data-testid="stSidebar"] button:active {
            background: transparent !important;
            border: none !important;
        }

        /* Button-Container ohne Padding */
        section[data-testid="stSidebar"] .stButton {
            margin-bottom: 0 !important;
        }

        section[data-testid="stSidebar"] .stButton > button {
            width: 100% !important;
        }

        /* ========== DISABLED BUTTONS (AKTIVE SEITE) ========== */
        section[data-testid="stSidebar"] button:disabled {
            background: transparent !important;
            color: #2563eb !important;
            font-weight: 600 !important;
            opacity: 1 !important;
            cursor: default !important;
        }

        /* ========== EXPANDER STYLING ========== */
        section[data-testid="stSidebar"] .streamlit-expanderHeader {
            font-weight: 500 !important;
            font-size: 0.95rem !important;
            padding: 0.5rem 0 !important;
            background: transparent !important;
            border: none !important;
        }

        section[data-testid="stSidebar"] .streamlit-expanderContent {
            padding-left: 0.75rem !important;
            border-left: 2px solid #e5e7eb !important;
            margin-left: 0.5rem !important;
        }

        /* ========== TOP SUCHLEISTE ========== */
        .top-search-bar {
            background: linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%);
            padding: 0.75rem 1rem;
            margin: -1rem -1rem 1rem -1rem;
            border-radius: 0;
        }

        .top-search-bar input {
            border-radius: 1.5rem !important;
            border: none !important;
            padding: 0.5rem 1rem !important;
        }
    </style>
    """, unsafe_allow_html=True)


def render_top_search():
    """
    Rendert die globale Suchleiste oben auf der Seite.
    """
    cols = st.columns([1, 6, 1])

    with cols[1]:
        search_query = st.text_input(
            "Suche",
            placeholder="🔍 Dokumente durchsuchen... (Enter drücken)",
            key="top_global_search",
            label_visibility="collapsed"
        )

        if search_query:
            st.session_state.search_query_from_top = search_query
            st.switch_page("pages/0_🔎_Suche.py")


def render_tree_sidebar():
    """
    Rendert die komplette Sidebar mit:
    - Baum-Navigation (als Expander mit Text-Links)
    - Aktentasche
    - API-Status
    """
    from database.db import get_db, get_current_user_id
    from database.models import Document
    from utils.components import get_version_string, render_api_status

    # CSS anwenden
    apply_sidebar_style()

    with st.sidebar:
        # Logo/Titel
        st.markdown("### 📁 Dokumentenverwaltung")

        # Globale Suche
        if st.button("🔍 Suche", key="nav_search", use_container_width=True):
            st.switch_page("pages/0_🔎_Suche.py")

        st.markdown("---")

        # Aktuelle Seite ermitteln
        current_page = st.session_state.get('_current_page', '')

        # Baum-Navigation mit Expander
        for category, items in TREE_NAVIGATION.items():
            # Prüfen ob Kategorie aktive Seite enthält
            has_active = any(path in current_page for path in items.values())

            with st.expander(f"📂 {category}", expanded=has_active):
                for item_name, item_path in items.items():
                    is_active = item_path in current_page

                    # Prefix für aktive Seite
                    display_name = f"→ {item_name}" if is_active else f"   {item_name}"

                    if st.button(
                        display_name,
                        key=f"nav_{item_path}",
                        use_container_width=True,
                        disabled=is_active
                    ):
                        st.session_state['_current_page'] = item_path
                        st.switch_page(item_path)

        st.markdown("---")

        # API-Status (kompakt)
        with st.expander("🚦 API-Status", expanded=False):
            render_api_status()

        st.markdown("---")

        # Aktentasche
        cart_items = st.session_state.get('active_cart_items', [])
        cart_count = len(cart_items) if cart_items else 0

        with st.expander(f"💼 Aktentasche ({cart_count})", expanded=False):
            if cart_items:
                user_id = get_current_user_id()
                with get_db() as session:
                    docs = session.query(Document).filter(
                        Document.id.in_(cart_items)
                    ).all()

                    for doc in docs[:5]:
                        title = (doc.title or doc.filename)[:20]
                        st.caption(f"• {title}...")

                    if len(docs) > 5:
                        st.caption(f"... +{len(docs) - 5} weitere")

                if st.button("🗑️ Leeren", key="clear_cart"):
                    st.session_state.active_cart_items = []
                    st.rerun()
            else:
                st.caption("Leer")

        # Version
        st.caption(get_version_string())


def apply_new_layout():
    """
    Wendet das neue Layout mit Top-Suche und Baum-Navigation an.
    Sollte am Anfang jeder Seite aufgerufen werden.
    """
    # Aktuelle Seite ermitteln
    import inspect
    try:
        frame = inspect.currentframe()
        if frame and frame.f_back:
            caller_file = frame.f_back.f_globals.get('__file__', '')
            if caller_file:
                caller_path = Path(caller_file)
                if 'pages' in caller_path.parts:
                    idx = caller_path.parts.index('pages')
                    rel_path = '/'.join(caller_path.parts[idx:])
                    st.session_state['_current_page'] = rel_path
                else:
                    st.session_state['_current_page'] = caller_path.name
    except Exception:
        pass

    # Sidebar rendern
    render_tree_sidebar()

    # Top-Suchleiste rendern
    render_top_search()
