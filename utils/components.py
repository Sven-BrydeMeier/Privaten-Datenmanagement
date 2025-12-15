"""
Gemeinsame UI-Komponenten für alle Seiten
"""
import streamlit as st
from pathlib import Path
import sys
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

# App-Version im Format JJ.MM.TT.HHMM (letzte 4 Ziffern = Uhrzeit der letzten Änderung)
APP_VERSION = "25.12.15.1230"
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
    Rendert die Aktentasche in der Sidebar.
    Muss in jeder Seite aufgerufen werden.
    """
    from database.db import get_db, get_current_user_id
    from database.models import Document

    with st.sidebar:
        st.title("📁 Dokumentenmanagement")

        # API-Status mit Ampel
        render_api_status()

        st.divider()

        # === AKTENTASCHE ===
        st.markdown("### 💼 Aktentasche")

        cart_items = st.session_state.get('active_cart_items', [])
        cart_name = st.session_state.get('active_cart_name', 'Aktuelle Aktentasche')

        # Aktentasche-Name bearbeiten
        with st.expander(f"**{cart_name}** ({len(cart_items)})", expanded=True):
            # Dokumente in der Aktentasche anzeigen
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

                # Aktionen
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

                # Teilen-Dialog
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

            # Schnelles Hinzufügen per Dokument-ID
            st.markdown("---")
            st.caption("**Schnell hinzufügen:**")
            quick_add = st.text_input("Dokument-ID", key="sb_quick_add", label_visibility="collapsed", placeholder="Dokument-ID...")
            if quick_add:
                try:
                    doc_id = int(quick_add)
                    if 'active_cart_items' not in st.session_state:
                        st.session_state.active_cart_items = []
                    if doc_id not in st.session_state.active_cart_items:
                        st.session_state.active_cart_items.append(doc_id)
                        st.success("Hinzugefügt!")
                        st.rerun()
                except ValueError:
                    pass

        st.divider()
        st.caption(f"📌 {get_version_string()}")
        st.caption("Privat & Sicher 🔒")


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
            width: 280px !important;
        }

        section[data-testid="stSidebar"] .block-container {
            padding: 1rem;
        }
    </style>
    """, unsafe_allow_html=True)
