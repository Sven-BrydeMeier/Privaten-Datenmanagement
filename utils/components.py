"""
Gemeinsame UI-Komponenten für alle Seiten
"""
import streamlit as st
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))


def render_sidebar_cart():
    """
    Rendert die Aktentasche in der Sidebar.
    Muss in jeder Seite aufgerufen werden.
    """
    from database.db import get_db, get_current_user_id
    from database.models import Document
    from config.settings import get_settings

    with st.sidebar:
        st.title("📁 Dokumentenmanagement")

        # API-Status
        settings = get_settings()
        from services.ai_service import get_ai_service
        ai_service = get_ai_service()

        if 'api_status' not in st.session_state:
            st.session_state.api_status = ai_service.test_connection()

        status = st.session_state.api_status

        # Kompakte Status-Anzeige
        col1, col2 = st.columns(2)
        with col1:
            if status.get('openai'):
                st.markdown('<span style="color: #28a745;">●</span> OpenAI', unsafe_allow_html=True)
            elif settings.openai_api_key:
                st.markdown('<span style="color: #dc3545;">●</span> OpenAI', unsafe_allow_html=True)
            else:
                st.markdown('<span style="color: #6c757d;">●</span> OpenAI', unsafe_allow_html=True)

        with col2:
            if status.get('anthropic'):
                st.markdown('<span style="color: #28a745;">●</span> Claude', unsafe_allow_html=True)
            elif settings.anthropic_api_key:
                st.markdown('<span style="color: #dc3545;">●</span> Claude', unsafe_allow_html=True)
            else:
                st.markdown('<span style="color: #6c757d;">●</span> Claude', unsafe_allow_html=True)

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
                col_a, col_b = st.columns(2)
                with col_a:
                    if st.button("🗑️", key="sb_clear_cart", help="Leeren"):
                        st.session_state.active_cart_items = []
                        st.rerun()
                with col_b:
                    if st.button("📂", key="sb_open_cart", help="Öffnen"):
                        st.switch_page("pages/4_🔍_Intelligente_Ordner.py")

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

        # Navigation
        st.markdown("### 📌 Navigation")

        nav_items = [
            ("📊 Dashboard", "streamlit_app.py"),
            ("📄 Dokumentenaufnahme", "pages/2_📄_Dokumentenaufnahme.py"),
            ("📁 Dokumente", "pages/3_📁_Dokumente.py"),
            ("🔍 Intelligente Ordner", "pages/4_🔍_Intelligente_Ordner.py"),
            ("📅 Kalender", "pages/5_📅_Kalender.py"),
            ("📧 E-Mail", "pages/6_📧_E-Mail.py"),
            ("💰 Finanzen", "pages/7_💰_Finanzen.py"),
            ("⚙️ Einstellungen", "pages/8_⚙️_Einstellungen.py"),
        ]

        for label, page in nav_items:
            if st.button(label, key=f"nav_{page}", use_container_width=True):
                st.switch_page(page)

        st.divider()
        st.caption("v1.0.0 | Privat & Sicher")


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
