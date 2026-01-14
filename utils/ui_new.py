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
        "icon": "📄",
        "items": {
            "Aufnahme": "pages/2_📄_Dokumentenaufnahme.py",
            "Verwaltung": "pages/3_📁_Dokumente.py",
            "Intelligente Ordner": "pages/4_🔍_Intelligente_Ordner.py",
            "Dokument-Chat": "pages/11_💬_Dokument_Chat.py",
        }
    },
    "Finanzen": {
        "icon": "💰",
        "items": {
            "Übersicht": "pages/7_💰_Finanzen.py",
            "Dashboard": "pages/13_📈_Finanz_Dashboard.py",
            "Steuer-Report": "pages/21_📊_Steuer_Report.py",
            "Abonnements": "pages/17_💳_Abonnements.py",
        }
    },
    "Verträge": {
        "icon": "📑",
        "items": {
            "Vertragsübersicht": "pages/10_📑_Vertraege.py",
            "Versicherungen": "pages/16_🏥_Versicherungen.py",
            "Garantien": "pages/15_🛡️_Garantien.py",
        }
    },
    "Objekte": {
        "icon": "🏠",
        "items": {
            "Immobilien": "pages/23_🏘️_Immobilien.py",
            "Entitäten": "pages/24_👥_Entitäten.py",
            "Inventar": "pages/18_🏠_Inventar.py",
            "Kilometerlogbuch": "pages/20_🚗_Kilometerlogbuch.py",
        }
    },
    "Organisation": {
        "icon": "📅",
        "items": {
            "Kalender": "pages/5_📅_Kalender.py",
            "E-Mail": "pages/6_📧_E-Mail.py",
            "Vorlagen": "pages/19_📝_Vorlagen.py",
        }
    },
    "Tools": {
        "icon": "🔧",
        "items": {
            "Diktierfunktion": "pages/9_🎤_Diktierfunktion.py",
            "Automatisierung": "pages/12_🤖_Automatisierung.py",
            "Backup": "pages/22_💾_Backup.py",
        }
    },
    "System": {
        "icon": "⚙️",
        "items": {
            "Einstellungen": "pages/8_⚙️_Einstellungen.py",
            "Diagnose": "pages/50_🔧_Diagnose.py",
        }
    },
}


def inject_custom_css():
    """Injiziert das CSS für die neue Navigation - entfernt Button-Styling komplett"""
    st.markdown("""
    <style>
        /* ============================================
           STREAMLIT STANDARD-NAVIGATION AUSBLENDEN
           ============================================ */
        [data-testid="stSidebarNav"] {
            display: none !important;
        }

        /* ============================================
           SIDEBAR BUTTONS -> REINE TEXT-LINKS
           ============================================ */

        /* ALLE Buttons in der Sidebar: Kein Hintergrund, kein Rahmen */
        section[data-testid="stSidebar"] button[kind="secondary"],
        section[data-testid="stSidebar"] button[data-testid="baseButton-secondary"],
        section[data-testid="stSidebar"] .stButton button {
            background: none !important;
            background-color: transparent !important;
            border: none !important;
            border-color: transparent !important;
            box-shadow: none !important;
            color: #4b5563 !important;
            font-weight: 400 !important;
            padding: 0.3rem 0.5rem !important;
            text-align: left !important;
            justify-content: flex-start !important;
        }

        section[data-testid="stSidebar"] button[kind="secondary"]:hover,
        section[data-testid="stSidebar"] button[data-testid="baseButton-secondary"]:hover,
        section[data-testid="stSidebar"] .stButton button:hover {
            background: none !important;
            background-color: transparent !important;
            border: none !important;
            color: #2563eb !important;
            text-decoration: underline !important;
        }

        section[data-testid="stSidebar"] button[kind="secondary"]:focus,
        section[data-testid="stSidebar"] button[data-testid="baseButton-secondary"]:focus,
        section[data-testid="stSidebar"] .stButton button:focus {
            box-shadow: none !important;
            outline: none !important;
            border: none !important;
        }

        section[data-testid="stSidebar"] button[kind="secondary"]:active,
        section[data-testid="stSidebar"] button[data-testid="baseButton-secondary"]:active,
        section[data-testid="stSidebar"] .stButton button:active {
            background: none !important;
            border: none !important;
        }

        /* Disabled Buttons (aktive Seite) */
        section[data-testid="stSidebar"] button:disabled {
            background: none !important;
            background-color: transparent !important;
            border: none !important;
            color: #2563eb !important;
            font-weight: 600 !important;
            opacity: 1 !important;
        }

        /* Button Container */
        section[data-testid="stSidebar"] .stButton {
            margin: 0 !important;
            padding: 0 !important;
        }

        /* ============================================
           EXPANDER STYLING
           ============================================ */
        section[data-testid="stSidebar"] [data-testid="stExpander"] {
            border: none !important;
            background: transparent !important;
        }

        section[data-testid="stSidebar"] [data-testid="stExpander"] summary {
            padding: 0.4rem 0 !important;
        }

        section[data-testid="stSidebar"] .streamlit-expanderHeader {
            font-size: 0.9rem !important;
            font-weight: 500 !important;
            color: #374151 !important;
            background: transparent !important;
            border: none !important;
            padding: 0.3rem 0 !important;
        }

        section[data-testid="stSidebar"] .streamlit-expanderHeader:hover {
            color: #1f2937 !important;
        }

        section[data-testid="stSidebar"] .streamlit-expanderContent {
            padding: 0 0 0 1rem !important;
            border-left: 2px solid #e5e7eb !important;
            margin-left: 0.5rem !important;
        }
    </style>
    """, unsafe_allow_html=True)


def render_tree_sidebar():
    """
    Rendert die komplette Sidebar mit Baum-Navigation.
    """
    from utils.components import get_version_string, render_api_status

    # CSS injizieren
    inject_custom_css()

    # Aktuelle Seite ermitteln
    current_page = st.session_state.get('_current_page', '')

    with st.sidebar:
        # Titel
        st.markdown("### 📁 Dokumentenverwaltung")

        # Suche-Button (als echter Streamlit-Button für Funktionalität)
        if st.button("🔍 Suche", key="nav_search_btn", use_container_width=True, type="secondary"):
            st.switch_page("pages/0_🔎_Suche.py")

        st.markdown("---")

        # Navigation mit nativen Streamlit Expandern
        for category_name, category_data in TREE_NAVIGATION.items():
            icon = category_data.get("icon", "📁")
            items = category_data.get("items", {})

            # Prüfen ob aktive Seite in dieser Kategorie
            has_active = any(path in current_page for path in items.values())

            with st.expander(f"{icon} {category_name}", expanded=has_active):
                for item_name, item_path in items.items():
                    is_active = item_path in current_page

                    # Text-Label mit Pfeil für aktive Seite
                    label = f"→ {item_name}" if is_active else item_name

                    if st.button(
                        label,
                        key=f"nav_{item_path}",
                        use_container_width=True,
                        disabled=is_active
                    ):
                        st.session_state['_current_page'] = item_path
                        st.switch_page(item_path)

        st.markdown("---")

        # API Status
        with st.expander("🚦 Status", expanded=False):
            render_api_status()

        # Aktentasche
        cart_items = st.session_state.get('active_cart_items', [])
        with st.expander(f"💼 Aktentasche ({len(cart_items) if cart_items else 0})", expanded=False):
            if cart_items:
                from database.db import get_db
                from database.models import Document
                with get_db() as session:
                    docs = session.query(Document).filter(Document.id.in_(cart_items)).all()
                    for doc in docs[:5]:
                        st.caption(f"• {(doc.title or doc.filename)[:25]}...")
                    if len(docs) > 5:
                        st.caption(f"... +{len(docs)-5} weitere")
                if st.button("🗑️ Leeren", key="clear_cart"):
                    st.session_state.active_cart_items = []
                    st.rerun()
            else:
                st.caption("Leer")

        st.markdown("---")
        st.caption(get_version_string())


def render_top_search():
    """Rendert die Suchleiste oben auf der Seite"""
    cols = st.columns([1, 6, 1])
    with cols[1]:
        query = st.text_input(
            "Suche",
            placeholder="🔍 Dokumente durchsuchen...",
            key="top_search_input",
            label_visibility="collapsed"
        )
        if query:
            st.session_state.search_query_from_top = query
            st.switch_page("pages/0_🔎_Suche.py")


def apply_new_layout():
    """
    Wendet das neue Layout an.
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
    except Exception:
        pass

    # Sidebar rendern
    render_tree_sidebar()

    # Top-Suche rendern
    render_top_search()
