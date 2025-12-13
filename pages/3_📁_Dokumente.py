"""
Dokumentenmanagement - Ordnerstruktur und Dokumentenverwaltung
"""
import streamlit as st
import io
from pathlib import Path
import sys
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.db import init_db, get_db, get_current_user_id
from database.models import Document, Folder, DocumentStatus, InvoiceStatus
from config.settings import DOCUMENT_CATEGORIES
from services.encryption import get_encryption_service
from services.document_classifier import get_classifier
from services.search_service import get_search_service
from utils.helpers import format_currency, format_date, generate_share_link, truncate_text
from utils.components import render_sidebar_cart, add_to_cart

st.set_page_config(page_title="Dokumente", page_icon="📁", layout="wide")
init_db()


def build_folder_tree(session, user_id: int, include_root: bool = False) -> list:
    """
    Baut eine hierarchische Ordnerliste für Selectboxen.

    Returns:
        Liste von Dicts mit 'id', 'display_name', 'path', 'depth'
    """
    from database.models import Folder

    result = []

    # Alle Ordner laden
    all_folders = session.query(Folder).filter(
        Folder.user_id == user_id
    ).order_by(Folder.name).all()

    # Index nach ID und parent_id
    folders_by_id = {f.id: f for f in all_folders}
    children_by_parent = {}
    root_folders = []

    for folder in all_folders:
        if folder.parent_id is None:
            root_folders.append(folder)
        else:
            if folder.parent_id not in children_by_parent:
                children_by_parent[folder.parent_id] = []
            children_by_parent[folder.parent_id].append(folder)

    # Sortiere Root-Ordner: Posteingang zuerst, dann alphabetisch, Papierkorb zuletzt
    def sort_key(f):
        if f.name == "Posteingang":
            return (0, f.name)
        elif f.name == "Papierkorb":
            return (2, f.name)
        else:
            return (1, f.name)

    root_folders.sort(key=sort_key)

    def add_folder_recursive(folder, depth=0, path_parts=None):
        if path_parts is None:
            path_parts = []

        current_path = path_parts + [folder.name]

        # Icon basierend auf Ordnername
        if folder.name == "Posteingang":
            icon = "📥"
        elif folder.name == "Papierkorb":
            icon = "🗑️"
        elif folder.name == "Archiv" or "Archiv" in folder.name:
            icon = "📦"
        else:
            icon = "📂"

        # Einrückung mit Baumstruktur
        if depth == 0:
            prefix = ""
        else:
            prefix = "    " * (depth - 1) + "└── "

        display_name = f"{prefix}{icon} {folder.name}"
        full_path = " / ".join(current_path)

        result.append({
            'id': folder.id,
            'name': folder.name,
            'display_name': display_name,
            'path': full_path,
            'depth': depth
        })

        # Unterordner rekursiv hinzufügen
        if folder.id in children_by_parent:
            children = sorted(children_by_parent[folder.id], key=lambda f: f.name)
            for child in children:
                add_folder_recursive(child, depth + 1, current_path)

    # Wurzelordner durchgehen
    for folder in root_folders:
        add_folder_recursive(folder)

    return result


# Sidebar mit Aktentasche
render_sidebar_cart()

user_id = get_current_user_id()

st.title("📁 Dokumente & Ordner")

# Layout: Sidebar für Ordner, Hauptbereich für Dokumente
col_folders, col_docs = st.columns([1, 3])

with col_folders:
    st.subheader("📂 Ordner")

    # Aktuellen Ordner aus Session
    current_folder_id = st.session_state.get('current_folder_id')

    # Ordnerdaten laden (als einfache Dicts, um DetachedInstanceError zu vermeiden)
    folder_data = []
    with get_db() as session:
        # Alle Ordner laden
        folders = session.query(Folder).filter(
            Folder.user_id == user_id,
            Folder.parent_id.is_(None)  # Nur Root-Ordner
        ).order_by(Folder.name).all()

        # Ordnerdaten extrahieren während Session aktiv ist
        for folder in folders:
            doc_count = session.query(Document).filter(
                Document.folder_id == folder.id
            ).count()

            # Unterordner laden
            subfolders_data = []
            subfolders = session.query(Folder).filter(
                Folder.parent_id == folder.id
            ).all()
            for sub in subfolders:
                sub_count = session.query(Document).filter(
                    Document.folder_id == sub.id
                ).count()
                subfolders_data.append({
                    'id': sub.id,
                    'name': sub.name,
                    'count': sub_count
                })

            folder_data.append({
                'id': folder.id,
                'name': folder.name,
                'count': doc_count,
                'subfolders': subfolders_data
            })

    # "Alle Dokumente" Option
    if st.button("📄 Alle Dokumente", use_container_width=True,
                 type="primary" if current_folder_id is None else "secondary"):
        st.session_state.current_folder_id = None
        st.rerun()

    st.divider()

    # Ordner anzeigen
    for folder in folder_data:
        icon = "📥" if folder['name'] == "Posteingang" else "📂"
        if folder['name'] == "Papierkorb":
            icon = "🗑️"
        elif folder['name'] == "Archiv":
            icon = "📦"

        is_selected = current_folder_id == folder['id']
        if st.button(f"{icon} {folder['name']} ({folder['count']})",
                    use_container_width=True,
                    type="primary" if is_selected else "secondary",
                    key=f"folder_{folder['id']}"):
            st.session_state.current_folder_id = folder['id']
            st.rerun()

        # Unterordner
        for sub in folder['subfolders']:
            if st.button(f"  └ {sub['name']} ({sub['count']})",
                        use_container_width=True,
                        key=f"folder_{sub['id']}"):
                st.session_state.current_folder_id = sub['id']
                st.rerun()

    st.divider()

    # Neuen Ordner erstellen
    with st.expander("➕ Neuer Ordner"):
        new_folder_name = st.text_input("Ordnername", key="new_folder_name")

        # Hierarchische Ordnerauswahl für Parent
        with get_db() as session:
            parent_tree = build_folder_tree(session, user_id)

        parent_options = [None] + [f['id'] for f in parent_tree]
        parent_folder = st.selectbox(
            "Übergeordneter Ordner",
            options=parent_options,
            format_func=lambda x: "📁 Kein (Root-Ordner)" if x is None else next((f['display_name'] for f in parent_tree if f['id'] == x), ""),
            key="parent_folder"
        )

        # Pfad anzeigen
        if parent_folder:
            selected_parent = next((f for f in parent_tree if f['id'] == parent_folder), None)
            if selected_parent:
                st.caption(f"📍 Wird erstellt unter: {selected_parent['path']}")

        if st.button("Erstellen") and new_folder_name:
            with get_db() as session:
                new_folder = Folder(
                    user_id=user_id,
                    name=new_folder_name,
                    parent_id=parent_folder
                )
                session.add(new_folder)
                session.commit()
            st.success(f"✓ Ordner '{new_folder_name}' erstellt!")
            st.rerun()


with col_docs:
    # Suchleiste
    search_col, filter_col = st.columns([3, 1])

    with search_col:
        search_query = st.text_input("🔍 Suchen...", placeholder="Stichwort, Betrag, IBAN...")

    with filter_col:
        filter_category = st.selectbox(
            "Kategorie",
            options=["Alle"] + DOCUMENT_CATEGORIES,
            key="filter_category"
        )

    # Dokumente laden
    with get_db() as session:
        query = session.query(Document).filter(Document.user_id == user_id)

        # Ordnerfilter
        if current_folder_id:
            query = query.filter(Document.folder_id == current_folder_id)

        # Kategoriefilter
        if filter_category != "Alle":
            query = query.filter(Document.category == filter_category)

        # Suche
        if search_query:
            search_service = get_search_service(user_id)
            search_results = search_service.search(search_query)
            doc_ids = [item['id'] for item in search_results['items']]
            if doc_ids:
                query = query.filter(Document.id.in_(doc_ids))
            else:
                # Fallback: einfache Textsuche
                query = query.filter(
                    Document.ocr_text.ilike(f'%{search_query}%') |
                    Document.filename.ilike(f'%{search_query}%') |
                    Document.sender.ilike(f'%{search_query}%')
                )

        documents = query.order_by(Document.created_at.desc()).limit(50).all()

        # Aktuellen Ordnernamen anzeigen
        if current_folder_id:
            folder = session.query(Folder).get(current_folder_id)
            st.subheader(f"📂 {folder.name}" if folder else "Dokumente")
        else:
            st.subheader("📄 Alle Dokumente")

        st.caption(f"{len(documents)} Dokumente")

        # Dokumentenliste
        if documents:
            for doc in documents:
                with st.container():
                    col1, col2, col3, col4 = st.columns([3, 1, 1, 1])

                    with col1:
                        # Status-Icon
                        if doc.status == DocumentStatus.COMPLETED:
                            status = "✓"
                        elif doc.status == DocumentStatus.PROCESSING:
                            status = "⏳"
                        elif doc.status == DocumentStatus.ERROR:
                            status = "❌"
                        else:
                            status = "📄"

                        st.markdown(f"**{status} {doc.title or doc.filename}**")
                        meta_parts = []
                        if doc.sender:
                            meta_parts.append(doc.sender)
                        if doc.category:
                            meta_parts.append(doc.category)
                        if doc.document_date:
                            meta_parts.append(format_date(doc.document_date))
                        st.caption(" | ".join(meta_parts) if meta_parts else "Keine Metadaten")

                    with col2:
                        if doc.invoice_amount:
                            st.markdown(f"**{format_currency(doc.invoice_amount)}**")
                            if doc.invoice_status == InvoiceStatus.OPEN:
                                st.caption("🔴 Offen")
                            elif doc.invoice_status == InvoiceStatus.PAID:
                                st.caption("✅ Bezahlt")

                    with col3:
                        if doc.iban:
                            st.code(doc.iban[:12] + "...")

                    with col4:
                        # Aktionsmenü
                        with st.popover("⋮"):
                            if st.button("👁️ Anzeigen", key=f"view_{doc.id}"):
                                st.session_state.view_document_id = doc.id

                            if st.button("📋 In Aktentasche", key=f"cart_{doc.id}"):
                                if 'active_cart_items' not in st.session_state:
                                    st.session_state.active_cart_items = []
                                if doc.id not in st.session_state.active_cart_items:
                                    st.session_state.active_cart_items.append(doc.id)
                                    st.success("Hinzugefügt!")

                            if st.button("📂 Verschieben", key=f"move_{doc.id}"):
                                st.session_state.move_document_id = doc.id

                            if st.button("🔗 Teilen", key=f"share_{doc.id}"):
                                link = generate_share_link(doc.id)
                                st.code(link)

                            if st.button("🗑️ Löschen", key=f"del_{doc.id}"):
                                st.session_state.delete_document_id = doc.id

                    st.divider()
        else:
            st.info("Keine Dokumente gefunden")

# Dokument anzeigen Dialog - Erweitert
if 'view_document_id' in st.session_state:
    doc_id = st.session_state.view_document_id

    with get_db() as session:
        doc = session.query(Document).get(doc_id)
        if doc:
            # Dokumentdaten in Dict extrahieren (für Verwendung außerhalb der Session)
            doc_data = {
                'id': doc.id,
                'title': doc.title,
                'filename': doc.filename,
                'file_path': doc.file_path,
                'mime_type': doc.mime_type,
                'encryption_iv': doc.encryption_iv,
                'category': doc.category,
                'sender': doc.sender,
                'sender_address': doc.sender_address,
                'document_date': doc.document_date,
                'subject': doc.subject,
                'ai_summary': doc.ai_summary,
                'reference_number': doc.reference_number,
                'customer_number': doc.customer_number,
                'insurance_number': doc.insurance_number,
                'processing_number': doc.processing_number,
                'contract_number': doc.contract_number,
                'invoice_number': getattr(doc, 'invoice_number', None),
                'invoice_amount': doc.invoice_amount,
                'invoice_due_date': doc.invoice_due_date,
                'invoice_status': doc.invoice_status,
                'invoice_paid_date': doc.invoice_paid_date,
                'paid_with_bank_account': getattr(doc, 'paid_with_bank_account', None),
                'iban': doc.iban,
                'bic': doc.bic,
                'bank_name': getattr(doc, 'bank_name', None),
                'ocr_text': doc.ocr_text,
                'created_at': doc.created_at,
                'folder_id': doc.folder_id
            }

    st.divider()
    st.subheader(f"📄 {doc_data['title'] or doc_data['filename']}")

    # Zusammenfassung anzeigen
    if doc_data['ai_summary']:
        st.info(f"📝 **Zusammenfassung:** {doc_data['ai_summary']}")

    # Tabs für verschiedene Ansichten
    tab_preview, tab_metadata, tab_edit, tab_actions = st.tabs([
        "👁️ Vorschau", "📋 Metadaten", "✏️ Bearbeiten", "⚡ Aktionen"
    ])

    with tab_preview:
        col_doc, col_text = st.columns([1, 1])

        with col_doc:
            st.markdown("### 📄 Dokument-Vorschau")
            if doc_data['file_path'] and Path(doc_data['file_path']).exists():
                encryption = get_encryption_service()
                try:
                    with open(doc_data['file_path'], 'rb') as f:
                        encrypted_data = f.read()
                    decrypted = encryption.decrypt_file(encrypted_data, doc_data['encryption_iv'], doc_data['filename'])

                    # Bild-Vorschau
                    if doc_data['mime_type'] and doc_data['mime_type'].startswith('image/'):
                        from PIL import Image
                        img = Image.open(io.BytesIO(decrypted))
                        st.image(img, use_container_width=True)
                    elif doc_data['mime_type'] == 'application/pdf':
                        st.info("📄 PDF-Dokument - Vorschau unten")
                        # PDF Info
                        st.caption(f"Größe: {len(decrypted) / 1024:.1f} KB")

                    # Download
                    st.download_button(
                        "⬇️ Herunterladen",
                        data=decrypted,
                        file_name=doc_data['filename'],
                        mime=doc_data['mime_type'],
                        key="download_preview"
                    )
                except Exception as e:
                    st.error(f"Fehler beim Laden: {e}")
            else:
                st.warning("Dokument-Datei nicht gefunden")

        with col_text:
            st.markdown("### 📝 Erkannter Text")
            if doc_data['ocr_text']:
                st.text_area("OCR-Text", doc_data['ocr_text'], height=400, disabled=True, key="ocr_preview")
            else:
                st.info("Kein OCR-Text verfügbar")

    with tab_metadata:
        # Drei-Spalten-Layout für Metadaten
        col_sender, col_refs, col_finance = st.columns(3)

        with col_sender:
            st.markdown("### 📤 Absender & Basis")
            st.write(f"**Absender:** {doc_data['sender'] or '—'}")
            if doc_data['sender_address']:
                st.write(f"**Adresse:** {doc_data['sender_address']}")
            st.write(f"**Betreff:** {doc_data['subject'] or '—'}")
            st.write(f"**Kategorie:** {doc_data['category'] or '—'}")
            st.write(f"**Dokumentdatum:** {format_date(doc_data['document_date'])}")
            st.write(f"**Hochgeladen:** {format_date(doc_data['created_at'], True)}")

        with col_refs:
            st.markdown("### 🔢 Referenznummern")
            refs = [
                ("Aktenzeichen", doc_data['reference_number']),
                ("Kundennummer", doc_data['customer_number']),
                ("Rechnungsnr.", doc_data['invoice_number']),
                ("Vers.-Nummer", doc_data['insurance_number']),
                ("Bearbeitungsnr.", doc_data['processing_number']),
                ("Vertragsnummer", doc_data['contract_number']),
            ]
            has_refs = False
            for label, value in refs:
                if value:
                    st.write(f"**{label}:** {value}")
                    has_refs = True
            if not has_refs:
                st.caption("Keine Referenznummern erkannt")

        with col_finance:
            st.markdown("### 💰 Finanzdaten")
            if doc_data.get('invoice_status'):
                from database.models import InvoiceStatus
                if doc_data['invoice_status'] == InvoiceStatus.OPEN:
                    st.error("🔴 Rechnung OFFEN")
                elif doc_data['invoice_status'] == InvoiceStatus.PAID:
                    st.success("✅ Rechnung BEZAHLT")
                    # Zahlungsdetails anzeigen
                    if doc_data.get('invoice_paid_date'):
                        st.write(f"📅 Bezahlt am: **{format_date(doc_data['invoice_paid_date'])}**")
                    if doc_data.get('paid_with_bank_account'):
                        st.write(f"🏦 Konto: **{doc_data['paid_with_bank_account']}**")
            if doc_data['invoice_amount']:
                st.write(f"**Betrag:** {format_currency(doc_data['invoice_amount'])}")
            if doc_data['invoice_due_date']:
                st.write(f"**Fällig bis:** {format_date(doc_data['invoice_due_date'])}")
            if doc_data['iban']:
                st.code(doc_data['iban'], language=None)
                st.caption("IBAN")
            if doc_data['bic']:
                st.write(f"**BIC:** {doc_data['bic']}")
            if doc_data.get('bank_name'):
                st.write(f"**Bank:** {doc_data['bank_name']}")
            if not any([doc_data['invoice_amount'], doc_data['iban']]):
                st.caption("Keine Finanzdaten erkannt")

    with tab_edit:
        st.markdown("### ✏️ Metadaten bearbeiten")

        with st.form("edit_metadata"):
            col_e1, col_e2 = st.columns(2)

            with col_e1:
                edit_sender = st.text_input("Absender", value=doc_data['sender'] or "")
                edit_sender_address = st.text_area("Absender-Adresse", value=doc_data['sender_address'] or "", height=100)
                edit_category = st.selectbox("Kategorie", DOCUMENT_CATEGORIES,
                    index=DOCUMENT_CATEGORIES.index(doc_data['category']) if doc_data['category'] in DOCUMENT_CATEGORIES else 0)
                edit_subject = st.text_input("Betreff", value=doc_data['subject'] or "")
                edit_doc_date = st.date_input("Dokumentdatum",
                    value=doc_data['document_date'].date() if doc_data['document_date'] else None)

            with col_e2:
                edit_ref = st.text_input("Aktenzeichen", value=doc_data['reference_number'] or "")
                edit_customer = st.text_input("Kundennummer", value=doc_data['customer_number'] or "")
                edit_invoice_nr = st.text_input("Rechnungsnummer", value=doc_data['invoice_number'] or "")
                edit_insurance = st.text_input("Versicherungsnummer", value=doc_data['insurance_number'] or "")
                edit_processing = st.text_input("Bearbeitungsnummer", value=doc_data['processing_number'] or "")
                edit_contract = st.text_input("Vertragsnummer", value=doc_data['contract_number'] or "")

            st.markdown("**Finanzdaten**")
            col_f1, col_f2, col_f3, col_f4 = st.columns(4)
            with col_f1:
                edit_amount = st.number_input("Betrag (€)", value=doc_data['invoice_amount'] or 0.0, min_value=0.0, step=0.01)
            with col_f2:
                edit_due = st.date_input("Fällig bis",
                    value=doc_data['invoice_due_date'].date() if doc_data['invoice_due_date'] else None)
            with col_f3:
                edit_iban = st.text_input("IBAN", value=doc_data['iban'] or "")
            with col_f4:
                edit_bank = st.text_input("Bank", value=doc_data.get('bank_name') or "")

            if st.form_submit_button("💾 Speichern", type="primary"):
                with get_db() as session:
                    doc = session.query(Document).get(doc_id)
                    if doc:
                        doc.sender = edit_sender or None
                        doc.sender_address = edit_sender_address or None
                        doc.category = edit_category
                        doc.subject = edit_subject or None
                        doc.title = edit_subject or doc.filename
                        doc.document_date = datetime.combine(edit_doc_date, datetime.min.time()) if edit_doc_date else None
                        doc.reference_number = edit_ref or None
                        doc.customer_number = edit_customer or None
                        doc.invoice_number = edit_invoice_nr or None
                        doc.insurance_number = edit_insurance or None
                        doc.processing_number = edit_processing or None
                        doc.contract_number = edit_contract or None
                        doc.invoice_amount = edit_amount if edit_amount > 0 else None
                        doc.invoice_due_date = datetime.combine(edit_due, datetime.min.time()) if edit_due else None
                        doc.iban = edit_iban or None
                        doc.bank_name = edit_bank or None
                        session.commit()
                        st.success("✅ Metadaten gespeichert!")
                        st.rerun()

    with tab_actions:
        st.markdown("### ⚡ Aktionen")

        col_act1, col_act2 = st.columns(2)

        with col_act1:
            # In Aktentasche
            st.markdown("**📋 Aktentasche**")
            if st.button("📋 In Aktentasche legen", use_container_width=True):
                if 'active_cart_items' not in st.session_state:
                    st.session_state.active_cart_items = []
                if doc_id not in st.session_state.active_cart_items:
                    st.session_state.active_cart_items.append(doc_id)
                    st.success("✅ Zur Aktentasche hinzugefügt!")
                else:
                    st.info("Bereits in der Aktentasche")

            # Verschieben
            st.markdown("**📂 Ordner**")
            with get_db() as session:
                folder_tree = build_folder_tree(session, user_id)

            move_folder = st.selectbox(
                "Zielordner",
                options=[f['id'] for f in folder_tree],
                format_func=lambda x: next((f['display_name'] for f in folder_tree if f['id'] == x), ""),
                key="move_select"
            )

            # Pfad anzeigen
            selected = next((f for f in folder_tree if f['id'] == move_folder), None)
            if selected:
                st.caption(f"📍 {selected['path']}")

            col_mv, col_cp = st.columns(2)
            with col_mv:
                if st.button("📂 Verschieben", use_container_width=True):
                    with get_db() as session:
                        doc = session.query(Document).get(doc_id)
                        if doc:
                            doc.folder_id = move_folder
                            session.commit()
                            # Klassifikator lernen lassen
                            classifier = get_classifier(user_id)
                            classifier.learn_from_move(doc_id, move_folder)
                            target_name = next((f['name'] for f in folder_tree if f['id'] == move_folder), "")
                            st.success(f"✅ Verschoben nach '{target_name}'!")
                            st.rerun()
            with col_cp:
                if st.button("📄 Kopieren", use_container_width=True):
                    st.info("Dokument wird in Zielordner kopiert (Referenz)")

        with col_act2:
            # Teilen
            st.markdown("**📤 Teilen**")

            # Share-Text erstellen
            share_title = doc_data['title'] or doc_data['filename']
            share_lines = [f"📄 {share_title}"]
            if doc_data['sender']:
                share_lines.append(f"Von: {doc_data['sender']}")
            if doc_data['category']:
                share_lines.append(f"Kategorie: {doc_data['category']}")
            if doc_data['document_date']:
                share_lines.append(f"Datum: {format_date(doc_data['document_date'])}")
            if doc_data['invoice_amount']:
                share_lines.append(f"Betrag: {format_currency(doc_data['invoice_amount'])}")
            if doc_data['iban']:
                share_lines.append(f"IBAN: {doc_data['iban']}")
            if doc_data['reference_number']:
                share_lines.append(f"Aktenzeichen: {doc_data['reference_number']}")
            share_text = "\n".join(share_lines)

            from utils.helpers import render_share_buttons
            render_share_buttons(share_title, share_text, key_prefix=f"doc_{doc_id}")

    # Schließen-Button
    st.markdown("---")
    if st.button("✕ Schließen", type="secondary"):
        del st.session_state.view_document_id
        st.rerun()

# Verschieben Dialog
if 'move_document_id' in st.session_state:
    doc_id = st.session_state.move_document_id

    with st.container():
        st.divider()
        st.subheader("📂 Dokument verschieben")

        with get_db() as session:
            # Hierarchische Ordnerstruktur laden
            folder_tree = build_folder_tree(session, user_id)

            # Aktuellen Ordner des Dokuments ermitteln
            doc = session.query(Document).get(doc_id)
            current_folder_name = ""
            if doc and doc.folder_id:
                current_folder = session.query(Folder).get(doc.folder_id)
                if current_folder:
                    current_folder_name = current_folder.name

            st.info(f"📄 Aktueller Ordner: **{current_folder_name or 'Kein Ordner'}**")

            # Ordnerauswahl mit Baumstruktur
            target_folder = st.selectbox(
                "Zielordner auswählen",
                options=[f['id'] for f in folder_tree],
                format_func=lambda x: next((f['display_name'] for f in folder_tree if f['id'] == x), ""),
                key="move_target_folder"
            )

            # Zeige vollständigen Pfad
            selected_folder = next((f for f in folder_tree if f['id'] == target_folder), None)
            if selected_folder:
                st.caption(f"📍 Pfad: {selected_folder['path']}")

            col1, col2 = st.columns(2)
            with col1:
                if st.button("Verschieben", type="primary"):
                    doc = session.query(Document).get(doc_id)
                    if doc:
                        old_folder_id = doc.folder_id
                        doc.folder_id = target_folder
                        session.commit()

                        # Klassifikator lernen lassen
                        classifier = get_classifier(user_id)
                        classifier.learn_from_move(doc_id, target_folder)

                        target_name = next((f['name'] for f in folder_tree if f['id'] == target_folder), "")
                        st.success(f"✓ Verschoben nach '{target_name}'!")
                        del st.session_state.move_document_id
                        st.rerun()
            with col2:
                if st.button("Abbrechen"):
                    del st.session_state.move_document_id
                    st.rerun()

# Löschen Dialog
if 'delete_document_id' in st.session_state:
    doc_id = st.session_state.delete_document_id

    with st.container():
        st.divider()
        st.warning("⚠️ Dokument wirklich löschen?")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("🗑️ Ja, löschen", type="primary"):
                with get_db() as session:
                    doc = session.query(Document).get(doc_id)
                    if doc:
                        # In Papierkorb verschieben statt löschen
                        trash = session.query(Folder).filter(
                            Folder.user_id == user_id,
                            Folder.name == "Papierkorb"
                        ).first()
                        if trash:
                            doc.folder_id = trash.id
                        else:
                            session.delete(doc)
                        session.commit()
                del st.session_state.delete_document_id
                st.rerun()
        with col2:
            if st.button("Abbrechen"):
                del st.session_state.delete_document_id
                st.rerun()
