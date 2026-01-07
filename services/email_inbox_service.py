"""
Email Inbox Processor Service

Verarbeitet eingehende Emails mit autorisierten Signaturen:
- Empfängt Emails über IMAP
- Prüft auf autorisierte Absender (Signaturen)
- Extrahiert Verfügungen aus dem Email-Text
- Kategorisiert Emails automatisch mit KI
- Verarbeitet Anhänge separat
"""

import imaplib
import email
from email import policy
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Generator
import logging
import re
import time

logger = logging.getLogger(__name__)


class EmailInboxService:
    """Service für die Verarbeitung von Emails aus dem Posteingang."""

    def __init__(self, user_id: int):
        self.user_id = user_id
        self._imap_connection = None
        self._load_settings()

    def _load_settings(self):
        """Lädt die Einstellungen aus der Konfiguration."""
        from config.settings import get_settings
        self.settings = get_settings()

    def _get_imap_connection(self) -> imaplib.IMAP4_SSL:
        """Erstellt oder gibt die bestehende IMAP-Verbindung zurück."""
        if self._imap_connection is None:
            if not self.settings.imap_server or not self.settings.imap_username:
                raise ValueError("IMAP-Server nicht konfiguriert. Bitte in Einstellungen hinterlegen.")

            try:
                self._imap_connection = imaplib.IMAP4_SSL(
                    self.settings.imap_server,
                    self.settings.imap_port
                )
                self._imap_connection.login(
                    self.settings.imap_username,
                    self.settings.imap_password
                )
                logger.info(f"IMAP-Verbindung hergestellt zu {self.settings.imap_server}")
            except Exception as e:
                logger.error(f"IMAP-Verbindung fehlgeschlagen: {e}")
                raise

        return self._imap_connection

    def close_connection(self):
        """Schließt die IMAP-Verbindung."""
        if self._imap_connection:
            try:
                self._imap_connection.logout()
            except Exception:
                pass
            self._imap_connection = None

    def is_authorized_sender(self, from_address: str) -> bool:
        """
        Prüft ob der Absender eine autorisierte Signatur hat.

        Args:
            from_address: Email-Adresse des Absenders

        Returns:
            True wenn autorisiert
        """
        if not from_address:
            return False

        from_address = from_address.lower().strip()
        authorized = [sig.lower().strip() for sig in self.settings.email_authorized_signatures]

        # Exakte Übereinstimmung
        if from_address in authorized:
            return True

        # Domain-Übereinstimmung (wenn Signatur mit @ beginnt, nur Domain prüfen)
        for sig in authorized:
            if sig.startswith("@") and from_address.endswith(sig):
                return True

        return False

    def parse_verfuegung(self, email_text: str) -> Optional[Dict]:
        """
        Extrahiert eine Verfügung aus dem Email-Text.

        Format der Verfügung:
        Verfügung:
        Ordner: [Ordnername]
        Kategorie: [Kategorie]
        Frist: [DD.MM.YYYY]
        Notiz: [Zusätzliche Notizen]

        Args:
            email_text: Der Email-Body-Text

        Returns:
            Dict mit Verfügungsdetails oder None
        """
        if not email_text:
            return None

        # Prüfe auf Verfügungs-Schlüsselwörter
        keywords = self.settings.email_verfuegung_keywords
        verfuegung_start = -1

        for keyword in keywords:
            pos = email_text.find(keyword)
            if pos >= 0:
                verfuegung_start = pos + len(keyword)
                break

        if verfuegung_start < 0:
            return None

        # Extrahiere den Verfügungsblock (bis zur nächsten Leerzeile oder Signatur)
        verfuegung_text = email_text[verfuegung_start:]

        # Ende bei doppelter Leerzeile, "---", oder typischen Signatur-Anfängen
        end_markers = ["\n\n\n", "\n---", "\n--", "\nMit freundlichen", "\nFreundliche", "\nBeste Grüße", "\nViele Grüße"]
        end_pos = len(verfuegung_text)
        for marker in end_markers:
            pos = verfuegung_text.find(marker)
            if pos >= 0 and pos < end_pos:
                end_pos = pos

        verfuegung_text = verfuegung_text[:end_pos].strip()

        result = {
            "raw_text": verfuegung_text,
            "ordner": None,
            "kategorie": None,
            "frist": None,
            "notiz": None,
            "aktenzeichen": None,
            "mandant": None,
            "prioritaet": None
        }

        # Parse die einzelnen Felder
        patterns = {
            "ordner": r"(?:Ordner|Ablage|Akte):\s*(.+?)(?:\n|$)",
            "kategorie": r"(?:Kategorie|Typ|Art):\s*(.+?)(?:\n|$)",
            "frist": r"(?:Frist|Termin|Deadline|Bis|Wiedervorlage):\s*(.+?)(?:\n|$)",
            "notiz": r"(?:Notiz|Anmerkung|Bemerkung|Hinweis):\s*(.+?)(?:\n|$)",
            "aktenzeichen": r"(?:Aktenzeichen|Az\.|AZ|Geschäftszeichen):\s*(.+?)(?:\n|$)",
            "mandant": r"(?:Mandant|Kunde|Klient):\s*(.+?)(?:\n|$)",
            "prioritaet": r"(?:Priorität|Dringend|Wichtigkeit):\s*(.+?)(?:\n|$)"
        }

        for field, pattern in patterns.items():
            match = re.search(pattern, verfuegung_text, re.IGNORECASE)
            if match:
                result[field] = match.group(1).strip()

        # Frist in Datum konvertieren
        if result["frist"]:
            result["frist_date"] = self._parse_date(result["frist"])

        # Wenn keine strukturierten Felder gefunden, verwende den ganzen Text als Notiz
        if not any([result["ordner"], result["kategorie"], result["frist"]]):
            # Prüfe ob es überhaupt strukturierte Anweisungen gibt
            if ":" not in verfuegung_text:
                result["notiz"] = verfuegung_text

        return result

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parst verschiedene Datumsformate."""
        if not date_str:
            return None

        date_str = date_str.strip()

        # Verschiedene Formate probieren
        formats = [
            "%d.%m.%Y",
            "%d.%m.%y",
            "%Y-%m-%d",
            "%d/%m/%Y",
            "%d-%m-%Y"
        ]

        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue

        # Relative Datumsangaben
        relative_patterns = {
            r"(?:in\s+)?(\d+)\s*(?:tage?|days?)": lambda m: datetime.now().replace(hour=0, minute=0, second=0) + __import__('datetime').timedelta(days=int(m.group(1))),
            r"(?:in\s+)?(\d+)\s*(?:wochen?|weeks?)": lambda m: datetime.now().replace(hour=0, minute=0, second=0) + __import__('datetime').timedelta(weeks=int(m.group(1))),
            r"morgen": lambda m: datetime.now().replace(hour=0, minute=0, second=0) + __import__('datetime').timedelta(days=1),
            r"übermorgen": lambda m: datetime.now().replace(hour=0, minute=0, second=0) + __import__('datetime').timedelta(days=2),
        }

        from datetime import timedelta
        for pattern, handler in relative_patterns.items():
            match = re.search(pattern, date_str.lower())
            if match:
                try:
                    now = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                    if "tag" in pattern or "day" in pattern:
                        return now + timedelta(days=int(match.group(1)))
                    elif "woche" in pattern or "week" in pattern:
                        return now + timedelta(weeks=int(match.group(1)))
                    elif "morgen" in pattern:
                        return now + timedelta(days=1)
                    elif "übermorgen" in pattern:
                        return now + timedelta(days=2)
                except Exception:
                    pass

        return None

    def categorize_with_ai(self, email_text: str, subject: str, attachments: List[str]) -> Dict:
        """
        Kategorisiert eine Email mit KI (ChatGPT/OpenAI).

        Args:
            email_text: Der Email-Body-Text
            subject: Email-Betreff
            attachments: Liste der Anhang-Dateinamen

        Returns:
            Dict mit Kategorisierungsvorschlägen
        """
        from services.ai_service import get_ai_service
        from config.settings import DOCUMENT_CATEGORIES

        ai_service = get_ai_service()

        if not ai_service.openai_available:
            logger.warning("OpenAI nicht verfügbar für Kategorisierung")
            return {
                "kategorie": "E-Mail",
                "ordner": "Emailverkehr",
                "zusammenfassung": "",
                "confidence": 0.0
            }

        # Prompt für ChatGPT
        attachments_str = "\n".join(f"- {a}" for a in attachments) if attachments else "Keine"

        prompt = f"""Analysiere diese Email und kategorisiere sie für ein Dokumentenmanagement-System.

Betreff: {subject}

Email-Text:
{email_text[:3000]}

Anhänge:
{attachments_str}

Verfügbare Kategorien: {', '.join(DOCUMENT_CATEGORIES)}

Verfügbare Ordner: Posteingang, Emailverkehr, Verträge, Darlehen, Versicherungen, Rentenbescheide, Lebensversicherungen, Finanzen, Steuern, Archiv

Antworte im JSON-Format:
{{
    "kategorie": "Passende Kategorie aus der Liste",
    "ordner": "Passender Ordner",
    "zusammenfassung": "Kurze Zusammenfassung in 1-2 Sätzen",
    "absender_typ": "Firma|Behörde|Privatperson|Unbekannt",
    "dringlichkeit": "hoch|mittel|niedrig",
    "handlungsbedarf": true/false,
    "handlung_beschreibung": "Was zu tun ist (falls Handlungsbedarf)",
    "schlagworte": ["Schlagwort1", "Schlagwort2"]
}}
"""

        try:
            # Nutze OpenAI (ChatGPT) explizit
            client = ai_service.get_openai_client()
            if not client:
                raise Exception("OpenAI Client nicht verfügbar")

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "Du bist ein Assistent für Dokumentenmanagement. Analysiere Emails und kategorisiere sie präzise. Antworte immer im JSON-Format."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3
            )

            result_text = response.choices[0].message.content

            # JSON extrahieren
            import json
            json_start = result_text.find('{')
            json_end = result_text.rfind('}') + 1

            if json_start >= 0 and json_end > json_start:
                result = json.loads(result_text[json_start:json_end])
                result["confidence"] = 0.85  # ChatGPT Confidence
                return result

        except Exception as e:
            logger.error(f"KI-Kategorisierung fehlgeschlagen: {e}")

        # Fallback
        return {
            "kategorie": "E-Mail",
            "ordner": "Emailverkehr",
            "zusammenfassung": subject,
            "confidence": 0.0
        }

    def fetch_unread_emails(self, folder: str = "INBOX", limit: int = 50) -> Generator[Dict, None, None]:
        """
        Ruft ungelesene Emails aus dem Postfach ab.

        Args:
            folder: IMAP-Ordner (Standard: INBOX)
            limit: Maximale Anzahl Emails

        Yields:
            Dict mit Email-Daten für jede Email
        """
        conn = self._get_imap_connection()

        try:
            # Ordner auswählen
            status, messages = conn.select(folder)
            if status != "OK":
                logger.error(f"Konnte Ordner '{folder}' nicht öffnen")
                return

            # Ungelesene Emails suchen
            status, message_ids = conn.search(None, "UNSEEN")
            if status != "OK":
                logger.error("Fehler beim Suchen nach ungelesenen Emails")
                return

            ids = message_ids[0].split()
            logger.info(f"Gefundene ungelesene Emails: {len(ids)}")

            # Nur die neuesten (limit) Emails verarbeiten
            for msg_id in ids[-limit:]:
                try:
                    # Email abrufen
                    status, msg_data = conn.fetch(msg_id, "(RFC822)")
                    if status != "OK":
                        continue

                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email, policy=policy.default)

                    # Header parsen
                    from_header = msg.get("From", "")
                    from_name, from_addr = parseaddr(from_header)
                    from_name = self._decode_header_value(from_name)

                    # Prüfe auf autorisierte Signatur
                    if not self.is_authorized_sender(from_addr):
                        logger.debug(f"Email von {from_addr} übersprungen - keine autorisierte Signatur")
                        continue

                    # Email-Daten extrahieren
                    subject = self._decode_header_value(msg.get("Subject", ""))

                    # Datum parsen
                    date_str = msg.get("Date")
                    try:
                        email_date = parsedate_to_datetime(date_str) if date_str else datetime.now()
                    except Exception:
                        email_date = datetime.now()

                    # Body extrahieren
                    body_text, body_html, attachments = self._extract_content(msg)

                    # Verfügung parsen
                    verfuegung = self.parse_verfuegung(body_text)

                    # KI-Kategorisierung wenn keine Verfügung
                    ai_result = None
                    if not verfuegung or not verfuegung.get("ordner"):
                        if self.settings.email_auto_categorize:
                            attachment_names = [a["filename"] for a in attachments]
                            ai_result = self.categorize_with_ai(body_text, subject, attachment_names)

                    yield {
                        "message_id": msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id),
                        "from_address": from_addr,
                        "from_name": from_name,
                        "subject": subject,
                        "date": email_date,
                        "body_text": body_text,
                        "body_html": body_html,
                        "attachments": attachments,
                        "verfuegung": verfuegung,
                        "ai_categorization": ai_result,
                        "raw_message": raw_email
                    }

                except Exception as e:
                    logger.error(f"Fehler beim Verarbeiten von Email {msg_id}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Fehler beim Abrufen von Emails: {e}")
            raise

    def _decode_header_value(self, value: str) -> str:
        """Dekodiert einen Header-Wert."""
        if not value:
            return ""

        try:
            decoded_parts = decode_header(value)
            result = []
            for content, charset in decoded_parts:
                if isinstance(content, bytes):
                    charset = charset or "utf-8"
                    result.append(content.decode(charset, errors="replace"))
                else:
                    result.append(content)
            return " ".join(result)
        except Exception:
            return str(value)

    def _extract_content(self, msg) -> Tuple[str, str, List[Dict]]:
        """
        Extrahiert Body-Text, HTML und Anhänge aus einer Email.

        Returns:
            Tuple aus (body_text, body_html, attachments)
        """
        body_text = ""
        body_html = ""
        attachments = []

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))

                # Anhang
                if "attachment" in content_disposition or part.get_filename():
                    filename = part.get_filename()
                    if filename:
                        filename = self._decode_header_value(filename)
                        try:
                            payload = part.get_payload(decode=True)
                            if payload:
                                attachments.append({
                                    "filename": filename,
                                    "mime_type": content_type,
                                    "data": payload,
                                    "size": len(payload)
                                })
                        except Exception as e:
                            logger.warning(f"Fehler beim Extrahieren von Anhang {filename}: {e}")

                # Text-Body
                elif content_type == "text/plain" and not body_text:
                    try:
                        payload = part.get_payload(decode=True)
                        if payload:
                            charset = part.get_content_charset() or "utf-8"
                            body_text = payload.decode(charset, errors="replace")
                    except Exception as e:
                        logger.warning(f"Fehler beim Dekodieren des Text-Bodys: {e}")

                # HTML-Body
                elif content_type == "text/html" and not body_html:
                    try:
                        payload = part.get_payload(decode=True)
                        if payload:
                            charset = part.get_content_charset() or "utf-8"
                            body_html = payload.decode(charset, errors="replace")
                    except Exception as e:
                        logger.warning(f"Fehler beim Dekodieren des HTML-Bodys: {e}")
        else:
            # Einfache Email
            content_type = msg.get_content_type()
            try:
                payload = msg.get_payload(decode=True)
                if payload:
                    charset = msg.get_content_charset() or "utf-8"
                    decoded = payload.decode(charset, errors="replace")
                    if content_type == "text/html":
                        body_html = decoded
                        body_text = self._html_to_text(decoded)
                    else:
                        body_text = decoded
            except Exception as e:
                logger.warning(f"Fehler beim Dekodieren des Bodys: {e}")

        # Falls nur HTML, Text-Version erstellen
        if not body_text and body_html:
            body_text = self._html_to_text(body_html)

        return body_text, body_html, attachments

    def _html_to_text(self, html_content: str) -> str:
        """Konvertiert HTML zu Text."""
        import re
        import html as html_module

        text = html_content

        # Script und Style Tags entfernen
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)

        # Zeilenumbrüche
        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'</?p[^>]*>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'</?div[^>]*>', '\n', text, flags=re.IGNORECASE)

        # Alle anderen Tags entfernen
        text = re.sub(r'<[^>]+>', '', text)

        # HTML-Entities dekodieren
        text = html_module.unescape(text)

        # Mehrfache Leerzeilen reduzieren
        text = re.sub(r'\n\s*\n', '\n\n', text)

        return text.strip()

    def mark_as_read(self, message_id: str):
        """Markiert eine Email als gelesen."""
        conn = self._get_imap_connection()
        try:
            conn.store(message_id.encode() if isinstance(message_id, str) else message_id, '+FLAGS', '\\Seen')
        except Exception as e:
            logger.error(f"Fehler beim Markieren als gelesen: {e}")

    def move_to_folder(self, message_id: str, target_folder: str):
        """Verschiebt eine Email in einen anderen Ordner."""
        conn = self._get_imap_connection()
        try:
            # Kopieren
            result = conn.copy(message_id.encode() if isinstance(message_id, str) else message_id, target_folder)
            if result[0] == "OK":
                # Original löschen
                conn.store(message_id.encode() if isinstance(message_id, str) else message_id, '+FLAGS', '\\Deleted')
                conn.expunge()
        except Exception as e:
            logger.error(f"Fehler beim Verschieben: {e}")

    def process_email_to_document(self, email_data: Dict) -> Dict:
        """
        Verarbeitet eine Email und erstellt ein Dokument im System.

        Args:
            email_data: Email-Daten aus fetch_unread_emails

        Returns:
            Dict mit Ergebnis der Verarbeitung
        """
        from database.db import get_db
        from database.models import Document, Folder
        from services.storage_service import get_storage_service
        from config.settings import DOCUMENT_CATEGORIES

        result = {
            "success": False,
            "document_id": None,
            "attachment_ids": [],
            "message": ""
        }

        try:
            # Verfügung oder KI-Kategorisierung verwenden
            verfuegung = email_data.get("verfuegung") or {}
            ai_result = email_data.get("ai_categorization") or {}

            # Kategorie bestimmen
            kategorie = verfuegung.get("kategorie") or ai_result.get("kategorie") or "E-Mail"
            if kategorie not in DOCUMENT_CATEGORIES:
                kategorie = "E-Mail"

            # Ordner bestimmen
            ordner_name = verfuegung.get("ordner") or ai_result.get("ordner") or "Emailverkehr"

            # Ordner in DB finden oder erstellen
            with get_db() as session:
                folder = session.query(Folder).filter(
                    Folder.user_id == self.user_id,
                    Folder.name == ordner_name
                ).first()

                if not folder:
                    # Standard-Ordner "Emailverkehr" verwenden
                    folder = session.query(Folder).filter(
                        Folder.user_id == self.user_id,
                        Folder.name == "Emailverkehr"
                    ).first()

                folder_id = folder.id if folder else None

                # Dokument-Titel erstellen
                title = email_data.get("subject") or f"Email vom {email_data['date'].strftime('%d.%m.%Y')}"

                # Zusammenfassung
                summary = ai_result.get("zusammenfassung") or verfuegung.get("notiz") or ""

                # Volltext erstellen
                full_text = self._create_fulltext(email_data)

                # Dokument erstellen
                document = Document(
                    user_id=self.user_id,
                    title=title,
                    filename=f"{title[:50]}.eml",
                    mime_type="message/rfc822",
                    category=kategorie,
                    folder_id=folder_id,
                    sender=email_data.get("from_name") or email_data.get("from_address"),
                    document_date=email_data.get("date"),
                    ocr_text=full_text,
                    ai_summary=summary,
                    subject=email_data.get("subject")  # Betreff in Subject-Feld
                )

                # Frist als Fälligkeitsdatum setzen wenn vorhanden
                if verfuegung.get("frist_date"):
                    document.invoice_due_date = verfuegung["frist_date"]

                session.add(document)
                session.flush()

                # Email-Rohdaten speichern
                storage = get_storage_service()
                if email_data.get("raw_message"):
                    file_path = f"emails/{self.user_id}/{document.id}.eml"
                    storage.upload_file(email_data["raw_message"], file_path, "message/rfc822")
                    document.file_path = file_path

                session.commit()
                result["document_id"] = document.id
                result["success"] = True
                result["message"] = f"Email '{title}' als Dokument gespeichert"

                # Anhänge verarbeiten wenn aktiviert
                if self.settings.email_process_attachments and email_data.get("attachments"):
                    for attachment in email_data["attachments"]:
                        try:
                            att_doc = self._process_attachment(
                                session, attachment, document.id, folder_id,
                                verfuegung, ai_result
                            )
                            if att_doc:
                                result["attachment_ids"].append(att_doc.id)
                        except Exception as e:
                            logger.error(f"Fehler beim Verarbeiten von Anhang: {e}")

                    session.commit()

            # Email als gelesen markieren wenn konfiguriert
            if self.settings.email_mark_as_read:
                self.mark_as_read(email_data["message_id"])

            # Email verschieben wenn konfiguriert
            if self.settings.email_move_to_folder:
                self.move_to_folder(email_data["message_id"], self.settings.email_move_to_folder)

        except Exception as e:
            logger.error(f"Fehler beim Erstellen des Dokuments: {e}")
            result["message"] = f"Fehler: {str(e)}"

        return result

    def _create_fulltext(self, email_data: Dict) -> str:
        """Erstellt den Volltext für die Suche."""
        parts = [
            f"Betreff: {email_data.get('subject', '')}",
            f"Von: {email_data.get('from_name', '')} <{email_data.get('from_address', '')}>",
            f"Datum: {email_data.get('date', datetime.now()).strftime('%d.%m.%Y %H:%M')}",
            "-" * 50,
            email_data.get("body_text", "")
        ]

        if email_data.get("attachments"):
            parts.append("\n--- Anhänge ---")
            for att in email_data["attachments"]:
                parts.append(f"- {att['filename']}")

        if email_data.get("verfuegung"):
            v = email_data["verfuegung"]
            parts.append("\n--- Verfügung ---")
            if v.get("ordner"):
                parts.append(f"Ordner: {v['ordner']}")
            if v.get("kategorie"):
                parts.append(f"Kategorie: {v['kategorie']}")
            if v.get("frist"):
                parts.append(f"Frist: {v['frist']}")
            if v.get("notiz"):
                parts.append(f"Notiz: {v['notiz']}")

        return "\n".join(parts)

    def _process_attachment(self, session, attachment: Dict, parent_doc_id: int,
                           folder_id: int, verfuegung: Dict, ai_result: Dict):
        """Verarbeitet einen Email-Anhang als separates Dokument."""
        from database.models import Document
        from services.storage_service import get_storage_service

        filename = attachment["filename"]
        mime_type = attachment["mime_type"]
        data = attachment["data"]

        # Kategorie vom Anhang-Typ ableiten oder von Email übernehmen
        kategorie = verfuegung.get("kategorie") or ai_result.get("kategorie") or "Sonstiges"

        # Dokument erstellen (reference_number speichert Referenz zur Email)
        doc = Document(
            user_id=self.user_id,
            title=filename,
            filename=filename,
            mime_type=mime_type,
            category=kategorie,
            folder_id=folder_id,
            file_size=len(data),
            reference_number=f"email:{parent_doc_id}"  # Referenz zur Quell-Email
        )

        session.add(doc)
        session.flush()

        # Datei speichern
        storage = get_storage_service()
        file_path = f"attachments/{self.user_id}/{doc.id}/{filename}"
        storage.upload_file(data, file_path, mime_type)
        doc.file_path = file_path

        # OCR für Bilder und PDFs
        if mime_type in ["application/pdf", "image/png", "image/jpeg", "image/jpg", "image/tiff"]:
            try:
                from services.ocr_service import get_ocr_service
                ocr_service = get_ocr_service()
                ocr_text = ocr_service.extract_text(data, mime_type)
                if ocr_text:
                    doc.ocr_text = ocr_text
            except Exception as e:
                logger.warning(f"OCR für Anhang {filename} fehlgeschlagen: {e}")

        return doc

    def process_all_unread(self, progress_callback=None) -> Dict:
        """
        Verarbeitet alle ungelesenen Emails von autorisierten Absendern.

        Args:
            progress_callback: Optional callback function(current, total, message)

        Returns:
            Dict mit Zusammenfassung der Verarbeitung
        """
        result = {
            "processed": 0,
            "errors": 0,
            "skipped": 0,
            "documents": [],
            "error_messages": []
        }

        try:
            emails = list(self.fetch_unread_emails())
            total = len(emails)

            for i, email_data in enumerate(emails):
                if progress_callback:
                    progress_callback(i + 1, total, f"Verarbeite: {email_data.get('subject', 'Email')[:50]}")

                try:
                    doc_result = self.process_email_to_document(email_data)
                    if doc_result["success"]:
                        result["processed"] += 1
                        result["documents"].append({
                            "id": doc_result["document_id"],
                            "title": email_data.get("subject"),
                            "attachments": len(doc_result.get("attachment_ids", []))
                        })
                    else:
                        result["errors"] += 1
                        result["error_messages"].append(doc_result.get("message", "Unbekannter Fehler"))
                except Exception as e:
                    result["errors"] += 1
                    result["error_messages"].append(str(e))

                # Kleine Pause zwischen Emails
                time.sleep(0.2)

        except Exception as e:
            result["error_messages"].append(f"Allgemeiner Fehler: {str(e)}")

        finally:
            self.close_connection()

        return result


# Singleton-Instanz
_email_inbox_services = {}


def get_email_inbox_service(user_id: int) -> EmailInboxService:
    """Gibt die Email-Inbox-Service Instanz für einen Benutzer zurück."""
    global _email_inbox_services
    if user_id not in _email_inbox_services:
        _email_inbox_services[user_id] = EmailInboxService(user_id)
    return _email_inbox_services[user_id]
