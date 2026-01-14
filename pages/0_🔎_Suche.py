"""
Globale Dokumentensuche
Ermöglicht die Suche nach Begriffen in der gesamten Datenbank.
"""
import streamlit as st
from pathlib import Path
import sys
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.db import init_db, get_db, get_current_user_id
from database.models import Document, Folder
from config.settings import DOCUMENT_CATEGORIES
from services.search_service import get_search_service
from utils.helpers import format_currency, format_date, get_document_file_content
from services.encryption import get_encryption_service

st.set_page_config(page_title="Suche", page_icon="🔎", layout="wide")
init_db()

# Sidebar mit Navigation
from utils.components import render_sidebar_cart
render_sidebar_cart()

user_id = get_current_user_id()

st.title("🔎 Dokumentensuche")
st.caption("Durchsuchen Sie alle Ihre Dokumente nach Begriffen, Beträgen, Absender und mehr.")

# ============================================================
# SUCHBEREICH
# ============================================================

# Hauptsuchfeld
search_col, btn_col = st.columns([5, 1])

with search_col:
    search_terms = st.text_input(
        "Suchbegriffe",
        placeholder="Suchbegriffe eingeben (mehrere mit Leerzeichen trennen)...",
        key="main_search_input",
        label_visibility="collapsed"
    )

with btn_col:
    search_clicked = st.button("🔍 Suchen", type="primary", use_container_width=True)

# Erweiterte Filter in Expander
with st.expander("🎯 Erweiterte Filter", expanded=False):
    filter_row1 = st.columns(4)

    with filter_row1[0]:
        filter_category = st.selectbox(
            "Kategorie",
            options=["Alle Kategorien"] + DOCUMENT_CATEGORIES,
            key="filter_category"
        )

    with filter_row1[1]:
        filter_sender = st.text_input(
            "Absender enthält",
            placeholder="z.B. Telekom",
            key="filter_sender"
        )

    with filter_row1[2]:
        filter_date_from = st.date_input(
            "Datum von",
            value=None,
            key="filter_date_from"
        )

    with filter_row1[3]:
        filter_date_to = st.date_input(
            "Datum bis",
            value=None,
            key="filter_date_to"
        )

    filter_row2 = st.columns(4)

    with filter_row2[0]:
        filter_amount_min = st.number_input(
            "Betrag von (€)",
            min_value=0.0,
            value=0.0,
            step=10.0,
            key="filter_amount_min"
        )

    with filter_row2[1]:
        filter_amount_max = st.number_input(
            "Betrag bis (€)",
            min_value=0.0,
            value=0.0,
            step=10.0,
            key="filter_amount_max"
        )

    with filter_row2[2]:
        filter_iban = st.text_input(
            "IBAN enthält",
            placeholder="z.B. DE89",
            key="filter_iban"
        )

    with filter_row2[3]:
        filter_ref = st.text_input(
            "Aktenzeichen/Ref.",
            placeholder="z.B. 123456",
            key="filter_ref"
        )

st.divider()

# ============================================================
# SUCHE AUSFÜHREN
# ============================================================

if search_clicked or (search_terms and st.session_state.get('last_search') != search_terms):
    st.session_state.last_search = search_terms

    with st.spinner("Suche läuft..."):
        with get_db() as session:
            # Basis-Query
            query = session.query(Document).filter(
                Document.user_id == user_id,
                (Document.is_deleted == False) | (Document.is_deleted == None)
            )

            # Suchbegriffe anwenden (UND-Verknüpfung)
            if search_terms:
                terms = search_terms.strip().split()
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
                        (Document.invoice_number.ilike(search_pattern)) |
                        (Document.iban.ilike(search_pattern)) |
                        (Document.category.ilike(search_pattern)) |
                        (Document.ai_summary.ilike(search_pattern))
                    )

            # Filter anwenden
            if filter_category != "Alle Kategorien":
                query = query.filter(Document.category == filter_category)

            if filter_sender:
                query = query.filter(Document.sender.ilike(f'%{filter_sender}%'))

            if filter_date_from:
                query = query.filter(Document.document_date >= filter_date_from)

            if filter_date_to:
                query = query.filter(Document.document_date <= filter_date_to)

            if filter_amount_min > 0:
                query = query.filter(Document.invoice_amount >= filter_amount_min)

            if filter_amount_max > 0:
                query = query.filter(Document.invoice_amount <= filter_amount_max)

            if filter_iban:
                query = query.filter(Document.iban.ilike(f'%{filter_iban}%'))

            if filter_ref:
                query = query.filter(
                    (Document.reference_number.ilike(f'%{filter_ref}%')) |
                    (Document.customer_number.ilike(f'%{filter_ref}%')) |
                    (Document.invoice_number.ilike(f'%{filter_ref}%'))
                )

            # Ergebnisse laden
            results = query.order_by(Document.document_date.desc()).limit(200).all()

            # Ordnerpfade laden für Standort-Anzeige
            folder_paths = {}
            folders = session.query(Folder).filter(Folder.user_id == user_id).all()
            for folder in folders:
                path_parts = [folder.name]
                parent = session.get(Folder, folder.parent_id) if folder.parent_id else None
                while parent:
                    path_parts.insert(0, parent.name)
                    parent = session.get(Folder, parent.parent_id) if parent.parent_id else None
                folder_paths[folder.id] = " / ".join(path_parts)

            # Ergebnisse als Dicts speichern
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
                    'folder_path': folder_paths.get(doc.folder_id, "📥 Nicht zugeordnet"),
                    'document_date': doc.document_date,
                    'invoice_amount': doc.invoice_amount,
                    'iban': doc.iban,
                    'reference_number': doc.reference_number,
                    'ai_summary': doc.ai_summary,
                })

            st.session_state.search_results = results_data
            st.session_state.search_query = search_terms

# ============================================================
# ERGEBNISSE ANZEIGEN
# ============================================================

if 'search_results' in st.session_state:
    results = st.session_state.search_results
    query = st.session_state.get('search_query', '')

    if results:
        # Ergebnis-Header
        result_header = st.columns([3, 1, 1])

        with result_header[0]:
            st.success(f"**{len(results)} Treffer** gefunden" + (f" für \"{query}\"" if query else ""))

        with result_header[1]:
            sort_by = st.selectbox(
                "Sortieren",
                options=["Datum (neu)", "Datum (alt)", "Betrag", "Absender"],
                key="sort_results",
                label_visibility="collapsed"
            )

        with result_header[2]:
            view_mode = st.selectbox(
                "Ansicht",
                options=["Liste", "Kompakt", "Karten"],
                key="view_mode",
                label_visibility="collapsed"
            )

        # Sortierung anwenden
        if sort_by == "Datum (alt)":
            results = sorted(results, key=lambda x: x['document_date'] or datetime.min)
        elif sort_by == "Betrag":
            results = sorted(results, key=lambda x: x['invoice_amount'] or 0, reverse=True)
        elif sort_by == "Absender":
            results = sorted(results, key=lambda x: x['sender'] or "")
        # Default: Datum (neu) - bereits so sortiert

        st.divider()

        # Ergebnisliste
        for i, doc in enumerate(results):
            with st.container():
                if view_mode == "Kompakt":
                    # Kompakte einzeilige Ansicht
                    cols = st.columns([3, 2, 2, 1, 2])

                    with cols[0]:
                        st.markdown(f"**{doc['title'][:40]}**{'...' if len(doc['title']) > 40 else ''}")

                    with cols[1]:
                        st.caption(doc['folder_path'])

                    with cols[2]:
                        parts = []
                        if doc['sender']:
                            parts.append(doc['sender'][:20])
                        if doc['document_date']:
                            parts.append(format_date(doc['document_date']))
                        st.caption(" | ".join(parts) if parts else "—")

                    with cols[3]:
                        if doc['invoice_amount']:
                            st.markdown(f"**{format_currency(doc['invoice_amount'])}**")

                    with cols[4]:
                        action_cols = st.columns(3)
                        with action_cols[0]:
                            if st.button("👁️", key=f"c_view_{doc['id']}", help="Ansehen"):
                                st.session_state.view_document_id = doc['id']
                                st.switch_page("pages/3_📁_Dokumente.py")
                        with action_cols[1]:
                            if st.button("📥", key=f"c_cart_{doc['id']}", help="Aktentasche"):
                                if 'active_cart_items' not in st.session_state:
                                    st.session_state.active_cart_items = []
                                if doc['id'] not in st.session_state.active_cart_items:
                                    st.session_state.active_cart_items.append(doc['id'])
                                    st.toast("✅ Zur Aktentasche hinzugefügt")
                        with action_cols[2]:
                            if st.button("📧", key=f"c_send_{doc['id']}", help="E-Mail"):
                                st.session_state.email_document_id = doc['id']
                                st.switch_page("pages/6_📧_E-Mail.py")

                elif view_mode == "Karten":
                    # Karten-Ansicht mit mehr Details
                    with st.container():
                        st.markdown(f"""
                        <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; margin-bottom: 10px; border-left: 4px solid #007bff;">
                            <h4 style="margin: 0 0 8px 0;">{doc['title']}</h4>
                            <p style="color: #666; margin: 0 0 5px 0;"><strong>Standort:</strong> {doc['folder_path']}</p>
                        </div>
                        """, unsafe_allow_html=True)

                        card_cols = st.columns([2, 2, 1])

                        with card_cols[0]:
                            if doc['sender']:
                                st.caption(f"**Absender:** {doc['sender']}")
                            if doc['category']:
                                st.caption(f"**Kategorie:** {doc['category']}")
                            if doc['document_date']:
                                st.caption(f"**Datum:** {format_date(doc['document_date'])}")

                        with card_cols[1]:
                            if doc['invoice_amount']:
                                st.markdown(f"**Betrag: {format_currency(doc['invoice_amount'])}**")
                            if doc['iban']:
                                st.code(doc['iban'][:20] + "..." if len(doc['iban'] or "") > 20 else doc['iban'])
                            if doc['reference_number']:
                                st.caption(f"Ref: {doc['reference_number']}")

                        with card_cols[2]:
                            if st.button("👁️ Ansehen", key=f"k_view_{doc['id']}", use_container_width=True):
                                st.session_state.view_document_id = doc['id']
                                st.switch_page("pages/3_📁_Dokumente.py")

                            # Download
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
                                            "⬇️ Download",
                                            data=file_data,
                                            file_name=doc['filename'],
                                            mime=doc.get('mime_type') or "application/octet-stream",
                                            key=f"k_dl_{doc['id']}",
                                            use_container_width=True
                                        )
                                except:
                                    pass

                            if st.button("📧 Senden", key=f"k_send_{doc['id']}", use_container_width=True):
                                st.session_state.email_document_id = doc['id']
                                st.switch_page("pages/6_📧_E-Mail.py")

                else:
                    # Standard Listen-Ansicht
                    main_cols = st.columns([4, 2, 2])

                    with main_cols[0]:
                        st.markdown(f"**{doc['title']}**")

                        # Zusammenfassung anzeigen wenn vorhanden
                        if doc['ai_summary']:
                            st.caption(f"_{doc['ai_summary'][:100]}{'...' if len(doc['ai_summary'] or '') > 100 else ''}_")

                        # Standort hervorheben
                        st.markdown(f"📍 **Standort:** {doc['folder_path']}")

                    with main_cols[1]:
                        meta_items = []
                        if doc['sender']:
                            meta_items.append(f"**Von:** {doc['sender']}")
                        if doc['category']:
                            meta_items.append(f"**Kategorie:** {doc['category']}")
                        if doc['document_date']:
                            meta_items.append(f"**Datum:** {format_date(doc['document_date'])}")

                        for item in meta_items:
                            st.caption(item)

                        if doc['invoice_amount']:
                            st.markdown(f"**{format_currency(doc['invoice_amount'])}**")

                    with main_cols[2]:
                        # Aktions-Buttons
                        st.markdown("**Aktionen:**")

                        btn_row1 = st.columns(2)

                        with btn_row1[0]:
                            if st.button("👁️ Ansehen", key=f"l_view_{doc['id']}", use_container_width=True):
                                st.session_state.view_document_id = doc['id']
                                st.switch_page("pages/3_📁_Dokumente.py")

                        with btn_row1[1]:
                            if st.button("📥 Aktentasche", key=f"l_cart_{doc['id']}", use_container_width=True):
                                if 'active_cart_items' not in st.session_state:
                                    st.session_state.active_cart_items = []
                                if doc['id'] not in st.session_state.active_cart_items:
                                    st.session_state.active_cart_items.append(doc['id'])
                                    st.toast("✅ Zur Aktentasche hinzugefügt")

                        btn_row2 = st.columns(2)

                        # Download
                        with btn_row2[0]:
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
                                            "⬇️ Download",
                                            data=file_data,
                                            file_name=doc['filename'],
                                            mime=doc.get('mime_type') or "application/octet-stream",
                                            key=f"l_dl_{doc['id']}",
                                            use_container_width=True
                                        )
                                except:
                                    st.button("⬇️ Download", disabled=True, key=f"l_dl_{doc['id']}", use_container_width=True)

                        with btn_row2[1]:
                            if st.button("📧 Senden", key=f"l_send_{doc['id']}", use_container_width=True):
                                st.session_state.email_document_id = doc['id']
                                st.switch_page("pages/6_📧_E-Mail.py")

                st.divider()

        # Pagination Info
        st.caption(f"Zeige {len(results)} von maximal 200 Ergebnissen")

    else:
        st.info("🔍 Keine Treffer gefunden. Versuchen Sie andere Suchbegriffe oder passen Sie die Filter an.")

else:
    # Willkommens-Info wenn noch nicht gesucht
    st.info("""
    **So funktioniert die Suche:**

    - Geben Sie einen oder mehrere Suchbegriffe ein
    - Mehrere Begriffe werden mit UND verknüpft (alle müssen vorkommen)
    - Die Suche durchsucht: Titel, Inhalt (OCR), Absender, Betreff, IBAN, Referenznummern
    - Nutzen Sie die erweiterten Filter für genauere Ergebnisse

    **Beispiele:**
    - `Telekom Rechnung` - Findet Telekom-Rechnungen
    - `DE89` - Findet Dokumente mit dieser IBAN
    - `2023` - Findet Dokumente aus 2023
    """)
