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
                folder = session.get(Folder, existing.folder_id)
                if folder:
                    folder_name = folder.name
                    # Pfad aufbauen
                    path_parts = [folder.name]
                    parent = folder.parent_id
                    while parent:
                        parent_folder = session.get(Folder, parent)
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
                    doc = session.get(Document, existing_doc['id'])
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
tab_upload, tab_multi, tab_folder, tab_cloud, tab_process = st.tabs([
    "📤 Einzelupload", "📑 Mehrere Dokumente", "📂 Ordner-Upload", "☁️ Cloud-Import", "⚙️ Verarbeitung"
])


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
        document = session.get(Document, document_id)
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
                folder = session.get(Folder, folder_id)
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
                                doc = session.get(Document, doc_id)
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


with tab_folder:
    st.subheader("📂 Ordner-Upload")
    st.markdown("Laden Sie einen kompletten Ordner mit Unterordnern hoch.")

    user_id = get_current_user_id()

    # Option 1: Lokaler Ordnerpfad
    st.markdown("### 📁 Lokalen Ordner importieren")
    st.info("💡 Geben Sie den vollständigen Pfad zu einem Ordner auf Ihrem Computer ein.")

    local_folder_path = st.text_input(
        "Ordnerpfad",
        placeholder="z.B. C:\\Users\\Name\\Documents\\Dokumente oder /home/user/Dokumente",
        help="Der vollständige Pfad zum Ordner auf Ihrem Computer"
    )

    if local_folder_path:
        from pathlib import Path as LocalPath
        import os

        folder_path_obj = LocalPath(local_folder_path)

        if folder_path_obj.exists() and folder_path_obj.is_dir():
            # Dateien im Ordner zählen (rekursiv)
            supported_ext = ['.pdf', '.jpg', '.jpeg', '.png', '.gif', '.doc', '.docx', '.xls', '.xlsx', '.txt']
            all_files = []

            for root, dirs, files in os.walk(local_folder_path):
                for file in files:
                    if any(file.lower().endswith(ext) for ext in supported_ext):
                        full_path = os.path.join(root, file)
                        rel_path = os.path.relpath(full_path, local_folder_path)
                        all_files.append({
                            'full_path': full_path,
                            'rel_path': rel_path,
                            'filename': file,
                            'folder': os.path.dirname(rel_path) if os.path.dirname(rel_path) else ""
                        })

            # Ordner zählen
            folders = set(f['folder'] for f in all_files if f['folder'])

            st.success(f"✅ **{len(all_files)} Dokumente** gefunden in **{len(folders)} Unterordnern**")

            if folders:
                with st.expander("📁 Gefundene Ordnerstruktur", expanded=False):
                    for folder in sorted(folders):
                        file_count = len([f for f in all_files if f['folder'] == folder])
                        st.write(f"📂 `{folder}` ({file_count} Dateien)")

            # Optionen
            col1, col2 = st.columns(2)
            with col1:
                preserve_local_structure = st.checkbox("Ordnerstruktur übernehmen", value=True, key="preserve_local")
            with col2:
                process_local_docs = st.checkbox("Sofort verarbeiten (OCR)", value=True, key="process_local")

            if st.button("📥 Ordner importieren", type="primary", key="import_local_folder"):
                if all_files:
                    progress_bar = st.progress(0, text="Starte Import...")
                    status_text = st.empty()

                    imported_count = 0
                    error_count = 0
                    created_folders = {}

                    for idx, file_info in enumerate(all_files):
                        progress = (idx + 1) / len(all_files)
                        progress_bar.progress(progress, text=f"Importiere {idx + 1}/{len(all_files)}...")
                        status_text.markdown(f"📄 **{file_info['filename']}**" +
                                           (f" (aus `{file_info['folder']}`)" if file_info['folder'] else ""))

                        try:
                            # Datei lesen
                            with open(file_info['full_path'], 'rb') as f:
                                file_data = f.read()

                            # Ordner erstellen wenn nötig
                            target_folder_id = None
                            if preserve_local_structure and file_info['folder']:
                                folder_key = file_info['folder']
                                if folder_key not in created_folders:
                                    with get_db() as session:
                                        parent_id = None
                                        for part in folder_key.replace('\\', '/').split('/'):
                                            if not part:
                                                continue
                                            existing = session.query(Folder).filter(
                                                Folder.user_id == user_id,
                                                Folder.name == part,
                                                Folder.parent_id == parent_id
                                            ).first()

                                            if existing:
                                                parent_id = existing.id
                                            else:
                                                new_folder = Folder(
                                                    user_id=user_id,
                                                    name=part,
                                                    parent_id=parent_id,
                                                    color="#4CAF50"
                                                )
                                                session.add(new_folder)
                                                session.flush()
                                                parent_id = new_folder.id

                                        created_folders[folder_key] = parent_id
                                        session.commit()

                                target_folder_id = created_folders.get(folder_key)

                            # Dokument speichern
                            doc_id = save_document(file_data, file_info['filename'], user_id)

                            # Ordner zuweisen
                            if target_folder_id:
                                with get_db() as session:
                                    doc = session.get(Document, doc_id)
                                    if doc:
                                        doc.folder_id = target_folder_id
                                        doc.notes = f"Importiert aus: {file_info['folder']}"
                                        session.commit()

                            # OCR verarbeiten
                            if process_local_docs:
                                try:
                                    process_document(doc_id, file_data, user_id)
                                except:
                                    pass

                            imported_count += 1

                        except Exception as e:
                            error_count += 1
                            st.warning(f"⚠️ Fehler bei {file_info['filename']}: {str(e)[:50]}")

                    progress_bar.progress(1.0, text="✅ Import abgeschlossen!")
                    status_text.empty()

                    st.success(f"✅ **{imported_count} Dokumente erfolgreich importiert!**")
                    if created_folders:
                        st.info(f"📁 **{len(created_folders)} Ordner** wurden erstellt")
                    if error_count > 0:
                        st.warning(f"⚠️ {error_count} Fehler beim Import")
                else:
                    st.warning("Keine unterstützten Dateien im Ordner gefunden.")
        else:
            st.error("❌ Ordner nicht gefunden. Bitte prüfen Sie den Pfad.")

    # Option 2: ZIP-Upload
    st.markdown("---")
    st.markdown("### 📦 ZIP-Archiv hochladen")
    st.info("💡 Alternativ: Ordner als ZIP komprimieren und hier hochladen.")

    zip_file = st.file_uploader(
        "ZIP-Datei mit Ordnerstruktur",
        type=['zip'],
        key="folder_zip_upload",
        help="ZIP-Archiv mit Dokumenten und Unterordnern"
    )

    if zip_file:
        import zipfile
        from io import BytesIO

        user_id = get_current_user_id()

        # ZIP-Inhalt analysieren
        try:
            zip_buffer = BytesIO(zip_file.read())
            with zipfile.ZipFile(zip_buffer, 'r') as zf:
                # Alle Dateien im ZIP auflisten
                all_files = [f for f in zf.namelist() if not f.endswith('/')]

                # Nur unterstützte Dateitypen
                supported_ext = ['.pdf', '.jpg', '.jpeg', '.png', '.gif', '.doc', '.docx', '.xls', '.xlsx', '.txt']
                valid_files = [f for f in all_files if any(f.lower().endswith(ext) for ext in supported_ext)]

                # Ordnerstruktur anzeigen
                folders = set()
                for f in valid_files:
                    parts = f.split('/')
                    if len(parts) > 1:
                        folders.add('/'.join(parts[:-1]))

                st.success(f"✅ ZIP-Datei erkannt: **{len(valid_files)} Dokumente** in **{len(folders)} Ordnern**")

                if folders:
                    with st.expander("📁 Gefundene Ordnerstruktur", expanded=False):
                        for folder in sorted(folders):
                            file_count = len([f for f in valid_files if f.startswith(folder + '/')])
                            st.write(f"📂 `{folder}` ({file_count} Dateien)")

                # Verarbeitungsoptionen
                col1, col2 = st.columns(2)
                with col1:
                    preserve_structure = st.checkbox("Ordnerstruktur in App übernehmen", value=True,
                                                    help="Erstellt die Ordner automatisch in der App")
                with col2:
                    process_docs = st.checkbox("Dokumente sofort verarbeiten (OCR)", value=True)

                if st.button("📥 Ordner importieren", type="primary", key="import_zip"):
                    progress_bar = st.progress(0, text="Starte Import...")
                    status_text = st.empty()

                    imported_count = 0
                    error_count = 0
                    created_folders = {}

                    for idx, file_path in enumerate(valid_files):
                        progress = (idx + 1) / len(valid_files)
                        progress_bar.progress(progress, text=f"Importiere {idx + 1}/{len(valid_files)}...")

                        filename = file_path.split('/')[-1]
                        folder_path = '/'.join(file_path.split('/')[:-1]) if '/' in file_path else ""

                        status_text.markdown(f"📄 **{filename}**" + (f" (aus `{folder_path}`)" if folder_path else ""))

                        try:
                            # Datei aus ZIP extrahieren
                            file_data = zf.read(file_path)

                            # Ordner erstellen wenn nötig
                            target_folder_id = None
                            if preserve_structure and folder_path:
                                if folder_path not in created_folders:
                                    # Ordnerstruktur erstellen
                                    with get_db() as session:
                                        parent_id = None
                                        for part in folder_path.split('/'):
                                            if not part:
                                                continue
                                            # Prüfen ob Ordner existiert
                                            existing = session.query(Folder).filter(
                                                Folder.user_id == user_id,
                                                Folder.name == part,
                                                Folder.parent_id == parent_id
                                            ).first()

                                            if existing:
                                                parent_id = existing.id
                                            else:
                                                # Neuen Ordner erstellen
                                                new_folder = Folder(
                                                    user_id=user_id,
                                                    name=part,
                                                    parent_id=parent_id,
                                                    color="#4CAF50"
                                                )
                                                session.add(new_folder)
                                                session.flush()
                                                parent_id = new_folder.id

                                        created_folders[folder_path] = parent_id
                                        session.commit()

                                target_folder_id = created_folders.get(folder_path)

                            # Dokument speichern
                            doc_id = save_document(file_data, filename, user_id)

                            # Ordner zuweisen wenn erstellt
                            if target_folder_id:
                                with get_db() as session:
                                    doc = session.get(Document, doc_id)
                                    if doc:
                                        doc.folder_id = target_folder_id
                                        # Speichere Quellpfad für spätere Analyse
                                        doc.notes = f"Importiert aus: {folder_path}"
                                        session.commit()

                            # OCR verarbeiten wenn gewünscht
                            if process_docs:
                                try:
                                    process_document(doc_id, file_data, user_id)
                                except Exception as e:
                                    pass  # Fehler bei Verarbeitung ignorieren

                            imported_count += 1

                        except Exception as e:
                            error_count += 1
                            st.warning(f"⚠️ Fehler bei {filename}: {str(e)[:50]}")

                    progress_bar.progress(1.0, text="✅ Import abgeschlossen!")
                    status_text.empty()

                    # Ergebnis
                    st.success(f"✅ **{imported_count} Dokumente erfolgreich importiert!**")
                    if created_folders:
                        st.info(f"📁 **{len(created_folders)} Ordner** wurden erstellt")
                    if error_count > 0:
                        st.warning(f"⚠️ {error_count} Fehler beim Import")

        except zipfile.BadZipFile:
            st.error("❌ Ungültige ZIP-Datei. Bitte prüfen Sie das Archiv.")
        except Exception as e:
            st.error(f"❌ Fehler beim Lesen der ZIP-Datei: {e}")

    # Option 2: Mehrere Dateien per Drag & Drop
    st.markdown("---")
    st.markdown("### 📎 Option 2: Mehrere Dateien hochladen")
    st.info("💡 Wählen Sie mehrere Dateien aus einem Ordner aus (Strg+A zum Auswählen aller Dateien)")

    multi_files = st.file_uploader(
        "Dateien auswählen (Mehrfachauswahl möglich)",
        type=['pdf', 'jpg', 'jpeg', 'png', 'gif', 'doc', 'docx', 'xls', 'xlsx', 'txt'],
        accept_multiple_files=True,
        key="folder_multi_upload",
        help="Halten Sie Strg/Cmd gedrückt um mehrere Dateien auszuwählen"
    )

    if multi_files and len(multi_files) > 0:
        st.success(f"✅ **{len(multi_files)} Dateien** ausgewählt")

        user_id = get_current_user_id()

        # Zielordner auswählen
        with get_db() as session:
            folders = session.query(Folder).filter(
                Folder.user_id == user_id
            ).order_by(Folder.name).all()
            folder_options = {f.id: f.name for f in folders}
            folder_options[None] = "📥 Posteingang"

        target_folder = st.selectbox(
            "Zielordner",
            options=list(folder_options.keys()),
            format_func=lambda x: folder_options.get(x, "Posteingang"),
            key="multi_target_folder"
        )

        process_multi = st.checkbox("Dokumente sofort verarbeiten (OCR)", value=True, key="process_multi_files")

        if st.button("📥 Alle Dateien importieren", type="primary", key="import_multi"):
            progress_bar = st.progress(0, text="Starte Import...")

            imported = 0
            for idx, file in enumerate(multi_files):
                progress_bar.progress((idx + 1) / len(multi_files), text=f"Importiere {file.name}...")

                try:
                    file_data = file.read()
                    doc_id = save_document(file_data, file.name, user_id)

                    # Zielordner setzen
                    if target_folder:
                        with get_db() as session:
                            doc = session.get(Document, doc_id)
                            if doc:
                                doc.folder_id = target_folder
                                session.commit()

                    # Verarbeiten
                    if process_multi:
                        try:
                            process_document(doc_id, file_data, user_id)
                        except:
                            pass

                    imported += 1
                except Exception as e:
                    st.warning(f"⚠️ Fehler bei {file.name}: {e}")

            progress_bar.progress(1.0, text="✅ Fertig!")
            st.success(f"✅ **{imported} Dateien** erfolgreich importiert!")


with tab_cloud:
    st.subheader("☁️ Cloud-Import")
    st.markdown("Importieren Sie Dokumente direkt aus Dropbox oder Google Drive.")

    # Import Cloud-Sync Service
    try:
        from services.cloud_sync_service import CloudSyncService, CloudProvider, SyncStatus
        CLOUD_IMPORT_AVAILABLE = True
    except ImportError:
        CLOUD_IMPORT_AVAILABLE = False

    if not CLOUD_IMPORT_AVAILABLE:
        st.error("Cloud-Import Module nicht verfügbar.")
    else:
        user_id = get_current_user_id()
        cloud_service = CloudSyncService(user_id)

        # Aktive Sync-Verbindungen anzeigen
        connections = cloud_service.get_connections()
        active_connections = [c for c in connections if c.is_active]

        if active_connections:
            st.markdown("### 🔗 Gespeicherte Cloud-Verbindungen")

            for conn in active_connections:
                provider_icon = "📦" if conn.provider == CloudProvider.DROPBOX else "🔵"
                provider_name = "Dropbox" if conn.provider == CloudProvider.DROPBOX else "Google Drive"

                col_info, col_actions = st.columns([3, 1])

                with col_info:
                    interval_text = f" (alle {conn.sync_interval_minutes} Min.)" if conn.sync_interval_minutes else " (einmalig)"
                    folder_display = conn.folder_path or conn.folder_id or "Unbekannt"
                    # Kürze lange URLs
                    if len(folder_display) > 60:
                        folder_display = folder_display[:57] + "..."
                    st.info(f"{provider_icon} **{provider_name}**{interval_text}\n\n`{folder_display}`")

                with col_actions:
                    if st.button("🗑️ Löschen", key=f"delete_conn_{conn.id}", help="Verbindung löschen"):
                        cloud_service.delete_connection(conn.id)
                        st.success("Verbindung gelöscht!")
                        st.rerun()

            st.markdown("---")

        # Schnell-Import Formular
        st.markdown("### 📥 Schnell-Import aus Cloud-Ordner")

        col1, col2 = st.columns([2, 1])

        with col1:
            cloud_link = st.text_input(
                "Cloud-Link einfügen",
                placeholder="https://www.dropbox.com/scl/fo/... oder https://drive.google.com/drive/folders/...",
                help="Fügen Sie hier den Link zu einem Dropbox- oder Google Drive-Ordner ein"
            )

        with col2:
            # Automatische Erkennung des Providers
            detected_provider = None
            if cloud_link:
                if "dropbox.com" in cloud_link.lower():
                    detected_provider = "dropbox"
                    st.success("📦 Dropbox erkannt")
                elif "drive.google.com" in cloud_link.lower():
                    detected_provider = "google_drive"
                    st.success("🔵 Google Drive erkannt")
                else:
                    st.warning("⚠️ Unbekannter Link")

        # Sync-Optionen
        st.markdown("#### Sync-Optionen")
        col_opt1, col_opt2 = st.columns(2)

        with col_opt1:
            import_mode = st.radio(
                "Import-Modus",
                options=["once", "interval", "continuous"],
                format_func=lambda x: {
                    "once": "🔂 Einmalig - Nur jetzt importieren",
                    "interval": "⏱️ Intervall - Regelmäßig synchronisieren",
                    "continuous": "♾️ Dauerhaft - Bis ich stoppe"
                }.get(x),
                horizontal=False
            )

        with col_opt2:
            if import_mode == "interval":
                sync_interval = st.selectbox(
                    "Sync-Intervall",
                    options=[5, 15, 30, 60, 120, 360, 720, 1440],
                    format_func=lambda x: {
                        5: "Alle 5 Minuten",
                        15: "Alle 15 Minuten",
                        30: "Alle 30 Minuten",
                        60: "Jede Stunde",
                        120: "Alle 2 Stunden",
                        360: "Alle 6 Stunden",
                        720: "Alle 12 Stunden",
                        1440: "Täglich"
                    }.get(x),
                    index=2
                )
            elif import_mode == "continuous":
                st.info("♾️ Dauerhaft: Ordner wird kontinuierlich überwacht (alle 5 Min.)")
                sync_interval = 5
            else:
                st.info("🔂 Einmalig: Dateien werden nur jetzt importiert")
                sync_interval = None

        # Hilfsfunktion für Zeitformatierung
        def format_time(seconds):
            """Formatiert Sekunden als lesbare Zeit"""
            if seconds is None or seconds < 0:
                return "Berechne..."
            if seconds < 60:
                return f"{int(seconds)} Sek."
            elif seconds < 3600:
                mins = int(seconds / 60)
                secs = int(seconds % 60)
                return f"{mins} Min. {secs} Sek."
            else:
                hours = int(seconds / 3600)
                mins = int((seconds % 3600) / 60)
                return f"{hours} Std. {mins} Min."

        def format_file_size(bytes_size):
            """Formatiert Bytes als lesbare Größe"""
            if bytes_size < 1024:
                return f"{bytes_size} B"
            elif bytes_size < 1024 * 1024:
                return f"{bytes_size / 1024:.1f} KB"
            else:
                return f"{bytes_size / (1024 * 1024):.1f} MB"

        # Import starten
        if st.button("☁️ Import starten", type="primary", disabled=not cloud_link or not detected_provider):
            if cloud_link and detected_provider:
                try:
                    # Verbindung erstellen
                    conn = cloud_service.create_connection(
                        provider=CloudProvider.DROPBOX if detected_provider == "dropbox" else CloudProvider.GOOGLE_DRIVE,
                        folder_id=cloud_link,
                        folder_path=cloud_link,
                        sync_interval_minutes=sync_interval
                    )

                    st.success("✅ Cloud-Verbindung erstellt!")

                    # Fortschrittsanzeige
                    progress_container = st.container()

                    with progress_container:
                        progress_bar = st.progress(0, text="Initialisiere...")
                        status_container = st.empty()
                        file_info_container = st.empty()
                        step_detail_container = st.empty()  # NEU: Detaillierte Schritte
                        stats_container = st.empty()

                        # Synchronisieren mit Fortschrittsanzeige
                        final_result = None
                        for progress in cloud_service.sync_connection_with_progress(conn.id):
                            final_result = progress
                            phase = progress.get("phase", "")

                            # Fortschrittsbalken aktualisieren
                            percent = progress.get("progress_percent", 0)
                            progress_bar.progress(percent / 100)

                            # Status-Text
                            if phase == "initializing":
                                status_container.info("🔄 Initialisiere Verbindung...")
                                step_detail_container.markdown("*Verbindung wird hergestellt...*")
                            elif phase == "scanning":
                                status_container.info("🔍 **Scanne Cloud-Ordner nach Dateien...**")
                                step_detail_container.markdown(
                                    "⏳ *Durchsuche Ordner und Unterordner... Dies kann einen Moment dauern.*"
                                )
                            elif phase == "downloading":
                                files_total = progress.get("files_total", 0)
                                files_processed = progress.get("files_processed", 0)
                                elapsed = progress.get("elapsed_seconds", 0)
                                remaining = progress.get("estimated_remaining_seconds")

                                time_info = f"⏱️ Verstrichene Zeit: {format_time(elapsed)}"
                                if remaining is not None and remaining > 0:
                                    time_info += f" | ⏳ Restzeit: ~{format_time(remaining)}"

                                status_container.info(
                                    f"📥 Importiere Dateien: {files_processed + 1} von {files_total}\n\n{time_info}"
                                )

                                # Aktuelle Datei anzeigen
                                current_file = progress.get("current_file")
                                current_size = progress.get("current_file_size", 0)
                                source_folder = progress.get("source_folder", "")
                                if current_file:
                                    folder_info = f" (aus `{source_folder}`)" if source_folder else ""
                                    file_info_container.markdown(
                                        f"📄 **Aktuelle Datei:** `{current_file}` ({format_file_size(current_size)}){folder_info}"
                                    )

                                # Detaillierter Verarbeitungsschritt anzeigen
                                current_step_detail = progress.get("current_step_detail", "")
                                if current_step_detail:
                                    step_detail_container.markdown(f"**Aktion:** {current_step_detail}")
                                else:
                                    step_detail_container.empty()

                                # Statistiken
                                synced = progress.get("files_synced", 0)
                                skipped = progress.get("files_skipped", 0)
                                errors = progress.get("files_error", 0)
                                stats_container.caption(
                                    f"✅ Importiert: {synced} | ⏭️ Übersprungen: {skipped} | ❌ Fehler: {errors}"
                                )

                            elif phase == "completed":
                                progress_bar.progress(1.0, text="✅ Abgeschlossen!")
                                status_container.success(
                                    f"✅ **Synchronisation abgeschlossen!**\n\n"
                                    f"⏱️ Gesamtzeit: {format_time(progress.get('elapsed_seconds', 0))}"
                                )
                                step_detail_container.empty()
                            elif phase == "error":
                                progress_bar.progress(0, text="❌ Fehler")
                                status_container.error(f"❌ Fehler: {progress.get('error', 'Unbekannt')}")
                                step_detail_container.empty()

                        # Endergebnis verarbeiten
                        file_info_container.empty()
                        step_detail_container.empty()

                        if final_result:
                            new_files = final_result.get("new_files", 0)
                            skipped = final_result.get("skipped_files", 0)
                            synced_files = final_result.get("synced_files", [])

                            if new_files > 0:
                                st.success(f"✅ **{new_files} Dateien erfolgreich importiert!**")

                                # Importierte Dateien auflisten
                                if synced_files:
                                    with st.expander(f"📋 Importierte Dateien ({len(synced_files)})", expanded=False):
                                        for fname in synced_files:
                                            st.write(f"• {fname}")

                                st.info(f"📁 Dateien wurden im Posteingang abgelegt.")

                                # Hinweis auf Verarbeitung
                                st.markdown("---")
                                st.markdown("### 📋 Nächste Schritte")
                                st.write("1. Gehen Sie zum Tab **'⚙️ Verarbeitung'** um die importierten Dokumente zu verarbeiten")
                                st.write("2. Oder besuchen Sie **'📁 Dokumente'** um die neuen Dokumente zu sehen")

                            elif final_result.get("files_total", 0) == 0:
                                st.warning("📭 **Keine Dateien gefunden!**")

                                # Zeige den verwendeten Link zur Kontrolle
                                st.markdown(f"**Verwendeter Link:** `{cloud_link}`")

                                # Hilfreiche Tipps anzeigen
                                with st.expander("🔍 Mögliche Ursachen & Lösungen", expanded=True):
                                    st.markdown("""
**1. Ordner ist nicht öffentlich freigegeben:**
   - Öffnen Sie den Ordner in Google Drive
   - Rechtsklick → **Freigeben**
   - Klicken Sie auf "Zugriff beschränkt" → **"Jeder mit dem Link"**
   - Stellen Sie sicher, dass "Betrachter" ausgewählt ist

**2. Link ist falsch:**
   - Der Link muss auf einen **Ordner** zeigen (nicht auf eine einzelne Datei)
   - Format: `https://drive.google.com/drive/folders/ORDNER_ID`

**3. Ordner ist leer:**
   - Prüfen Sie, ob der Ordner tatsächlich Dateien enthält

**4. Unterstützte Dateitypen:**
   - PDF, JPG, JPEG, PNG, GIF, DOC, DOCX, XLS, XLSX, TXT
                                    """)

                                # Button zum Testen des Links
                                st.markdown(f"[🔗 Link im Browser öffnen]({cloud_link})")

                            if skipped > 0:
                                st.caption(f"ℹ️ {skipped} Dateien übersprungen (bereits vorhanden oder nicht unterstützt)")

                            if final_result.get("error") and not final_result.get("success"):
                                error_msg = final_result.get("error", "Unbekannter Fehler")
                                if "token" in error_msg.lower() or "auth" in error_msg.lower():
                                    st.warning(f"⚠️ API-Authentifizierung erforderlich. Bitte konfigurieren Sie Ihre Cloud-API unter **Einstellungen → Cloud-Sync**.")
                                else:
                                    st.error(f"❌ Import fehlgeschlagen: {error_msg}")

                    # Bei einmaligem Import Verbindung deaktivieren
                    if import_mode == "once":
                        cloud_service.delete_connection(conn.id)
                        st.caption("ℹ️ Einmaliger Import abgeschlossen. Verbindung wurde entfernt.")
                    else:
                        st.info(f"🔄 Dauerhafte Sync eingerichtet. Verwalten unter **Einstellungen → Cloud-Sync**.")

                except Exception as e:
                    st.error(f"Fehler beim Import: {e}")
            else:
                st.error("Bitte geben Sie einen gültigen Cloud-Link ein.")

        # Hinweis auf Einstellungen
        st.markdown("---")
        st.caption("💡 **Tipp:** Für erweiterte Cloud-Sync Optionen und API-Konfiguration besuchen Sie **Einstellungen → Cloud-Sync**.")


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
