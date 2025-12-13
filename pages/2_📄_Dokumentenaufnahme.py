"""
Dokumentenaufnahme - Upload, Scan und Verarbeitung von Dokumenten
"""
import streamlit as st
import io
import hashlib
from pathlib import Path
import sys
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.db import init_db, get_db, get_current_user_id
from database.models import Document, Folder, DocumentStatus, CalendarEvent, EventType, InvoiceStatus
from config.settings import DOCUMENTS_DIR, DOCUMENT_CATEGORIES
from services.encryption import get_encryption_service
from services.ocr import get_ocr_service
from services.ai_service import get_ai_service
from services.document_classifier import get_classifier
from services.search_service import get_search_service
from utils.pdf_utils import get_pdf_processor
from utils.helpers import format_currency, format_date, sanitize_filename
from utils.components import render_sidebar_cart

st.set_page_config(page_title="Dokumentenaufnahme", page_icon="📄", layout="wide")
init_db()

# Sidebar mit Aktentasche
render_sidebar_cart()

st.title("📄 Dokumentenaufnahme")
st.markdown("Laden Sie Dokumente hoch oder scannen Sie sie ein")


def calculate_content_hash(file_data: bytes) -> str:
    """Berechnet SHA-256 Hash des Dateiinhalts"""
    return hashlib.sha256(file_data).hexdigest()


def check_for_duplicate(file_data: bytes, user_id: int) -> dict | None:
    """
    Prüft ob ein Dokument mit gleichem Inhalt bereits existiert.

    Returns:
        Dict mit Duplikat-Info oder None wenn kein Duplikat
    """
    content_hash = calculate_content_hash(file_data)

    with get_db() as session:
        existing = session.query(Document).filter(
            Document.user_id == user_id,
            Document.content_hash == content_hash
        ).first()

        if existing:
            # Ordnerinfo laden
            folder_name = "Kein Ordner"
            folder_path = ""
            if existing.folder_id:
                folder = session.query(Folder).get(existing.folder_id)
                if folder:
                    folder_name = folder.name
                    # Pfad aufbauen
                    path_parts = [folder.name]
                    parent = folder.parent_id
                    while parent:
                        parent_folder = session.query(Folder).get(parent)
                        if parent_folder:
                            path_parts.insert(0, parent_folder.name)
                            parent = parent_folder.parent_id
                        else:
                            break
                    folder_path = " / ".join(path_parts)

            return {
                'id': existing.id,
                'filename': existing.filename,
                'title': existing.title or existing.filename,
                'sender': existing.sender,
                'category': existing.category,
                'document_date': existing.document_date,
                'created_at': existing.created_at,
                'folder_id': existing.folder_id,
                'folder_name': folder_name,
                'folder_path': folder_path,
                'file_path': existing.file_path,
                'content_hash': content_hash
            }

    return None


def render_duplicate_comparison(new_file_data: bytes, new_filename: str, existing_doc: dict, user_id: int):
    """Zeigt Vergleichsansicht für Duplikate"""
    st.warning("⚠️ **Mögliches Duplikat erkannt!**")
    st.info(f"Ein Dokument mit identischem Inhalt existiert bereits in: **{existing_doc['folder_path']}**")

    col_new, col_existing = st.columns(2)

    with col_new:
        st.markdown("### 📄 Neues Dokument")
        st.write(f"**Dateiname:** {new_filename}")
        st.write(f"**Größe:** {len(new_file_data) / 1024:.1f} KB")

        # Vorschau für neues Dokument
        if new_filename.lower().endswith('.pdf'):
            try:
                from pdf2image import convert_from_bytes
                images = convert_from_bytes(new_file_data, first_page=1, last_page=1, dpi=100)
                if images:
                    st.image(images[0], caption="Vorschau (Seite 1)", use_container_width=True)
            except Exception:
                st.info("PDF-Vorschau nicht verfügbar")
        else:
            st.image(new_file_data, caption="Vorschau", use_container_width=True)

    with col_existing:
        st.markdown("### 📁 Bestehendes Dokument")
        st.write(f"**Dateiname:** {existing_doc['filename']}")
        st.write(f"**Titel:** {existing_doc['title'] or '—'}")
        st.write(f"**Absender:** {existing_doc['sender'] or '—'}")
        st.write(f"**Kategorie:** {existing_doc['category'] or '—'}")
        st.write(f"**Datum:** {format_date(existing_doc['document_date'])}")
        st.write(f"**Hochgeladen:** {format_date(existing_doc['created_at'])}")
        st.write(f"**📁 Ordner:** {existing_doc['folder_path']}")

        # Vorschau für bestehendes Dokument laden
        if existing_doc['file_path']:
            try:
                encryption = get_encryption_service()
                with open(existing_doc['file_path'], 'rb') as f:
                    encrypted_data = f.read()

                with get_db() as session:
                    doc = session.query(Document).get(existing_doc['id'])
                    if doc and doc.encryption_iv:
                        decrypted_data = encryption.decrypt_file(encrypted_data, doc.encryption_iv)

                        if existing_doc['filename'].lower().endswith('.pdf'):
                            try:
                                from pdf2image import convert_from_bytes
                                images = convert_from_bytes(decrypted_data, first_page=1, last_page=1, dpi=100)
                                if images:
                                    st.image(images[0], caption="Vorschau (Seite 1)", use_container_width=True)
                            except Exception:
                                st.info("PDF-Vorschau nicht verfügbar")
                        else:
                            st.image(decrypted_data, caption="Vorschau", use_container_width=True)
            except Exception as e:
                st.info(f"Vorschau nicht verfügbar: {e}")

    st.divider()

    # Aktionen
    st.markdown("### Was möchten Sie tun?")
    col_action1, col_action2, col_action3 = st.columns(3)

    with col_action1:
        if st.button("🚫 Nicht hochladen", use_container_width=True, help="Abbrechen, bestehendes Dokument behalten"):
            if 'duplicate_check' in st.session_state:
                del st.session_state.duplicate_check
            st.rerun()

    with col_action2:
        if st.button("📂 Zum bestehenden Dokument", use_container_width=True, help="Bestehendes Dokument öffnen"):
            st.session_state.current_folder_id = existing_doc['folder_id']
            if 'duplicate_check' in st.session_state:
                del st.session_state.duplicate_check
            st.switch_page("pages/3_📁_Dokumente.py")

    with col_action3:
        if st.button("✅ Trotzdem hochladen", type="primary", use_container_width=True, help="Als neues Dokument speichern"):
            st.session_state.force_upload = True
            if 'duplicate_check' in st.session_state:
                del st.session_state.duplicate_check
            st.rerun()


# Tabs für verschiedene Upload-Optionen
tab_upload, tab_multi, tab_process = st.tabs(["📤 Einzelupload", "📑 Mehrere Dokumente", "⚙️ Verarbeitung"])


def save_document(file_data: bytes, filename: str, user_id: int) -> Document:
    """Speichert ein Dokument verschlüsselt und erstellt DB-Eintrag"""
    encryption = get_encryption_service()

    # Content-Hash berechnen
    content_hash = calculate_content_hash(file_data)

    # Datei verschlüsseln
    encrypted_data, nonce = encryption.encrypt_file(file_data, filename)

    # Sicheren Dateinamen generieren
    safe_filename = sanitize_filename(filename)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stored_filename = f"{timestamp}_{safe_filename}.enc"
    file_path = DOCUMENTS_DIR / stored_filename

    # Verschlüsselte Datei speichern
    with open(file_path, 'wb') as f:
        f.write(encrypted_data)

    # Mime-Type bestimmen
    mime_type = "application/pdf" if filename.lower().endswith('.pdf') else "image/jpeg"
    if filename.lower().endswith('.png'):
        mime_type = "image/png"

    # Posteingang-Ordner finden
    with get_db() as session:
        inbox = session.query(Folder).filter(
            Folder.user_id == user_id,
            Folder.name == "Posteingang"
        ).first()

        # Dokument in DB erstellen
        document = Document(
            user_id=user_id,
            folder_id=inbox.id if inbox else None,
            filename=filename,
            file_path=str(file_path),
            file_size=len(file_data),
            mime_type=mime_type,
            is_encrypted=True,
            encryption_iv=nonce,
            content_hash=content_hash,
            status=DocumentStatus.PENDING
        )
        session.add(document)
        session.commit()

        return document.id


def process_document(document_id: int, file_data: bytes, user_id: int) -> dict:
    """Verarbeitet ein Dokument mit OCR und KI. Gibt Info über zugewiesenen Ordner zurück."""
    ocr = get_ocr_service()
    ai = get_ai_service()
    classifier = get_classifier(user_id)
    search = get_search_service(user_id)

    result = {'folder_name': None, 'folder_created': False, 'sender': None}

    with get_db() as session:
        document = session.query(Document).get(document_id)
        if not document:
            return result

        document.status = DocumentStatus.PROCESSING
        session.commit()

        try:
            # OCR durchführen
            full_text = ""
            confidence = 0.0

            if document.mime_type == "application/pdf":
                results = ocr.extract_text_from_pdf(file_data)
                if results:
                    full_text = "\n\n".join(text for text, _ in results)
                    confidence = sum(conf for _, conf in results) / len(results)
            else:
                # Bild
                from PIL import Image
                image = Image.open(io.BytesIO(file_data))
                full_text, confidence = ocr.extract_text_from_image(image)

            document.ocr_text = full_text
            document.ocr_confidence = confidence

            # Metadaten extrahieren
            metadata = ocr.extract_metadata(full_text)

            # Daten zuweisen
            if metadata.get('dates'):
                document.document_date = metadata['dates'][0]

            if metadata.get('amounts'):
                document.invoice_amount = max(metadata['amounts'])

            if metadata.get('ibans'):
                document.iban = metadata['ibans'][0]

            if metadata.get('contract_numbers'):
                document.contract_number = metadata['contract_numbers'][0]

            # KI-basierte Klassifikation (wenn verfügbar)
            if ai.any_ai_available:
                try:
                    structured_data = ai.extract_structured_data(full_text)

                    # Absender-Informationen
                    if structured_data.get('sender'):
                        document.sender = structured_data['sender']
                        result['sender'] = structured_data['sender']
                    if structured_data.get('sender_address'):
                        document.sender_address = structured_data['sender_address']

                    # Betreff und Kategorie
                    if structured_data.get('subject'):
                        document.subject = structured_data['subject']
                        document.title = structured_data['subject']
                    if structured_data.get('category'):
                        document.category = structured_data['category']

                    # Zusammenfassung
                    if structured_data.get('summary'):
                        document.ai_summary = structured_data['summary']

                    # Referenznummern
                    if structured_data.get('reference_number'):
                        document.reference_number = structured_data['reference_number']
                    if structured_data.get('customer_number'):
                        document.customer_number = structured_data['customer_number']
                    if structured_data.get('insurance_number'):
                        document.insurance_number = structured_data['insurance_number']
                    if structured_data.get('processing_number'):
                        document.processing_number = structured_data['processing_number']
                    if structured_data.get('contract_number') and not document.contract_number:
                        document.contract_number = structured_data['contract_number']

                    # Rechnungsnummer
                    if structured_data.get('invoice_number'):
                        document.invoice_number = structured_data['invoice_number']

                    # Finanzinformationen
                    if structured_data.get('invoice_amount'):
                        document.invoice_amount = float(structured_data['invoice_amount'])
                    if structured_data.get('invoice_due_date'):
                        from utils.helpers import parse_date_string
                        due_date = parse_date_string(structured_data['invoice_due_date'])
                        if due_date:
                            document.invoice_due_date = due_date
                    if structured_data.get('iban') and not document.iban:
                        document.iban = structured_data['iban']
                    if structured_data.get('bic'):
                        document.bic = structured_data['bic']
                    if structured_data.get('bank_name'):
                        document.bank_name = structured_data['bank_name']

                    # Automatische Rechnungserkennung - als OFFEN markieren
                    is_invoice = structured_data.get('is_invoice', False)
                    if is_invoice or structured_data.get('category') in ['Rechnung', 'Mahnung']:
                        if document.invoice_amount and document.invoice_amount > 0:
                            document.invoice_status = InvoiceStatus.OPEN

                except Exception as e:
                    st.warning(f"KI-Analyse teilweise fehlgeschlagen: {e}")

            # Selbstlernende Klassifikation
            folder_id, category, conf = classifier.classify(full_text, metadata)

            if not document.category and category:
                document.category = category

            # Ordnerzuweisung mit Sender-Fallback
            assigned_folder_name = None
            folder_created = False

            # Prüfen ob ein intelligenter Ordner gefunden wurde (nicht nur Posteingang)
            if folder_id:
                folder = session.query(Folder).get(folder_id)
                if folder and folder.name != 'Posteingang':
                    # Intelligenter Ordner gefunden
                    document.folder_id = folder_id
                    assigned_folder_name = folder.name
                else:
                    folder_id = None  # Posteingang zählt nicht als "gefunden"

            # Wenn kein passender Ordner gefunden, Ordner nach Absender erstellen
            if not folder_id and document.sender:
                sender_name = document.sender.strip()
                if sender_name:
                    # Prüfen ob Absender-Ordner bereits existiert
                    existing_folder = session.query(Folder).filter(
                        Folder.user_id == user_id,
                        Folder.name == sender_name
                    ).first()

                    if existing_folder:
                        document.folder_id = existing_folder.id
                        assigned_folder_name = existing_folder.name
                    else:
                        # Neuen Ordner nach Absender erstellen
                        new_folder = Folder(
                            user_id=user_id,
                            name=sender_name,
                            description=f"Automatisch erstellt für Dokumente von {sender_name}",
                            color="#607D8B"  # Grau-Blau für auto-erstellte Ordner
                        )
                        session.add(new_folder)
                        session.flush()  # ID generieren
                        document.folder_id = new_folder.id
                        assigned_folder_name = sender_name
                        folder_created = True

            result['folder_name'] = assigned_folder_name
            result['folder_created'] = folder_created

            # Fristen erkennen und Kalendereintrag erstellen
            for deadline in metadata.get('deadlines', []):
                deadline_date = None
                # Versuche Datum zu parsen
                from utils.helpers import parse_german_date
                deadline_date = parse_german_date(deadline['date_str'])

                if deadline_date:
                    event = CalendarEvent(
                        user_id=user_id,
                        document_id=document.id,
                        title=f"Frist: {document.title or document.filename}",
                        description=f"Automatisch erkannte Frist aus Dokument",
                        event_type=EventType.DEADLINE,
                        start_date=deadline_date,
                        all_day=True
                    )
                    session.add(event)

            # Suchindex aktualisieren
            search.index_document(document.id, {
                'title': document.title or document.filename,
                'content': full_text,
                'sender': document.sender or '',
                'category': document.category or '',
                'folder_id': document.folder_id,
                'document_date': document.document_date,
                'amounts': metadata.get('amounts', []),
                'ibans': metadata.get('ibans', []),
                'contract_numbers': metadata.get('contract_numbers', []),
                'created_at': document.created_at
            })

            document.status = DocumentStatus.COMPLETED
            session.commit()

            return result

        except Exception as e:
            document.status = DocumentStatus.ERROR
            document.processing_error = str(e)
            session.commit()
            raise

    return result


with tab_upload:
    st.subheader("Einzelnes Dokument hochladen")

    uploaded_file = st.file_uploader(
        "PDF oder Bild auswählen",
        type=['pdf', 'jpg', 'jpeg', 'png'],
        help="Unterstützte Formate: PDF, JPG, PNG"
    )

    if uploaded_file:
        file_data = uploaded_file.read()
        uploaded_file.seek(0)  # Reset für spätere Verwendung

        # Prüfe auf Duplikat (außer bei force_upload)
        user_id = get_current_user_id()
        force_upload = st.session_state.get('force_upload', False)

        if not force_upload:
            duplicate = check_for_duplicate(file_data, user_id)
            if duplicate:
                render_duplicate_comparison(file_data, uploaded_file.name, duplicate, user_id)
                st.stop()  # Stoppe hier, zeige nur Duplikat-Vergleich

        # Kein Duplikat oder force_upload - normale Ansicht
        if force_upload:
            st.info("📄 Dokument wird trotz Duplikat hochgeladen...")
            st.session_state.force_upload = False  # Reset

        st.success(f"Datei: {uploaded_file.name} ({uploaded_file.size / 1024:.1f} KB)")

        # Vorschau
        if uploaded_file.type == "application/pdf":
            st.info("PDF-Vorschau wird nach Verarbeitung verfügbar")
        else:
            st.image(uploaded_file, width=400, caption="Vorschau")

        col1, col2 = st.columns(2)

        with col1:
            process_now = st.checkbox("Sofort verarbeiten (OCR & KI)", value=True)

        with col2:
            if st.button("📥 Hochladen", type="primary"):
                with st.spinner("Speichere Dokument..."):
                    doc_id = save_document(file_data, uploaded_file.name, user_id)

                if process_now:
                    with st.spinner("Verarbeite Dokument (OCR & Analyse)..."):
                        try:
                            process_result = process_document(doc_id, file_data, user_id)
                            st.success("Dokument erfolgreich verarbeitet!")

                            # Ordnerzuweisung anzeigen
                            if process_result.get('folder_name'):
                                if process_result.get('folder_created'):
                                    st.info(f"📁 **Neuer Ordner erstellt:** '{process_result['folder_name']}' (nach Absender)")
                                else:
                                    st.info(f"📁 **Eingeordnet in:** '{process_result['folder_name']}'")
                            else:
                                st.warning("📁 Kein passender Ordner gefunden. Dokument bleibt im Posteingang.")

                            # Ergebnisse anzeigen
                            with get_db() as session:
                                doc = session.query(Document).get(doc_id)
                                if doc:
                                    st.markdown("---")
                                    st.markdown("## 📋 Extrahierte Dokumentdaten")

                                    # Zusammenfassung (wenn vorhanden)
                                    if doc.ai_summary:
                                        st.info(f"**Zusammenfassung:** {doc.ai_summary}")

                                    # Drei-Spalten-Layout für Metadaten
                                    col_sender, col_refs, col_finance = st.columns(3)

                                    with col_sender:
                                        st.markdown("### 📤 Absender")
                                        st.write(f"**Name:** {doc.sender or '—'}")
                                        if doc.sender_address:
                                            st.write(f"**Adresse:** {doc.sender_address}")
                                        st.write(f"**Kategorie:** {doc.category or '—'}")
                                        st.write(f"**Datum:** {format_date(doc.document_date)}")

                                    with col_refs:
                                        st.markdown("### 🔢 Referenznummern")
                                        if doc.reference_number:
                                            st.write(f"**Aktenzeichen:** {doc.reference_number}")
                                        if doc.customer_number:
                                            st.write(f"**Kundennummer:** {doc.customer_number}")
                                        if getattr(doc, 'invoice_number', None):
                                            st.write(f"**Rechnungsnr:** {doc.invoice_number}")
                                        if doc.insurance_number:
                                            st.write(f"**Vers.-Nr:** {doc.insurance_number}")
                                        if doc.processing_number:
                                            st.write(f"**Bearbeitungsnr:** {doc.processing_number}")
                                        if doc.contract_number:
                                            st.write(f"**Vertragsnr:** {doc.contract_number}")
                                        if not any([doc.reference_number, doc.customer_number,
                                                   getattr(doc, 'invoice_number', None),
                                                   doc.insurance_number, doc.processing_number,
                                                   doc.contract_number]):
                                            st.write("—")

                                    with col_finance:
                                        st.markdown("### 💰 Finanzdaten")
                                        # Rechnungsstatus anzeigen
                                        if doc.invoice_status == InvoiceStatus.OPEN:
                                            st.error("🔴 Rechnung OFFEN")
                                        if doc.invoice_amount:
                                            st.write(f"**Betrag:** {format_currency(doc.invoice_amount)}")
                                        if doc.invoice_due_date:
                                            st.write(f"**Fällig bis:** {format_date(doc.invoice_due_date)}")
                                        if doc.iban:
                                            st.write(f"**IBAN:** {doc.iban}")
                                        if doc.bic:
                                            st.write(f"**BIC:** {doc.bic}")
                                        if getattr(doc, 'bank_name', None):
                                            st.write(f"**Bank:** {doc.bank_name}")
                                        if not any([doc.invoice_amount, doc.iban]):
                                            st.write("—")

                                    # Link zum Dokument
                                    st.markdown("---")
                                    if st.button("📂 Dokument in Ordner öffnen"):
                                        st.session_state.view_document_id = doc_id
                                        st.switch_page("pages/3_📁_Dokumente.py")
                        except Exception as e:
                            st.error(f"Verarbeitungsfehler: {e}")
                else:
                    st.success("Dokument gespeichert! Kann später verarbeitet werden.")


with tab_multi:
    st.subheader("Mehrere Dokumente in einer PDF")
    st.markdown("""
    Laden Sie eine PDF mit mehreren Dokumenten hoch. Die App erkennt automatisch:
    - **Trennseiten** (weiße Seite mit dem Wort "Trennseite")
    - **Layoutwechsel** (unterschiedliche Dokumenttypen)
    """)

    multi_file = st.file_uploader(
        "PDF mit mehreren Dokumenten",
        type=['pdf'],
        key="multi_upload",
        help="PDF mit mehreren gescannten Dokumenten"
    )

    if multi_file:
        pdf_processor = get_pdf_processor()
        file_data = multi_file.read()

        page_count = pdf_processor.get_page_count(file_data)
        st.info(f"PDF enthält {page_count} Seiten")

        col1, col2 = st.columns(2)

        with col1:
            auto_detect = st.checkbox("Automatische Dokumenttrennung", value=True)

        with col2:
            manual_pages = st.text_input(
                "Manuelle Seitenbereiche (z.B. 1-3,4-6,7-10)",
                disabled=auto_detect,
                help="Kommagetrennte Seitenbereiche"
            )

        if st.button("📑 Dokumente trennen und verarbeiten", type="primary"):
            user_id = get_current_user_id()

            with st.spinner("Analysiere PDF..."):
                if auto_detect:
                    # Neue text-basierte Erkennung mit automatischer Trennseiten-Entfernung
                    boundaries, separator_pages = pdf_processor.detect_document_boundaries(file_data)

                    if separator_pages:
                        st.info(f"🔍 {len(separator_pages)} Trennseite(n) erkannt auf Seite(n): {[s+1 for s in separator_pages]}")
                        st.write(f"Dokumentgrenzen: Seiten {[b+1 for b in boundaries]}")
                    else:
                        st.write(f"Erkannte Dokumentgrenzen: Seiten {[b+1 for b in boundaries]}")

                    # Automatisch trennen und Trennseiten entfernen
                    split_pdfs = pdf_processor.split_and_remove_separators(file_data)
                else:
                    # Manuelle Bereiche parsen
                    page_ranges = []
                    for range_str in manual_pages.split(','):
                        if '-' in range_str:
                            start, end = range_str.strip().split('-')
                            page_ranges.append((int(start) - 1, int(end)))
                        else:
                            page_ranges.append((int(range_str.strip()) - 1, int(range_str.strip())))

                    split_pdfs = pdf_processor.split_pdf(file_data, page_ranges)

            st.write(f"Trenne in {len(split_pdfs)} Dokumente...")

            # Jedes Teildokument verarbeiten
            progress = st.progress(0)
            processed_docs = []

            for i, pdf_data in enumerate(split_pdfs):
                progress.progress((i + 1) / len(split_pdfs))
                filename = f"{multi_file.name.rsplit('.', 1)[0]}_Teil{i+1}.pdf"

                with st.spinner(f"Verarbeite Dokument {i+1}/{len(split_pdfs)}..."):
                    doc_id = save_document(pdf_data, filename, user_id)
                    try:
                        result = process_document(doc_id, pdf_data, user_id)
                        folder_info = ""
                        if result.get('folder_name'):
                            if result.get('folder_created'):
                                folder_info = f" → 📁 Neuer Ordner: '{result['folder_name']}'"
                            else:
                                folder_info = f" → 📁 '{result['folder_name']}'"
                        else:
                            folder_info = " → 📁 Posteingang"
                        st.success(f"✓ Dokument {i+1} verarbeitet{folder_info}")
                        processed_docs.append({'num': i+1, 'folder': result.get('folder_name') or 'Posteingang', 'created': result.get('folder_created', False)})
                    except Exception as e:
                        st.warning(f"⚠ Dokument {i+1}: {e}")

            st.success(f"Alle {len(split_pdfs)} Dokumente wurden verarbeitet!")

            # Zusammenfassung der Ordnerzuweisungen
            if processed_docs:
                st.markdown("### 📁 Ordnerzuweisungen")
                for doc_info in processed_docs:
                    if doc_info['created']:
                        st.write(f"- Dokument {doc_info['num']}: **{doc_info['folder']}** *(neu erstellt)*")
                    else:
                        st.write(f"- Dokument {doc_info['num']}: **{doc_info['folder']}**")


with tab_process:
    st.subheader("Unverarbeitete Dokumente")

    user_id = get_current_user_id()

    with get_db() as session:
        pending_docs = session.query(Document).filter(
            Document.user_id == user_id,
            Document.status.in_([DocumentStatus.PENDING, DocumentStatus.ERROR])
        ).all()

        if pending_docs:
            st.info(f"{len(pending_docs)} Dokumente warten auf Verarbeitung")

            for doc in pending_docs:
                col1, col2, col3 = st.columns([3, 1, 1])
                with col1:
                    status_icon = "⏳" if doc.status == DocumentStatus.PENDING else "❌"
                    st.write(f"{status_icon} {doc.filename}")
                    if doc.processing_error:
                        st.caption(f"Fehler: {doc.processing_error}")
                with col2:
                    st.caption(format_date(doc.created_at))
                with col3:
                    if st.button("Verarbeiten", key=f"process_{doc.id}"):
                        # Datei entschlüsseln
                        encryption = get_encryption_service()
                        with open(doc.file_path, 'rb') as f:
                            encrypted_data = f.read()
                        file_data = encryption.decrypt_file(encrypted_data, doc.encryption_iv, doc.filename)

                        with st.spinner("Verarbeite..."):
                            try:
                                process_document(doc.id, file_data, user_id)
                                st.success("Erfolgreich!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Fehler: {e}")

            if st.button("Alle verarbeiten", type="primary"):
                progress = st.progress(0)
                for i, doc in enumerate(pending_docs):
                    progress.progress((i + 1) / len(pending_docs))
                    encryption = get_encryption_service()
                    with open(doc.file_path, 'rb') as f:
                        encrypted_data = f.read()
                    file_data = encryption.decrypt_file(encrypted_data, doc.encryption_iv, doc.filename)

                    try:
                        process_document(doc.id, file_data, user_id)
                    except:
                        pass
                st.success("Verarbeitung abgeschlossen!")
                st.rerun()
        else:
            st.success("Keine unverarbeiteten Dokumente")
