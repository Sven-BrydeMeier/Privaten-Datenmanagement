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


# =============================================================================
# TOP-MENÜ MIT GLOBALER SUCHE
# =============================================================================

def render_top_search_bar():
    """
    Rendert die globale Suchleiste im oberen Bereich.
    Wird auf jeder Seite angezeigt.
    """
    # CSS für die Suchleiste
    st.markdown("""
    <style>
        /* Top-Bar Container */
        .top-search-container {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 12px 20px;
            margin: -1rem -1rem 1rem -1rem;
            border-radius: 0 0 10px 10px;
        }

        /* Such-Input Styling */
        .top-search-container input {
            border-radius: 20px !important;
            border: none !important;
            padding: 10px 20px !important;
        }

        /* Suchergebnisse Dropdown */
        .search-results-dropdown {
            background: white;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            margin-top: 8px;
            max-height: 400px;
            overflow-y: auto;
        }

        .search-result-item {
            padding: 10px 15px;
            border-bottom: 1px solid #eee;
            cursor: pointer;
        }

        .search-result-item:hover {
            background: #f8f9fa;
        }
    </style>
    """, unsafe_allow_html=True)

    # Suchleiste
    col_logo, col_search, col_actions = st.columns([1, 4, 1])

    with col_logo:
        st.markdown("**📁 DMS**")

    with col_search:
        search_query = st.text_input(
            "Suche",
            placeholder="🔍 Dokumente durchsuchen... (Begriff eingeben + Enter)",
            key="global_top_search",
            label_visibility="collapsed"
        )

        # Bei Eingabe zur Suchseite navigieren
        if search_query:
            st.session_state.search_query_from_top = search_query
            st.switch_page("pages/0_🔎_Suche.py")

    with col_actions:
        if st.button("⚙️", key="top_settings", help="Einstellungen"):
            st.switch_page("pages/8_⚙️_Einstellungen.py")

    st.divider()


def render_top_menu_full():
    """
    Vollständiges Top-Menü mit Suchleiste.
    Immer oben auf jeder Seite sichtbar.
    """
    # CSS für fixiertes Top-Menü
    st.markdown("""
    <style>
        /* Fixiertes Top-Menü */
        .stApp > header {
            background: transparent !important;
        }

        /* Haupt-Content nach unten verschieben */
        .main .block-container {
            padding-top: 0.5rem !important;
        }
    </style>
    """, unsafe_allow_html=True)

    # Suchzeile
    search_cols = st.columns([1, 5, 1])

    with search_cols[0]:
        st.markdown("### 📁")

    with search_cols[1]:
        search = st.text_input(
            "Suche",
            placeholder="🔍 Dokumente, Beträge, IBAN suchen...",
            key="topmenu_search",
            label_visibility="collapsed"
        )

        if search:
            st.session_state.search_query_from_top = search
            st.switch_page("pages/0_🔎_Suche.py")

    with search_cols[2]:
        st.markdown("")  # Spacer

    st.divider()


# =============================================================================
# BAUM-NAVIGATION OHNE BUTTONS
# =============================================================================

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


def render_tree_sidebar():
    """
    Rendert die komplette Sidebar mit:
    - Baum-Navigation (klickbare Texte, keine Buttons)
    - Aktentasche
    - API-Status
    """
    from database.db import get_db, get_current_user_id
    from database.models import Document
    from utils.components import get_version_string, render_api_status

    # CSS für Button-lose Navigation
    st.markdown("""
    <style>
        /* Standard-Navigation ausblenden */
        [data-testid="stSidebarNav"] {
            display: none !important;
        }

        /* Sidebar schmaler */
        section[data-testid="stSidebar"] {
            width: 280px !important;
        }

        /* Navigation: Buttons wie Links aussehen lassen */
        .nav-text-link button {
            background: none !important;
            border: none !important;
            color: #444 !important;
            text-align: left !important;
            padding: 4px 0 !important;
            font-size: 0.9rem !important;
            cursor: pointer !important;
            width: 100% !important;
        }

        .nav-text-link button:hover {
            color: #0066cc !important;
            background: none !important;
        }

        .nav-text-link button:focus {
            box-shadow: none !important;
            outline: none !important;
        }

        /* Aktive Seite */
        .nav-text-link-active button {
            background: none !important;
            border: none !important;
            color: #0066cc !important;
            font-weight: 600 !important;
            text-align: left !important;
            padding: 4px 0 !important;
        }

        /* Kategorie-Header */
        .nav-category-header button {
            background: none !important;
            border: none !important;
            color: #222 !important;
            font-weight: 600 !important;
            font-size: 0.95rem !important;
            padding: 8px 0 4px 0 !important;
            cursor: pointer !important;
        }

        .nav-category-header button:hover {
            color: #0066cc !important;
        }

        /* Untermenü Einrückung */
        .nav-submenu {
            padding-left: 12px;
            border-left: 2px solid #e0e0e0;
            margin-left: 8px;
        }

        /* Pfeil-Icons */
        .nav-arrow {
            font-size: 0.7em;
            color: #666;
        }
    </style>
    """, unsafe_allow_html=True)

    with st.sidebar:
        # Logo/Titel
        st.markdown("## 📁 Dokumentenverwaltung")

        # Globale Suche Button
        st.markdown('<div class="nav-text-link">', unsafe_allow_html=True)
        if st.button("🔍 Suche", key="nav_search", use_container_width=True):
            st.switch_page("pages/0_🔎_Suche.py")
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown("---")

        # Aktuelle Seite ermitteln
        current_page = st.session_state.get('_current_page', '')

        # Baum-Navigation
        for category, items in TREE_NAVIGATION.items():
            # State für geöffnete Kategorien
            state_key = f"nav_open_{category}"
            if state_key not in st.session_state:
                # Automatisch öffnen wenn aktive Seite darin
                st.session_state[state_key] = any(
                    path in current_page for path in items.values()
                )

            # Kategorie-Header (klickbar zum Auf-/Zuklappen)
            arrow = "▼" if st.session_state[state_key] else "▶"

            st.markdown('<div class="nav-category-header">', unsafe_allow_html=True)
            if st.button(f"{arrow} {category}", key=f"cat_{category}", use_container_width=True):
                st.session_state[state_key] = not st.session_state[state_key]
                st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

            # Untermenü anzeigen wenn geöffnet
            if st.session_state[state_key]:
                st.markdown('<div class="nav-submenu">', unsafe_allow_html=True)

                for item_name, item_path in items.items():
                    is_active = item_path in current_page

                    css_class = "nav-text-link-active" if is_active else "nav-text-link"
                    prefix = "→ " if is_active else "  "

                    st.markdown(f'<div class="{css_class}">', unsafe_allow_html=True)
                    if st.button(
                        f"{prefix}{item_name}",
                        key=f"nav_{item_path}",
                        use_container_width=True,
                        disabled=is_active
                    ):
                        st.session_state['_current_page'] = item_path
                        st.switch_page(item_path)
                    st.markdown('</div>', unsafe_allow_html=True)

                st.markdown('</div>', unsafe_allow_html=True)

        st.markdown("---")

        # API-Status
        render_api_status()

        st.markdown("---")

        # Aktentasche
        st.markdown("### 💼 Aktentasche")

        cart_items = st.session_state.get('active_cart_items', [])

        if cart_items:
            st.caption(f"{len(cart_items)} Dokument(e)")

            user_id = get_current_user_id()
            with get_db() as session:
                docs = session.query(Document).filter(
                    Document.id.in_(cart_items)
                ).all()

                for doc in docs[:5]:  # Nur erste 5 anzeigen
                    title = (doc.title or doc.filename)[:20]
                    col_doc, col_rm = st.columns([5, 1])
                    with col_doc:
                        st.caption(f"• {title}...")
                    with col_rm:
                        if st.button("×", key=f"rm_cart_{doc.id}"):
                            st.session_state.active_cart_items.remove(doc.id)
                            st.rerun()

                if len(docs) > 5:
                    st.caption(f"... und {len(docs) - 5} weitere")

            if st.button("Aktentasche leeren", key="clear_cart_btn"):
                st.session_state.active_cart_items = []
                st.rerun()
        else:
            st.caption("Leer")

        st.markdown("---")

        # Version
        st.caption(get_version_string())


def apply_new_layout():
    """
    Wendet das neue Layout mit Top-Menü und Baum-Navigation an.
    Sollte am Anfang jeder Seite aufgerufen werden.
    """
    # Aktuelle Seite ermitteln
    import inspect
    try:
        frame = inspect.currentframe()
        if frame and frame.f_back:
            caller_file = frame.f_back.f_globals.get('__file__', '')
            if caller_file:
                from pathlib import Path
                caller_path = Path(caller_file)
                if 'pages' in caller_path.parts:
                    idx = caller_path.parts.index('pages')
                    rel_path = '/'.join(caller_path.parts[idx:])
                    st.session_state['_current_page'] = rel_path
                else:
                    st.session_state['_current_page'] = caller_path.name
    except Exception:
        pass

    # Top-Suchleiste rendern
    render_top_menu_full()

    # Sidebar mit Baum-Navigation rendern
    render_tree_sidebar()


# =============================================================================
# SUCHSEITEN-FUNKTIONEN
# =============================================================================

def render_search_page():
    """
    Rendert eine dedizierte Suchseite mit erweiterten Optionen.
    """
    from database.db import get_db, get_current_user_id
    from database.models import Document, Folder
    from config.settings import DOCUMENT_CATEGORIES
    from utils.helpers import format_currency, format_date, get_document_file_content
    from services.encryption import get_encryption_service

    user_id = get_current_user_id()

    st.title("🔍 Dokumentensuche")

    # Suchbegriff aus Top-Menü übernehmen wenn vorhanden
    initial_search = st.session_state.get('search_query_from_top', '')
    if initial_search:
        # Einmalig übernehmen und dann löschen
        del st.session_state['search_query_from_top']

    # Suchbereich
    search_terms = st.text_input(
        "Suchbegriffe",
        value=initial_search,
        placeholder="Mehrere Begriffe mit Leerzeichen trennen...",
        key="search_terms_input"
    )

    # Erweiterte Filter
    with st.expander("Erweiterte Filter", expanded=False):
        filter_cols = st.columns(3)

        with filter_cols[0]:
            filter_category = st.selectbox(
                "Kategorie",
                options=["Alle"] + DOCUMENT_CATEGORIES,
                key="search_filter_category"
            )

        with filter_cols[1]:
            filter_date_from = st.date_input(
                "Datum von",
                value=None,
                key="search_filter_date_from"
            )

        with filter_cols[2]:
            filter_date_to = st.date_input(
                "Datum bis",
                value=None,
                key="search_filter_date_to"
            )

        filter_cols2 = st.columns(3)

        with filter_cols2[0]:
            filter_sender = st.text_input(
                "Absender",
                key="search_filter_sender"
            )

        with filter_cols2[1]:
            filter_amount_min = st.number_input(
                "Betrag min (€)",
                min_value=0.0,
                value=0.0,
                step=10.0,
                key="search_filter_amount_min"
            )

        with filter_cols2[2]:
            filter_amount_max = st.number_input(
                "Betrag max (€)",
                min_value=0.0,
                value=0.0,
                step=10.0,
                key="search_filter_amount_max"
            )

    # Ansichtsmodus
    view_mode = st.radio(
        "Ansicht",
        options=["Liste", "Kompakt", "Karten"],
        horizontal=True,
        key="search_view_mode",
        label_visibility="collapsed"
    )

    # Automatisch suchen wenn Suchbegriff vorhanden
    if search_terms:
        with st.spinner("Suche läuft..."):
            # Alle Suchbegriffe extrahieren (AND-Logik)
            terms = search_terms.strip().split()

            with get_db() as session:
                # Basis-Query
                query = session.query(Document).filter(
                    Document.user_id == user_id,
                    (Document.is_deleted == False) | (Document.is_deleted == None)
                )

                # Für jeden Begriff suchen (AND-Logik)
                for term in terms:
                    search_pattern = f'%{term}%'
                    query = query.filter(
                        (Document.title.ilike(search_pattern)) |
                        (Document.filename.ilike(search_pattern)) |
                        (Document.sender.ilike(search_pattern)) |
                        (Document.ocr_text.ilike(search_pattern)) |
                        (Document.subject.ilike(search_pattern)) |
                        (Document.reference_number.ilike(search_pattern)) |
                        (Document.customer_number.ilike(search_pattern)) |
                        (Document.iban.ilike(search_pattern)) |
                        (Document.category.ilike(search_pattern))
                    )

                # Filter anwenden
                if filter_category != "Alle":
                    query = query.filter(Document.category == filter_category)

                if filter_date_from:
                    query = query.filter(Document.document_date >= filter_date_from)

                if filter_date_to:
                    query = query.filter(Document.document_date <= filter_date_to)

                if st.session_state.get('search_filter_sender'):
                    query = query.filter(Document.sender.ilike(f"%{filter_sender}%"))

                if filter_amount_min > 0:
                    query = query.filter(Document.invoice_amount >= filter_amount_min)

                if filter_amount_max > 0:
                    query = query.filter(Document.invoice_amount <= filter_amount_max)

                # Ergebnisse holen
                results = query.order_by(Document.document_date.desc()).limit(100).all()

                # Ordnerpfade laden
                folder_map = {}
                folders = session.query(Folder).filter(Folder.user_id == user_id).all()
                for folder in folders:
                    path_parts = [folder.name]
                    parent = session.get(Folder, folder.parent_id) if folder.parent_id else None
                    while parent:
                        path_parts.insert(0, parent.name)
                        parent = session.get(Folder, parent.parent_id) if parent.parent_id else None
                    folder_map[folder.id] = " / ".join(path_parts)

                # Ergebnisse vorbereiten
                results_data = []
                for doc in results:
                    results_data.append({
                        'id': doc.id,
                        'title': doc.title or doc.filename,
                        'filename': doc.filename,
                        'file_path': doc.file_path,
                        'mime_type': doc.mime_type,
                        'is_encrypted': doc.is_encrypted,
                        'encryption_iv': doc.encryption_iv,
                        'sender': doc.sender,
                        'category': doc.category,
                        'folder_id': doc.folder_id,
                        'folder_path': folder_map.get(doc.folder_id, "Nicht zugeordnet"),
                        'document_date': doc.document_date,
                        'invoice_amount': doc.invoice_amount,
                        'iban': doc.iban,
                    })

        # Ergebnisse anzeigen
        if results_data:
            st.success(f"**{len(results_data)} Treffer** für \"{search_terms}\"")

            if view_mode == "Liste":
                _render_search_results_list(results_data)
            elif view_mode == "Kompakt":
                _render_search_results_compact(results_data)
            else:
                _render_search_results_cards(results_data)
        else:
            st.info("Keine Treffer gefunden. Versuchen Sie andere Suchbegriffe.")
    else:
        st.info("Geben Sie einen Suchbegriff ein, um Dokumente zu finden.")


def _render_search_results_list(results: list):
    """Rendert Suchergebnisse als Liste"""
    from utils.helpers import format_currency, format_date

    for doc in results:
        with st.container():
            col_info, col_actions = st.columns([4, 1])

            with col_info:
                st.markdown(f"**{doc['title']}**")

                meta_parts = []
                if doc['sender']:
                    meta_parts.append(f"Von: {doc['sender']}")
                if doc['category']:
                    meta_parts.append(doc['category'])
                if doc['document_date']:
                    meta_parts.append(format_date(doc['document_date']))
                if doc['invoice_amount']:
                    meta_parts.append(format_currency(doc['invoice_amount']))

                st.caption(" | ".join(meta_parts) if meta_parts else "—")
                st.caption(f"📍 {doc['folder_path']}")

            with col_actions:
                # Ansehen
                if st.button("Öffnen", key=f"sr_view_{doc['id']}"):
                    st.session_state.view_document_id = doc['id']
                    st.switch_page("pages/3_📁_Dokumente.py")

            st.divider()


def _render_search_results_compact(results: list):
    """Rendert Suchergebnisse kompakt"""
    from utils.helpers import format_currency, format_date

    for doc in results:
        col_title, col_sender, col_date, col_amount, col_action = st.columns([3, 2, 1, 1, 1])

        with col_title:
            st.markdown(f"**{doc['title'][:30]}**" + ("..." if len(doc['title']) > 30 else ""))

        with col_sender:
            st.caption(doc['sender'] or "—")

        with col_date:
            if doc['document_date']:
                st.caption(format_date(doc['document_date']))

        with col_amount:
            if doc['invoice_amount']:
                st.caption(format_currency(doc['invoice_amount']))

        with col_action:
            if st.button("→", key=f"sr_go_{doc['id']}", help="Öffnen"):
                st.session_state.view_document_id = doc['id']
                st.switch_page("pages/3_📁_Dokumente.py")


def _render_search_results_cards(results: list):
    """Rendert Suchergebnisse als Karten"""
    from utils.helpers import format_currency, format_date

    # 3 Karten pro Zeile
    cols = st.columns(3)

    for i, doc in enumerate(results):
        with cols[i % 3]:
            with st.container():
                st.markdown(f"**{doc['title'][:25]}**" + ("..." if len(doc['title']) > 25 else ""))

                if doc['sender']:
                    st.caption(f"Von: {doc['sender']}")

                if doc['document_date']:
                    st.caption(f"📅 {format_date(doc['document_date'])}")

                if doc['invoice_amount']:
                    st.caption(f"💰 {format_currency(doc['invoice_amount'])}")

                st.caption(f"📍 {doc['folder_path']}")

                if st.button("Öffnen", key=f"sr_card_{doc['id']}", use_container_width=True):
                    st.session_state.view_document_id = doc['id']
                    st.switch_page("pages/3_📁_Dokumente.py")

                st.markdown("---")
