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
        parent_folder = st.selectbox(
            "Übergeordneter Ordner",
            options=[None] + [f['id'] for f in folder_data],
            format_func=lambda x: "Kein (Root)" if x is None else next((f['name'] for f in folder_data if f['id'] == x), ""),
            key="parent_folder"
        )
        if st.button("Erstellen") and new_folder_name:
            with get_db() as session:
                new_folder = Folder(
                    user_id=user_id,
                    name=new_folder_name,
                    parent_id=parent_folder
                )
                session.add(new_folder)
                session.commit()
            st.success(f"Ordner '{new_folder_name}' erstellt!")
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

# Dokument anzeigen Dialog
if 'view_document_id' in st.session_state:
    doc_id = st.session_state.view_document_id

    with get_db() as session:
        doc = session.query(Document).get(doc_id)
        if doc:
            st.divider()
            st.subheader(f"📄 {doc.title or doc.filename}")

            col_meta, col_preview = st.columns([1, 2])

            with col_meta:
                st.markdown("### Metadaten")
                st.write(f"**Dateiname:** {doc.filename}")
                st.write(f"**Kategorie:** {doc.category or '-'}")
                st.write(f"**Absender:** {doc.sender or '-'}")
                st.write(f"**Datum:** {format_date(doc.document_date)}")
                st.write(f"**Erstellt:** {format_date(doc.created_at, True)}")

                if doc.invoice_amount:
                    st.write(f"**Betrag:** {format_currency(doc.invoice_amount)}")
                if doc.iban:
                    st.write(f"**IBAN:** {doc.iban}")
                if doc.contract_number:
                    st.write(f"**Vertragsnr.:** {doc.contract_number}")

            with col_preview:
                st.markdown("### OCR-Text")
                if doc.ocr_text:
                    st.text_area("", doc.ocr_text, height=300, disabled=True)
                else:
                    st.info("Kein OCR-Text verfügbar")

                # Download-Button
                if doc.file_path and Path(doc.file_path).exists():
                    encryption = get_encryption_service()
                    with open(doc.file_path, 'rb') as f:
                        encrypted_data = f.read()
                    try:
                        decrypted = encryption.decrypt_file(encrypted_data, doc.encryption_iv, doc.filename)
                        st.download_button(
                            "⬇️ Herunterladen",
                            data=decrypted,
                            file_name=doc.filename,
                            mime=doc.mime_type
                        )
                    except Exception as e:
                        st.error(f"Entschlüsselung fehlgeschlagen: {e}")

            if st.button("Schließen"):
                del st.session_state.view_document_id
                st.rerun()

# Verschieben Dialog
if 'move_document_id' in st.session_state:
    doc_id = st.session_state.move_document_id

    with st.container():
        st.divider()
        st.subheader("📂 Dokument verschieben")

        with get_db() as session:
            folders = session.query(Folder).filter(Folder.user_id == user_id).all()
            folder_options = {f.id: f.name for f in folders}

            target_folder = st.selectbox(
                "Zielordner",
                options=list(folder_options.keys()),
                format_func=lambda x: folder_options[x]
            )

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

                        st.success("Verschoben!")
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
