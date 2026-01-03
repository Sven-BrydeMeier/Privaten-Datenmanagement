"""
Gemeinsame UI-Komponenten für alle Seiten
"""
import streamlit as st
from pathlib import Path
import sys
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

# App-Version im Format JJ.MM.TT.HHMM (letzte 4 Ziffern = Uhrzeit der letzten Änderung)
APP_VERSION = "26.01.03.1520"
APP_NAME = "Privates Dokumentenmanagement"


def get_version_string():
    """Gibt den formatierten Versionsstring zurück"""
    return f"Version {APP_VERSION}"


def page_header(title: str, subtitle: str = None):
    """
    Rendert einen einheitlichen Seitenkopf.

    Args:
        title: Haupttitel der Seite
        subtitle: Optionaler Untertitel
    """
    st.title(title)
    if subtitle:
        st.caption(subtitle)


def show_notification(message: str, type: str = "info"):
    """
    Zeigt eine Benachrichtigung an.

    Args:
        message: Nachrichtentext
        type: Typ der Nachricht (info, success, warning, error)
    """
    if type == "success":
        st.success(message)
    elif type == "warning":
        st.warning(message)
    elif type == "error":
        st.error(message)
    else:
        st.info(message)


def _render_compact_share_buttons(title: str, text: str, key_prefix: str = "share"):
    """
    Kompakte Teilen-Buttons für die Sidebar.
    """
    import urllib.parse

    share_text = f"{title}\n\n{text}"
    encoded_text = urllib.parse.quote(share_text)

    whatsapp_url = f"https://wa.me/?text={encoded_text}"
    telegram_url = f"https://t.me/share/url?text={encoded_text}"

    st.markdown(
        f'<a href="{whatsapp_url}" target="_blank">'
        f'<button style="background: #25D366; color: white; border: none; '
        f'padding: 5px 10px; border-radius: 5px; margin: 2px; font-size: 12px;">'
        f'📱 WhatsApp</button></a>'
        f'<a href="{telegram_url}" target="_blank">'
        f'<button style="background: #0088cc; color: white; border: none; '
        f'padding: 5px 10px; border-radius: 5px; margin: 2px; font-size: 12px;">'
        f'✈️ Telegram</button></a>',
        unsafe_allow_html=True
    )


def render_api_status():
    """
    Rendert die Ampel-Anzeige für API-Status.
    🟢 = Verbunden und funktioniert
    🟡 = Konfiguriert, aber nicht verbunden/Fehler
    🔴 = Nicht konfiguriert
    """
    from config.settings import get_settings
    from services.ai_service import get_ai_service

    settings = get_settings()
    ai_service = get_ai_service()

    # Status-Check (gecached)
    if 'api_status' not in st.session_state:
        st.session_state.api_status = ai_service.test_connection()

    status = st.session_state.api_status

    st.markdown("### 🚦 API-Status")

    # OpenAI Status
    col1, col2 = st.columns([1, 3])
    with col1:
        if status.get('openai'):
            st.markdown("🟢")
        elif settings.openai_api_key:
            st.markdown("🟡")
        else:
            st.markdown("🔴")
    with col2:
        st.markdown("**OpenAI**")
        if status.get('openai'):
            st.caption("✓ Verbunden")
        elif settings.openai_api_key:
            error = status.get('openai_error', 'Verbindungsfehler')
            # Fehler kürzen
            if len(str(error)) > 50:
                error = str(error)[:50] + "..."
            st.caption(f"⚠ {error}")
        else:
            st.caption("Nicht konfiguriert")

    # Anthropic/Claude Status
    col1, col2 = st.columns([1, 3])
    with col1:
        if status.get('anthropic'):
            st.markdown("🟢")
        elif settings.anthropic_api_key:
            st.markdown("🟡")
        else:
            st.markdown("🔴")
    with col2:
        st.markdown("**Claude**")
        if status.get('anthropic'):
            st.caption("✓ Verbunden")
        elif settings.anthropic_api_key:
            error = status.get('anthropic_error', 'Verbindungsfehler')
            if len(str(error)) > 50:
                error = str(error)[:50] + "..."
            st.caption(f"⚠ {error}")
        else:
            st.caption("Nicht konfiguriert")

    # Button zum erneuten Testen
    if st.button("🔄 Verbindung testen", key="sb_test_api", use_container_width=True):
        # Cache löschen und neu testen
        if 'api_status' in st.session_state:
            del st.session_state.api_status
        if 'ai_service' in st.session_state:
            del st.session_state.ai_service
        st.rerun()


def render_sidebar_cart():
    """
    Rendert die Sidebar mit Navigation und Aktentasche.
    Diese Funktion ist jetzt ein Alias für render_sidebar_with_navigation()
    für Rückwärtskompatibilität.
    """
    # Versuche den Dateinamen der aufrufenden Seite zu ermitteln
    import inspect
    try:
        frame = inspect.currentframe()
        if frame and frame.f_back:
            caller_file = frame.f_back.f_globals.get('__file__', '')
            if caller_file:
                # Pfad normalisieren
                from pathlib import Path
                caller_path = Path(caller_file)
                if 'pages' in caller_path.parts:
                    # Relativer Pfad ab pages/
                    idx = caller_path.parts.index('pages')
                    rel_path = '/'.join(caller_path.parts[idx:])
                    st.session_state['_current_page'] = rel_path
                else:
                    st.session_state['_current_page'] = caller_path.name
    except Exception:
        pass

    # Neue Navigation rendern
    render_sidebar_with_navigation()


def add_to_cart(document_id: int):
    """Fügt ein Dokument zur Aktentasche hinzu"""
    if 'active_cart_items' not in st.session_state:
        st.session_state.active_cart_items = []
    if document_id not in st.session_state.active_cart_items:
        st.session_state.active_cart_items.append(document_id)
        return True
    return False


def remove_from_cart(document_id: int):
    """Entfernt ein Dokument aus der Aktentasche"""
    if 'active_cart_items' in st.session_state:
        if document_id in st.session_state.active_cart_items:
            st.session_state.active_cart_items.remove(document_id)
            return True
    return False


def get_cart_items():
    """Gibt die Dokument-IDs in der Aktentasche zurück"""
    return st.session_state.get('active_cart_items', [])


def clear_cart():
    """Leert die Aktentasche"""
    st.session_state.active_cart_items = []


def apply_custom_css():
    """Wendet das benutzerdefinierte CSS an"""
    st.markdown("""
    <style>
        .main .block-container {
            padding-top: 2rem;
            padding-bottom: 2rem;
        }

        .deadline-warning {
            background-color: #fff3cd;
            border-left: 4px solid #ffc107;
            padding: 10px 15px;
            margin: 10px 0;
            border-radius: 4px;
        }

        .deadline-urgent {
            background-color: #f8d7da;
            border-left: 4px solid #dc3545;
            padding: 10px 15px;
            margin: 10px 0;
            border-radius: 4px;
        }

        .info-card {
            background-color: #f8f9fa;
            border-radius: 8px;
            padding: 15px;
            margin: 10px 0;
            border: 1px solid #e9ecef;
        }

        .stButton>button {
            border-radius: 6px;
        }

        /* Sidebar kompakter */
        section[data-testid="stSidebar"] {
            width: 300px !important;
        }

        section[data-testid="stSidebar"] .block-container {
            padding: 1rem;
        }

        /* Standard-Navigation verstecken */
        [data-testid="stSidebarNav"] {
            display: none !important;
        }

        /* Benutzerdefinierte Navigation Styling */
        .nav-category {
            font-weight: 600;
            font-size: 0.85rem;
            color: #666;
            padding: 8px 0 4px 0;
            margin-top: 8px;
            border-bottom: 1px solid #eee;
        }

        .nav-item {
            padding: 6px 12px;
            margin: 2px 0;
            border-radius: 6px;
            cursor: pointer;
            transition: background-color 0.2s;
            font-size: 0.9rem;
        }

        .nav-item:hover {
            background-color: #f0f2f6;
        }

        .nav-item.active {
            background-color: #e3e8ef;
            font-weight: 500;
        }

        .nav-expander {
            border: none !important;
            background: transparent !important;
        }

        .nav-expander > div:first-child {
            padding: 4px 0 !important;
        }
    </style>
    """, unsafe_allow_html=True)


# Navigationsstruktur: Kategorien mit Seiten
NAVIGATION_STRUCTURE = {
    "📊 Übersicht": {
        "icon": "📊",
        "pages": [
            {"name": "Dashboard", "icon": "📊", "path": "streamlit_app.py"},
        ]
    },
    "📄 Dokumente": {
        "icon": "📄",
        "expanded": True,  # Standardmäßig geöffnet
        "pages": [
            {"name": "Dokumentenaufnahme", "icon": "📄", "path": "pages/2_📄_Dokumentenaufnahme.py"},
            {"name": "Dokumentenverwaltung", "icon": "📁", "path": "pages/3_📁_Dokumente.py"},
            {"name": "Intelligente Ordner", "icon": "🔍", "path": "pages/4_🔍_Intelligente_Ordner.py"},
            {"name": "Dokument-Chat", "icon": "💬", "path": "pages/11_💬_Dokument_Chat.py"},
        ]
    },
    "💰 Finanzen": {
        "icon": "💰",
        "pages": [
            {"name": "Finanzen", "icon": "💰", "path": "pages/7_💰_Finanzen.py"},
            {"name": "Finanz-Dashboard", "icon": "📈", "path": "pages/13_📈_Finanz_Dashboard.py"},
            {"name": "Steuer-Report", "icon": "📊", "path": "pages/21_📊_Steuer_Report.py"},
            {"name": "Abonnements", "icon": "💳", "path": "pages/17_💳_Abonnements.py"},
        ]
    },
    "📋 Verträge & Versicherungen": {
        "icon": "📋",
        "pages": [
            {"name": "Verträge", "icon": "📑", "path": "pages/10_📑_Vertraege.py"},
            {"name": "Versicherungen", "icon": "🏥", "path": "pages/16_🏥_Versicherungen.py"},
            {"name": "Garantien", "icon": "🛡️", "path": "pages/15_🛡️_Garantien.py"},
        ]
    },
    "🏠 Objekte & Entitäten": {
        "icon": "🏠",
        "pages": [
            {"name": "Immobilien", "icon": "🏘️", "path": "pages/23_🏘️_Immobilien.py"},
            {"name": "Entitäten", "icon": "👥", "path": "pages/24_👥_Entitäten.py"},
            {"name": "Inventar", "icon": "🏠", "path": "pages/18_🏠_Inventar.py"},
            {"name": "Kilometerlogbuch", "icon": "🚗", "path": "pages/20_🚗_Kilometerlogbuch.py"},
        ]
    },
    "📅 Organisation": {
        "icon": "📅",
        "pages": [
            {"name": "Kalender", "icon": "📅", "path": "pages/5_📅_Kalender.py"},
            {"name": "E-Mail", "icon": "📧", "path": "pages/6_📧_E-Mail.py"},
            {"name": "Vorlagen", "icon": "📝", "path": "pages/19_📝_Vorlagen.py"},
        ]
    },
    "🔧 Tools": {
        "icon": "🔧",
        "pages": [
            {"name": "Diktierfunktion", "icon": "🎤", "path": "pages/9_🎤_Diktierfunktion.py"},
            {"name": "Automatisierung", "icon": "🤖", "path": "pages/12_🤖_Automatisierung.py"},
            {"name": "Backup", "icon": "💾", "path": "pages/22_💾_Backup.py"},
        ]
    },
    "⚙️ System": {
        "icon": "⚙️",
        "pages": [
            {"name": "Einstellungen", "icon": "⚙️", "path": "pages/8_⚙️_Einstellungen.py"},
        ]
    },
}


def get_current_page_path():
    """Ermittelt den aktuellen Seitenpfad"""
    try:
        # Versuche den aktuellen Pfad aus verschiedenen Quellen zu ermitteln
        import streamlit as st
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        if ctx:
            return ctx.page_script_hash
    except Exception:
        pass

    # Fallback: Aus URL oder Session State
    return st.session_state.get('_current_page', 'streamlit_app.py')


def render_smart_navigation():
    """
    Rendert eine intelligente, gruppierte Navigation in der Sidebar.
    Ersetzt die Standard-Streamlit-Navigation.
    """
    # Aktuelle Seite ermitteln für Highlighting
    try:
        current_page = st.session_state.get('_current_page', '')
    except Exception:
        current_page = ''

    st.markdown("### 🗂️ Navigation")

    for category_name, category_data in NAVIGATION_STRUCTURE.items():
        # Session State Key für Expander-Status
        expander_key = f"nav_exp_{category_name}"
        if expander_key not in st.session_state:
            st.session_state[expander_key] = category_data.get('expanded', False)

        # Prüfen ob eine Seite dieser Kategorie aktiv ist
        category_has_active = any(
            page['path'] in current_page or current_page in page['path']
            for page in category_data['pages']
        )

        # Kategorie automatisch öffnen wenn aktive Seite darin
        if category_has_active:
            st.session_state[expander_key] = True

        with st.expander(category_name, expanded=st.session_state[expander_key]):
            for page in category_data['pages']:
                # Aktive Seite hervorheben
                is_active = page['path'] in current_page or current_page in page['path']

                # Button-Style je nach Status
                button_type = "primary" if is_active else "secondary"

                col1, col2 = st.columns([1, 6])
                with col1:
                    st.write(page['icon'])
                with col2:
                    if st.button(
                        page['name'],
                        key=f"nav_{page['path']}",
                        use_container_width=True,
                        type=button_type if is_active else "secondary",
                        disabled=is_active
                    ):
                        st.session_state['_current_page'] = page['path']
                        st.switch_page(page['path'])


def render_sidebar_with_navigation():
    """
    Rendert die komplette Sidebar mit Navigation, Aktentasche und Status.
    Sollte in jeder Seite aufgerufen werden.
    """
    from database.db import get_db, get_current_user_id
    from database.models import Document

    with st.sidebar:
        st.title("📁 Dokumentenmanagement")

        # Smart Navigation
        render_smart_navigation()

        st.divider()

        # API-Status mit Ampel
        render_api_status()

        st.divider()

        # === AKTENTASCHE ===
        st.markdown("### 💼 Aktentasche")

        cart_items = st.session_state.get('active_cart_items', [])
        cart_name = st.session_state.get('active_cart_name', 'Aktuelle Aktentasche')

        with st.expander(f"**{cart_name}** ({len(cart_items)})", expanded=False):
            if cart_items:
                user_id = get_current_user_id()
                with get_db() as session:
                    docs = session.query(Document).filter(
                        Document.id.in_(cart_items)
                    ).all()

                    for doc in docs:
                        col_doc, col_remove = st.columns([4, 1])
                        with col_doc:
                            st.caption(f"📄 {(doc.title or doc.filename)[:25]}...")
                        with col_remove:
                            if st.button("✕", key=f"sb_remove_{doc.id}", help="Entfernen"):
                                st.session_state.active_cart_items.remove(doc.id)
                                st.rerun()

                st.divider()

                col_a, col_b, col_c = st.columns(3)
                with col_a:
                    if st.button("🗑️", key="sb_clear_cart", help="Leeren"):
                        st.session_state.active_cart_items = []
                        st.rerun()
                with col_b:
                    if st.button("📂", key="sb_open_cart", help="Öffnen"):
                        st.switch_page("pages/4_🔍_Intelligente_Ordner.py")
                with col_c:
                    if st.button("📤", key="sb_share_cart", help="Teilen"):
                        st.session_state.show_cart_share = True
                        st.rerun()

                if st.session_state.get('show_cart_share'):
                    from utils.helpers import create_share_text_for_documents
                    share_text = create_share_text_for_documents(docs)
                    _render_compact_share_buttons(
                        f"💼 Aktentasche: {cart_name}",
                        share_text,
                        "cart"
                    )
                    if st.button("✕ Schließen", key="close_share"):
                        st.session_state.show_cart_share = False
                        st.rerun()
            else:
                st.caption("Leer - Dokumente hier ablegen")

        st.divider()
        st.caption(f"📌 {get_version_string()}")
        st.caption("Privat & Sicher 🔒")
