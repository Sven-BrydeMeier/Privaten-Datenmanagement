"""
Email Parser Service für .eml und .msg Dateien

Ermöglicht das Importieren von E-Mails als Dokumente ins DMS.
Unterstützt:
- .eml Dateien (RFC 822 Format)
- .msg Dateien (Microsoft Outlook Format)
- Extraktion von Metadaten (Absender, Betreff, Datum)
- Extraktion von Anhängen
- Textextraktion für Volltextsuche
"""

import email
import email.policy
from email import message_from_bytes, message_from_string
from email.header import decode_header
from email.utils import parsedate_to_datetime, parseaddr
from datetime import datetime
from typing import Dict, List, Optional, Tuple, BinaryIO
import logging
import re
import html
import tempfile
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Versuche extract-msg zu importieren
try:
    import extract_msg
    MSG_SUPPORT = True
except ImportError:
    MSG_SUPPORT = False
    logger.info("extract-msg nicht installiert, MSG-Unterstützung deaktiviert")


class EmailParserService:
    """Service zum Parsen von E-Mail-Dateien."""

    def __init__(self):
        pass

    def parse_eml(self, file_data: bytes) -> Dict:
        """
        Parst eine .eml Datei und extrahiert alle relevanten Informationen.

        Args:
            file_data: Binärdaten der .eml Datei

        Returns:
            Dict mit allen extrahierten Informationen:
            - subject: Betreff
            - from_address: Absender-Adresse
            - from_name: Absender-Name
            - to_addresses: Liste der Empfänger
            - cc_addresses: Liste der CC-Empfänger
            - date: Datum der E-Mail
            - body_text: Nur-Text-Version des Inhalts
            - body_html: HTML-Version des Inhalts (falls vorhanden)
            - attachments: Liste der Anhänge mit Name, MIME-Type und Daten
            - message_id: Message-ID Header
            - full_text: Kombinierter Text für Volltextsuche
        """
        try:
            # E-Mail parsen
            msg = message_from_bytes(file_data, policy=email.policy.default)

            result = {
                "subject": self._decode_header(msg.get("Subject", "")),
                "from_address": "",
                "from_name": "",
                "to_addresses": [],
                "cc_addresses": [],
                "date": None,
                "body_text": "",
                "body_html": "",
                "attachments": [],
                "message_id": msg.get("Message-ID", ""),
                "full_text": "",
                "in_reply_to": msg.get("In-Reply-To", ""),
                "references": msg.get("References", ""),
            }

            # Absender parsen
            from_header = msg.get("From", "")
            from_name, from_addr = parseaddr(from_header)
            result["from_name"] = self._decode_header(from_name) if from_name else ""
            result["from_address"] = from_addr

            # Empfänger parsen
            result["to_addresses"] = self._parse_address_list(msg.get("To", ""))
            result["cc_addresses"] = self._parse_address_list(msg.get("Cc", ""))

            # Datum parsen
            date_str = msg.get("Date")
            if date_str:
                try:
                    result["date"] = parsedate_to_datetime(date_str)
                except Exception:
                    # Fallback: Aktuelles Datum
                    result["date"] = datetime.now()
            else:
                result["date"] = datetime.now()

            # Body und Anhänge extrahieren
            self._extract_body_and_attachments(msg, result)

            # Volltext für Suche zusammenstellen
            result["full_text"] = self._create_full_text(result)

            logger.info(f"E-Mail geparst: '{result['subject']}' von {result['from_address']}")
            return result

        except Exception as e:
            logger.error(f"Fehler beim Parsen der E-Mail: {e}")
            raise

    def _decode_header(self, header_value: str) -> str:
        """Dekodiert einen E-Mail-Header (kann encoded sein)."""
        if not header_value:
            return ""

        try:
            decoded_parts = decode_header(header_value)
            result = []
            for content, charset in decoded_parts:
                if isinstance(content, bytes):
                    charset = charset or "utf-8"
                    try:
                        result.append(content.decode(charset, errors="replace"))
                    except (LookupError, UnicodeDecodeError):
                        result.append(content.decode("utf-8", errors="replace"))
                else:
                    result.append(content)
            return " ".join(result)
        except Exception:
            return str(header_value)

    def _parse_address_list(self, header_value: str) -> List[Dict]:
        """Parst eine Liste von E-Mail-Adressen."""
        if not header_value:
            return []

        addresses = []
        # Einfaches Splitting bei Komma (funktioniert für die meisten Fälle)
        decoded = self._decode_header(header_value)

        # Regex für E-Mail-Adressen
        email_pattern = r'([^<,]+)?<?([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})>?'
        matches = re.findall(email_pattern, decoded)

        for name, addr in matches:
            addresses.append({
                "name": name.strip().strip('"') if name else "",
                "address": addr.strip()
            })

        return addresses

    def _extract_body_and_attachments(self, msg, result: Dict):
        """Extrahiert Body-Text und Anhänge aus der E-Mail."""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))

                # Anhang
                if "attachment" in content_disposition or part.get_filename():
                    filename = part.get_filename()
                    if filename:
                        filename = self._decode_header(filename)
                        try:
                            payload = part.get_payload(decode=True)
                            if payload:
                                result["attachments"].append({
                                    "filename": filename,
                                    "mime_type": content_type,
                                    "data": payload,
                                    "size": len(payload)
                                })
                                logger.debug(f"Anhang gefunden: {filename} ({len(payload)} Bytes)")
                        except Exception as e:
                            logger.warning(f"Fehler beim Extrahieren des Anhangs {filename}: {e}")

                # Text-Body
                elif content_type == "text/plain" and not result["body_text"]:
                    try:
                        payload = part.get_payload(decode=True)
                        if payload:
                            charset = part.get_content_charset() or "utf-8"
                            result["body_text"] = payload.decode(charset, errors="replace")
                    except Exception as e:
                        logger.warning(f"Fehler beim Dekodieren des Text-Bodys: {e}")

                # HTML-Body
                elif content_type == "text/html" and not result["body_html"]:
                    try:
                        payload = part.get_payload(decode=True)
                        if payload:
                            charset = part.get_content_charset() or "utf-8"
                            result["body_html"] = payload.decode(charset, errors="replace")
                    except Exception as e:
                        logger.warning(f"Fehler beim Dekodieren des HTML-Bodys: {e}")
        else:
            # Einfache E-Mail ohne Multipart
            content_type = msg.get_content_type()
            try:
                payload = msg.get_payload(decode=True)
                if payload:
                    charset = msg.get_content_charset() or "utf-8"
                    decoded = payload.decode(charset, errors="replace")
                    if content_type == "text/html":
                        result["body_html"] = decoded
                        # HTML zu Text konvertieren als Fallback
                        result["body_text"] = self._html_to_text(decoded)
                    else:
                        result["body_text"] = decoded
            except Exception as e:
                logger.warning(f"Fehler beim Dekodieren des Bodys: {e}")

        # Falls nur HTML vorhanden, Text-Version erstellen
        if not result["body_text"] and result["body_html"]:
            result["body_text"] = self._html_to_text(result["body_html"])

    def _html_to_text(self, html_content: str) -> str:
        """Konvertiert HTML zu Nur-Text."""
        if not html_content:
            return ""

        # Einfache HTML-zu-Text-Konvertierung
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
        text = html.unescape(text)

        # Mehrfache Leerzeilen reduzieren
        text = re.sub(r'\n\s*\n', '\n\n', text)
        text = text.strip()

        return text

    def _create_full_text(self, result: Dict) -> str:
        """Erstellt den Volltext für die Suche."""
        parts = []

        # Betreff
        if result["subject"]:
            parts.append(f"Betreff: {result['subject']}")

        # Absender
        if result["from_name"]:
            parts.append(f"Von: {result['from_name']} <{result['from_address']}>")
        elif result["from_address"]:
            parts.append(f"Von: {result['from_address']}")

        # Empfänger
        if result["to_addresses"]:
            to_str = ", ".join([
                f"{a['name']} <{a['address']}>" if a['name'] else a['address']
                for a in result["to_addresses"]
            ])
            parts.append(f"An: {to_str}")

        # Datum
        if result["date"]:
            parts.append(f"Datum: {result['date'].strftime('%d.%m.%Y %H:%M')}")

        # Trennlinie
        parts.append("-" * 50)

        # Body
        if result["body_text"]:
            parts.append(result["body_text"])

        # Anhänge auflisten
        if result["attachments"]:
            parts.append("\n--- Anhänge ---")
            for att in result["attachments"]:
                parts.append(f"- {att['filename']} ({att['mime_type']}, {att['size']} Bytes)")

        return "\n".join(parts)

    def create_document_title(self, parsed_email: Dict) -> str:
        """Erstellt einen Dokumenten-Titel aus der E-Mail."""
        subject = parsed_email.get("subject", "")
        from_addr = parsed_email.get("from_address", "")
        date = parsed_email.get("date")

        # Absender-Domain extrahieren
        sender_domain = ""
        if from_addr and "@" in from_addr:
            sender_domain = from_addr.split("@")[1].split(".")[0].capitalize()

        # Titel zusammenstellen
        if subject:
            # Betreff bereinigen (Re:, Fwd: etc. entfernen)
            clean_subject = re.sub(r'^(Re:|Fwd:|AW:|WG:|Antwort:)\s*', '', subject, flags=re.IGNORECASE)
            clean_subject = clean_subject[:100]  # Max 100 Zeichen

            if sender_domain:
                return f"{sender_domain}: {clean_subject}"
            return clean_subject

        # Fallback wenn kein Betreff
        date_str = date.strftime('%Y-%m-%d') if date else datetime.now().strftime('%Y-%m-%d')
        if sender_domain:
            return f"E-Mail von {sender_domain} ({date_str})"
        return f"E-Mail vom {date_str}"

    def parse_msg(self, file_data: bytes) -> Dict:
        """
        Parst eine .msg Datei (Microsoft Outlook Format) und extrahiert alle Informationen.

        Args:
            file_data: Binärdaten der .msg Datei

        Returns:
            Dict mit allen extrahierten Informationen (gleiches Format wie parse_eml)
        """
        if not MSG_SUPPORT:
            logger.error("MSG-Unterstützung nicht verfügbar. Bitte 'extract-msg' installieren.")
            return {
                "subject": "MSG-Datei (nicht unterstützt)",
                "from_address": "",
                "from_name": "",
                "to_addresses": [],
                "cc_addresses": [],
                "date": datetime.now(),
                "body_text": "MSG-Dateien werden nicht unterstützt. Bitte installieren Sie 'extract-msg'.",
                "body_html": "",
                "attachments": [],
                "message_id": "",
                "full_text": "MSG-Datei nicht unterstützt",
                "error": "extract-msg nicht installiert"
            }

        result = {
            "subject": "",
            "from_address": "",
            "from_name": "",
            "to_addresses": [],
            "cc_addresses": [],
            "date": None,
            "body_text": "",
            "body_html": "",
            "attachments": [],
            "message_id": "",
            "full_text": ""
        }

        temp_file = None
        try:
            # MSG-Datei in temporäre Datei schreiben (extract-msg braucht Dateipfad)
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.msg')
            temp_file.write(file_data)
            temp_file.close()

            # MSG-Datei öffnen
            msg = extract_msg.Message(temp_file.name)

            # Metadaten extrahieren
            result["subject"] = msg.subject or ""
            result["from_address"] = msg.sender or ""
            result["from_name"] = msg.senderName or ""

            # Empfänger
            if msg.to:
                # Kann eine einzelne Adresse oder kommagetrennte Liste sein
                to_addrs = msg.to.split(';') if ';' in msg.to else msg.to.split(',')
                for addr in to_addrs:
                    addr = addr.strip()
                    if addr:
                        result["to_addresses"].append({
                            "name": "",
                            "address": addr
                        })

            # CC
            if msg.cc:
                cc_addrs = msg.cc.split(';') if ';' in msg.cc else msg.cc.split(',')
                for addr in cc_addrs:
                    addr = addr.strip()
                    if addr:
                        result["cc_addresses"].append({
                            "name": "",
                            "address": addr
                        })

            # Datum
            if msg.date:
                try:
                    if isinstance(msg.date, datetime):
                        result["date"] = msg.date
                    else:
                        # Versuche verschiedene Formate
                        result["date"] = datetime.fromisoformat(str(msg.date).replace('Z', '+00:00'))
                except Exception:
                    result["date"] = datetime.now()
            else:
                result["date"] = datetime.now()

            # Body
            result["body_text"] = msg.body or ""
            if msg.htmlBody:
                result["body_html"] = msg.htmlBody if isinstance(msg.htmlBody, str) else msg.htmlBody.decode('utf-8', errors='replace')

            # Message-ID
            result["message_id"] = msg.messageId or ""

            # Anhänge
            for attachment in msg.attachments:
                try:
                    att_data = attachment.data
                    if att_data:
                        result["attachments"].append({
                            "filename": attachment.longFilename or attachment.shortFilename or "attachment",
                            "mime_type": attachment.mimetype or "application/octet-stream",
                            "data": att_data,
                            "size": len(att_data)
                        })
                        logger.debug(f"MSG-Anhang: {attachment.longFilename}")
                except Exception as att_error:
                    logger.warning(f"Fehler beim Extrahieren eines MSG-Anhangs: {att_error}")

            # Volltext erstellen
            result["full_text"] = self._create_full_text(result)

            logger.info(f"MSG erfolgreich geparst: {result['subject']}")

        except Exception as e:
            logger.error(f"Fehler beim Parsen der MSG-Datei: {e}")
            result["error"] = str(e)
            result["subject"] = "Fehler beim Lesen der MSG-Datei"
            result["body_text"] = f"Die MSG-Datei konnte nicht gelesen werden: {str(e)}"
            result["full_text"] = result["body_text"]

        finally:
            # Temporäre Datei löschen
            if temp_file and os.path.exists(temp_file.name):
                try:
                    os.unlink(temp_file.name)
                except Exception:
                    pass

        return result

    def parse_email_file(self, file_data: bytes, filename: str) -> Dict:
        """
        Parst eine E-Mail-Datei basierend auf der Dateiendung.

        Args:
            file_data: Binärdaten der Datei
            filename: Dateiname (für Erkennung des Formats)

        Returns:
            Dict mit extrahierten Informationen
        """
        lower_filename = filename.lower()

        if lower_filename.endswith('.msg'):
            return self.parse_msg(file_data)
        elif lower_filename.endswith('.eml'):
            return self.parse_eml(file_data)
        else:
            logger.warning(f"Unbekanntes E-Mail-Format: {filename}")
            return self.parse_eml(file_data)  # Fallback auf EML

    def get_detected_sender(self, parsed_email: Dict) -> str:
        """Extrahiert den Absender für die Klassifizierung."""
        from_name = parsed_email.get("from_name", "")
        from_addr = parsed_email.get("from_address", "")

        if from_name:
            return from_name

        if from_addr and "@" in from_addr:
            # Domain als Absender-Name
            domain = from_addr.split("@")[1]
            # Bekannte Domains zu Namen
            domain_names = {
                "gmail.com": "Gmail",
                "outlook.com": "Microsoft",
                "hotmail.com": "Microsoft",
                "yahoo.com": "Yahoo",
                "web.de": "Web.de",
                "gmx.de": "GMX",
                "t-online.de": "T-Online",
                "posteo.de": "Posteo",
                "icloud.com": "Apple",
            }
            return domain_names.get(domain.lower(), domain.split(".")[0].capitalize())

        return "Unbekannt"


# Singleton-Instanz
_email_parser = None


def get_email_parser() -> EmailParserService:
    """Gibt die Email-Parser Singleton-Instanz zurück."""
    global _email_parser
    if _email_parser is None:
        _email_parser = EmailParserService()
    return _email_parser
