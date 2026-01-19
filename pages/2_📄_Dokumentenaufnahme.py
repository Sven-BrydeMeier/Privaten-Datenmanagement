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
from services.email_parser_service import get_email_parser
from utils.pdf_utils import get_pdf_processor
from utils.helpers import format_currency, format_date, sanitize_filename, get_local_now
from utils.components import render_sidebar_cart

st.set_page_config(page_title="Dokumentenaufnahme", page_icon="📄", layout="wide")
init_db()

# Sidebar mit Aktentasche
# MaStR-Layout anwenden
from utils.components import render_sidebar_with_navigation
from utils.layout_mastr import render_breadcrumb, render_page_title
render_sidebar_with_navigation(use_mastr_layout=True)
render_breadcrumb("Dokumente", "Dokumentenaufnahme")
render_page_title("Dokumentenaufnahme")

# Debug-Modus Toggle in der Sidebar
with st.sidebar:
    st.divider()
    debug_mode = st.checkbox("🐛 Debug-Modus", value=st.session_state.get('debug_mode', False),
                             help="Zeigt detaillierte Verarbeitungsschritte an")
    st.session_state.debug_mode = debug_mode

st.markdown("Laden Sie Dokumente hoch oder scannen Sie sie ein")


def debug_log(message: str, level: str = "info"):
    """Fügt eine Debug-Nachricht zum Log hinzu"""
    if 'debug_log' not in st.session_state:
        st.session_state.debug_log = []
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    st.session_state.debug_log.append({
        'time': timestamp,
        'level': level,
        'message': message
    })


def clear_debug_log():
    """Löscht das Debug-Log"""
    st.session_state.debug_log = []


def show_debug_panel():
    """Zeigt das Debug-Panel an"""
    if not st.session_state.get('debug_mode', False):
        return

    if 'debug_log' not in st.session_state or not st.session_state.debug_log:
        return

    with st.expander("🐛 Debug-Log", expanded=True):
        # Log anzeigen
        for entry in st.session_state.debug_log:
            icon = "ℹ️" if entry['level'] == "info" else "✅" if entry['level'] == "success" else "⚠️" if entry['level'] == "warning" else "❌"
            color = "gray" if entry['level'] == "info" else "green" if entry['level'] == "success" else "orange" if entry['level'] == "warning" else "red"
            st.markdown(f"<span style='color:{color}'>{icon} [{entry['time']}] {entry['message']}</span>",
                       unsafe_allow_html=True)

        if st.button("🗑️ Log löschen"):
            clear_debug_log()
            st.rerun()


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
                    st.image(images[0], caption="Vorschau (Seite 1)", width="stretch")
            except Exception:
                st.info("PDF-Vorschau nicht verfügbar")
        else:
            st.image(new_file_data, caption="Vorschau", width="stretch")

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
                from utils.helpers import get_document_file_content
                encryption = get_encryption_service()
                success, result = get_document_file_content(existing_doc['file_path'], existing_doc.get('user_id'))

                with get_db() as session:
                    doc = session.get(Document, existing_doc['id'])
                    if doc and doc.encryption_iv and success:
                        decrypted_data = encryption.decrypt_file(result, doc.encryption_iv, doc.filename)

                        if existing_doc['filename'].lower().endswith('.pdf'):
                            try:
                                from pdf2image import convert_from_bytes
                                images = convert_from_bytes(decrypted_data, first_page=1, last_page=1, dpi=100)
                                if images:
                                    st.image(images[0], caption="Vorschau (Seite 1)", width="stretch")
                            except Exception:
                                st.info("PDF-Vorschau nicht verfügbar")
                        else:
                            st.image(decrypted_data, caption="Vorschau", width="stretch")
            except Exception as e:
                st.info(f"Vorschau nicht verfügbar: {e}")

    st.divider()

    # Aktionen
    st.markdown("### Was möchten Sie tun?")
    col_action1, col_action2, col_action3 = st.columns(3)

    with col_action1:
        if st.button("🚫 Nicht hochladen", width="stretch", help="Abbrechen, bestehendes Dokument behalten"):
            if 'duplicate_check' in st.session_state:
                del st.session_state.duplicate_check
            st.rerun()

    with col_action2:
        if st.button("📂 Zum bestehenden Dokument", width="stretch", help="Bestehendes Dokument öffnen"):
            st.session_state.current_folder_id = existing_doc['folder_id']
            if 'duplicate_check' in st.session_state:
                del st.session_state.duplicate_check
            st.switch_page("pages/3_📁_Dokumente.py")

    with col_action3:
        if st.button("✅ Trotzdem hochladen", type="primary", width="stretch", help="Als neues Dokument speichern"):
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
    import unicodedata

    encryption = get_encryption_service()

    # Dateiname normalisieren für konsistente Umlaut-Behandlung
    if isinstance(filename, bytes):
        try:
            filename = filename.decode('utf-8')
        except UnicodeDecodeError:
            filename = filename.decode('latin-1', errors='replace')

    # Unicode-Normalisierung (NFC) für konsistente Umlaute (ä, ö, ü)
    filename = unicodedata.normalize('NFC', filename)

    # WICHTIG: Dateiname auf sichere Länge kürzen
    # VARCHAR(255) in der DB, aber UTF-8-Umlaute brauchen 2 Bytes
    # Also maximal ~120 Zeichen um sicher zu sein
    if len(filename) > 150:
        name_part, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
        # Kürze den Namen, behalte die Extension
        max_name_len = 150 - len(ext) - 1 if ext else 150
        name_part = name_part[:max_name_len]
        filename = f"{name_part}.{ext}" if ext else name_part

    # Content-Hash berechnen
    content_hash = calculate_content_hash(file_data)

    # Datei verschlüsseln (verwendet intern auch NFC-Normalisierung)
    encrypted_data, nonce = encryption.encrypt_file(file_data, filename)

    # Sicheren Dateinamen generieren (behält Umlaute bei)
    safe_filename = sanitize_filename(filename)
    timestamp = get_local_now().strftime("%Y%m%d_%H%M%S")
    stored_filename = f"{timestamp}_{safe_filename}.enc"

    # Auch den gespeicherten Pfad auf sichere Länge begrenzen
    if len(stored_filename) > 200:
        # Kürze den safe_filename wenn nötig
        max_safe = 200 - len(timestamp) - 6  # 6 für "_.enc"
        safe_filename = safe_filename[:max_safe]
        stored_filename = f"{timestamp}_{safe_filename}.enc"

    file_path = DOCUMENTS_DIR / stored_filename

    # Verschlüsselte Datei speichern
    with open(file_path, 'wb') as f:
        f.write(encrypted_data)

    # Mime-Type bestimmen
    lower_filename = filename.lower()
    if lower_filename.endswith('.pdf'):
        mime_type = "application/pdf"
    elif lower_filename.endswith('.png'):
        mime_type = "image/png"
    elif lower_filename.endswith('.eml'):
        mime_type = "message/rfc822"
    elif lower_filename.endswith('.msg'):
        mime_type = "application/vnd.ms-outlook"
    elif lower_filename.endswith('.jpg') or lower_filename.endswith('.jpeg'):
        mime_type = "image/jpeg"
    else:
        mime_type = "application/octet-stream"

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
            filename=filename[:250],  # Sicherheits-Limit für DB
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
    is_debug = st.session_state.get('debug_mode', False)

    if is_debug:
        debug_log(f"▶️ Starte Verarbeitung für Dokument ID: {document_id}", "info")
        debug_log(f"📦 Dateigröße: {len(file_data)} Bytes", "info")

    try:
        if is_debug:
            debug_log("🔧 Initialisiere Services...", "info")
        ocr = get_ocr_service()
        ai = get_ai_service()
        classifier = get_classifier(user_id)
        search = get_search_service(user_id)
        if is_debug:
            debug_log("✅ Services initialisiert", "success")
    except Exception as e:
        if is_debug:
            debug_log(f"❌ Service-Initialisierung fehlgeschlagen: {str(e)[:200]}", "error")
        return {'error': f"Service-Init fehlgeschlagen: {str(e)[:100]}"}

    result = {
        'folder_name': None,
        'folder_path': None,
        'folder_created': False,
        'sender': None,
        'virtual_folders': [],
        'property_name': None,
        'category': None,
        'subcategory': None
    }

    try:
        with get_db() as session:
            if is_debug:
                debug_log("🔍 Lade Dokument aus Datenbank...", "info")

            document = session.get(Document, document_id)
            if not document:
                if is_debug:
                    debug_log(f"❌ Dokument {document_id} nicht gefunden!", "error")
                return result

            if is_debug:
                debug_log(f"📄 Dokument geladen: {document.filename[:50]}...", "success")
                debug_log(f"📋 MIME-Type: {document.mime_type}", "info")

            document.status = DocumentStatus.PROCESSING
            session.commit()

            try:
                # OCR durchführen (oder überspringen wenn bereits vorhanden)
                full_text = ""
                confidence = 0.0
                ocr_error = None
                ocr_skipped = False

                # Prüfen ob bereits OCR-Text vorhanden ist
                if document.ocr_text and len(document.ocr_text.strip()) > 100:
                    full_text = document.ocr_text
                    confidence = document.ocr_confidence or 0.9
                    ocr_skipped = True
                    if is_debug:
                        debug_log(f"⏭️ OCR übersprungen - bereits {len(full_text)} Zeichen vorhanden", "info")
                else:
                    if is_debug:
                        debug_log("🔤 Starte Text-Extraktion...", "info")

                    # E-Mail (.eml oder .msg) Verarbeitung
                    lower_filename = document.filename.lower()
                    is_email_file = (
                        document.mime_type == "message/rfc822" or
                        document.mime_type == "application/vnd.ms-outlook" or
                        lower_filename.endswith('.eml') or
                        lower_filename.endswith('.msg')
                    )
                    if is_email_file:
                        email_type = "MSG" if lower_filename.endswith('.msg') else "EML"
                        if is_debug:
                            debug_log(f"📧 {email_type}-E-Mail erkannt - parse Inhalt...", "info")
                        try:
                            email_parser = get_email_parser()
                            parsed_email = email_parser.parse_email_file(file_data, document.filename)

                            # Text aus E-Mail extrahieren
                            full_text = parsed_email.get("full_text", "")
                            confidence = 1.0  # E-Mail-Text ist exakt

                            # E-Mail-Metadaten setzen
                            if parsed_email.get("subject"):
                                document.title = email_parser.create_document_title(parsed_email)
                                document.subject = parsed_email["subject"]
                            if parsed_email.get("from_address"):
                                document.sender = email_parser.get_detected_sender(parsed_email)
                                document.sender_address = parsed_email["from_address"]
                            if parsed_email.get("date"):
                                document.document_date = parsed_email["date"]

                            # Kategorie auf E-Mail setzen
                            document.category = "E-Mail"
                            result['category'] = "E-Mail"

                            if is_debug:
                                debug_log(f"✅ E-Mail geparst: '{parsed_email.get('subject', 'Kein Betreff')}'", "success")
                                debug_log(f"📬 Von: {parsed_email.get('from_address', 'Unbekannt')}", "info")

                            # E-Mail-Anhänge speichern
                            attachments = parsed_email.get("attachments", [])
                            if attachments:
                                if is_debug:
                                    debug_log(f"📎 {len(attachments)} Anhänge gefunden - speichere separat...", "info")
                                result['attachments'] = []
                                email_subject = parsed_email.get('subject', 'E-Mail')[:50]

                                for i, attachment in enumerate(attachments):
                                    try:
                                        att_filename = attachment.get('filename', f'anhang_{i+1}')
                                        att_data = attachment.get('data')
                                        att_mime = attachment.get('mime_type', 'application/octet-stream')

                                        if att_data:
                                            # Anhang als separates Dokument speichern
                                            att_doc_id = save_document(att_data, att_filename, user_id)

                                            if att_doc_id:
                                                # Anhang-Dokument aktualisieren
                                                att_doc = session.get(Document, att_doc_id)
                                                if att_doc:
                                                    att_doc.title = f"📎 {att_filename} (aus: {email_subject})"
                                                    att_doc.sender = document.sender
                                                    att_doc.document_date = document.document_date
                                                    # Anhang in gleichen Ordner wie E-Mail (wird später gesetzt)
                                                    result['attachments'].append({
                                                        'id': att_doc_id,
                                                        'filename': att_filename,
                                                        'size': attachment.get('size', 0)
                                                    })
                                                    if is_debug:
                                                        debug_log(f"  ✅ Anhang gespeichert: {att_filename}", "success")
                                    except Exception as att_err:
                                        if is_debug:
                                            debug_log(f"  ⚠️ Fehler bei Anhang {att_filename}: {str(att_err)[:100]}", "warning")

                        except Exception as email_err:
                            ocr_error = str(email_err)[:200]
                            if is_debug:
                                debug_log(f"⚠️ E-Mail-Parsing Fehler: {ocr_error}", "warning")
                            full_text = f"[E-Mail-Parsing-Fehler: {ocr_error}]"
                            document.category = "E-Mail"

                    elif document.mime_type == "application/pdf":
                        if is_debug:
                            debug_log("📑 PDF erkannt - extrahiere Text...", "info")
                        try:
                            results = ocr.extract_text_from_pdf(file_data)
                            if results:
                                full_text = "\n\n".join(text for text, _ in results)
                                confidence = sum(conf for _, conf in results) / len(results)
                                if is_debug:
                                    debug_log(f"✅ OCR erfolgreich: {len(full_text)} Zeichen, Konfidenz: {confidence:.2f}", "success")
                            else:
                                if is_debug:
                                    debug_log("⚠️ Kein Text extrahiert (möglicherweise Bild-PDF)", "warning")
                        except Exception as ocr_err:
                            ocr_error = str(ocr_err)[:200]
                            if is_debug:
                                debug_log(f"⚠️ PDF-OCR Fehler (wird übersprungen): {ocr_error}", "warning")
                            # NICHT abbrechen - Dokument trotzdem speichern
                            full_text = f"[OCR-Fehler: {ocr_error}]"
                    else:
                        # Bild
                        if is_debug:
                            debug_log("🖼️ Bild erkannt - starte Bild-OCR...", "info")
                        try:
                            from PIL import Image
                            image = Image.open(io.BytesIO(file_data))
                            if is_debug:
                                debug_log(f"📐 Bildgröße: {image.size}", "info")
                            full_text, confidence = ocr.extract_text_from_image(image)
                            if is_debug:
                                debug_log(f"✅ Bild-OCR erfolgreich: {len(full_text)} Zeichen", "success")
                        except Exception as img_err:
                            ocr_error = str(img_err)[:200]
                            if is_debug:
                                debug_log(f"⚠️ Bild-OCR Fehler (wird übersprungen): {ocr_error}", "warning")
                            # NICHT abbrechen - Dokument trotzdem speichern
                            full_text = f"[OCR-Fehler: {ocr_error}]"

                # OCR-Text nur speichern wenn neu extrahiert
                if not ocr_skipped:
                    document.ocr_text = full_text
                document.ocr_confidence = confidence
                if ocr_error:
                    document.processing_notes = f"OCR-Fehler: {ocr_error}"

                # Metadaten extrahieren
                if is_debug:
                    debug_log("📊 Extrahiere Metadaten aus Text...", "info")

                try:
                    metadata = ocr.extract_metadata(full_text)
                    if is_debug:
                        debug_log(f"✅ Metadaten extrahiert: {len(metadata.get('dates', []))} Daten, {len(metadata.get('amounts', []))} Beträge", "success")
                except Exception as meta_err:
                    if is_debug:
                        debug_log(f"⚠️ Metadaten-Extraktion Fehler: {str(meta_err)[:200]}", "warning")
                    metadata = {}

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
                if is_debug:
                    debug_log(f"🤖 KI verfügbar: {ai.any_ai_available}", "info")

                if ai.any_ai_available:
                    if is_debug:
                        debug_log("🧠 Starte KI-Analyse...", "info")
                    try:
                        structured_data = ai.extract_structured_data(full_text)
                        if is_debug:
                            debug_log(f"✅ KI-Analyse abgeschlossen", "success")

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

                        # Vertragsdaten
                        if structured_data.get('contract_start'):
                            from utils.helpers import parse_date_string
                            contract_start = parse_date_string(structured_data['contract_start'])
                            if contract_start:
                                document.contract_start = contract_start
                        if structured_data.get('contract_end'):
                            from utils.helpers import parse_date_string
                            contract_end = parse_date_string(structured_data['contract_end'])
                            if contract_end:
                                document.contract_end = contract_end
                        if structured_data.get('contract_notice_period_days'):
                            try:
                                document.contract_notice_period = int(structured_data['contract_notice_period_days'])
                            except:
                                pass

                        # Erweiterte dokumenttyp-spezifische Metadaten
                        if structured_data.get('extended_metadata'):
                            document.extended_metadata = structured_data['extended_metadata']

                        # Automatische Rechnungserkennung - als OFFEN markieren
                        is_invoice = structured_data.get('is_invoice', False)
                        if is_invoice or structured_data.get('category') in ['Rechnung', 'Mahnung']:
                            if document.invoice_amount and document.invoice_amount > 0:
                                document.invoice_status = InvoiceStatus.OPEN

                    except Exception as e:
                        if is_debug:
                            debug_log(f"⚠️ KI-Analyse fehlgeschlagen: {str(e)[:200]}", "warning")
                        st.warning(f"KI-Analyse teilweise fehlgeschlagen: {e}")

                # ============================================================
                # GELERNTE FELDPOSITIONEN ANWENDEN (Field Learning)
                # ============================================================
                if not document.sender or document.sender.strip() == "":
                    if is_debug:
                        debug_log("🎯 Prüfe gelernte Feldpositionen...", "info")
                    try:
                        from services.field_learning_service import get_field_learning_service
                        field_service = get_field_learning_service(user_id)

                        # Passendes Template suchen
                        template = field_service.find_matching_template(full_text, document.sender)

                        if template:
                            if is_debug:
                                debug_log(f"✅ Template gefunden: {template['name']} (Score: {template.get('score', 0):.0%})", "success")

                            # Dokument als Bild laden für Feldextraktion
                            doc_image = None
                            if filename.lower().endswith('.pdf'):
                                try:
                                    from pdf2image import convert_from_bytes
                                    images = convert_from_bytes(file_data, first_page=1, last_page=1, dpi=150)
                                    if images:
                                        doc_image = images[0]
                                except:
                                    pass
                            else:
                                from PIL import Image
                                doc_image = Image.open(io.BytesIO(file_data))

                            if doc_image:
                                # Felder extrahieren
                                extracted = field_service.extract_fields_with_template(doc_image, template)

                                if extracted:
                                    if is_debug:
                                        debug_log(f"📋 Felder extrahiert: {list(extracted.keys())}", "success")

                                    # Felder auf Dokument anwenden
                                    if 'sender' in extracted and not document.sender:
                                        document.sender = extracted['sender']
                                        result['sender'] = extracted['sender']
                                    if 'amount' in extracted and not document.invoice_amount:
                                        try:
                                            document.invoice_amount = float(extracted['amount'].replace(',', '.'))
                                        except:
                                            pass
                                    if 'iban' in extracted and not document.iban:
                                        document.iban = extracted['iban'].replace(' ', '')
                                    if 'customer_number' in extracted and not document.customer_number:
                                        document.customer_number = extracted['customer_number']
                                    if 'invoice_number' in extracted and not document.invoice_number:
                                        document.invoice_number = extracted['invoice_number']
                                    if 'due_date' in extracted and not document.invoice_due_date:
                                        parsed = field_service._parse_date(extracted['due_date'])
                                        if parsed:
                                            document.invoice_due_date = parsed
                        else:
                            if is_debug:
                                debug_log("ℹ️ Kein passendes Template gefunden", "info")

                    except Exception as fl_error:
                        if is_debug:
                            debug_log(f"⚠️ Field Learning Fehler: {str(fl_error)[:200]}", "warning")

                # ============================================================
                # INTELLIGENTE KLASSIFIKATION MIT KI-UNTERSTÜTZUNG
                # ============================================================
                if is_debug:
                    debug_log("📂 Starte Dokumenten-Klassifikation...", "info")

                try:
                    classification = classifier.classify_with_ai(full_text, metadata)
                    if is_debug:
                        debug_log(f"✅ Klassifikation abgeschlossen: Kategorie={classification.get('category')}, Ordner={classification.get('primary_folder_path')}", "success")
                except Exception as class_error:
                    if is_debug:
                        debug_log(f"❌ Klassifikation fehlgeschlagen: {str(class_error)[:200]}", "error")
                    # Bei Klassifikationsfehler: Standardwerte verwenden
                    classification = {
                        'category': document.category or 'Sonstiges',
                        'subcategory': None,
                        'primary_folder_id': None,
                        'primary_folder_path': None,
                        'virtual_folder_ids': [],
                        'property_id': None,
                        'detected_address': None,
                        'confidence': 0.0
                    }

                # Kategorie und Unterkategorie zuweisen
                # WICHTIG: Bei E-Mails wird die Kategorie "E-Mail" beibehalten,
                # damit sie immer im "Emailverkehr" Smart Folder erscheinen.
                # Die inhaltliche Klassifikation wird nur für die Ordner-Zuweisung genutzt.
                is_email = document.category == "E-Mail"

                if classification.get('category'):
                    if is_email:
                        # E-Mails behalten ihre Kategorie, Inhalt wird als Subcategory gespeichert
                        if classification['category'] != "E-Mail" and classification['category'] != "Sonstiges":
                            result['subcategory'] = classification['category']
                            result['content_type'] = classification['category']  # Für Anzeige
                        result['category'] = "E-Mail"
                    else:
                        document.category = classification['category']
                        result['category'] = classification['category']
                if classification.get('subcategory'):
                    if not is_email:
                        result['subcategory'] = classification['subcategory']

                # Extrahierte Adresse speichern (für Immobilien-Zuordnung)
                if classification.get('detected_address'):
                    document.property_address = classification['detected_address']

                # Immobilien-Zuordnung
                if classification.get('property_id'):
                    document.property_id = classification['property_id']
                    # Property-Name für Anzeige laden
                    from database.models import Property
                    prop = session.get(Property, classification['property_id'])
                    if prop:
                        result['property_name'] = prop.name or prop.full_address

                # Ordnerzuweisung aus Klassifikation
                assigned_folder_name = None
                folder_created = False
                folder_id = classification.get('primary_folder_id')
                folder_path = classification.get('primary_folder_path')

                # Prüfen ob ein intelligenter Ordner gefunden wurde (nicht nur Posteingang)
                if folder_id:
                    folder = session.get(Folder, folder_id)
                    if folder and folder.name != 'Posteingang':
                        # Intelligenter Ordner gefunden
                        document.folder_id = folder_id
                        assigned_folder_name = folder.name
                        result['folder_path'] = folder_path
                        # Ordner wurde möglicherweise neu erstellt
                        folder_created = classification.get('confidence', 0) > 0.7
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
                                color="#607D8B"  # Grau-Blau für auto-erstellte Ordner
                            )
                            session.add(new_folder)
                            session.flush()  # ID generieren
                            document.folder_id = new_folder.id
                            assigned_folder_name = sender_name
                            folder_created = True

                result['folder_name'] = assigned_folder_name
                result['folder_created'] = folder_created

                # ============================================================
                # E-MAIL-ANHÄNGE IN GLEICHEN ORDNER VERSCHIEBEN
                # ============================================================
                if result.get('attachments') and document.folder_id:
                    for att_info in result['attachments']:
                        try:
                            att_doc = session.get(Document, att_info['id'])
                            if att_doc:
                                att_doc.folder_id = document.folder_id
                                if is_debug:
                                    debug_log(f"📁 Anhang '{att_info['filename']}' in Ordner verschoben", "info")
                        except Exception:
                            pass  # Fehler bei Anhang-Zuordnung ignorieren

                # ============================================================
                # VIRTUELLE ORDNER-ZUORDNUNG (Dokument in mehreren Ordnern)
                # ============================================================
                virtual_folder_ids = classification.get('virtual_folder_ids', [])
                if virtual_folder_ids:
                    try:
                        # Virtuelle Ordner zuweisen
                        classifier.assign_to_virtual_folders(document_id, virtual_folder_ids)
                        # Namen der virtuellen Ordner für Anzeige sammeln
                        for vf_id in virtual_folder_ids:
                            vf = session.get(Folder, vf_id)
                            if vf:
                                result['virtual_folders'].append(vf.name)
                    except Exception:
                        pass  # Fehler bei virtuellen Ordnern ignorieren

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
                if is_debug:
                    debug_log("🔍 Aktualisiere Suchindex...", "info")
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

                if is_debug:
                    debug_log("💾 Speichere Dokument...", "info")
                document.status = DocumentStatus.COMPLETED
                session.commit()

                if is_debug:
                    debug_log("✅ Verarbeitung abgeschlossen!", "success")
                return result

            except Exception as e:
                if is_debug:
                    import traceback
                    debug_log(f"❌ FEHLER: {str(e)[:300]}", "error")
                    debug_log(f"📍 Traceback: {traceback.format_exc()[-500:]}", "error")
                document.status = DocumentStatus.ERROR
                document.processing_error = str(e)[:500]  # Begrenze Fehlerlänge
                try:
                    session.commit()
                except Exception:
                    pass  # Commit-Fehler ignorieren
                # NICHT raise - stattdessen Fehler protokollieren und weitermachen
                result['error'] = str(e)[:200]
                return result

    except Exception as outer_err:
        if is_debug:
            import traceback
            debug_log(f"❌ ÄUSSERER FEHLER: {str(outer_err)[:300]}", "error")
            debug_log(f"📍 Traceback: {traceback.format_exc()[-500:]}", "error")
        return {'error': str(outer_err)[:200]}

    return result


with tab_upload:
    st.subheader("Einzelnes Dokument hochladen")

    uploaded_file = st.file_uploader(
        "PDF, Bild oder E-Mail auswählen",
        type=['pdf', 'jpg', 'jpeg', 'png', 'eml', 'msg'],
        help="Unterstützte Formate: PDF, JPG, PNG, EML, MSG (Outlook)"
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
                    # Debug-Log vor Start löschen
                    if st.session_state.get('debug_mode', False):
                        clear_debug_log()

                    with st.spinner("Verarbeite Dokument (OCR & Analyse)..."):
                        try:
                            process_result = process_document(doc_id, file_data, user_id)

                            # Debug-Panel anzeigen
                            show_debug_panel()

                            # Fehler anzeigen falls vorhanden
                            if process_result.get('error'):
                                st.error(f"⚠️ Fehler bei Verarbeitung: {process_result['error']}")
                            else:
                                st.success("Dokument erfolgreich verarbeitet!")

                            # Ordnerzuweisung anzeigen
                            if process_result.get('folder_name'):
                                folder_info = process_result['folder_name']
                                if process_result.get('folder_path'):
                                    folder_info = process_result['folder_path']
                                if process_result.get('folder_created'):
                                    st.info(f"📁 **Neuer Ordner erstellt:** '{folder_info}'")
                                else:
                                    st.info(f"📁 **Eingeordnet in:** '{folder_info}'")
                            else:
                                st.warning("📁 Kein passender Ordner gefunden. Dokument bleibt im Posteingang.")

                            # Kategorie und Unterkategorie anzeigen
                            if process_result.get('subcategory'):
                                st.info(f"🏷️ **Kategorie:** {process_result['category']} / {process_result['subcategory']}")

                            # Immobilien-Zuordnung anzeigen
                            if process_result.get('property_name'):
                                st.success(f"🏠 **Immobilie erkannt:** {process_result['property_name']}")

                            # Virtuelle Ordner-Zuordnungen anzeigen
                            if process_result.get('virtual_folders'):
                                vf_list = ", ".join(process_result['virtual_folders'])
                                st.info(f"📂 **Auch verfügbar in:** {vf_list}")

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

    import base64
    import json

    # Option 1: Mehrere Dateien auswählen
    st.markdown("### 📄 Mehrere Dateien hochladen")
    st.info("💡 Wählen Sie alle Dateien eines Ordners aus (im Datei-Dialog: **Strg+A** zum Auswählen aller Dateien)")

    folder_files = st.file_uploader(
        "Dateien auswählen",
        type=['pdf', 'jpg', 'jpeg', 'png', 'gif', 'doc', 'docx', 'xls', 'xlsx', 'txt', 'eml', 'msg'],
        accept_multiple_files=True,
        key="multi_file_upload",
        help="Halten Sie Strg gedrückt um mehrere Dateien auszuwählen, oder Strg+A für alle"
    )

    if folder_files and len(folder_files) > 0:
        st.success(f"✅ **{len(folder_files)} Dateien** ausgewählt")

        # Optionen
        col_opt1, col_opt2 = st.columns(2)
        with col_opt1:
            # Zielordner auswählen
            with get_db() as session:
                folders_db = session.query(Folder).filter(
                    Folder.user_id == user_id
                ).order_by(Folder.name).all()
                folder_options = {"__posteingang__": "📥 Posteingang (Standard)"}
                folder_options.update({str(f.id): f"📁 {f.name}" for f in folders_db})

            target_folder = st.selectbox(
                "Zielordner",
                options=list(folder_options.keys()),
                format_func=lambda x: folder_options.get(x, "Posteingang"),
                key="multi_file_target"
            )
        with col_opt2:
            process_multi = st.checkbox("Mit OCR verarbeiten", value=True, key="process_multi_files")

        if st.button("📥 Dateien importieren", type="primary", key="import_multi_files"):
            progress_bar = st.progress(0, text="Starte Import...")
            imported = 0
            errors = 0

            target_id = None if target_folder == "__posteingang__" else int(target_folder)

            for idx, file in enumerate(folder_files):
                progress_bar.progress((idx + 1) / len(folder_files), text=f"Importiere {idx + 1}/{len(folder_files)}: {file.name[:30]}...")

                try:
                    file_data = file.read()
                    doc_id = save_document(file_data, file.name, user_id)

                    # Zielordner setzen
                    if target_id:
                        with get_db() as session:
                            doc = session.get(Document, doc_id)
                            if doc:
                                doc.folder_id = target_id
                                session.commit()

                    # OCR verarbeiten
                    if process_multi:
                        try:
                            process_document(doc_id, file_data, user_id)
                        except Exception as proc_err:
                            st.toast(f"⚠️ Verarbeitung von {file.name}: {str(proc_err)[:50]}")

                    imported += 1

                except Exception as e:
                    errors += 1
                    st.warning(f"⚠️ Fehler bei {file.name}: {str(e)[:100]}")

            progress_bar.progress(1.0, text="✅ Import abgeschlossen!")
            st.success(f"✅ **{imported} Dateien** erfolgreich importiert!")
            if errors > 0:
                st.warning(f"⚠️ {errors} Fehler beim Import")

    # Option 2: ZIP-Upload für Ordnerstruktur
    st.markdown("---")
    st.markdown("### 📦 ZIP-Archiv mit Ordnerstruktur")
    st.info("💡 Um die **Unterordner-Struktur zu erhalten**: Ordner als ZIP komprimieren und hier hochladen.")

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
                # Dekodiere Dateinamen korrekt (ZIP kann CP437 oder UTF-8 verwenden)
                def decode_zip_filename(name):
                    """Dekodiert ZIP-Dateinamen mit Umlaut-Unterstützung"""
                    import unicodedata
                    try:
                        # Versuche UTF-8 (moderne ZIPs)
                        if isinstance(name, bytes):
                            decoded = name.decode('utf-8')
                        else:
                            decoded = name
                        # Normalisiere Unicode für konsistente Umlaute
                        return unicodedata.normalize('NFC', decoded)
                    except UnicodeDecodeError:
                        try:
                            # Fallback: CP437 (alte ZIP-Kodierung)
                            return name.decode('cp437')
                        except (UnicodeDecodeError, AttributeError):
                            try:
                                # Weiterer Fallback: Latin-1
                                return name.decode('latin-1') if isinstance(name, bytes) else name
                            except:
                                return str(name)

                all_files = [decode_zip_filename(f) for f in zf.namelist() if not f.endswith('/')]

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
                                except Exception as proc_err:
                                    st.toast(f"⚠️ Verarbeitung: {str(proc_err)[:50]}")

                            imported_count += 1

                        except Exception as e:
                            error_count += 1
                            st.warning(f"⚠️ Fehler bei {filename}: {str(e)[:100]}")

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
        type=['pdf', 'jpg', 'jpeg', 'png', 'gif', 'doc', 'docx', 'xls', 'xlsx', 'txt', 'eml', 'msg'],
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
                        except Exception as proc_err:
                            st.toast(f"⚠️ Verarbeitung von {file.name}: {str(proc_err)[:50]}")

                    imported += 1
                except Exception as e:
                    st.warning(f"⚠️ Fehler bei {file.name}: {str(e)[:100]}")

            progress_bar.progress(1.0, text="✅ Fertig!")
            st.success(f"✅ **{imported} Dateien** erfolgreich importiert!")


with tab_cloud:
    st.subheader("☁️ Cloud-Import")
    st.markdown("Importieren Sie Dokumente direkt aus Dropbox oder Google Drive.")

    # Import Cloud-Sync Service
    CLOUD_IMPORT_ERROR = None
    try:
        from services.cloud_sync_service import CloudSyncService, CloudProvider, SyncStatus
        CLOUD_IMPORT_AVAILABLE = True
    except ImportError as e:
        CLOUD_IMPORT_AVAILABLE = False
        CLOUD_IMPORT_ERROR = f"ImportError: {e}"
    except Exception as e:
        CLOUD_IMPORT_AVAILABLE = False
        CLOUD_IMPORT_ERROR = f"{type(e).__name__}: {e}"

    if not CLOUD_IMPORT_AVAILABLE:
        st.error(f"Cloud-Import Module nicht verfügbar. {CLOUD_IMPORT_ERROR or ''}")
    else:
        user_id = get_current_user_id()
        cloud_service = CloudSyncService(user_id)

        # Duplikate automatisch bereinigen (einmalig pro Session)
        if 'cloud_duplicates_cleaned' not in st.session_state:
            deleted = cloud_service.cleanup_duplicate_connections()
            st.session_state.cloud_duplicates_cleaned = True
            if deleted > 0:
                st.toast(f"✅ {deleted} doppelte Cloud-Verbindungen bereinigt")

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

        # Debug-Modus Toggle
        st.markdown("---")
        debug_mode = st.checkbox(
            "🔧 **Debug-Modus aktivieren**",
            value=False,
            help="Aktiviert detailliertes Logging um Sync-Probleme zu diagnostizieren. "
                 "Zeigt Live-Events, API-Aufrufe, Speicherverbrauch und Fehleranalyse."
        )

        if debug_mode:
            st.info(
                "🔧 **Debug-Modus aktiv** - Während des Imports werden detaillierte "
                "Diagnose-Informationen angezeigt: Events, API-Calls, DB-Status, Speicher und Fehler."
            )

        # Buttons nebeneinander
        col_import, col_diagnose = st.columns([2, 1])

        with col_import:
            import_clicked = st.button("☁️ Import starten", type="primary", disabled=not cloud_link or not detected_provider)

        with col_diagnose:
            diagnose_clicked = st.button("🔍 Diagnose", disabled=not cloud_link or detected_provider != "google_drive",
                                         help="Zeigt Details zum Google Drive Ordner")

        # Diagnose-Funktion
        if diagnose_clicked and cloud_link and detected_provider == "google_drive":
            import requests
            import re
            from config.settings import get_api_key

            # Folder-ID extrahieren
            folder_id = None
            for pattern in [r'folders/([a-zA-Z0-9_-]+)', r'id=([a-zA-Z0-9_-]+)']:
                match = re.search(pattern, cloud_link)
                if match:
                    folder_id = match.group(1)
                    break

            if folder_id:
                st.markdown("---")
                st.subheader("🔍 Google Drive Diagnose")
                st.code(f"Folder-ID: {folder_id}")

                # ========== API TEST ==========
                api_key = get_api_key('GOOGLE_API_KEY')
                if api_key:
                    st.markdown("### 🔑 Google Drive API Test")
                    st.success(f"API Key gefunden: `{api_key[:10]}...`")

                    with st.spinner("Teste Google Drive API..."):
                        try:
                            BASE = "https://www.googleapis.com/drive/v3/files"
                            params = {
                                "q": f"'{folder_id}' in parents and trashed=false",
                                "fields": "files(id,name,mimeType,size)",
                                "pageSize": 100,
                                "key": api_key,
                            }
                            api_response = requests.get(BASE, params=params, timeout=30)

                            st.markdown(f"**API Status:** {api_response.status_code}")

                            if api_response.status_code == 200:
                                data = api_response.json()
                                files = data.get("files", [])
                                st.success(f"✅ API funktioniert! {len(files)} Einträge gefunden")

                                if files:
                                    folders = [f for f in files if f.get('mimeType') == 'application/vnd.google-apps.folder']
                                    docs = [f for f in files if f.get('mimeType') != 'application/vnd.google-apps.folder']

                                    st.markdown(f"**Ordner:** {len(folders)} | **Dateien:** {len(docs)}")

                                    with st.expander(f"📋 API-Ergebnisse ({len(files)} Einträge)", expanded=True):
                                        for f in files[:20]:
                                            mime = f.get('mimeType', '')
                                            icon = "📁" if 'folder' in mime else "📄"
                                            st.write(f"{icon} {f.get('name')} (`{mime[:30]}`)")
                                        if len(files) > 20:
                                            st.caption(f"... und {len(files) - 20} weitere")

                                    # Test Unterordner
                                    if folders:
                                        st.markdown("### 📂 Test Unterordner-Zugriff")
                                        test_folder = folders[0]
                                        st.markdown(f"Teste Zugriff auf: **{test_folder.get('name')}**")

                                        subfolder_params = {
                                            "q": f"'{test_folder.get('id')}' in parents and trashed=false",
                                            "fields": "files(id,name,mimeType)",
                                            "pageSize": 50,
                                            "key": api_key,
                                        }
                                        sub_response = requests.get(BASE, params=subfolder_params, timeout=30)

                                        if sub_response.status_code == 200:
                                            sub_data = sub_response.json()
                                            sub_files = sub_data.get("files", [])
                                            st.success(f"✅ Unterordner-Zugriff OK! {len(sub_files)} Einträge in '{test_folder.get('name')}'")

                                            if sub_files:
                                                with st.expander(f"Inhalt von '{test_folder.get('name')}'"):
                                                    for sf in sub_files[:10]:
                                                        mime = sf.get('mimeType', '')
                                                        icon = "📁" if 'folder' in mime else "📄"
                                                        st.write(f"{icon} {sf.get('name')}")
                                            else:
                                                st.info("Unterordner ist leer oder enthält nur Google Docs")
                                        else:
                                            st.error(f"❌ Unterordner-Zugriff fehlgeschlagen: {sub_response.status_code}")
                                            st.code(sub_response.text[:500])
                                else:
                                    st.warning("Ordner ist leer oder API hat keine Berechtigung")

                            elif api_response.status_code == 404:
                                st.error("❌ **404 - Ordner nicht gefunden**")
                                st.markdown("""
                                **Mögliche Ursachen:**
                                1. Der Ordner ist nicht mit "Jeder mit dem Link" geteilt
                                2. Die Google Drive API ist nicht aktiviert
                                3. Der API Key hat keine Berechtigung

                                **Lösung:** Öffnen Sie den Ordner in Google Drive → Rechtsklick → Freigeben → "Jeder mit dem Link" → "Betrachter"
                                """)
                            elif api_response.status_code == 403:
                                st.error("❌ **403 - Zugriff verweigert**")
                                st.code(api_response.text[:500])
                            else:
                                st.error(f"❌ API Fehler: {api_response.status_code}")
                                st.code(api_response.text[:500])

                        except Exception as e:
                            st.error(f"API Fehler: {e}")
                else:
                    st.warning("⚠️ Kein Google API Key in Streamlit Secrets gefunden")
                    st.markdown("Bitte `GOOGLE_API_KEY` in Streamlit Secrets hinterlegen")

                st.markdown("---")
                st.markdown("### 🌐 Web-Scraping Fallback")

                with st.spinner("Lade Ordner-Inhalt..."):
                    try:
                        headers = {
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        }

                        # Standard-URL
                        url = f"https://drive.google.com/drive/folders/{folder_id}"
                        response = requests.get(url, headers=headers, timeout=30, allow_redirects=True)

                        st.markdown(f"**HTTP Status:** {response.status_code}")
                        st.markdown(f"**Finale URL:** `{response.url[:80]}...`")
                        st.markdown(f"**HTML Länge:** {len(response.text)} Zeichen")

                        html = response.text
                        html_lower = html.lower()

                        # Zugriffsprüfung
                        if 'accounts.google.com' in response.url:
                            st.error("❌ **Problem:** Weiterleitung zur Anmeldung - Ordner ist NICHT öffentlich!")
                        elif 'you need access' in html_lower:
                            st.error("❌ **Problem:** Zugriff verweigert!")
                        else:
                            st.success("✓ Ordner scheint zugänglich")

                        # Dateien suchen mit verbesserten Methoden
                        st.markdown("**Suche nach Dateien/Ordnern:**")

                        found_items = []
                        seen_ids = set()

                        def is_valid_name(name):
                            """Prüft ob ein Name ein gültiger Datei/Ordnername ist"""
                            if not name or len(name) < 2 or len(name) > 200:
                                return False
                            # Filtere URLs, JS-Code und System-Strings
                            invalid = ['http', 'https', 'clients', '.com', '.google',
                                       'sign in', 'anmelden', 'null', 'undefined',
                                       'function', 'return', 'var ', 'const ', 'window.',
                                       '();', '{}', 'prototype', 'throw', 'catch']
                            name_lower = name.lower()
                            if any(inv in name_lower for inv in invalid):
                                return False
                            # Muss mindestens einen Buchstaben enthalten
                            if not re.search(r'[a-zA-ZäöüÄÖÜß]', name):
                                return False
                            return True

                        # Methode 1: Suche nach Dateinamen mit Erweiterungen
                        # Flexibleres Pattern: ID gefolgt von Name mit Erweiterung
                        ext_pattern = r'"([a-zA-Z0-9_-]{20,})"[,\]\[null"]*"([^"]+\.(?:pdf|jpg|jpeg|png|gif|doc|docx|xls|xlsx|ppt|pptx|txt|csv|zip|PDF|JPG|PNG|DOC|XLS))"'
                        for fid, name in re.findall(ext_pattern, html):
                            if fid not in seen_ids and is_valid_name(name):
                                seen_ids.add(fid)
                                found_items.append((fid, name, "📄"))

                        # Methode 2: Name mit Erweiterung gefolgt von ID
                        rev_pattern = r'"([^"]+\.(?:pdf|jpg|jpeg|png|doc|docx|xls|xlsx|txt|PDF|JPG|PNG))"[,\]\[null"]*"([a-zA-Z0-9_-]{20,})"'
                        for name, fid in re.findall(rev_pattern, html):
                            if fid not in seen_ids and is_valid_name(name):
                                seen_ids.add(fid)
                                found_items.append((fid, name, "📄"))

                        # Methode 3: Suche alle .pdf Erwähnungen ZUERST (vor Ordnern)
                        pdf_names = re.findall(r'"([^"]{3,80}\.pdf)"', html, re.IGNORECASE)
                        for name in pdf_names:
                            if is_valid_name(name) and name not in [f[1] for f in found_items]:
                                # Suche ID in der Nähe
                                idx = html.find(f'"{name}"')
                                if idx >= 0:
                                    context = html[max(0,idx-150):idx+150]
                                    id_match = re.search(r'"([a-zA-Z0-9_-]{25,})"', context)
                                    if id_match:
                                        fid = id_match.group(1)
                                        if fid not in seen_ids:
                                            seen_ids.add(fid)
                                            found_items.append((fid, name, "📄"))

                        # Methode 4: Alle Ordner-IDs aus /folders/ Links
                        folder_ids_found = set(re.findall(r'/folders/([a-zA-Z0-9_-]{20,})', html))
                        folder_ids_found.discard(folder_id)
                        for fid in folder_ids_found:
                            if fid not in seen_ids:
                                # Suche Namen in der Nähe der ID
                                idx = html.find(fid)
                                if idx >= 0:
                                    context = html[max(0,idx-100):idx+200]
                                    # Suche nach "Name" nach der ID
                                    name_match = re.search(rf'{fid}"[,\]\[null"]*"([^"]+)"', context)
                                    if name_match and is_valid_name(name_match.group(1)):
                                        name = name_match.group(1)
                                        # WICHTIG: Prüfen ob es eine Datei ist (hat Erweiterung)
                                        is_file = bool(re.search(r'\.\w{2,5}$', name))
                                        seen_ids.add(fid)
                                        found_items.append((fid, name, "📄" if is_file else "📁"))
                                    else:
                                        seen_ids.add(fid)
                                        found_items.append((fid, f"Ordner {len(found_items)+1}", "📁"))

                        # Methode 5: data-id Attribute mit aria-label/title in der Nähe
                        for match in re.finditer(r'data-id="([a-zA-Z0-9_-]{20,})"', html):
                            fid = match.group(1)
                            if fid not in seen_ids:
                                # Hole Kontext um das Attribut
                                start = max(0, match.start() - 300)
                                end = min(len(html), match.end() + 300)
                                context = html[start:end]

                                # Suche nach aria-label oder data-tooltip
                                label = re.search(r'(?:aria-label|data-tooltip|title)="([^"]+)"', context)
                                if label and is_valid_name(label.group(1)):
                                    name = label.group(1)
                                    seen_ids.add(fid)
                                    is_file = bool(re.search(r'\.\w{2,5}$', name))
                                    found_items.append((fid, name, "📄" if is_file else "📁"))

                        # Methode 6: Kompakte JSON-Struktur ["ID","Name"]
                        compact_pattern = r'\["([a-zA-Z0-9_-]{25,})",\s*"([^"]{2,100})"'
                        for fid, name in re.findall(compact_pattern, html):
                            if fid not in seen_ids and is_valid_name(name):
                                seen_ids.add(fid)
                                is_file = bool(re.search(r'\.\w{2,5}$', name))
                                found_items.append((fid, name, "📄" if is_file else "📁"))

                        col1, col2 = st.columns(2)
                        with col1:
                            st.metric("Gefundene Elemente", len(found_items))
                        with col2:
                            files_count = len([f for f in found_items if f[2] == "📄"])
                            folders_count = len([f for f in found_items if f[2] == "📁"])
                            st.metric("Dateien / Ordner", f"{files_count} / {folders_count}")

                        if found_items:
                            with st.expander(f"📋 Gefundene Elemente ({len(found_items)})", expanded=True):
                                for fid, name, icon in found_items[:30]:
                                    st.write(f"{icon} {name}")
                                if len(found_items) > 30:
                                    st.caption(f"... und {len(found_items) - 30} weitere")
                        else:
                            st.warning("⚠️ Keine Dateien/Ordner im HTML gefunden!")
                            st.markdown("""
**Mögliche Ursachen:**
1. **Google lädt Inhalte mit JavaScript** - nicht direkt im HTML
2. Der Ordner ist leer
3. Das HTML-Format hat sich geändert

**Empfehlung:** Teilen Sie die Debug-Info unten mit dem Entwickler.
                            """)

                        # Debug-Info
                        with st.expander("🔧 Debug-Info", expanded=True):
                            st.markdown("**Gefundene Marker im HTML:**")
                            markers = {
                                "data-id Attribute": len(re.findall(r'data-id="[a-zA-Z0-9_-]{20,}"', html)),
                                "file/d/ Links": len(re.findall(r'/file/d/[a-zA-Z0-9_-]{20,}', html)),
                                "folders/ Links": len(re.findall(r'/folders/[a-zA-Z0-9_-]{20,}', html)),
                                "PDF im Text": html.lower().count('.pdf'),
                                "Ordner-ID im HTML": html.count(folder_id),
                            }
                            for marker, count in markers.items():
                                st.write(f"- {marker}: {count}")

                            # Zeige was jede Methode findet
                            st.markdown("---")
                            st.markdown("**Details pro Methode:**")

                            # Methode 1 Debug
                            m1_results = re.findall(r'"([a-zA-Z0-9_-]{20,})"[,\]\[null"]*"([^"]+\.(?:pdf|jpg|jpeg|png|gif|doc|docx|xls|xlsx|ppt|pptx|txt|csv|zip|PDF|JPG|PNG|DOC|XLS))"', html)
                            st.write(f"Methode 1 (ID→Datei): {len(m1_results)} Treffer")
                            if m1_results[:3]:
                                for fid, name in m1_results[:3]:
                                    st.code(f"  {fid[:15]}... → {name}")

                            # Methode 2 Debug
                            m2_results = re.findall(r'"([^"]+\.(?:pdf|jpg|jpeg|png|doc|docx|xls|xlsx|txt|PDF|JPG|PNG))"[,\]\[null"]*"([a-zA-Z0-9_-]{20,})"', html)
                            st.write(f"Methode 2 (Datei→ID): {len(m2_results)} Treffer")
                            if m2_results[:3]:
                                for name, fid in m2_results[:3]:
                                    st.code(f"  {name} → {fid[:15]}...")

                            # Methode 3 Debug - PDFs
                            m3_results = re.findall(r'"([^"]{3,80}\.pdf)"', html, re.IGNORECASE)
                            st.write(f"Methode 3 (PDF-Namen): {len(m3_results)} Treffer")
                            valid_pdfs = [n for n in m3_results if is_valid_name(n)]
                            st.write(f"  Davon gültig: {len(valid_pdfs)}")
                            if valid_pdfs[:5]:
                                for name in valid_pdfs[:5]:
                                    st.code(f"  📄 {name}")

                            # Methode 4 Debug - Ordner
                            m4_results = set(re.findall(r'/folders/([a-zA-Z0-9_-]{20,})', html))
                            m4_results.discard(folder_id)
                            st.write(f"Methode 4 (/folders/ Links): {len(m4_results)} Ordner-IDs")

                            # Zeige Ordnernamen die gefunden werden
                            folder_names_found = []
                            for fid in list(m4_results)[:5]:
                                idx = html.find(fid)
                                if idx >= 0:
                                    context = html[max(0,idx-100):idx+200]
                                    name_match = re.search(rf'{fid}"[,\]\[null"]*"([^"]+)"', context)
                                    if name_match:
                                        folder_names_found.append((fid[:15], name_match.group(1)))
                            if folder_names_found:
                                for fid, name in folder_names_found:
                                    is_file = bool(re.search(r'\.\w{2,5}$', name))
                                    icon = "📄" if is_file else "📁"
                                    valid = "✓" if is_valid_name(name) else "✗"
                                    st.code(f"  {icon} {valid} {fid}... → {name}")

                            # Zeige Beispiel-Datenstruktur
                            st.markdown("---")
                            st.markdown("**Suche nach JSON-Daten im HTML:**")

                            # Suche nach typischen Google Drive Datenstrukturen
                            # Google verwendet oft Arrays wie: ["ID","Titel",null,null,...]
                            json_arrays = re.findall(r'\["([a-zA-Z0-9_-]{25,})","([^"]{2,60})"', html)
                            st.write(f'JSON-Arrays ["ID","Name"]: {len(json_arrays)} gefunden')

                            # Filtere gültige Namen
                            valid_arrays = [(fid, name) for fid, name in json_arrays if is_valid_name(name)]
                            st.write(f"Davon mit gültigen Namen: {len(valid_arrays)}")
                            if valid_arrays[:5]:
                                for fid, name in valid_arrays[:5]:
                                    is_file = bool(re.search(r'\.\w{2,5}$', name))
                                    st.code(f"  {'📄' if is_file else '📁'} {name}")

                            st.markdown("---")
                            st.markdown("**Erste 4000 Zeichen des HTML:**")
                            st.code(html[:4000])

                    except Exception as e:
                        st.error(f"Fehler: {e}")

        # Import starten
        if import_clicked:
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

                    # Debug-Container (nur wenn Debug-Modus aktiv)
                    debug_container = None
                    debug_log_container = None
                    debug_api_container = None
                    debug_files_container = None
                    debug_memory_container = None
                    debug_errors_container = None

                    if debug_mode:
                        st.markdown("---")
                        st.markdown("### 🔧 Debug-Konsole (Live)")
                        debug_container = st.container()
                        with debug_container:
                            debug_cols = st.columns([2, 2, 1])
                            with debug_cols[0]:
                                st.markdown("**📋 Events**")
                                debug_log_container = st.empty()
                            with debug_cols[1]:
                                st.markdown("**🌐 API-Calls**")
                                debug_api_container = st.empty()
                            with debug_cols[2]:
                                st.markdown("**💾 RAM & Disk**")
                                debug_memory_container = st.empty()

                            st.markdown("**📄 Datei-Operationen**")
                            debug_files_container = st.empty()

                            st.markdown("**❌ Fehler**")
                            debug_errors_container = st.empty()

                    with progress_container:
                        progress_bar = st.progress(0, text="Initialisiere...")
                        status_container = st.empty()
                        file_info_container = st.empty()
                        step_detail_container = st.empty()  # NEU: Detaillierte Schritte
                        stats_container = st.empty()

                        # Synchronisieren mit Fortschrittsanzeige
                        final_result = None
                        sync_error = None
                        try:
                            for progress in cloud_service.sync_connection_with_progress(
                                conn.id,
                                enable_diagnostics=debug_mode,
                                batch_size=0  # 0 = unbegrenzt (RAM-Isolation durch Subprocess-OCR)
                            ):
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

                                # === DEBUG-MODUS: Live-Diagnose anzeigen ===
                                if debug_mode and debug_container:
                                    diag_live = progress.get("diagnostics_live")
                                    if diag_live:
                                        # Events anzeigen
                                        if debug_log_container and diag_live.get("events"):
                                            events_text = ""
                                            for evt in reversed(diag_live["events"][-10:]):
                                                ts = evt.get("timestamp", "")[-12:-4]  # HH:MM:SS
                                                elapsed = evt.get("elapsed_ms", 0)
                                                evt_type = evt.get("type", "")
                                                detail = evt.get("detail", "")[:50]
                                                events_text += f"`{ts}` [{elapsed}ms] **{evt_type}**\n{detail}\n\n"
                                            debug_log_container.markdown(events_text or "*Keine Events*")

                                        # API-Calls anzeigen
                                        if debug_api_container and diag_live.get("api_calls"):
                                            api_text = ""
                                            for call in reversed(diag_live["api_calls"][-5:]):
                                                status = call.get("status_code", 0)
                                                duration = call.get("duration_ms", 0)
                                                endpoint = call.get("endpoint", "")[:30]
                                                status_icon = "✅" if status == 200 else "❌"
                                                api_text += f"{status_icon} `{status}` {duration:.0f}ms\n`{endpoint}...`\n\n"
                                            debug_api_container.markdown(api_text or "*Keine API-Calls*")

                                        # Speicher und Disk anzeigen
                                        if debug_memory_container and diag_live.get("memory_snapshots"):
                                            mem = diag_live["memory_snapshots"][-1] if diag_live["memory_snapshots"] else {}
                                            rss = mem.get("rss_mb", 0)
                                            label = mem.get("label", "")
                                            disk_used = mem.get("disk_tmp_used_mb", 0)
                                            disk_free = mem.get("disk_tmp_free_mb", 0)
                                            disk_percent = mem.get("disk_tmp_percent", 0)
                                            temp_count = mem.get("temp_files_count", 0)

                                            # Farbe basierend auf kritischen Werten
                                            ram_color = "🔴" if rss > 400 else "🟡" if rss > 300 else "🟢"
                                            disk_color = "🔴" if disk_free < 50 else "🟡" if disk_free < 100 else "🟢"

                                            mem_text = f"**RAM:** {ram_color} {rss:.1f} MB\n"
                                            mem_text += f"**Disk:** {disk_color} {disk_free:.1f} MB frei\n"
                                            mem_text += f"*/tmp: {disk_percent:.1f}% belegt*\n"
                                            mem_text += f"*Temp-Files: {temp_count}*\n"
                                            mem_text += f"`{label}`"
                                            debug_memory_container.markdown(mem_text)
                                        elif debug_memory_container:
                                            debug_memory_container.markdown("*Monitoring nicht verfügbar*")

                                        # Datei-Operationen anzeigen
                                        if debug_files_container and diag_live.get("file_operations"):
                                            files_text = ""
                                            for op in reversed(diag_live["file_operations"][-5:]):
                                                fname = op.get("filename", "")[:40]
                                                operation = op.get("operation", "")
                                                status = op.get("status", "")
                                                duration = op.get("duration_ms", 0)
                                                status_icon = "✅" if status == "success" else "⏭️" if status == "skipped" else "❌"
                                                files_text += f"{status_icon} `{fname}` - {operation} ({duration:.0f}ms)\n"
                                            debug_files_container.code(files_text or "Keine Datei-Operationen")

                                        # Fehler anzeigen
                                        if debug_errors_container and diag_live.get("errors"):
                                            errors_text = ""
                                            for err in diag_live["errors"][-5:]:
                                                err_type = err.get("type", "")
                                                msg = err.get("message", "")[:60]
                                                exc_type = err.get("exception_type", "")
                                                errors_text += f"🔴 **{err_type}**: {msg}\n"
                                                if exc_type:
                                                    errors_text += f"   Exception: `{exc_type}`\n"
                                            debug_errors_container.markdown(errors_text)
                                        elif debug_errors_container:
                                            debug_errors_container.markdown("*Keine Fehler* ✅")
                        except Exception as sync_err:
                            sync_error = str(sync_err)
                            st.error(f"❌ Sync-Fehler: {sync_error}")
                            import traceback
                            with st.expander("Fehlerdetails"):
                                st.code(traceback.format_exc())

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

                                # Debug-Info zur Verbindung
                                with st.expander("🔧 Verbindungs-Details", expanded=True):
                                    st.code(f"""Connection ID: {conn.id}
Provider: {conn.provider}
Remote Folder ID: {conn.folder_id}
Remote Folder Path: {conn.folder_path}
Is Active: {conn.is_active}
File Extensions: {conn.file_extensions}""")

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

**5. Google Drive Format-Änderung:**
   - Google ändert manchmal das HTML-Format
   - Prüfen Sie die Debug-Datei unter `data/debug/` für Details
                                    """)

                                # Button zum Testen des Links
                                st.markdown(f"[🔗 Link im Browser öffnen]({cloud_link})")

                                # Debug-Informationen anzeigen
                                from pathlib import Path
                                debug_path = Path("data/debug")
                                if debug_path.exists():
                                    debug_files = list(debug_path.glob("gdrive_debug_*.html"))
                                    if debug_files:
                                        with st.expander("🔧 Debug-Informationen (für Entwickler)", expanded=False):
                                            st.markdown("Eine Debug-Datei wurde erstellt. Diese kann helfen, das Problem zu analysieren:")
                                            for df in sorted(debug_files, key=lambda x: x.stat().st_mtime, reverse=True)[:3]:
                                                st.code(f"{df.name} ({df.stat().st_size / 1024:.1f} KB)")

                            if skipped > 0:
                                st.caption(f"ℹ️ {skipped} Dateien übersprungen (bereits vorhanden oder nicht unterstützt)")

                            # Fehler anzeigen wenn vorhanden
                            errors_list = final_result.get("errors", [])
                            files_error = final_result.get("files_error", 0)
                            failed_files = final_result.get("failed_files", [])

                            if files_error > 0 or errors_list:
                                st.error(f"❌ **{files_error} Dateien konnten nicht importiert werden**")

                                # Fehlgeschlagene Dateien mit Retry-Option anzeigen
                                if failed_files:
                                    with st.expander(f"🔄 Fehlgeschlagene Dateien - Einzeln wiederholen ({len(failed_files)})", expanded=True):
                                        st.markdown("Diese Dateien konnten nicht importiert werden. Sie können einzeln erneut versucht werden:")

                                        for idx, failed_entry in enumerate(failed_files[:20]):
                                            file_info = failed_entry.get("file_info", {})
                                            error_msg = failed_entry.get("error", "Unbekannter Fehler")
                                            attempts = failed_entry.get("attempt", 1)
                                            file_name = file_info.get("name", "Unbekannt")
                                            file_size = file_info.get("size", 0)
                                            size_kb = file_size / 1024

                                            col_info, col_action = st.columns([3, 1])
                                            with col_info:
                                                st.markdown(f"**{file_name}** ({size_kb:.1f} KB)")
                                                st.caption(f"Fehler: {error_msg} | Versuche: {attempts}")
                                            with col_action:
                                                if st.button("🔄 Retry", key=f"retry_single_{idx}"):
                                                    st.session_state[f"retry_file_{idx}"] = file_info
                                                    st.rerun()

                                        if len(failed_files) > 20:
                                            st.caption(f"... und {len(failed_files) - 20} weitere fehlgeschlagene Dateien")

                                        # Button zum erneuten Versuch aller fehlgeschlagenen Dateien
                                        st.markdown("---")
                                        if st.button("🔄 Alle erneut versuchen", type="primary", key="retry_all_failed"):
                                            st.session_state["retry_all_failed_files"] = failed_files
                                            st.rerun()

                                # Detaillierte Fehlerliste
                                with st.expander(f"🔍 Fehlerdetails ({len(errors_list)} Fehler)", expanded=False):
                                    if errors_list:
                                        for i, err in enumerate(errors_list[:20]):  # Nur erste 20 anzeigen
                                            st.text(f"• {err}")
                                        if len(errors_list) > 20:
                                            st.caption(f"... und {len(errors_list) - 20} weitere Fehler")
                                    else:
                                        st.text("Keine detaillierten Fehlermeldungen verfügbar")

                            if final_result.get("error") and not final_result.get("success"):
                                error_msg = final_result.get("error", "Unbekannter Fehler")
                                if "token" in error_msg.lower() or "auth" in error_msg.lower():
                                    st.warning(f"⚠️ API-Authentifizierung erforderlich. Bitte konfigurieren Sie Ihre Cloud-API unter **Einstellungen → Cloud-Sync**.")
                                else:
                                    st.error(f"❌ Import fehlgeschlagen: {error_msg}")

                            # === DEBUG-MODUS: Vollständiger Diagnose-Bericht ===
                            if debug_mode and final_result:
                                st.markdown("---")
                                st.markdown("### 🔧 Vollständiger Diagnose-Bericht")

                                # Zusammenfassung anzeigen
                                diagnostics = final_result.get("diagnostics")
                                if diagnostics:
                                    st.markdown("#### 📊 Zusammenfassung")
                                    diag_cols = st.columns(4)
                                    with diag_cols[0]:
                                        st.metric("Dauer", f"{diagnostics.get('duration_seconds', 0):.1f}s")
                                    with diag_cols[1]:
                                        st.metric("Dateien verarbeitet",
                                                  f"{diagnostics.get('files_successful', 0)}/{diagnostics.get('total_files', 0)}")
                                    with diag_cols[2]:
                                        st.metric("API-Aufrufe", diagnostics.get('api_calls_total', 0))
                                    with diag_cols[3]:
                                        mem_growth = diagnostics.get('memory_growth_mb', 0)
                                        st.metric("Speicherwachstum", f"{mem_growth:+.1f} MB")

                                    # Detaillierte Statistiken
                                    with st.expander("📈 Detaillierte Statistiken", expanded=True):
                                        stat_cols = st.columns(2)
                                        with stat_cols[0]:
                                            st.markdown("**Datei-Statistiken:**")
                                            st.write(f"- Erfolgreich: {diagnostics.get('files_successful', 0)}")
                                            st.write(f"- Übersprungen: {diagnostics.get('files_skipped', 0)}")
                                            st.write(f"- Fehlgeschlagen: {diagnostics.get('files_failed', 0)}")
                                            if diagnostics.get('last_successful_file'):
                                                st.write(f"- Letzte erfolgreiche: `{diagnostics.get('last_successful_file')}`")
                                        with stat_cols[1]:
                                            st.markdown("**API-Statistiken:**")
                                            st.write(f"- Aufrufe gesamt: {diagnostics.get('api_calls_total', 0)}")
                                            st.write(f"- Fehlgeschlagen: {diagnostics.get('api_calls_failed', 0)}")
                                            st.write(f"- Ø Dauer: {diagnostics.get('api_avg_duration_ms', 0):.0f}ms")
                                            st.write(f"- Max Dauer: {diagnostics.get('api_max_duration_ms', 0):.0f}ms")

                                        st.markdown("**Speicher-Statistiken:**")
                                        st.write(f"- Start: {diagnostics.get('memory_start_mb', 0):.1f} MB")
                                        st.write(f"- Ende: {diagnostics.get('memory_end_mb', 0):.1f} MB")
                                        st.write(f"- Maximum: {diagnostics.get('memory_max_mb', 0):.1f} MB")

                                # Fehleranalyse anzeigen
                                analysis = final_result.get("diagnostics_analysis")
                                if analysis:
                                    causes = analysis.get("possible_causes", [])
                                    recommendations = analysis.get("recommendations", [])

                                    if causes or recommendations:
                                        with st.expander("🔍 Fehleranalyse", expanded=True):
                                            if causes:
                                                st.markdown("**Mögliche Ursachen:**")
                                                for cause in causes:
                                                    st.warning(f"⚠️ {cause}")

                                            if recommendations:
                                                st.markdown("**Empfehlungen:**")
                                                for rec in recommendations:
                                                    st.info(f"💡 {rec}")

                                            last_success = analysis.get("last_successful")
                                            if last_success:
                                                st.markdown("**Letzter erfolgreicher Import:**")
                                                st.code(f"Datei: {last_success.get('file')}\n"
                                                        f"Index: {last_success.get('index')}\n"
                                                        f"Zeit: {last_success.get('time')}")

                                # Vollständiger Bericht zum Download
                                full_report = final_result.get("diagnostics_full_report")
                                if full_report:
                                    import json
                                    with st.expander("📄 Vollständiger Debug-Report (JSON)", expanded=False):
                                        # Events zeigen
                                        st.markdown("**Letzte Events:**")
                                        events = full_report.get("events", [])[-20:]
                                        for evt in events:
                                            ts = evt.get("timestamp", "")[-12:]
                                            st.text(f"[{ts}] {evt.get('type')}: {evt.get('detail', '')[:80]}")

                                        # API-Calls zeigen
                                        st.markdown("**API-Aufrufe:**")
                                        api_calls = full_report.get("api_calls", [])[-10:]
                                        for call in api_calls:
                                            status = call.get("status_code", 0)
                                            duration = call.get("duration_ms", 0)
                                            endpoint = call.get("endpoint", "")[:50]
                                            error = call.get("error", "")
                                            status_icon = "✅" if status == 200 else "❌"
                                            st.text(f"{status_icon} [{status}] {duration:.0f}ms - {endpoint}")
                                            if error:
                                                st.text(f"    Error: {error[:60]}")

                                        # Alle Fehler zeigen
                                        all_errors = full_report.get("errors", [])
                                        if all_errors:
                                            st.markdown("**Alle Fehler:**")
                                            for err in all_errors:
                                                st.error(f"🔴 **{err.get('type')}**: {err.get('message')}")
                                                if err.get("traceback"):
                                                    with st.expander(f"Traceback für {err.get('type')}"):
                                                        st.code(err.get("traceback"))

                                        # JSON-Export
                                        st.markdown("---")
                                        st.markdown("**JSON-Export:**")
                                        report_json = json.dumps(full_report, indent=2, default=str, ensure_ascii=False)
                                        st.download_button(
                                            label="📥 Debug-Report herunterladen",
                                            data=report_json,
                                            file_name=f"cloud_sync_debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                                            mime="application/json"
                                        )

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

        # Vergangene Diagnose-Berichte anzeigen
        st.markdown("---")
        with st.expander("📊 Vergangene Diagnose-Berichte", expanded=False):
            try:
                past_reports = cloud_service.get_diagnostic_reports(limit=10)

                if past_reports:
                    st.markdown("**Letzte Sync-Diagnosen:**")

                    for report in past_reports:
                        status_icon = {
                            "completed": "✅",
                            "error": "❌",
                            "running": "🔄",
                            "aborted": "⚠️"
                        }.get(report.get("sync_status", ""), "❓")

                        started = report.get("sync_started_at")
                        started_str = started.strftime("%d.%m.%Y %H:%M") if started else "?"

                        with st.expander(f"{status_icon} {started_str} - {report.get('sync_status', '?')} ({report.get('files_successful', 0)}/{report.get('total_files', 0)} Dateien)"):
                            # Zusammenfassung
                            cols = st.columns(4)
                            with cols[0]:
                                st.metric("Dateien", f"{report.get('files_successful', 0)}/{report.get('total_files', 0)}")
                            with cols[1]:
                                duration = report.get('duration_seconds', 0) or 0
                                st.metric("Dauer", f"{duration:.1f}s")
                            with cols[2]:
                                st.metric("API-Calls", report.get('api_calls_total', 0))
                            with cols[3]:
                                mem_growth = report.get('memory_growth_mb', 0) or 0
                                st.metric("Speicher", f"{mem_growth:+.1f} MB")

                            # Fehler anzeigen
                            if report.get("error_message"):
                                st.error(f"**Fehler:** {report.get('error_message')}")

                            # Letzte erfolgreiche Datei
                            if report.get("last_successful_file"):
                                st.info(f"**Letzte erfolgreiche Datei:** `{report.get('last_successful_file')}` "
                                       f"(Index: {report.get('last_successful_index', '?')})")

                            # Mögliche Ursachen
                            causes = report.get("possible_causes", [])
                            if causes:
                                st.markdown("**Mögliche Ursachen:**")
                                for cause in causes:
                                    st.warning(f"⚠️ {cause}")

                            # Empfehlungen
                            recommendations = report.get("recommendations", [])
                            if recommendations:
                                st.markdown("**Empfehlungen:**")
                                for rec in recommendations:
                                    st.info(f"💡 {rec}")

                            # Fehler-Log
                            errors_log = report.get("errors_log", [])
                            if errors_log:
                                with st.expander(f"🔴 Fehler-Log ({len(errors_log)} Fehler)"):
                                    for err in errors_log[:10]:
                                        st.text(f"[{err.get('type', '?')}] {err.get('message', '')[:80]}")
                                    if len(errors_log) > 10:
                                        st.caption(f"... und {len(errors_log) - 10} weitere")

                            # Traceback falls vorhanden
                            if report.get("error_traceback"):
                                with st.expander("📋 Traceback"):
                                    st.code(report.get("error_traceback"))

                            # JSON-Export
                            import json
                            report_json = json.dumps(report, indent=2, default=str, ensure_ascii=False)
                            st.download_button(
                                label="📥 Bericht herunterladen",
                                data=report_json,
                                file_name=f"sync_diag_{report.get('id', 'unknown')}_{started_str.replace('.', '').replace(':', '').replace(' ', '_')}.json",
                                mime="application/json",
                                key=f"download_diag_{report.get('id', 0)}"
                            )
                else:
                    st.info("Keine vergangenen Diagnose-Berichte vorhanden. "
                           "Aktivieren Sie den Debug-Modus und starten Sie einen Import.")

            except Exception as e:
                st.warning(f"Diagnose-Berichte konnten nicht geladen werden: {e}")

        # Hinweis auf Einstellungen
        st.markdown("---")
        st.caption("💡 **Tipp:** Für erweiterte Cloud-Sync Optionen und API-Konfiguration besuchen Sie **Einstellungen → Cloud-Sync**.")


with tab_process:
    st.subheader("Unverarbeitete Dokumente")

    user_id = get_current_user_id()

    with get_db() as session:
        # Korrigiere falsch markierte Dokumente (is_encrypted=True ohne IV)
        # Dies passiert bei Cloud-Importen vor dem Fix
        mismarked = session.query(Document).filter(
            Document.user_id == user_id,
            Document.is_encrypted == True,
            Document.encryption_iv == None
        ).all()
        if mismarked:
            for doc in mismarked:
                doc.is_encrypted = False
            session.commit()
            st.info(f"🔧 {len(mismarked)} Dokumente korrigiert (waren fälschlich als verschlüsselt markiert)")

        pending_docs = session.query(Document).filter(
            Document.user_id == user_id,
            Document.status.in_([DocumentStatus.PENDING, DocumentStatus.ERROR])
        ).order_by(Document.created_at.desc()).all()

        if pending_docs:
            # Header mit Statistik
            pending_count = sum(1 for d in pending_docs if d.status == DocumentStatus.PENDING)
            error_count = sum(1 for d in pending_docs if d.status == DocumentStatus.ERROR)

            st.markdown(f"""
            ### 📋 Ausstehende Dokumente

            | Status | Anzahl |
            |--------|--------|
            | ⏳ Wartend | **{pending_count}** |
            | ❌ Fehler | **{error_count}** |
            | **Gesamt** | **{len(pending_docs)}** |
            """)

            # Verarbeitungs-Button mit Live-Fortschritt
            col_btn, col_space = st.columns([1, 3])
            with col_btn:
                start_processing = st.button("▶️ Alle verarbeiten", type="primary", width="stretch")

            if start_processing:
                from utils.helpers import get_document_file_content
                import time

                # Live-Fortschritts-Container
                progress_container = st.container()
                with progress_container:
                    st.markdown("---")
                    st.markdown("### 🔄 Verarbeitung läuft...")

                    # Statistik-Anzeige
                    stats_cols = st.columns(4)
                    with stats_cols[0]:
                        stat_total = st.empty()
                        stat_total.metric("Gesamt", len(pending_docs))
                    with stats_cols[1]:
                        stat_done = st.empty()
                        stat_done.metric("Erledigt", "0", delta=None)
                    with stats_cols[2]:
                        stat_errors = st.empty()
                        stat_errors.metric("Fehler", "0")
                    with stats_cols[3]:
                        stat_remaining = st.empty()
                        stat_remaining.metric("Verbleibend", len(pending_docs))

                    # Fortschrittsbalken
                    progress_bar = st.progress(0, text="Starte Verarbeitung...")

                    # Aktuelles Dokument
                    current_doc_display = st.empty()

                    # Verarbeitungslog
                    log_expander = st.expander("📜 Verarbeitungslog", expanded=True)
                    log_container = log_expander.empty()
                    log_entries = []

                # Verarbeitung starten
                processed = 0
                errors = 0
                start_time = time.time()

                for i, doc in enumerate(pending_docs):
                    # Fortschritt aktualisieren
                    percent = (i + 1) / len(pending_docs)
                    elapsed = time.time() - start_time
                    if i > 0:
                        avg_time = elapsed / i
                        remaining = avg_time * (len(pending_docs) - i)
                        time_text = f"~{int(remaining)}s verbleibend"
                    else:
                        time_text = "Berechne Zeit..."

                    progress_bar.progress(percent, text=f"Dokument {i+1}/{len(pending_docs)} ({time_text})")

                    # Aktuelles Dokument anzeigen
                    current_doc_display.info(f"📄 Verarbeite: **{doc.filename}**")

                    try:
                        encryption = get_encryption_service()
                        success, result = get_document_file_content(doc.file_path, user_id)

                        if success:
                            # Nur entschlüsseln wenn verschlüsselt UND IV vorhanden
                            if doc.is_encrypted and doc.encryption_iv:
                                try:
                                    file_data = encryption.decrypt_file(result, doc.encryption_iv, doc.filename)
                                except Exception:
                                    file_data = result
                            else:
                                file_data = result

                            process_document(doc.id, file_data, user_id)
                            processed += 1
                            log_entries.append(f"✅ {doc.filename}")

                            # Statistiken aktualisieren
                            stat_done.metric("Erledigt", processed, delta=f"+1")
                            stat_remaining.metric("Verbleibend", len(pending_docs) - i - 1)
                        else:
                            errors += 1
                            log_entries.append(f"❌ {doc.filename} - Datei nicht gefunden")
                            stat_errors.metric("Fehler", errors)
                    except Exception as e:
                        errors += 1
                        log_entries.append(f"❌ {doc.filename} - {str(e)[:50]}")
                        stat_errors.metric("Fehler", errors)
                        continue

                    # Log aktualisieren (letzte 10 Einträge)
                    log_text = "\n".join(log_entries[-10:])
                    if len(log_entries) > 10:
                        log_text = f"... {len(log_entries) - 10} weitere ...\n" + log_text
                    log_container.code(log_text)

                # Fertig!
                total_time = time.time() - start_time
                progress_bar.progress(1.0, text="✅ Verarbeitung abgeschlossen!")
                current_doc_display.empty()

                # Abschluss-Meldung
                st.markdown("---")
                if processed > 0:
                    st.success(f"✅ **{processed} Dokumente** erfolgreich verarbeitet in {int(total_time)}s")
                if errors > 0:
                    st.warning(f"⚠️ **{errors} Dokumente** konnten nicht verarbeitet werden")

                # Button zum Neu laden
                if st.button("🔄 Liste aktualisieren"):
                    st.rerun()

            else:
                # Dokumentenliste anzeigen (wenn nicht gerade verarbeitet wird)
                st.markdown("---")

                # Tabellen-Header
                header_cols = st.columns([0.5, 3, 1.5, 1, 1])
                with header_cols[0]:
                    st.markdown("**#**")
                with header_cols[1]:
                    st.markdown("**Dokument**")
                with header_cols[2]:
                    st.markdown("**Status**")
                with header_cols[3]:
                    st.markdown("**Datum**")
                with header_cols[4]:
                    st.markdown("**Aktion**")

                st.markdown("---")

                # Dokumentenliste (max 20 anzeigen)
                for idx, doc in enumerate(pending_docs[:20]):
                    col1, col2, col3, col4, col5 = st.columns([0.5, 3, 1.5, 1, 1])

                    with col1:
                        st.caption(f"{idx + 1}")

                    with col2:
                        filename_display = doc.filename[:35] + "..." if len(doc.filename) > 35 else doc.filename
                        st.markdown(f"📄 {filename_display}")
                        if doc.processing_error:
                            st.caption(f"⚠️ {doc.processing_error[:50]}...")

                    with col3:
                        if doc.status == DocumentStatus.PENDING:
                            st.markdown("⏳ Wartend")
                        else:
                            st.markdown("❌ Fehler")

                    with col4:
                        st.caption(format_date(doc.created_at))

                    with col5:
                        if st.button("▶️", key=f"process_{doc.id}", help="Einzeln verarbeiten"):
                            from utils.helpers import get_document_file_content
                            success, result = get_document_file_content(doc.file_path, user_id)
                            if not success:
                                st.error(f"Datei nicht gefunden")
                            else:
                                if doc.is_encrypted and doc.encryption_iv:
                                    try:
                                        encryption = get_encryption_service()
                                        file_data = encryption.decrypt_file(result, doc.encryption_iv, doc.filename)
                                    except:
                                        file_data = result
                                else:
                                    file_data = result

                                with st.spinner("Verarbeite..."):
                                    try:
                                        process_document(doc.id, file_data, user_id)
                                        st.success("✅")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Fehler: {e}")

                if len(pending_docs) > 20:
                    st.caption(f"... und {len(pending_docs) - 20} weitere Dokumente")
        else:
            st.success("Keine unverarbeiteten Dokumente")
