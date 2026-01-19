"""
Dokumentenmanagement - Ordnerstruktur und Dokumentenverwaltung
"""
import streamlit as st
import io
import base64
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
from utils.helpers import format_currency, format_date, generate_share_link, truncate_text, get_document_file_content

st.set_page_config(page_title="Dokumente", page_icon="📁", layout="wide")
init_db()


def render_inline_preview(doc: dict, user_id: int):
    """Rendert eine kompakte Inline-Vorschau direkt unter dem Dokument"""
    from utils.helpers import get_document_file_content, document_file_exists

    with st.container():
        st.markdown(
            """<div style="background-color: #f8f9fa; padding: 15px; border-radius: 10px;
            border-left: 4px solid #007bff; margin: 10px 0;">""",
            unsafe_allow_html=True
        )

        preview_col, action_col = st.columns([3, 1])

        with preview_col:
            if doc['file_path'] and document_file_exists(doc['file_path']):
                try:
                    success, result = get_document_file_content(doc['file_path'], user_id)
                    if success:
                        # Entschlüsseln wenn nötig
                        if doc.get('is_encrypted') and doc.get('encryption_iv'):
                            encryption = get_encryption_service()
                            try:
                                file_data = encryption.decrypt_file(result, doc['encryption_iv'], doc['filename'])
                            except:
                                file_data = result
                        else:
                            file_data = result

                        mime_type = doc.get('mime_type') or ""
                        filename_lower = doc['filename'].lower() if doc['filename'] else ""

                        # PDF-Vorschau
                        if "pdf" in mime_type or filename_lower.endswith(".pdf"):
                            pdf_base64 = base64.b64encode(file_data).decode('utf-8')
                            st.markdown(f'''
                                <iframe src="data:application/pdf;base64,{pdf_base64}"
                                    width="100%" height="400px"
                                    style="border: 1px solid #ddd; border-radius: 5px;">
                                </iframe>
                            ''', unsafe_allow_html=True)

                        # Excel-Vorschau
                        elif filename_lower.endswith((".xlsx", ".xls")):
                            try:
                                import pandas as pd
                                excel_file = io.BytesIO(file_data)
                                df = pd.read_excel(excel_file)
                                st.dataframe(df.head(20), width="stretch", height=300)
                                st.caption(f"📊 {len(df)} Zeilen (Vorschau: erste 20)")
                            except Exception as e:
                                st.warning(f"Excel-Vorschau nicht möglich: {e}")

                        # Word-Vorschau
                        elif filename_lower.endswith(".docx"):
                            try:
                                from docx import Document as DocxDocument
                                docx_file = io.BytesIO(file_data)
                                doc_content = DocxDocument(docx_file)
                                text_parts = [p.text for p in doc_content.paragraphs[:20] if p.text.strip()]
                                st.markdown("\n\n".join(text_parts[:10]))
                                if len(text_parts) > 10:
                                    st.caption("... (gekürzt)")
                            except Exception as e:
                                st.warning(f"Word-Vorschau nicht möglich: {e}")

                        # Bild-Vorschau
                        elif mime_type.startswith('image/') or filename_lower.endswith((".jpg", ".jpeg", ".png", ".gif")):
                            from PIL import Image
                            img = Image.open(io.BytesIO(file_data))
                            st.image(img, width="stretch")

                        else:
                            st.info(f"Vorschau für {mime_type or 'dieses Format'} nicht verfügbar")

                        # Download
                        st.download_button(
                            "⬇️ Herunterladen",
                            data=file_data,
                            file_name=doc['filename'],
                            mime=doc.get('mime_type') or "application/octet-stream",
                            key=f"dl_inline_{doc['id']}"
                        )
                    else:
                        st.error(f"Fehler: {result}")
                except Exception as e:
                    st.error(f"Vorschau-Fehler: {e}")
            else:
                st.warning("Datei nicht gefunden")

        with action_col:
            st.markdown("**Schnellaktionen**")

            # In Aktentasche
            if st.button("📋 Aktentasche", key=f"inline_cart_{doc['id']}"):
                if 'active_cart_items' not in st.session_state:
                    st.session_state.active_cart_items = []
                if doc['id'] not in st.session_state.active_cart_items:
                    st.session_state.active_cart_items.append(doc['id'])
                    st.toast("✅ Hinzugefügt!")

            # Erneut analysieren
            if st.button("🔄 Analysieren", key=f"inline_reanalyze_{doc['id']}"):
                st.session_state.reanalyze_doc_id = doc['id']
                st.rerun()

            # Vollansicht
            if st.button("🔍 Vollansicht", key=f"inline_full_{doc['id']}"):
                st.session_state.view_document_id = doc['id']
                st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)


def reanalyze_document(doc_id: int, user_id: int) -> dict:
    """Führt OCR und KI-Analyse erneut durch"""
    from services.ocr import get_ocr_service
    from services.ai_service import get_ai_service
    from utils.helpers import get_document_file_content

    result = {"success": False, "message": ""}

    with get_db() as session:
        doc = session.get(Document, doc_id)
        if not doc:
            return {"success": False, "message": "Dokument nicht gefunden"}

        # Datei laden
        success, file_result = get_document_file_content(doc.file_path, user_id)
        if not success:
            return {"success": False, "message": f"Datei nicht ladbar: {file_result}"}

        # Entschlüsseln wenn nötig
        if doc.is_encrypted and doc.encryption_iv:
            encryption = get_encryption_service()
            try:
                file_data = encryption.decrypt_file(file_result, doc.encryption_iv, doc.filename)
            except:
                file_data = file_result
        else:
            file_data = file_result

        # Status auf Processing setzen
        doc.status = DocumentStatus.PROCESSING
        # OCR-Text löschen um Neuanalyse zu erzwingen
        doc.ocr_text = None
        session.commit()

        try:
            ocr = get_ocr_service()
            ai = get_ai_service()

            # OCR durchführen
            full_text = ""
            confidence = 0.0

            if doc.mime_type == "application/pdf":
                results = ocr.extract_text_from_pdf(file_data)
                if results:
                    full_text = "\n\n".join(text for text, _ in results)
                    confidence = sum(conf for _, conf in results) / len(results)
            else:
                from PIL import Image
                image = Image.open(io.BytesIO(file_data))
                full_text, confidence = ocr.extract_text_from_image(image)

            doc.ocr_text = full_text
            doc.ocr_confidence = confidence

            # Metadaten extrahieren
            metadata = ocr.extract_metadata(full_text)

            if metadata.get('dates'):
                doc.document_date = metadata['dates'][0]
            if metadata.get('amounts'):
                doc.invoice_amount = max(metadata['amounts'])
            if metadata.get('ibans'):
                doc.iban = metadata['ibans'][0]

            # KI-Analyse wenn verfügbar
            if ai.any_ai_available:
                structured_data = ai.extract_structured_data(full_text)

                if structured_data.get('sender'):
                    doc.sender = structured_data['sender']
                if structured_data.get('sender_address'):
                    doc.sender_address = structured_data['sender_address']
                if structured_data.get('subject'):
                    doc.subject = structured_data['subject']
                    doc.title = structured_data['subject']
                if structured_data.get('category'):
                    doc.category = structured_data['category']
                if structured_data.get('summary'):
                    doc.ai_summary = structured_data['summary']
                if structured_data.get('reference_number'):
                    doc.reference_number = structured_data['reference_number']
                if structured_data.get('customer_number'):
                    doc.customer_number = structured_data['customer_number']
                if structured_data.get('invoice_number'):
                    doc.invoice_number = structured_data['invoice_number']
                if structured_data.get('insurance_number'):
                    doc.insurance_number = structured_data['insurance_number']
                if structured_data.get('processing_number'):
                    doc.processing_number = structured_data['processing_number']
                if structured_data.get('contract_number'):
                    doc.contract_number = structured_data['contract_number']

                # Vertragsdaten
                from utils.helpers import parse_date_string
                if structured_data.get('contract_start'):
                    contract_start = parse_date_string(structured_data['contract_start'])
                    if contract_start:
                        doc.contract_start = contract_start
                if structured_data.get('contract_end'):
                    contract_end = parse_date_string(structured_data['contract_end'])
                    if contract_end:
                        doc.contract_end = contract_end
                if structured_data.get('contract_notice_period_days'):
                    try:
                        doc.contract_notice_period = int(structured_data['contract_notice_period_days'])
                    except:
                        pass

                # Erweiterte dokumenttyp-spezifische Metadaten
                if structured_data.get('extended_metadata'):
                    doc.extended_metadata = structured_data['extended_metadata']

                # Finanzinformationen
                if structured_data.get('invoice_amount'):
                    doc.invoice_amount = float(structured_data['invoice_amount'])
                if structured_data.get('invoice_due_date'):
                    due_date = parse_date_string(structured_data['invoice_due_date'])
                    if due_date:
                        doc.invoice_due_date = due_date
                if structured_data.get('iban'):
                    doc.iban = structured_data['iban']
                if structured_data.get('bic'):
                    doc.bic = structured_data['bic']
                if structured_data.get('bank_name'):
                    doc.bank_name = structured_data['bank_name']

            doc.status = DocumentStatus.COMPLETED
            session.commit()

            # Suchindex aktualisieren
            search = get_search_service(user_id)
            search.index_document(doc_id, {
                'title': doc.title or doc.filename,
                'content': doc.ocr_text or '',
                'sender': doc.sender or '',
                'category': doc.category or '',
                'folder_id': doc.folder_id,
                'document_date': doc.document_date,
                'amounts': [doc.invoice_amount] if doc.invoice_amount else [],
                'ibans': [doc.iban] if doc.iban else [],
                'created_at': doc.created_at
            })

            return {"success": True, "message": "Analyse erfolgreich abgeschlossen"}

        except Exception as e:
            doc.status = DocumentStatus.ERROR
            doc.processing_notes = str(e)[:500]
            session.commit()
            return {"success": False, "message": f"Fehler: {str(e)[:200]}"}


# Sidebar mit Aktentasche
from utils.components import render_sidebar_cart, add_to_cart
render_sidebar_cart()


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


user_id = get_current_user_id()

# MaStR-Layout anwenden
from utils.components import render_sidebar_with_navigation
from utils.layout_mastr import render_breadcrumb, render_page_title
render_sidebar_with_navigation(use_mastr_layout=True)
render_breadcrumb("Dokumente", "Dokumentenverwaltung")
render_page_title("Dokumentenverwaltung")

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
    if st.button("📄 Alle Dokumente", width="stretch",
                 type="primary" if current_folder_id is None else "secondary"):
        st.session_state.current_folder_id = None
        st.rerun()

    st.divider()

    # Ordner anzeigen - NUR ORDNER MIT DOKUMENTEN (außer Systemordner)
    for folder in folder_data:
        # Systemordner immer anzeigen, andere nur wenn sie Dokumente haben
        is_system = folder['name'] in ["Posteingang", "Papierkorb", "Archiv"]
        total_count = folder['count'] + sum(sub['count'] for sub in folder['subfolders'])

        # Ordner überspringen wenn leer und kein Systemordner
        if not is_system and total_count == 0:
            continue

        icon = "📥" if folder['name'] == "Posteingang" else "📂"
        if folder['name'] == "Papierkorb":
            icon = "🗑️"
        elif folder['name'] == "Archiv":
            icon = "📦"

        is_selected = current_folder_id == folder['id']
        if st.button(f"{icon} {folder['name']} ({folder['count']})",
                    width="stretch",
                    type="primary" if is_selected else "secondary",
                    key=f"folder_{folder['id']}"):
            st.session_state.current_folder_id = folder['id']
            st.rerun()

        # Unterordner - nur anzeigen wenn sie Dokumente haben
        for sub in folder['subfolders']:
            if sub['count'] == 0:
                continue  # Leere Unterordner überspringen
            if st.button(f"  └ {sub['name']} ({sub['count']})",
                        width="stretch",
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
    # Breadcrumb-Navigation
    if current_folder_id:
        with get_db() as session:
            # Pfad zum aktuellen Ordner aufbauen
            breadcrumb_parts = []
            folder = session.get(Folder, current_folder_id)
            while folder:
                breadcrumb_parts.insert(0, {'id': folder.id, 'name': folder.name})
                folder = session.get(Folder, folder.parent_id) if folder.parent_id else None

            # Breadcrumb anzeigen
            bc_cols = st.columns([1] + [1] * len(breadcrumb_parts) + [4])

            with bc_cols[0]:
                if st.button("🏠", key="bc_home", help="Alle Dokumente"):
                    st.session_state.current_folder_id = None
                    st.rerun()

            for i, part in enumerate(breadcrumb_parts):
                with bc_cols[i + 1]:
                    is_current = (i == len(breadcrumb_parts) - 1)
                    if is_current:
                        st.markdown(f"**📂 {part['name']}**")
                    else:
                        if st.button(f"📁 {part['name']}", key=f"bc_{part['id']}"):
                            st.session_state.current_folder_id = part['id']
                            st.rerun()

            st.markdown("---")

    # Suchleiste und Filter
    search_col, filter_col, page_size_col = st.columns([3, 1, 1])

    with search_col:
        search_query = st.text_input("🔍 Suchen...", placeholder="Stichwort, Betrag, IBAN...")

    with filter_col:
        filter_category = st.selectbox(
            "Kategorie",
            options=["Alle"] + DOCUMENT_CATEGORIES,
            key="filter_category"
        )

    with page_size_col:
        page_size_options = {"10": 10, "20": 20, "50": 50, "100": 100, "Alle": 9999}
        page_size_label = st.selectbox(
            "Pro Seite",
            options=list(page_size_options.keys()),
            index=0,
            key="page_size_select"
        )
        page_size = page_size_options[page_size_label]

    # Dokumente laden
    with get_db() as session:
        query = session.query(Document).filter(Document.user_id == user_id)

        # Gelöschte Dokumente ausschließen (außer im Papierkorb-Modus)
        is_trash_view = False
        if current_folder_id:
            folder = session.get(Folder, current_folder_id)
            if folder and folder.name == "Papierkorb":
                is_trash_view = True
                # Im Papierkorb: nur gelöschte Dokumente zeigen
                query = query.filter(Document.is_deleted == True)
            else:
                query = query.filter(Document.folder_id == current_folder_id)
                query = query.filter((Document.is_deleted == False) | (Document.is_deleted == None))
        else:
            # Alle Dokumente: keine gelöschten
            query = query.filter((Document.is_deleted == False) | (Document.is_deleted == None))

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

        # Gesamtzahl für Pagination
        total_count = query.count()

        # Pagination
        current_page = st.session_state.get('doc_page', 1)
        total_pages = max(1, (total_count + page_size - 1) // page_size)
        if current_page > total_pages:
            current_page = 1
            st.session_state.doc_page = 1

        offset = (current_page - 1) * page_size
        documents = query.order_by(Document.created_at.desc()).offset(offset).limit(page_size).all()

        # Aktuellen Ordnernamen anzeigen
        if current_folder_id:
            folder = session.get(Folder, current_folder_id)
            st.subheader(f"📂 {folder.name}" if folder else "Dokumente")
        else:
            st.subheader("📄 Alle Dokumente")

        # Pagination Info und Aktionen-Leiste
        header_col1, header_col2 = st.columns([2, 2])
        with header_col1:
            start_doc = offset + 1 if documents else 0
            end_doc = min(offset + page_size, total_count)
            st.caption(f"Zeige {start_doc}-{end_doc} von {total_count} Dokumenten")

        # Multi-Select initialisieren
        if 'selected_docs' not in st.session_state:
            st.session_state.selected_docs = set()

        with header_col2:
            # Batch-Aktionen wenn Dokumente ausgewählt
            if st.session_state.selected_docs:
                sel_count = len(st.session_state.selected_docs)
                action_cols = st.columns([2, 1, 1, 1, 1])
                with action_cols[0]:
                    st.markdown(f"**{sel_count} ausgewählt**")
                with action_cols[1]:
                    if st.button("🔄 Erneut analysieren", key="batch_reanalyze", help="OCR und KI-Analyse erneut durchführen"):
                        st.session_state.batch_reanalyze = list(st.session_state.selected_docs)
                        st.rerun()
                with action_cols[2]:
                    if st.button("📋 Kopieren", key="batch_copy"):
                        st.session_state.batch_copy = list(st.session_state.selected_docs)
                        st.rerun()
                with action_cols[3]:
                    if st.button("🗑️ Löschen", key="batch_delete"):
                        st.session_state.batch_delete = list(st.session_state.selected_docs)
                        st.rerun()
                with action_cols[4]:
                    if st.button("✖️ Auswahl aufheben", key="clear_selection"):
                        st.session_state.selected_docs = set()
                        st.rerun()

        # Dokumentenliste mit Inline-Vorschau
        if documents:
            # Dokumente als Dicts extrahieren für Verwendung außerhalb der Session
            doc_list = []
            for doc in documents:
                doc_list.append({
                    'id': doc.id,
                    'title': doc.title,
                    'filename': doc.filename,
                    'file_path': doc.file_path,
                    'mime_type': doc.mime_type,
                    'is_encrypted': doc.is_encrypted,
                    'encryption_iv': doc.encryption_iv,
                    'status': doc.status,
                    'sender': doc.sender,
                    'category': doc.category,
                    'document_date': doc.document_date,
                    'invoice_amount': doc.invoice_amount,
                    'invoice_status': doc.invoice_status,
                    'iban': doc.iban
                })

    # Jetzt außerhalb der DB-Session die Dokumente anzeigen
    if documents:
        for doc in doc_list:
            with st.container():
                col_check, col1, col2, col3, col4 = st.columns([0.3, 3, 1, 1, 1])

                with col_check:
                    is_selected = doc['id'] in st.session_state.selected_docs
                    if st.checkbox("", value=is_selected, key=f"sel_{doc['id']}", label_visibility="collapsed"):
                        st.session_state.selected_docs.add(doc['id'])
                    else:
                        st.session_state.selected_docs.discard(doc['id'])

                with col1:
                    # Status-Icon
                    if doc['status'] == DocumentStatus.COMPLETED:
                        status = "✓"
                    elif doc['status'] == DocumentStatus.PROCESSING:
                        status = "⏳"
                    elif doc['status'] == DocumentStatus.ERROR:
                        status = "❌"
                    else:
                        status = "📄"

                    st.markdown(f"**{status} {doc['title'] or doc['filename']}**")
                    meta_parts = []
                    if doc['sender']:
                        meta_parts.append(doc['sender'])
                    if doc['category']:
                        meta_parts.append(doc['category'])
                    if doc['document_date']:
                        meta_parts.append(format_date(doc['document_date']))
                    st.caption(" | ".join(meta_parts) if meta_parts else "Keine Metadaten")

                with col2:
                    if doc['invoice_amount']:
                        st.markdown(f"**{format_currency(doc['invoice_amount'])}**")
                        if doc['invoice_status'] == InvoiceStatus.OPEN:
                            st.caption("🔴 Offen")
                        elif doc['invoice_status'] == InvoiceStatus.PAID:
                            st.caption("✅ Bezahlt")

                with col3:
                    if doc['iban']:
                        st.code(doc['iban'][:12] + "...")

                with col4:
                    # Aktionsmenü
                    btn_cols = st.columns(2)
                    with btn_cols[0]:
                        # Toggle Vorschau Button
                        preview_key = f"preview_{doc['id']}"
                        is_previewing = st.session_state.get(preview_key, False)
                        if st.button("👁️" if not is_previewing else "✖️", key=f"toggle_{doc['id']}",
                                    help="Vorschau anzeigen/schließen"):
                            st.session_state[preview_key] = not is_previewing
                            st.rerun()
                    with btn_cols[1]:
                        with st.popover("⋮"):
                            # Download-Button
                            if doc['file_path']:
                                try:
                                    success, file_result = get_document_file_content(doc['file_path'], user_id)
                                    if success:
                                        # Entschlüsseln wenn nötig
                                        if doc.get('is_encrypted') and doc.get('encryption_iv'):
                                            encryption = get_encryption_service()
                                            try:
                                                dl_data = encryption.decrypt_file(file_result, doc['encryption_iv'], doc['filename'])
                                            except:
                                                dl_data = file_result
                                        else:
                                            dl_data = file_result

                                        st.download_button(
                                            "⬇️ Herunterladen",
                                            data=dl_data,
                                            file_name=doc['filename'],
                                            mime=doc.get('mime_type') or "application/octet-stream",
                                            key=f"dl_menu_{doc['id']}"
                                        )
                                except Exception as e:
                                    st.caption(f"Download nicht verfügbar")

                            if st.button("🔄 Erneut analysieren", key=f"reanalyze_{doc['id']}"):
                                st.session_state.reanalyze_doc_id = doc['id']
                                st.rerun()

                            if st.button("📋 In Aktentasche", key=f"cart_{doc['id']}"):
                                if 'active_cart_items' not in st.session_state:
                                    st.session_state.active_cart_items = []
                                if doc['id'] not in st.session_state.active_cart_items:
                                    st.session_state.active_cart_items.append(doc['id'])
                                    st.toast("✅ Zur Aktentasche hinzugefügt!")
                                    st.rerun()

                            if st.button("📂 Verschieben", key=f"move_{doc['id']}"):
                                st.session_state.move_document_id = doc['id']
                                st.rerun()

                            # Teilen mit besserem UI
                            st.markdown("---")
                            st.markdown("**🔗 Teilen**")
                            share_link = generate_share_link(doc['id'])
                            st.text_input(
                                "Link kopieren:",
                                value=share_link,
                                key=f"share_link_{doc['id']}",
                                label_visibility="collapsed"
                            )
                            st.caption("Link ist 7 Tage gültig")
                            st.markdown("---")

                            if st.button("🗑️ Löschen", key=f"del_{doc['id']}"):
                                st.session_state.delete_document_id = doc['id']
                                st.rerun()

                # INLINE VORSCHAU - direkt unter dem Dokument
                if st.session_state.get(f"preview_{doc['id']}", False):
                    render_inline_preview(doc, user_id)

                st.divider()

        # Pagination Controls
        if total_pages > 1:
            st.markdown("---")
            page_cols = st.columns([1, 3, 1])

            with page_cols[0]:
                if current_page > 1:
                    if st.button("◀ Zurück", key="prev_page"):
                        st.session_state.doc_page = current_page - 1
                        st.rerun()

            with page_cols[1]:
                # Seitenauswahl
                page_options = list(range(1, total_pages + 1))
                selected_page = st.selectbox(
                    "Seite",
                    options=page_options,
                    index=current_page - 1,
                    key="page_select",
                    label_visibility="collapsed"
                )
                if selected_page != current_page:
                    st.session_state.doc_page = selected_page
                    st.rerun()

            with page_cols[2]:
                if current_page < total_pages:
                    if st.button("Weiter ▶", key="next_page"):
                        st.session_state.doc_page = current_page + 1
                        st.rerun()

            st.caption(f"Seite {current_page} von {total_pages}")
    else:
        st.info("Keine Dokumente gefunden")

# ============================================================
# HANDLER FÜR EINZELDOKUMENT-NEUANALYSE
# ============================================================
if 'reanalyze_doc_id' in st.session_state:
    doc_id = st.session_state.reanalyze_doc_id

    with st.spinner(f"🔄 Analysiere Dokument {doc_id} erneut..."):
        result = reanalyze_document(doc_id, user_id)

    if result['success']:
        st.success(f"✅ {result['message']}")
    else:
        st.error(f"❌ {result['message']}")

    del st.session_state.reanalyze_doc_id
    st.rerun()

# ============================================================
# HANDLER FÜR BATCH-NEUANALYSE
# ============================================================
if 'batch_reanalyze' in st.session_state:
    doc_ids = st.session_state.batch_reanalyze

    st.divider()
    st.subheader(f"🔄 {len(doc_ids)} Dokumente erneut analysieren")

    progress_bar = st.progress(0)
    status_text = st.empty()
    success_count = 0
    error_count = 0

    for i, doc_id in enumerate(doc_ids):
        status_text.text(f"Analysiere Dokument {i+1}/{len(doc_ids)}...")
        result = reanalyze_document(doc_id, user_id)

        if result['success']:
            success_count += 1
        else:
            error_count += 1

        progress_bar.progress((i + 1) / len(doc_ids))

    status_text.empty()
    st.success(f"✅ Fertig: {success_count} erfolgreich, {error_count} Fehler")

    # Auswahl aufheben
    st.session_state.selected_docs = set()
    del st.session_state.batch_reanalyze
    st.rerun()

# ============================================================
# HANDLER FÜR BATCH-LÖSCHEN
# ============================================================
if 'batch_delete' in st.session_state:
    doc_ids = st.session_state.batch_delete

    st.divider()
    st.warning(f"⚠️ {len(doc_ids)} Dokumente in den Papierkorb verschieben?")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🗑️ Ja, in Papierkorb", type="primary", key="confirm_batch_delete"):
            from services.trash_service import get_trash_service
            trash_service = get_trash_service()

            success_count = 0
            for doc_id in doc_ids:
                result = trash_service.move_to_trash(doc_id, user_id)
                if result.get('success'):
                    success_count += 1

            st.success(f"✅ {success_count} Dokumente in den Papierkorb verschoben")
            st.session_state.selected_docs = set()
            del st.session_state.batch_delete
            st.rerun()

    with col2:
        if st.button("❌ Abbrechen", key="cancel_batch_delete"):
            del st.session_state.batch_delete
            st.rerun()

# ============================================================
# HANDLER FÜR BATCH-KOPIEREN
# ============================================================
if 'batch_copy' in st.session_state:
    doc_ids = st.session_state.batch_copy

    st.divider()
    st.subheader(f"📋 {len(doc_ids)} Dokumente kopieren")

    with get_db() as session:
        folder_tree = build_folder_tree(session, user_id)

    target_folder = st.selectbox(
        "Zielordner auswählen",
        options=[f['id'] for f in folder_tree],
        format_func=lambda x: next((f['display_name'] for f in folder_tree if f['id'] == x), ""),
        key="batch_copy_target"
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("📋 Kopieren (Referenzen)", type="primary", key="confirm_batch_copy"):
            # Dokumente in virtuellen Ordner kopieren (Referenz)
            from database.models import DocumentVirtualFolder

            with get_db() as session:
                success_count = 0
                for doc_id in doc_ids:
                    # Prüfen ob bereits im Zielordner
                    existing = session.query(DocumentVirtualFolder).filter(
                        DocumentVirtualFolder.document_id == doc_id,
                        DocumentVirtualFolder.folder_id == target_folder
                    ).first()

                    if not existing:
                        vf = DocumentVirtualFolder(
                            document_id=doc_id,
                            folder_id=target_folder
                        )
                        session.add(vf)
                        success_count += 1

                session.commit()

            target_name = next((f['name'] for f in folder_tree if f['id'] == target_folder), "")
            st.success(f"✅ {success_count} Referenzen in '{target_name}' erstellt")
            st.session_state.selected_docs = set()
            del st.session_state.batch_copy
            st.rerun()

    with col2:
        if st.button("❌ Abbrechen", key="cancel_batch_copy"):
            del st.session_state.batch_copy
            st.rerun()

# Dokument anzeigen Dialog - Erweitert
if 'view_document_id' in st.session_state:
    doc_id = st.session_state.view_document_id

    with get_db() as session:
        doc = session.get(Document, doc_id)
        if doc:
            # Dokumentdaten in Dict extrahieren (für Verwendung außerhalb der Session)
            doc_data = {
                'id': doc.id,
                'title': doc.title,
                'filename': doc.filename,
                'file_path': doc.file_path,
                'mime_type': doc.mime_type,
                'is_encrypted': doc.is_encrypted,
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
                'contract_start': getattr(doc, 'contract_start', None),
                'contract_end': getattr(doc, 'contract_end', None),
                'contract_notice_period': getattr(doc, 'contract_notice_period', None),
                'extended_metadata': getattr(doc, 'extended_metadata', None),
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
                'folder_id': doc.folder_id,
                'user_id': doc.user_id
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
        import base64

        st.markdown("### 📄 Dokument-Vorschau")
        from utils.helpers import get_document_file_content, document_file_exists

        if doc_data['file_path'] and document_file_exists(doc_data['file_path']):
            try:
                success, result = get_document_file_content(doc_data['file_path'], doc_data.get('user_id'))
                if not success:
                    st.error(f"Fehler beim Laden: {result}")
                else:
                    # Entschlüsseln nur wenn verschlüsselt UND IV vorhanden
                    if doc_data.get('is_encrypted') and doc_data.get('encryption_iv'):
                        encryption = get_encryption_service()
                        try:
                            file_data = encryption.decrypt_file(result, doc_data['encryption_iv'], doc_data['filename'])
                        except:
                            file_data = result
                    else:
                        file_data = result

                    mime_type = doc_data['mime_type'] or ""
                    filename_lower = doc_data['filename'].lower() if doc_data['filename'] else ""

                    # PDF-Vorschau mit iframe
                    if mime_type == "application/pdf" or filename_lower.endswith(".pdf"):
                        pdf_base64 = base64.b64encode(file_data).decode('utf-8')

                        # Vollansicht-Button (öffnet PDF in neuem Tab)
                        col_fullview, col_download = st.columns([1, 1])
                        with col_fullview:
                            fullview_html = f'''
                            <a href="data:application/pdf;base64,{pdf_base64}"
                               target="_blank"
                               style="display: inline-block; padding: 0.5rem 1rem;
                                      background-color: #0066cc; color: white;
                                      text-decoration: none; border-radius: 5px;
                                      font-weight: 500; margin-bottom: 10px;">
                                🔍 Vollansicht in neuem Tab öffnen
                            </a>
                            '''
                            st.markdown(fullview_html, unsafe_allow_html=True)
                        with col_download:
                            st.download_button(
                                "⬇️ PDF herunterladen",
                                data=file_data,
                                file_name=doc_data['filename'],
                                mime="application/pdf",
                                key=f"download_pdf_{doc_id}"
                            )

                        pdf_display = f'''
                        <iframe
                            src="data:application/pdf;base64,{pdf_base64}"
                            width="100%"
                            height="700px"
                            type="application/pdf"
                            style="border: 1px solid #ddd; border-radius: 5px;">
                        </iframe>
                        '''
                        st.markdown(pdf_display, unsafe_allow_html=True)

                    # Excel-Vorschau
                    elif filename_lower.endswith((".xlsx", ".xls")) or "spreadsheet" in mime_type:
                        try:
                            import pandas as pd

                            excel_file = io.BytesIO(file_data)
                            xl = pd.ExcelFile(excel_file)
                            sheet_names = xl.sheet_names

                            if len(sheet_names) > 1:
                                selected_sheet = st.selectbox(
                                    "Tabellenblatt auswählen",
                                    sheet_names,
                                    key=f"sheet_select_{doc_id}"
                                )
                            else:
                                selected_sheet = sheet_names[0]

                            df = pd.read_excel(excel_file, sheet_name=selected_sheet)
                            st.dataframe(df, width="stretch", height=500)
                            st.caption(f"📊 {len(df)} Zeilen × {len(df.columns)} Spalten")
                        except Exception as excel_err:
                            st.warning(f"Excel-Vorschau nicht möglich: {excel_err}")

                    # Word-Vorschau (.docx)
                    elif filename_lower.endswith(".docx"):
                        try:
                            from docx import Document as DocxDocument

                            docx_file = io.BytesIO(file_data)
                            doc_content = DocxDocument(docx_file)

                            # Absätze extrahieren
                            full_text = []
                            for para in doc_content.paragraphs:
                                if para.text.strip():
                                    # Überschriften hervorheben
                                    if para.style and para.style.name.startswith('Heading'):
                                        full_text.append(f"\n### {para.text}\n")
                                    else:
                                        full_text.append(para.text)

                            # Tabellen extrahieren
                            if doc_content.tables:
                                full_text.append("\n---\n**Tabellen:**\n")
                                for table in doc_content.tables:
                                    table_data = []
                                    for row in table.rows:
                                        row_data = [cell.text.strip() for cell in row.cells]
                                        table_data.append(" | ".join(row_data))
                                    full_text.append("\n".join(table_data))
                                    full_text.append("\n")

                            text_content = "\n".join(full_text)
                            st.markdown(text_content)
                        except ImportError:
                            st.warning("python-docx nicht installiert. Bitte installieren: pip install python-docx")
                        except Exception as word_err:
                            st.warning(f"Word-Vorschau nicht möglich: {word_err}")

                    # Ältere .doc Dateien
                    elif filename_lower.endswith(".doc"):
                        st.info("📄 Älteres Word-Format (.doc) - Bitte herunterladen und in Word öffnen")
                        if doc_data.get('ocr_text'):
                            with st.expander("OCR-Text anzeigen"):
                                st.text_area("OCR-Text", doc_data['ocr_text'], height=300, disabled=True)

                    # Bild-Vorschau
                    elif mime_type.startswith('image/') or filename_lower.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
                        from PIL import Image
                        img = Image.open(io.BytesIO(file_data))
                        st.image(img, width="stretch")

                    # Textdateien
                    elif mime_type.startswith("text/") or filename_lower.endswith((".txt", ".csv", ".json", ".xml")):
                        try:
                            text_content = file_data.decode('utf-8')
                            if filename_lower.endswith('.csv'):
                                import pandas as pd
                                df = pd.read_csv(io.StringIO(text_content))
                                st.dataframe(df, width="stretch", height=500)
                            else:
                                st.code(text_content, language=None)
                        except:
                            st.warning("Textdatei konnte nicht dekodiert werden")

                    else:
                        st.info(f"📄 Vorschau für {mime_type or 'unbekanntes Format'} nicht verfügbar.")

                    # Download-Button
                    st.download_button(
                        "⬇️ Herunterladen",
                        data=file_data,
                        file_name=doc_data['filename'],
                        mime=doc_data['mime_type'] or "application/octet-stream",
                        key="download_preview"
                    )

            except Exception as e:
                st.error(f"Fehler beim Laden: {e}")
        else:
            st.warning("Dokument-Datei nicht gefunden")

        # OCR-Text
        st.markdown("---")
        st.markdown("### 📝 Erkannter Text (OCR)")
        if doc_data['ocr_text']:
            with st.expander("OCR-Text anzeigen", expanded=False):
                st.text_area("OCR-Text", doc_data['ocr_text'], height=400, disabled=True, key="ocr_preview")
        else:
            st.info("Kein OCR-Text verfügbar")

    with tab_metadata:
        # === DOKUMENTZUSAMMENFASSUNG ===
        st.markdown("### 📋 Zusammenfassung")

        # AI-Zusammenfassung anzeigen (falls vorhanden)
        if doc_data.get('ai_summary'):
            st.info(doc_data['ai_summary'])
        else:
            st.caption("Keine KI-Zusammenfassung verfügbar")

        # Dokumenttyp-spezifische Informationen
        category = doc_data.get('category', '').lower() if doc_data.get('category') else ''
        extended_meta = doc_data.get('extended_metadata') or {}

        # Versicherung-spezifische Anzeige
        if 'versicherung' in category or category == 'insurance':
            with st.container():
                st.markdown("#### 🛡️ Versicherungsdetails")
                vers_col1, vers_col2 = st.columns(2)

                with vers_col1:
                    if doc_data.get('insurance_number'):
                        st.write(f"**Versicherungsnr.:** {doc_data['insurance_number']}")
                    if doc_data.get('contract_start'):
                        st.write(f"**Vertragsbeginn:** {format_date(doc_data['contract_start'])}")
                    if doc_data.get('contract_end'):
                        st.write(f"**Vertragsende:** {format_date(doc_data['contract_end'])}")
                        # Restlaufzeit berechnen
                        from datetime import datetime
                        if isinstance(doc_data['contract_end'], datetime):
                            remaining = (doc_data['contract_end'] - datetime.now()).days
                            if remaining > 0:
                                years = remaining // 365
                                months = (remaining % 365) // 30
                                st.write(f"**Restlaufzeit:** {years} Jahre, {months} Monate")
                            else:
                                st.warning("⚠️ Vertrag abgelaufen")
                    if doc_data.get('contract_notice_period'):
                        st.write(f"**Kündigungsfrist:** {doc_data['contract_notice_period']} Tage")

                with vers_col2:
                    # Erweiterte Metadaten für Versicherungen
                    if extended_meta.get('monthly_rate'):
                        st.write(f"**Monatsbeitrag:** {format_currency(extended_meta['monthly_rate'])}")
                    if extended_meta.get('remaining_payments'):
                        st.write(f"**Verbleibende Raten:** {extended_meta['remaining_payments']}")
                    if extended_meta.get('payout_amount'):
                        st.write(f"**Auszahlungsbetrag:** {format_currency(extended_meta['payout_amount'])}")
                    if extended_meta.get('payout_date'):
                        st.write(f"**Auszahlungsdatum:** {extended_meta['payout_date']}")
                    if extended_meta.get('surrender_value'):
                        st.write(f"**Rückkaufswert:** {format_currency(extended_meta['surrender_value'])}")
                    if extended_meta.get('payout_conditions'):
                        st.write(f"**Auszahlungsbedingungen:** {extended_meta['payout_conditions']}")

        # Vertrag-spezifische Anzeige
        elif 'vertrag' in category or category == 'contract':
            with st.container():
                st.markdown("#### 📝 Vertragsdetails")
                vert_col1, vert_col2 = st.columns(2)

                with vert_col1:
                    if doc_data.get('contract_number'):
                        st.write(f"**Vertragsnr.:** {doc_data['contract_number']}")
                    if doc_data.get('contract_start'):
                        st.write(f"**Vertragsbeginn:** {format_date(doc_data['contract_start'])}")
                    if doc_data.get('contract_end'):
                        st.write(f"**Vertragsende:** {format_date(doc_data['contract_end'])}")
                    if doc_data.get('contract_notice_period'):
                        st.write(f"**Kündigungsfrist:** {doc_data['contract_notice_period']} Tage")

                with vert_col2:
                    if extended_meta.get('renewal_type'):
                        st.write(f"**Verlängerungsart:** {extended_meta['renewal_type']}")
                    if extended_meta.get('minimum_term'):
                        st.write(f"**Mindestlaufzeit:** {extended_meta['minimum_term']}")
                    if extended_meta.get('monthly_cost'):
                        st.write(f"**Monatliche Kosten:** {format_currency(extended_meta['monthly_cost'])}")

        # Kredit/Darlehen-spezifische Anzeige
        elif 'kredit' in category or 'darlehen' in category or category == 'loan':
            with st.container():
                st.markdown("#### 💳 Kreditdetails")
                kred_col1, kred_col2 = st.columns(2)

                with kred_col1:
                    if extended_meta.get('loan_amount'):
                        st.write(f"**Darlehenssumme:** {format_currency(extended_meta['loan_amount'])}")
                    if extended_meta.get('interest_rate'):
                        st.write(f"**Zinssatz:** {extended_meta['interest_rate']}%")
                    if extended_meta.get('remaining_debt'):
                        st.write(f"**Restschuld:** {format_currency(extended_meta['remaining_debt'])}")

                with kred_col2:
                    if extended_meta.get('monthly_rate'):
                        st.write(f"**Monatliche Rate:** {format_currency(extended_meta['monthly_rate'])}")
                    if extended_meta.get('remaining_payments'):
                        st.write(f"**Verbleibende Raten:** {extended_meta['remaining_payments']}")
                    if extended_meta.get('end_date'):
                        st.write(f"**Laufzeitende:** {extended_meta['end_date']}")

        st.markdown("---")

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
                    doc = session.get(Document, doc_id)
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

        # Vorlesen-Funktion
        st.markdown("**🔊 Vorlesen**")

        from services.tts_service import get_tts_service, TTSService
        from config.settings import get_settings
        tts_settings = get_settings()

        tts_col1, tts_col2 = st.columns([2, 1])

        with tts_col1:
            tts_voice = st.selectbox(
                "Stimme",
                options=list(TTSService.VOICES.keys()),
                format_func=lambda x: TTSService.VOICES.get(x, x),
                index=list(TTSService.VOICES.keys()).index(tts_settings.tts_voice) if tts_settings.tts_voice in TTSService.VOICES else 4,
                key="tts_voice_select"
            )

        with tts_col2:
            tts_speed = st.slider("Tempo", 0.5, 2.0, tts_settings.tts_speed, 0.1, key="tts_speed_select")

        if st.button("🔊 Dokument vorlesen", width="stretch", type="primary"):
            if not tts_settings.openai_api_key:
                if tts_settings.tts_use_browser:
                    # Browser-TTS als Fallback
                    text_to_read = doc_data.get('ai_summary') or doc_data.get('ocr_text') or doc_data.get('subject') or "Kein Text verfügbar"
                    tts_service = get_tts_service()
                    st.markdown(tts_service.get_browser_tts_script(text_to_read[:2000]), unsafe_allow_html=True)
                else:
                    st.warning("⚠️ OpenAI API nicht konfiguriert. Aktivieren Sie Browser-TTS in Einstellungen.")
            else:
                with st.spinner("Generiere Audio..."):
                    tts_service = get_tts_service()
                    result = tts_service.read_document(doc_id, tts_voice, tts_settings.tts_model, tts_speed)

                    if result.get("error"):
                        st.error(f"❌ {result['error']}")
                    else:
                        st.audio(result["audio_bytes"], format="audio/mp3")
                        st.success("✅ Audio generiert!")

        st.markdown("---")

        col_act1, col_act2 = st.columns(2)

        with col_act1:
            # In Aktentasche
            st.markdown("**📋 Aktentasche**")
            if st.button("📋 In Aktentasche legen", width="stretch"):
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
                if st.button("📂 Verschieben", width="stretch"):
                    with get_db() as session:
                        doc = session.get(Document, doc_id)
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
                if st.button("📄 Kopieren", width="stretch"):
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
            doc = session.get(Document, doc_id)
            current_folder_name = ""
            doc_title = ""
            if doc:
                doc_title = doc.title or doc.filename
                if doc.folder_id:
                    current_folder = session.get(Folder, doc.folder_id)
                    if current_folder:
                        current_folder_name = current_folder.name

            st.info(f"📄 **{doc_title}** | Aktueller Ordner: **{current_folder_name or 'Kein Ordner'}**")

            # Intelligente Ordnervorschläge
            classifier = get_classifier(user_id)
            suggestions = classifier.suggest_folders_for_document(doc_id, limit=5)

            if suggestions:
                st.markdown("### 💡 Empfohlene Ordner")
                for i, suggestion in enumerate(suggestions):
                    col_sug, col_btn = st.columns([4, 1])
                    with col_sug:
                        confidence_bar = "🟢" if suggestion['confidence'] > 0.7 else "🟡" if suggestion['confidence'] > 0.4 else "⚪"
                        st.markdown(f"{confidence_bar} **{suggestion['folder_name']}**")
                        st.caption(suggestion['reason'])
                    with col_btn:
                        if st.button("Hierhin", key=f"suggest_{i}_{suggestion['folder_id']}"):
                            with get_db() as move_session:
                                move_doc = move_session.get(Document, doc_id)
                                if move_doc:
                                    move_doc.folder_id = suggestion['folder_id']
                                    move_session.commit()
                                    classifier.learn_from_move(doc_id, suggestion['folder_id'])
                                    st.toast(f"✅ Verschoben nach '{suggestion['folder_name']}'!")
                                    del st.session_state.move_document_id
                                    st.rerun()

                st.divider()

            st.markdown("### 📂 Oder Ordner manuell wählen")

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
                    with get_db() as move_session:
                        move_doc = move_session.get(Document, doc_id)
                        if move_doc:
                            move_doc.folder_id = target_folder
                            move_session.commit()

                            # Klassifikator lernen lassen
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

        # Prüfen ob Dokument bereits im Papierkorb ist
        with get_db() as session:
            doc = session.get(Document, doc_id)
            is_already_deleted = doc.is_deleted if doc else False
            doc_title = doc.title or doc.filename if doc else "Dokument"

        if is_already_deleted:
            # Im Papierkorb: Endgültig löschen oder wiederherstellen
            st.warning(f"⚠️ '{doc_title}' ist im Papierkorb. Was möchten Sie tun?")

            col1, col2, col3 = st.columns(3)
            with col1:
                if st.button("♻️ Wiederherstellen", type="primary"):
                    from services.trash_service import get_trash_service
                    trash_service = get_trash_service()
                    result = trash_service.restore_from_trash(doc_id, user_id)
                    if result["success"]:
                        st.success(result["message"])
                    else:
                        st.error(result["error"])
                    del st.session_state.delete_document_id
                    st.rerun()
            with col2:
                if st.button("🗑️ Endgültig löschen"):
                    st.session_state.confirm_permanent_delete = doc_id
            with col3:
                if st.button("❌ Abbrechen"):
                    del st.session_state.delete_document_id
                    st.rerun()

            # Bestätigung für endgültiges Löschen
            if st.session_state.get('confirm_permanent_delete') == doc_id:
                st.error("⚠️ Das Dokument wird ENDGÜLTIG gelöscht und kann nicht wiederhergestellt werden!")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("✅ Ja, endgültig löschen", key="confirm_perm_del"):
                        from services.trash_service import get_trash_service
                        trash_service = get_trash_service()
                        result = trash_service.permanent_delete(doc_id, user_id)
                        if result["success"]:
                            st.success(result["message"])
                        else:
                            st.error(result["error"])
                        del st.session_state.delete_document_id
                        if 'confirm_permanent_delete' in st.session_state:
                            del st.session_state.confirm_permanent_delete
                        st.rerun()
                with c2:
                    if st.button("❌ Doch nicht", key="cancel_perm_del"):
                        del st.session_state.confirm_permanent_delete
                        st.rerun()
        else:
            # Normales Löschen: In Papierkorb verschieben
            from services.trash_service import get_trash_service
            from config.settings import get_settings
            settings = get_settings()

            st.warning(f"⚠️ '{doc_title}' in den Papierkorb verschieben?")
            st.info(f"💡 Das Dokument kann innerhalb von {settings.trash_retention_hours} Stunden wiederhergestellt werden.")

            col1, col2 = st.columns(2)
            with col1:
                if st.button("🗑️ In Papierkorb", type="primary"):
                    trash_service = get_trash_service()
                    result = trash_service.move_to_trash(doc_id, user_id)
                    if result["success"]:
                        st.success(result["message"])
                    else:
                        st.error(result.get("error", "Fehler beim Löschen"))
                    del st.session_state.delete_document_id
                    st.rerun()
            with col2:
                if st.button("Abbrechen"):
                    del st.session_state.delete_document_id
                    st.rerun()
