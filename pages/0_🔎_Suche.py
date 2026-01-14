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
from utils.helpers import format_currency, format_date, get_document_file_content
from services.encryption import get_encryption_service

st.set_page_config(page_title="Suche", page_icon="🔎", layout="wide")
init_db()

# Neues Layout anwenden
from utils.ui_new import apply_new_layout
apply_new_layout()

user_id = get_current_user_id()

st.title("🔎 Dokumentensuche")

# Suchbegriff aus Top-Menü übernehmen
initial_search = st.session_state.pop('search_query_from_top', '')

# ============================================================
# SUCHBEREICH
# ============================================================

# Hauptsuchfeld
search_terms = st.text_input(
    "Suchbegriffe",
    value=initial_search,
    placeholder="Suchbegriffe eingeben (mehrere mit Leerzeichen trennen)...",
    key="main_search_input",
    label_visibility="collapsed"
)

# Erweiterte Filter in Expander
with st.expander("Erweiterte Filter", expanded=False):
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

# Ansichtsmodus
view_mode = st.radio(
    "Ansicht",
    options=["Liste", "Kompakt", "Karten"],
    horizontal=True,
    key="view_mode",
    label_visibility="collapsed"
)

st.divider()

# ============================================================
# SUCHE AUSFÜHREN
# ============================================================

if search_terms:
    with st.spinner("Suche läuft..."):
        with get_db() as session:
            # Basis-Query
            query = session.query(Document).filter(
                Document.user_id == user_id,
                (Document.is_deleted == False) | (Document.is_deleted == None)
            )

            # Suchbegriffe anwenden (UND-Verknüpfung)
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
                    'folder_path': folder_paths.get(doc.folder_id, "Nicht zugeordnet"),
                    'document_date': doc.document_date,
                    'invoice_amount': doc.invoice_amount,
                    'iban': doc.iban,
                    'reference_number': doc.reference_number,
                    'ai_summary': doc.ai_summary,
                })

    # ============================================================
    # ERGEBNISSE ANZEIGEN
    # ============================================================

    if results_data:
        st.success(f"**{len(results_data)} Treffer** für \"{search_terms}\"")

        # Ergebnisse nach Ansichtsmodus anzeigen
        for doc in results_data:
            with st.container():
                if view_mode == "Kompakt":
                    # Kompakte einzeilige Ansicht
                    cols = st.columns([3, 2, 2, 1, 1])

                    with cols[0]:
                        title_display = doc['title'][:40] + ('...' if len(doc['title']) > 40 else '')
                        st.markdown(f"**{title_display}**")

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
                            st.caption(format_currency(doc['invoice_amount']))

                    with cols[4]:
                        if st.button("Öffnen", key=f"c_view_{doc['id']}"):
                            st.session_state.view_document_id = doc['id']
                            st.switch_page("pages/3_📁_Dokumente.py")

                elif view_mode == "Karten":
                    # Karten-Ansicht
                    st.markdown(f"### {doc['title']}")
                    st.caption(f"Standort: {doc['folder_path']}")

                    card_cols = st.columns([2, 2, 1])

                    with card_cols[0]:
                        if doc['sender']:
                            st.write(f"**Absender:** {doc['sender']}")
                        if doc['category']:
                            st.write(f"**Kategorie:** {doc['category']}")

                    with card_cols[1]:
                        if doc['document_date']:
                            st.write(f"**Datum:** {format_date(doc['document_date'])}")
                        if doc['invoice_amount']:
                            st.write(f"**Betrag:** {format_currency(doc['invoice_amount'])}")

                    with card_cols[2]:
                        if st.button("Öffnen", key=f"k_view_{doc['id']}", use_container_width=True):
                            st.session_state.view_document_id = doc['id']
                            st.switch_page("pages/3_📁_Dokumente.py")

                        if st.button("Senden", key=f"k_send_{doc['id']}", use_container_width=True):
                            st.session_state.email_document_id = doc['id']
                            st.switch_page("pages/6_📧_E-Mail.py")

                    st.divider()

                else:
                    # Standard Listen-Ansicht
                    main_cols = st.columns([4, 2, 1])

                    with main_cols[0]:
                        st.markdown(f"**{doc['title']}**")

                        # Zusammenfassung anzeigen wenn vorhanden
                        if doc['ai_summary']:
                            summary = doc['ai_summary'][:100] + ('...' if len(doc['ai_summary'] or '') > 100 else '')
                            st.caption(f"_{summary}_")

                        # Standort hervorheben
                        st.caption(f"Standort: {doc['folder_path']}")

                    with main_cols[1]:
                        meta_items = []
                        if doc['sender']:
                            meta_items.append(f"Von: {doc['sender']}")
                        if doc['category']:
                            meta_items.append(doc['category'])
                        if doc['document_date']:
                            meta_items.append(format_date(doc['document_date']))
                        if doc['invoice_amount']:
                            meta_items.append(format_currency(doc['invoice_amount']))

                        st.caption(" | ".join(meta_items) if meta_items else "—")

                    with main_cols[2]:
                        if st.button("Öffnen", key=f"l_view_{doc['id']}"):
                            st.session_state.view_document_id = doc['id']
                            st.switch_page("pages/3_📁_Dokumente.py")

                    st.divider()

        st.caption(f"Zeige {len(results_data)} Ergebnisse (max. 200)")

    else:
        st.info("Keine Treffer gefunden. Versuchen Sie andere Suchbegriffe.")

else:
    # Info wenn noch nicht gesucht
    st.info("""
    **So funktioniert die Suche:**

    - Geben Sie einen oder mehrere Suchbegriffe ein
    - Mehrere Begriffe werden mit UND verknüpft
    - Die Suche durchsucht: Titel, Inhalt (OCR), Absender, IBAN, Referenznummern

    **Beispiele:**
    - `Telekom Rechnung` - Findet Telekom-Rechnungen
    - `DE89` - Findet Dokumente mit dieser IBAN
    - `2023` - Findet Dokumente aus 2023
    """)
