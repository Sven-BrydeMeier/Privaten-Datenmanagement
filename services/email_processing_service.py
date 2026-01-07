"""
Email Processing Service - Orchestriert E-Mail-Verarbeitung

Hauptfunktionen:
1. E-Mail-Abruf (IMAP)
2. Signatur-Erkennung
3. Verfügungserkennung
4. Klassifikation (wenn keine Verfügung)
5. Speicherung + Audit-Logging
"""

import imaplib
import email
import email.policy
from email.header import decode_header
from email.utils import parsedate_to_datetime, parseaddr
import hashlib
import json
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple, BinaryIO
import time

from database.db import get_db
from database.models import (
    Email, EmailAttachment, EmailClassificationRule, EmailProcessingLog,
    Folder, Document
)
from config.settings import get_settings
from services.signature_service import get_signature_service
from services.disposition_service import get_disposition_engine

logger = logging.getLogger(__name__)


class EmailProcessingService:
    """Haupt-Service für E-Mail-Verarbeitung"""

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.settings = get_settings()
        self.signature_service = get_signature_service(user_id)
        self.disposition_engine = get_disposition_engine(user_id)
        self._ai_service = None
        self._classifier = None

    @property
    def ai_service(self):
        """Lazy-Loading des AI-Service"""
        if self._ai_service is None:
            try:
                from services.ai_service import get_ai_service
                self._ai_service = get_ai_service()
            except ImportError:
                pass
        return self._ai_service

    @property
    def classifier(self):
        """Lazy-Loading des Document Classifiers"""
        if self._classifier is None:
            try:
                from services.document_classifier import get_classifier
                self._classifier = get_classifier(self.user_id)
            except ImportError:
                pass
        return self._classifier

    # ============================================================
    # IMAP E-MAIL-ABRUF
    # ============================================================

    def fetch_new_emails(self, max_count: int = 50) -> List[Dict]:
        """
        Ruft neue E-Mails vom IMAP-Server ab.

        Returns:
            Liste der abgerufenen E-Mails als Dicts
        """
        if not self.settings.imap_server or not self.settings.imap_username:
            logger.warning("IMAP nicht konfiguriert")
            return []

        fetched_emails = []

        try:
            # IMAP-Verbindung herstellen
            if self.settings.imap_port == 993:
                mail = imaplib.IMAP4_SSL(
                    self.settings.imap_server,
                    self.settings.imap_port
                )
            else:
                mail = imaplib.IMAP4(
                    self.settings.imap_server,
                    self.settings.imap_port
                )

            mail.login(self.settings.imap_username, self.settings.imap_password)

            # INBOX auswählen
            mail.select("INBOX")

            # Ungelesene E-Mails suchen
            status, messages = mail.search(None, "UNSEEN")
            if status != "OK":
                logger.error("Fehler bei IMAP-Suche")
                return []

            email_ids = messages[0].split()
            logger.info(f"{len(email_ids)} neue E-Mails gefunden")

            # Limitieren
            email_ids = email_ids[:max_count]

            for email_id in email_ids:
                try:
                    # E-Mail abrufen
                    status, data = mail.fetch(email_id, "(RFC822)")
                    if status != "OK":
                        continue

                    raw_email = data[0][1]
                    parsed = self._parse_email(raw_email)

                    if parsed:
                        # Prüfen ob bereits verarbeitet (anhand Message-ID)
                        if not self._email_exists(parsed.get("message_id")):
                            fetched_emails.append(parsed)
                        else:
                            logger.debug(f"E-Mail bereits vorhanden: {parsed.get('message_id')}")

                except Exception as e:
                    logger.error(f"Fehler beim Abrufen von E-Mail {email_id}: {e}")

            mail.logout()

        except imaplib.IMAP4.error as e:
            logger.error(f"IMAP-Fehler: {e}")
        except Exception as e:
            logger.error(f"Fehler beim E-Mail-Abruf: {e}")

        return fetched_emails

    def _parse_email(self, raw_email: bytes) -> Optional[Dict]:
        """Parst eine rohe E-Mail"""
        try:
            msg = email.message_from_bytes(raw_email, policy=email.policy.default)

            # Header extrahieren
            result = {
                "message_id": msg.get("Message-ID", ""),
                "subject": self._decode_header(msg.get("Subject", "")),
                "from_address": "",
                "from_name": "",
                "to_addresses": [],
                "cc_addresses": [],
                "bcc_addresses": [],
                "reply_to": msg.get("Reply-To", ""),
                "date": None,
                "body_text": "",
                "body_html": "",
                "attachments": [],
                "in_reply_to": msg.get("In-Reply-To", ""),
                "references": msg.get("References", ""),
                "raw_data": raw_email
            }

            # Absender parsen
            from_header = msg.get("From", "")
            from_name, from_addr = parseaddr(from_header)
            result["from_name"] = self._decode_header(from_name) if from_name else ""
            result["from_address"] = from_addr

            # Empfänger parsen
            result["to_addresses"] = self._parse_address_list(msg.get("To", ""))
            result["cc_addresses"] = self._parse_address_list(msg.get("Cc", ""))
            result["bcc_addresses"] = self._parse_address_list(msg.get("Bcc", ""))

            # Datum parsen
            date_str = msg.get("Date")
            if date_str:
                try:
                    result["date"] = parsedate_to_datetime(date_str)
                except Exception:
                    result["date"] = datetime.now()
            else:
                result["date"] = datetime.now()

            # Body und Anhänge extrahieren
            self._extract_body_and_attachments(msg, result)

            return result

        except Exception as e:
            logger.error(f"Fehler beim Parsen der E-Mail: {e}")
            return None

    def _decode_header(self, header_value: str) -> str:
        """Dekodiert E-Mail-Header"""
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
        """Parst E-Mail-Adressen-Liste"""
        if not header_value:
            return []

        addresses = []
        decoded = self._decode_header(header_value)

        email_pattern = r'([^<,]+)?<?([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})>?'
        matches = re.findall(email_pattern, decoded)

        for name, addr in matches:
            addresses.append({
                "name": name.strip().strip('"') if name else "",
                "address": addr.strip()
            })

        return addresses

    def _extract_body_and_attachments(self, msg, result: Dict):
        """Extrahiert Body und Anhänge"""
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
                                    "size": len(payload),
                                    "content_hash": hashlib.sha256(payload).hexdigest(),
                                    "content_disposition": "attachment"
                                })
                        except Exception as e:
                            logger.warning(f"Fehler beim Anhang {filename}: {e}")

                # Text-Body
                elif content_type == "text/plain" and not result["body_text"]:
                    try:
                        payload = part.get_payload(decode=True)
                        if payload:
                            charset = part.get_content_charset() or "utf-8"
                            result["body_text"] = payload.decode(charset, errors="replace")
                    except Exception:
                        pass

                # HTML-Body
                elif content_type == "text/html" and not result["body_html"]:
                    try:
                        payload = part.get_payload(decode=True)
                        if payload:
                            charset = part.get_content_charset() or "utf-8"
                            result["body_html"] = payload.decode(charset, errors="replace")
                    except Exception:
                        pass
        else:
            # Einfache E-Mail
            content_type = msg.get_content_type()
            try:
                payload = msg.get_payload(decode=True)
                if payload:
                    charset = msg.get_content_charset() or "utf-8"
                    decoded = payload.decode(charset, errors="replace")
                    if content_type == "text/html":
                        result["body_html"] = decoded
                        result["body_text"] = self._html_to_text(decoded)
                    else:
                        result["body_text"] = decoded
            except Exception:
                pass

        # Fallback: HTML zu Text
        if not result["body_text"] and result["body_html"]:
            result["body_text"] = self._html_to_text(result["body_html"])

    def _html_to_text(self, html: str) -> str:
        """Konvertiert HTML zu Text"""
        if not html:
            return ""

        import html as html_module

        text = html
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'</?p[^>]*>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'<[^>]+>', '', text)
        text = html_module.unescape(text)
        text = re.sub(r'\n\s*\n', '\n\n', text)

        return text.strip()

    def _email_exists(self, message_id: str) -> bool:
        """Prüft ob E-Mail bereits existiert"""
        if not message_id:
            return False

        with get_db() as session:
            exists = session.query(Email).filter(
                Email.user_id == self.user_id,
                Email.message_id == message_id
            ).first()
            return exists is not None

    # ============================================================
    # E-MAIL-VERARBEITUNG (PIPELINE)
    # ============================================================

    def process_email(self, email_data: Dict) -> Dict:
        """
        Verarbeitet eine E-Mail durch die komplette Pipeline.

        Pipeline:
        1. Speichern in DB
        2. Signatur-Erkennung
        3. Verfügungserkennung
        4. Klassifikation (wenn keine Verfügung)
        5. Anhänge verarbeiten
        6. Audit-Log

        Returns:
            Dict mit Verarbeitungsergebnis
        """
        result = {
            "success": False,
            "email_id": None,
            "signature_detected": False,
            "has_disposition": False,
            "classification": None,
            "attachments_count": 0,
            "errors": [],
            "logs": []
        }

        start_time = datetime.now()

        try:
            # 1. E-Mail in DB speichern
            email_id = self._save_email(email_data)
            if not email_id:
                result["errors"].append("Fehler beim Speichern der E-Mail")
                return result

            result["email_id"] = email_id
            self._log_step(email_id, "save", "success", "E-Mail gespeichert")

            # 2. Signatur-Erkennung
            sig_result = self._process_signature(email_id, email_data)
            result["signature_detected"] = sig_result.get("detected", False)
            if sig_result.get("detected"):
                self._log_step(
                    email_id, "signature", "success",
                    f"Signatur erkannt: {sig_result.get('signature_name')}",
                    {"confidence": sig_result.get("confidence")}
                )

            # Text ohne Signatur für weitere Analyse
            clean_text = sig_result.get("stripped_text", email_data.get("body_text", ""))

            # 3. Verfügungserkennung
            disp_result = self._process_disposition(email_id, clean_text, email_data.get("subject"))
            result["has_disposition"] = disp_result.get("has_disposition", False)

            if disp_result.get("has_disposition"):
                self._log_step(
                    email_id, "disposition", "success",
                    f"Verfügung erkannt: {disp_result.get('trigger_keyword')}",
                    {
                        "type": disp_result.get("disposition_type"),
                        "confidence": disp_result.get("confidence"),
                        "actions": disp_result.get("actions", [])
                    }
                )

            # 4. Klassifikation (wenn keine Verfügung)
            if not result["has_disposition"]:
                class_result = self._process_classification(email_id, email_data)
                result["classification"] = class_result
                if class_result:
                    self._log_step(
                        email_id, "classify", "success",
                        f"Klassifiziert: {class_result.get('folder_path', 'Unbekannt')}",
                        class_result
                    )

            # 5. Anhänge verarbeiten
            attachments = email_data.get("attachments", [])
            if attachments:
                att_count = self._process_attachments(email_id, attachments)
                result["attachments_count"] = att_count
                self._log_step(
                    email_id, "attachments", "success",
                    f"{att_count} Anhänge verarbeitet"
                )

            # 6. Verarbeitungsstatus aktualisieren
            self._update_processing_status(email_id, "completed")

            result["success"] = True

        except Exception as e:
            logger.error(f"Fehler bei E-Mail-Verarbeitung: {e}")
            result["errors"].append(str(e))
            if result.get("email_id"):
                self._update_processing_status(result["email_id"], "error", str(e))

        # Dauer berechnen
        duration = (datetime.now() - start_time).total_seconds() * 1000
        result["duration_ms"] = int(duration)

        return result

    def _save_email(self, email_data: Dict) -> Optional[int]:
        """Speichert E-Mail in der Datenbank"""
        with get_db() as session:
            email_obj = Email(
                user_id=self.user_id,
                message_id=email_data.get("message_id"),
                folder="inbox",
                from_address=email_data.get("from_address"),
                from_name=email_data.get("from_name"),
                to_addresses=json.dumps(email_data.get("to_addresses", [])),
                cc_addresses=json.dumps(email_data.get("cc_addresses", [])),
                bcc_addresses=json.dumps(email_data.get("bcc_addresses", [])),
                reply_to=email_data.get("reply_to"),
                subject=email_data.get("subject"),
                body_text=email_data.get("body_text"),
                body_html=email_data.get("body_html"),
                received_at=email_data.get("date"),
                in_reply_to=email_data.get("in_reply_to"),
                references=email_data.get("references"),
                has_attachments=len(email_data.get("attachments", [])) > 0,
                processing_status="processing"
            )
            session.add(email_obj)
            session.commit()

            return email_obj.id

    def _process_signature(self, email_id: int, email_data: Dict) -> Dict:
        """Verarbeitet Signatur-Erkennung"""
        body_text = email_data.get("body_text", "")
        from_address = email_data.get("from_address")

        sig_result = self.signature_service.detect_signature(body_text, from_address)

        with get_db() as session:
            email_obj = session.get(Email, email_id)
            if email_obj:
                email_obj.signature_detected = sig_result.get("detected", False)
                email_obj.signature_id = sig_result.get("signature_id")
                email_obj.signature_confidence = sig_result.get("confidence")
                session.commit()

        return sig_result

    def _process_disposition(self, email_id: int, text: str, subject: str = None) -> Dict:
        """Verarbeitet Verfügungserkennung"""
        disp_result = self.disposition_engine.detect_disposition(text, subject)

        if disp_result.get("has_disposition"):
            self.disposition_engine.save_disposition(email_id, disp_result)

        return disp_result

    def _process_classification(self, email_id: int, email_data: Dict) -> Optional[Dict]:
        """Klassifiziert E-Mail (wenn keine Verfügung)"""
        # Klassifikationsregeln prüfen
        rule_result = self._apply_classification_rules(email_data)

        if rule_result:
            with get_db() as session:
                email_obj = session.get(Email, email_id)
                if email_obj:
                    email_obj.classification_folder_id = rule_result.get("folder_id")
                    email_obj.classification_tags = rule_result.get("tags")
                    email_obj.classification_confidence = rule_result.get("confidence")
                    email_obj.classification_reason = rule_result.get("reason")
                    email_obj.classification_rule_id = rule_result.get("rule_id")
                    session.commit()

            return rule_result

        # Fallback: Document Classifier verwenden
        if self.classifier:
            try:
                metadata = {
                    "sender": email_data.get("from_name") or email_data.get("from_address"),
                    "title": email_data.get("subject"),
                    "document_date": email_data.get("date")
                }
                full_text = f"Betreff: {email_data.get('subject', '')}\n\n{email_data.get('body_text', '')}"

                class_result = self.classifier.classify(full_text, metadata, save_explanation=False)

                with get_db() as session:
                    email_obj = session.get(Email, email_id)
                    if email_obj:
                        email_obj.classification_folder_id = class_result.get("primary_folder_id")
                        email_obj.classification_confidence = class_result.get("confidence")
                        email_obj.classification_reason = f"Kategorie: {class_result.get('category')}"
                        session.commit()

                return class_result
            except Exception as e:
                logger.warning(f"Document Classifier fehlgeschlagen: {e}")

        return None

    def _apply_classification_rules(self, email_data: Dict) -> Optional[Dict]:
        """Wendet E-Mail-Klassifikationsregeln an"""
        with get_db() as session:
            rules = session.query(EmailClassificationRule).filter(
                EmailClassificationRule.user_id == self.user_id,
                EmailClassificationRule.is_enabled == True
            ).order_by(EmailClassificationRule.priority.desc()).all()

            for rule in rules:
                if self._rule_matches(rule, email_data):
                    # Regel-Statistik aktualisieren
                    rule.times_applied = (rule.times_applied or 0) + 1
                    rule.last_applied_at = datetime.now()
                    session.commit()

                    return {
                        "rule_id": rule.id,
                        "folder_id": rule.target_folder_id,
                        "folder_path": rule.target_folder_path,
                        "tags": rule.assign_tags,
                        "category": rule.assign_category,
                        "confidence": 0.9,
                        "reason": f"Regel: {rule.name}"
                    }

        return None

    def _rule_matches(self, rule: EmailClassificationRule, email_data: Dict) -> bool:
        """Prüft ob eine Regel auf die E-Mail zutrifft"""
        conditions = rule.conditions or {}
        operator = conditions.get("operator", "AND")
        condition_list = conditions.get("conditions", [])

        if not condition_list:
            return False

        results = []

        for cond in condition_list:
            field = cond.get("field")
            op = cond.get("op", "contains")
            value = cond.get("value", "")

            # Feldwert aus E-Mail holen
            if field == "from_address":
                field_value = email_data.get("from_address", "")
            elif field == "subject":
                field_value = email_data.get("subject", "")
            elif field == "body":
                field_value = email_data.get("body_text", "")
            else:
                field_value = ""

            field_value_lower = field_value.lower()
            value_lower = str(value).lower()

            # Operation anwenden
            if op == "contains":
                results.append(value_lower in field_value_lower)
            elif op == "equals":
                results.append(field_value_lower == value_lower)
            elif op == "startswith":
                results.append(field_value_lower.startswith(value_lower))
            elif op == "endswith":
                results.append(field_value_lower.endswith(value_lower))
            elif op == "regex":
                try:
                    results.append(bool(re.search(value, field_value, re.IGNORECASE)))
                except re.error:
                    results.append(False)
            else:
                results.append(False)

        # Operator anwenden
        if operator == "AND":
            return all(results)
        elif operator == "OR":
            return any(results)

        return False

    def _process_attachments(self, email_id: int, attachments: List[Dict]) -> int:
        """Verarbeitet E-Mail-Anhänge"""
        count = 0

        with get_db() as session:
            for att in attachments:
                try:
                    attachment = EmailAttachment(
                        email_id=email_id,
                        filename=att.get("filename"),
                        mime_type=att.get("mime_type"),
                        size=att.get("size"),
                        content_hash=att.get("content_hash"),
                        content_disposition=att.get("content_disposition", "attachment"),
                        is_stored=False  # Wird später gespeichert
                    )
                    session.add(attachment)
                    count += 1
                except Exception as e:
                    logger.warning(f"Fehler bei Anhang-Speicherung: {e}")

            session.commit()

        return count

    def _update_processing_status(self, email_id: int, status: str, error: str = None):
        """Aktualisiert Verarbeitungsstatus"""
        with get_db() as session:
            email_obj = session.get(Email, email_id)
            if email_obj:
                email_obj.processing_status = status
                email_obj.processed_at = datetime.now()
                if error:
                    email_obj.processing_error = error
                if status == "error" or (email_obj.classification_confidence or 0) < 0.5:
                    email_obj.needs_review = True
                session.commit()

    def _log_step(
        self,
        email_id: int,
        step: str,
        status: str,
        message: str,
        details: Dict = None
    ):
        """Erstellt Audit-Log-Eintrag"""
        with get_db() as session:
            log = EmailProcessingLog(
                email_id=email_id,
                user_id=self.user_id,
                step=step,
                status=status,
                message=message,
                details=details,
                completed_at=datetime.now()
            )
            session.add(log)
            session.commit()

    # ============================================================
    # BATCH-VERARBEITUNG
    # ============================================================

    def fetch_and_process_all(self, max_count: int = 50) -> Dict:
        """
        Ruft neue E-Mails ab und verarbeitet sie.

        Returns:
            Dict mit Statistiken
        """
        result = {
            "fetched": 0,
            "processed": 0,
            "errors": 0,
            "dispositions_found": 0,
            "details": []
        }

        # E-Mails abrufen
        emails = self.fetch_new_emails(max_count)
        result["fetched"] = len(emails)

        # E-Mails verarbeiten
        for email_data in emails:
            try:
                process_result = self.process_email(email_data)

                if process_result.get("success"):
                    result["processed"] += 1
                    if process_result.get("has_disposition"):
                        result["dispositions_found"] += 1
                else:
                    result["errors"] += 1

                result["details"].append({
                    "subject": email_data.get("subject", "")[:50],
                    "success": process_result.get("success"),
                    "has_disposition": process_result.get("has_disposition"),
                    "email_id": process_result.get("email_id")
                })

            except Exception as e:
                result["errors"] += 1
                logger.error(f"Fehler bei E-Mail-Verarbeitung: {e}")

        logger.info(
            f"E-Mail-Abruf abgeschlossen: {result['fetched']} abgerufen, "
            f"{result['processed']} verarbeitet, {result['errors']} Fehler"
        )

        return result


# Singleton-Cache
_email_services: Dict[int, EmailProcessingService] = {}


def get_email_processing_service(user_id: int) -> EmailProcessingService:
    """Gibt EmailProcessingService für Benutzer zurück"""
    if user_id not in _email_services:
        _email_services[user_id] = EmailProcessingService(user_id)
    return _email_services[user_id]
