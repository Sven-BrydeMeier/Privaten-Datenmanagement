"""
Neue UI-Komponenten:
- Globale Suchfunktion
- Top-Menü mit Suche und Einstellungen
- Baum-Navigation ohne Buttons
"""
import streamlit as st
from pathlib import Path
import sys
from typing import Optional, List, Dict
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))


def render_global_search():
    """
    Rendert die globale Suchfunktion.
    Zeigt Suchergebnisse mit Standort (Ordnerpfad) und Aktionen.
    """
    from database.db import get_db, get_current_user_id
    from database.models import Document, Folder
    from services.search_service import get_search_service
    from utils.helpers import format_currency, format_date

    user_id = get_current_user_id()

    # Such-State initialisieren
    if 'global_search_query' not in st.session_state:
        st.session_state.global_search_query = ""
    if 'global_search_results' not in st.session_state:
        st.session_state.global_search_results = None

    # Suchfeld
    col_search, col_filters = st.columns([3, 1])

    with col_search:
        search_query = st.text_input(
            "Suchen",
            value=st.session_state.global_search_query,
            placeholder="Begriff eingeben... (z.B. Rechnung, IBAN, Betrag)",
            key="global_search_input",
            label_visibility="collapsed"
        )

    with col_filters:
        search_in = st.selectbox(
            "Suchen in",
            options=["Alles", "Titel", "Inhalt", "Absender", "Beträge"],
            key="search_in_select",
            label_visibility="collapsed"
        )

    # Suche ausführen wenn Query vorhanden
    if search_query and search_query != st.session_state.global_search_query:
        st.session_state.global_search_query = search_query

        # Suchservice verwenden
        search_service = get_search_service(user_id)
        results = search_service.search(search_query, limit=50)

        # Erweiterte Suche direkt in der Datenbank als Fallback
        if not results['items']:
            with get_db() as session:
                query = session.query(Document).filter(
                    Document.user_id == user_id,
                    (Document.is_deleted == False) | (Document.is_deleted == None)
                )

                # Suche in verschiedenen Feldern
                search_pattern = f'%{search_query}%'
                query = query.filter(
                    (Document.title.ilike(search_pattern)) |
                    (Document.filename.ilike(search_pattern)) |
                    (Document.sender.ilike(search_pattern)) |
                    (Document.ocr_text.ilike(search_pattern)) |
                    (Document.subject.ilike(search_pattern)) |
                    (Document.reference_number.ilike(search_pattern)) |
                    (Document.customer_number.ilike(search_pattern)) |
                    (Document.iban.ilike(search_pattern))
                )

                docs = query.order_by(Document.created_at.desc()).limit(50).all()

                results['items'] = []
                for doc in docs:
                    results['items'].append({
                        'id': doc.id,
                        'title': doc.title or doc.filename,
                        'sender': doc.sender,
                        'category': doc.category,
                        'folder_id': doc.folder_id,
                        'document_date': doc.document_date,
                        'invoice_amount': doc.invoice_amount,
                        'score': 1.0
                    })
                results['total'] = len(results['items'])

        st.session_state.global_search_results = results

    # Ergebnisse anzeigen
    if st.session_state.global_search_results and st.session_state.global_search_query:
        results = st.session_state.global_search_results

        if results['total'] > 0:
            st.success(f"**{results['total']} Treffer** für \"{st.session_state.global_search_query}\"")

            # Ordnerpfade laden
            folder_paths = {}
            with get_db() as session:
                folders = session.query(Folder).filter(Folder.user_id == user_id).all()
                for folder in folders:
                    # Pfad aufbauen
                    path_parts = [folder.name]
                    parent = session.get(Folder, folder.parent_id) if folder.parent_id else None
                    while parent:
                        path_parts.insert(0, parent.name)
                        parent = session.get(Folder, parent.parent_id) if parent.parent_id else None
                    folder_paths[folder.id] = " / ".join(path_parts)

            # Ergebnisliste
            for item in results['items']:
                with st.container():
                    # Ordnerpfad ermitteln
                    folder_path = folder_paths.get(item.get('folder_id'), "Nicht zugeordnet")

                    col_info, col_actions = st.columns([4, 1])

                    with col_info:
                        st.markdown(f"**{item['title']}**")

                        meta_parts = []
                        if item.get('sender'):
                            meta_parts.append(f"Von: {item['sender']}")
                        if item.get('category'):
                            meta_parts.append(item['category'])
                        if item.get('document_date'):
                            meta_parts.append(format_date(item['document_date']))
                        if item.get('invoice_amount'):
                            meta_parts.append(format_currency(item['invoice_amount']))

                        st.caption(" | ".join(meta_parts) if meta_parts else "")
                        st.caption(f"**Standort:** {folder_path}")

                    with col_actions:
                        # Aktion-Buttons
                        action_cols = st.columns(3)

                        with action_cols[0]:
                            if st.button("Ansehen", key=f"gs_view_{item['id']}", help="Dokument ansehen"):
                                st.session_state.view_document_id = item['id']
                                st.switch_page("pages/3_📁_Dokumente.py")

                        with action_cols[1]:
                            if st.button("Drucken", key=f"gs_print_{item['id']}", help="Drucken"):
                                st.session_state.print_document_id = item['id']
                                st.rerun()

                        with action_cols[2]:
                            if st.button("Senden", key=f"gs_send_{item['id']}", help="Per E-Mail senden"):
                                st.session_state.email_document_id = item['id']
                                st.switch_page("pages/6_📧_E-Mail.py")

                    st.divider()
        else:
            st.info(f"Keine Treffer für \"{st.session_state.global_search_query}\"")

    elif st.session_state.global_search_query:
        st.info("Suche starten...")


def render_top_menu():
    """
    Rendert das Top-Menü mit Suchleiste und Einstellungen.
    Immer sichtbar oben auf jeder Seite.
    """
    from utils.components import APP_NAME, get_version_string

    # CSS für Top-Menü
    st.markdown("""
    <style>
        .top-menu {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            background: white;
            z-index: 999;
            padding: 10px 20px;
            border-bottom: 1px solid #eee;
            display: flex;
            align-items: center;
            gap: 20px;
        }
        .top-menu-search {
            flex: 1;
            max-width: 500px;
        }
        .top-menu-actions {
            display: flex;
            gap: 10px;
        }
        /* Inhalt unter dem Menü */
        .main .block-container {
            padding-top: 70px !important;
        }
    </style>
    """, unsafe_allow_html=True)

    # Top-Menü Leiste
    menu_cols = st.columns([1, 4, 1, 1])

    with menu_cols[0]:
        st.markdown(f"**{APP_NAME}**")

    with menu_cols[1]:
        # Globale Suche
        search_query = st.text_input(
            "Globale Suche",
            placeholder="Dokumente durchsuchen...",
            key="top_menu_search",
            label_visibility="collapsed"
        )

        if search_query:
            st.session_state.global_search_query = search_query
            st.session_state.show_search_results = True

    with menu_cols[2]:
        if st.button("Einstellungen", key="top_menu_settings", use_container_width=True):
            st.switch_page("pages/8_⚙️_Einstellungen.py")

    with menu_cols[3]:
        if st.button("?", key="top_menu_help", help="Hilfe"):
            st.session_state.show_help = not st.session_state.get('show_help', False)

    st.divider()

    # Suchergebnisse anzeigen wenn aktiviert
    if st.session_state.get('show_search_results') and st.session_state.get('global_search_query'):
        with st.expander("Suchergebnisse", expanded=True):
            render_global_search()
            if st.button("Suche schließen"):
                st.session_state.show_search_results = False
                st.session_state.global_search_query = ""
                st.rerun()


# Baum-Navigation Struktur
TREE_NAVIGATION = {
    "Suche": {
        "Dokumentensuche": "pages/0_🔎_Suche.py",
    },
    "Dokumente": {
        "Dokumentenaufnahme": "pages/2_📄_Dokumentenaufnahme.py",
        "Dokumentenverwaltung": "pages/3_📁_Dokumente.py",
        "Intelligente Ordner": "pages/4_🔍_Intelligente_Ordner.py",
        "Dokument-Chat": "pages/11_💬_Dokument_Chat.py",
    },
    "Finanzen": {
        "Übersicht": "pages/7_💰_Finanzen.py",
        "Finanz-Dashboard": "pages/13_📈_Finanz_Dashboard.py",
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


def render_tree_navigation():
    """
    Rendert die Baum-Navigation in der Sidebar.
    Ohne sichtbare Buttons, nur Text der bei Klick Untermenüs öffnet.
    """
    # CSS für Baum-Navigation
    st.markdown("""
    <style>
        /* Baum-Navigation Styling */
        .tree-nav-category {
            font-weight: 500;
            padding: 8px 0;
            cursor: pointer;
            color: #333;
            transition: color 0.2s;
        }
        .tree-nav-category:hover {
            color: #0066cc;
        }
        .tree-nav-item {
            padding: 4px 0 4px 16px;
            color: #666;
            cursor: pointer;
            font-size: 0.9em;
            transition: all 0.2s;
        }
        .tree-nav-item:hover {
            color: #0066cc;
            padding-left: 20px;
        }
        .tree-nav-item.active {
            color: #0066cc;
            font-weight: 500;
        }

        /* Standard-Navigation verstecken */
        [data-testid="stSidebarNav"] {
            display: none !important;
        }

        /* Expander ohne Rahmen */
        .tree-expander > div:first-child {
            border: none !important;
            background: transparent !important;
        }
    </style>
    """, unsafe_allow_html=True)

    # Aktuelle Seite ermitteln
    current_page = st.session_state.get('_current_page', '')

    st.markdown("### Navigation")

    for category, items in TREE_NAVIGATION.items():
        # State für geöffnete Kategorien
        state_key = f"tree_nav_{category}"
        if state_key not in st.session_state:
            # Prüfen ob aktive Seite in dieser Kategorie
            st.session_state[state_key] = any(
                path in current_page or current_page in path
                for path in items.values()
            )

        # Kategorie als klickbarer Text
        col_cat, col_arrow = st.columns([5, 1])

        with col_cat:
            # Verwende st.markdown mit on_click Simulation durch Button mit Custom CSS
            if st.button(
                category,
                key=f"tree_cat_{category}",
                use_container_width=True,
                type="secondary"
            ):
                st.session_state[state_key] = not st.session_state[state_key]
                st.rerun()

        with col_arrow:
            arrow = "▼" if st.session_state[state_key] else "▶"
            st.markdown(f"<span style='color: #666;'>{arrow}</span>", unsafe_allow_html=True)

        # Untermenü-Items anzeigen wenn geöffnet
        if st.session_state[state_key]:
            for item_name, item_path in items.items():
                is_active = item_path in current_page or current_page in item_path

                # Eingerücktes Item
                item_style = "font-weight: 500; color: #0066cc;" if is_active else "color: #666;"

                col_space, col_item = st.columns([0.2, 4])
                with col_item:
                    if st.button(
                        f"  {item_name}",
                        key=f"tree_item_{item_path}",
                        use_container_width=True,
                        disabled=is_active
                    ):
                        st.session_state['_current_page'] = item_path
                        st.switch_page(item_path)


def render_tree_navigation_pure():
    """
    Reine Text-basierte Baum-Navigation ohne Streamlit-Buttons.
    Verwendet HTML und JavaScript für die Interaktion.
    """
    current_page = st.session_state.get('_current_page', '')

    # Navigation HTML generieren
    nav_html = """
    <style>
        .tree-nav {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        }
        .tree-nav-cat {
            font-weight: 500;
            padding: 8px 0;
            cursor: pointer;
            color: #333;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .tree-nav-cat:hover {
            color: #0066cc;
        }
        .tree-nav-items {
            display: none;
            margin-left: 12px;
            border-left: 1px solid #e0e0e0;
            padding-left: 12px;
        }
        .tree-nav-items.open {
            display: block;
        }
        .tree-nav-item {
            padding: 6px 0;
            color: #666;
            cursor: pointer;
            font-size: 0.9em;
        }
        .tree-nav-item:hover {
            color: #0066cc;
        }
        .tree-nav-item.active {
            color: #0066cc;
            font-weight: 500;
        }
        .tree-arrow {
            font-size: 0.7em;
            transition: transform 0.2s;
        }
        .tree-arrow.open {
            transform: rotate(90deg);
        }
    </style>
    <div class="tree-nav">
    """

    for category, items in TREE_NAVIGATION.items():
        # Prüfen ob Kategorie aktive Seite enthält
        has_active = any(
            path in current_page or current_page in path
            for path in items.values()
        )

        cat_id = category.replace(" ", "_").lower()
        open_class = "open" if has_active else ""

        nav_html += f"""
        <div class="tree-nav-cat" onclick="toggleCategory('{cat_id}')">
            <span>{category}</span>
            <span class="tree-arrow {open_class}" id="arrow_{cat_id}">▶</span>
        </div>
        <div class="tree-nav-items {open_class}" id="items_{cat_id}">
        """

        for item_name, item_path in items.items():
            is_active = item_path in current_page or current_page in item_path
            active_class = "active" if is_active else ""
            nav_html += f"""
            <div class="tree-nav-item {active_class}" onclick="navigateTo('{item_path}')">{item_name}</div>
            """

        nav_html += "</div>"

    nav_html += """
    </div>
    <script>
        function toggleCategory(catId) {
            var items = document.getElementById('items_' + catId);
            var arrow = document.getElementById('arrow_' + catId);
            items.classList.toggle('open');
            arrow.classList.toggle('open');
        }

        function navigateTo(path) {
            // Streamlit-Navigation über URL
            window.parent.postMessage({type: 'streamlit:navigate', path: path}, '*');
        }
    </script>
    """

    st.markdown(nav_html, unsafe_allow_html=True)


def render_compact_tree_navigation():
    """
    Kompakte Baum-Navigation mit reinem Text und st.markdown Links.
    Verwendet Expander für Kategorien.
    """
    current_page = st.session_state.get('_current_page', '')

    # CSS für kompakte Navigation
    st.markdown("""
    <style>
        /* Verstecke Standard-Navigation */
        [data-testid="stSidebarNav"] {
            display: none !important;
        }

        /* Kompakte Expander */
        .stExpander {
            border: none !important;
            background: transparent !important;
        }
        .stExpander > div:first-child {
            padding: 0 !important;
        }
        .stExpander > div:first-child > div {
            background: transparent !important;
            border: none !important;
        }

        /* Link-Styling */
        .nav-link {
            display: block;
            padding: 4px 8px 4px 16px;
            color: #666;
            text-decoration: none;
            font-size: 0.9em;
            border-radius: 4px;
            transition: all 0.2s;
        }
        .nav-link:hover {
            background: #f0f2f6;
            color: #0066cc;
            padding-left: 20px;
        }
        .nav-link.active {
            background: #e3e8ef;
            color: #0066cc;
            font-weight: 500;
        }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("**Navigation**")

    for category, items in TREE_NAVIGATION.items():
        # Prüfen ob Kategorie aktive Seite enthält
        has_active = any(
            path in current_page or current_page in path
            for path in items.values()
        )

        with st.expander(category, expanded=has_active):
            for item_name, item_path in items.items():
                is_active = item_path in current_page or current_page in item_path

                if is_active:
                    st.markdown(f"**→ {item_name}**")
                else:
                    if st.button(
                        item_name,
                        key=f"nav_{item_path}",
                        use_container_width=True
                    ):
                        st.session_state['_current_page'] = item_path
                        st.switch_page(item_path)


def render_new_sidebar():
    """
    Rendert die neue Sidebar mit Baum-Navigation und Aktentasche.
    Ersetzt render_sidebar_with_navigation().
    """
    from database.db import get_db, get_current_user_id
    from database.models import Document
    from utils.components import get_version_string, render_api_status

    with st.sidebar:
        # Logo/Titel
        st.markdown("## Dokumentenmanagement")

        st.divider()

        # Baum-Navigation
        render_compact_tree_navigation()

        st.divider()

        # API-Status
        render_api_status()

        st.divider()

        # Aktentasche
        st.markdown("### Aktentasche")

        cart_items = st.session_state.get('active_cart_items', [])

        if cart_items:
            st.caption(f"{len(cart_items)} Dokument(e)")

            user_id = get_current_user_id()
            with get_db() as session:
                docs = session.query(Document).filter(
                    Document.id.in_(cart_items)
                ).all()

                for doc in docs:
                    col_doc, col_rm = st.columns([4, 1])
                    with col_doc:
                        title = (doc.title or doc.filename)[:20]
                        st.caption(f"• {title}...")
                    with col_rm:
                        if st.button("×", key=f"rm_cart_{doc.id}"):
                            st.session_state.active_cart_items.remove(doc.id)
                            st.rerun()

            if st.button("Aktentasche leeren", use_container_width=True):
                st.session_state.active_cart_items = []
                st.rerun()
        else:
            st.caption("Leer")

        st.divider()

        # Version
        st.caption(get_version_string())


def render_search_page():
    """
    Rendert eine dedizierte Suchseite mit erweiterten Optionen.
    """
    from database.db import get_db, get_current_user_id
    from database.models import Document, Folder
    from config.settings import DOCUMENT_CATEGORIES
    from services.search_service import get_search_service
    from utils.helpers import format_currency, format_date, get_document_file_content
    from services.encryption import get_encryption_service

    user_id = get_current_user_id()

    st.title("Dokumentensuche")

    # Suchbereich
    col_search, col_btn = st.columns([4, 1])

    with col_search:
        search_terms = st.text_input(
            "Suchbegriffe",
            placeholder="Mehrere Begriffe mit Leerzeichen trennen...",
            key="search_terms_input"
        )

    with col_btn:
        search_btn = st.button("Suchen", type="primary", use_container_width=True)

    # Erweiterte Filter
    with st.expander("Erweiterte Filter"):
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

        filter_cols2 = st.columns(2)

        with filter_cols2[0]:
            filter_amount_min = st.number_input(
                "Betrag min",
                min_value=0.0,
                value=0.0,
                step=10.0,
                key="search_filter_amount_min"
            )

        with filter_cols2[1]:
            filter_amount_max = st.number_input(
                "Betrag max",
                min_value=0.0,
                value=0.0,
                step=10.0,
                key="search_filter_amount_max"
            )

    # Suche ausführen
    if search_btn and search_terms:
        with st.spinner("Suche läuft..."):
            # Alle Suchbegriffe extrahieren
            terms = search_terms.strip().split()

            with get_db() as session:
                # Basis-Query
                query = session.query(Document).filter(
                    Document.user_id == user_id,
                    (Document.is_deleted == False) | (Document.is_deleted == None)
                )

                # Für jeden Begriff suchen
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

                # Ergebnisse in Session speichern
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

                st.session_state.search_results = results_data

    # Ergebnisse anzeigen
    if 'search_results' in st.session_state and st.session_state.search_results:
        results = st.session_state.search_results

        st.success(f"**{len(results)} Treffer gefunden**")

        # Ergebnistabelle
        for doc in results:
            with st.container():
                col_info, col_meta, col_actions = st.columns([3, 2, 2])

                with col_info:
                    st.markdown(f"**{doc['title']}**")
                    st.caption(f"Standort: {doc['folder_path']}")

                with col_meta:
                    meta_parts = []
                    if doc['sender']:
                        meta_parts.append(doc['sender'])
                    if doc['document_date']:
                        meta_parts.append(format_date(doc['document_date']))
                    if doc['invoice_amount']:
                        meta_parts.append(format_currency(doc['invoice_amount']))
                    st.caption(" | ".join(meta_parts) if meta_parts else "—")

                with col_actions:
                    btn_cols = st.columns(4)

                    # Ansehen
                    with btn_cols[0]:
                        if st.button("Ansehen", key=f"sr_view_{doc['id']}"):
                            st.session_state.view_document_id = doc['id']
                            st.switch_page("pages/3_📁_Dokumente.py")

                    # Download
                    with btn_cols[1]:
                        if doc['file_path']:
                            try:
                                success, file_result = get_document_file_content(doc['file_path'], user_id)
                                if success:
                                    if doc.get('is_encrypted') and doc.get('encryption_iv'):
                                        encryption = get_encryption_service()
                                        try:
                                            file_data = encryption.decrypt_file(file_result, doc['encryption_iv'], doc['filename'])
                                        except:
                                            file_data = file_result
                                    else:
                                        file_data = file_result

                                    st.download_button(
                                        "Download",
                                        data=file_data,
                                        file_name=doc['filename'],
                                        mime=doc.get('mime_type') or "application/octet-stream",
                                        key=f"sr_dl_{doc['id']}"
                                    )
                            except:
                                st.button("Download", disabled=True, key=f"sr_dl_{doc['id']}")

                    # Drucken (öffnet Druckdialog)
                    with btn_cols[2]:
                        if st.button("Drucken", key=f"sr_print_{doc['id']}"):
                            st.session_state.print_document_id = doc['id']
                            st.info("Druckfunktion: Dokument wird geladen...")

                    # E-Mail senden
                    with btn_cols[3]:
                        if st.button("Senden", key=f"sr_send_{doc['id']}"):
                            st.session_state.email_document_id = doc['id']
                            st.switch_page("pages/6_📧_E-Mail.py")

                st.divider()

    elif 'search_results' in st.session_state:
        st.info("Keine Treffer gefunden. Versuchen Sie andere Suchbegriffe.")
