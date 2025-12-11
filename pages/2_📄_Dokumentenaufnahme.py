"""
Dokumentenaufnahme - Upload, Scan und Verarbeitung von Dokumenten
"""
import streamlit as st
import io
from pathlib import Path
import sys
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.db import init_db, get_db, get_current_user_id
from database.models import Document, Folder, DocumentStatus, CalendarEvent, EventType
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

# Tabs für verschiedene Upload-Optionen
tab_upload, tab_multi, tab_process = st.tabs(["📤 Einzelupload", "📑 Mehrere Dokumente", "⚙️ Verarbeitung"])


def save_document(file_data: bytes, filename: str, user_id: int) -> Document:
    """Speichert ein Dokument verschlüsselt und erstellt DB-Eintrag"""
    encryption = get_encryption_service()

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
            status=DocumentStatus.PENDING
        )
        session.add(document)
        session.commit()

        return document.id


def process_document(document_id: int, file_data: bytes, user_id: int):
    """Verarbeitet ein Dokument mit OCR und KI"""
    ocr = get_ocr_service()
    ai = get_ai_service()
    classifier = get_classifier(user_id)
    search = get_search_service(user_id)

    with get_db() as session:
        document = session.query(Document).get(document_id)
        if not document:
            return

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

                except Exception as e:
                    st.warning(f"KI-Analyse teilweise fehlgeschlagen: {e}")

            # Selbstlernende Klassifikation
            folder_id, category, conf = classifier.classify(full_text, metadata)

            if not document.category and category:
                document.category = category

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

        except Exception as e:
            document.status = DocumentStatus.ERROR
            document.processing_error = str(e)
            session.commit()
            raise


with tab_upload:
    st.subheader("Einzelnes Dokument hochladen")

    uploaded_file = st.file_uploader(
        "PDF oder Bild auswählen",
        type=['pdf', 'jpg', 'jpeg', 'png'],
        help="Unterstützte Formate: PDF, JPG, PNG"
    )

    if uploaded_file:
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
                user_id = get_current_user_id()
                file_data = uploaded_file.read()

                with st.spinner("Speichere Dokument..."):
                    doc_id = save_document(file_data, uploaded_file.name, user_id)

                if process_now:
                    with st.spinner("Verarbeite Dokument (OCR & Analyse)..."):
                        try:
                            process_document(doc_id, file_data, user_id)
                            st.success("Dokument erfolgreich verarbeitet!")

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
                                        if doc.insurance_number:
                                            st.write(f"**Vers.-Nr:** {doc.insurance_number}")
                                        if doc.processing_number:
                                            st.write(f"**Bearbeitungsnr:** {doc.processing_number}")
                                        if doc.contract_number:
                                            st.write(f"**Vertragsnr:** {doc.contract_number}")
                                        if not any([doc.reference_number, doc.customer_number,
                                                   doc.insurance_number, doc.processing_number,
                                                   doc.contract_number]):
                                            st.write("—")

                                    with col_finance:
                                        st.markdown("### 💰 Finanzdaten")
                                        if doc.invoice_amount:
                                            st.write(f"**Betrag:** {format_currency(doc.invoice_amount)}")
                                        if doc.invoice_due_date:
                                            st.write(f"**Fällig bis:** {format_date(doc.invoice_due_date)}")
                                        if doc.iban:
                                            st.write(f"**IBAN:** {doc.iban}")
                                        if doc.bic:
                                            st.write(f"**BIC:** {doc.bic}")
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
                    boundaries = pdf_processor.detect_document_boundaries(file_data)
                    st.write(f"Erkannte Dokumentgrenzen: Seiten {boundaries}")

                    # Seitenbereiche erstellen
                    page_ranges = []
                    for i, start in enumerate(boundaries):
                        end = boundaries[i + 1] if i + 1 < len(boundaries) else page_count
                        page_ranges.append((start, end))
                else:
                    # Manuelle Bereiche parsen
                    page_ranges = []
                    for range_str in manual_pages.split(','):
                        if '-' in range_str:
                            start, end = range_str.strip().split('-')
                            page_ranges.append((int(start) - 1, int(end)))
                        else:
                            page_ranges.append((int(range_str.strip()) - 1, int(range_str.strip())))

            st.write(f"Trenne in {len(page_ranges)} Dokumente...")

            # PDFs trennen
            split_pdfs = pdf_processor.split_pdf(file_data, page_ranges)

            # Jedes Teildokument verarbeiten
            progress = st.progress(0)
            for i, pdf_data in enumerate(split_pdfs):
                progress.progress((i + 1) / len(split_pdfs))
                filename = f"{multi_file.name.rsplit('.', 1)[0]}_Teil{i+1}.pdf"

                with st.spinner(f"Verarbeite Dokument {i+1}/{len(split_pdfs)}..."):
                    doc_id = save_document(pdf_data, filename, user_id)
                    try:
                        process_document(doc_id, pdf_data, user_id)
                        st.success(f"✓ Dokument {i+1} verarbeitet")
                    except Exception as e:
                        st.warning(f"⚠ Dokument {i+1}: {e}")

            st.success(f"Alle {len(split_pdfs)} Dokumente wurden verarbeitet!")


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
