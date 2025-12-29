"""
Field Learning Service - Wendet gelernte Feldpositionen auf neue Dokumente an
"""
import io
import re
from typing import Dict, Optional, List, Tuple
from datetime import datetime
from PIL import Image
import streamlit as st

from database.db import get_db
from database.models import LayoutTemplate, FieldAnnotation, FieldType, Document


class FieldLearningService:
    """Service für lernende Felderkennung basierend auf Benutzer-Annotationen"""

    def __init__(self, user_id: int):
        self.user_id = user_id
        self._ocr_service = None

    @property
    def ocr_service(self):
        """Lazy-Load OCR Service"""
        if self._ocr_service is None:
            from services.ocr import get_ocr_service
            self._ocr_service = get_ocr_service()
        return self._ocr_service

    def find_matching_template(self, document_text: str, sender: str = None) -> Optional[LayoutTemplate]:
        """
        Findet ein passendes Layout-Template für ein Dokument.

        Args:
            document_text: Der OCR-Text des Dokuments
            sender: Optional erkannter Absender

        Returns:
            Das beste passende Template oder None
        """
        with get_db() as session:
            templates = session.query(LayoutTemplate).filter(
                LayoutTemplate.user_id == self.user_id,
                LayoutTemplate.is_active == True
            ).order_by(LayoutTemplate.confidence.desc()).all()

            best_match = None
            best_score = 0

            for template in templates:
                score = self._calculate_match_score(template, document_text, sender)

                if score > best_score and score >= 0.5:  # Mindest-Score
                    best_score = score
                    best_match = template

            if best_match:
                # Template-Daten zurückgeben (außerhalb der Session)
                return {
                    'id': best_match.id,
                    'name': best_match.name,
                    'sender_pattern': best_match.sender_pattern,
                    'field_positions': best_match.field_positions,
                    'confidence': best_match.confidence,
                    'score': best_score
                }

            return None

    def _calculate_match_score(self, template: LayoutTemplate,
                               document_text: str, sender: str = None) -> float:
        """Berechnet einen Match-Score zwischen Template und Dokument"""
        score = 0.0
        text_lower = document_text.lower()

        # Absender-Match (höchste Gewichtung)
        if template.sender_pattern:
            pattern = template.sender_pattern.lower()

            # Exakter Match im Absender
            if sender and pattern in sender.lower():
                score += 0.6
            # Pattern im Text gefunden
            elif pattern in text_lower:
                score += 0.4
            else:
                # Regex-Match versuchen
                try:
                    if re.search(pattern, text_lower):
                        score += 0.3
                except re.error:
                    pass

        # Keyword-Match
        if template.keywords:
            matches = sum(1 for kw in template.keywords if kw.lower() in text_lower)
            if template.keywords:
                keyword_score = matches / len(template.keywords)
                score += keyword_score * 0.3

        # Confidence des Templates berücksichtigen
        score *= template.confidence

        return min(score, 1.0)

    def extract_fields_with_template(self, image: Image.Image,
                                      template_data: dict) -> Dict[str, str]:
        """
        Extrahiert Felder aus einem Bild basierend auf Template-Positionen.

        Args:
            image: Das Dokument als PIL Image
            template_data: Das Template mit Feldpositionen

        Returns:
            Dict mit Feldnamen und extrahierten Werten
        """
        results = {}
        field_positions = template_data.get('field_positions', {})

        for field_name, position in field_positions.items():
            try:
                # Koordinaten extrahieren
                x_pct = position.get('x', 0)
                y_pct = position.get('y', 0)
                w_pct = position.get('w', 0.1)
                h_pct = position.get('h', 0.05)

                # Text extrahieren
                text = self._extract_text_from_region(
                    image, x_pct, y_pct, w_pct, h_pct
                )

                if text:
                    # Nachbearbeitung je nach Feldtyp
                    processed_text = self._process_field_value(field_name, text)
                    results[field_name] = processed_text

            except Exception as e:
                # Fehler ignorieren, weiter mit nächstem Feld
                continue

        return results

    def _extract_text_from_region(self, image: Image.Image,
                                   x_pct: float, y_pct: float,
                                   w_pct: float, h_pct: float) -> str:
        """Extrahiert Text aus einem Bildbereich"""
        try:
            img_width, img_height = image.size

            # Pixelkoordinaten berechnen (mit etwas Puffer)
            buffer = 0.01  # 1% Puffer
            x = max(0, int((x_pct - buffer) * img_width))
            y = max(0, int((y_pct - buffer) * img_height))
            w = min(img_width - x, int((w_pct + 2 * buffer) * img_width))
            h = min(img_height - y, int((h_pct + 2 * buffer) * img_height))

            # Bereich ausschneiden
            cropped = image.crop((x, y, x + w, y + h))

            # OCR
            text, confidence = self.ocr_service.extract_text_from_image(cropped)

            return text.strip()

        except Exception as e:
            return ""

    def _process_field_value(self, field_name: str, raw_text: str) -> str:
        """Verarbeitet extrahierten Text je nach Feldtyp"""
        text = raw_text.strip()

        if field_name == 'iban':
            # IBAN formatieren: Nur Buchstaben und Zahlen
            text = re.sub(r'[^A-Z0-9]', '', text.upper())

        elif field_name == 'amount':
            # Betrag extrahieren
            match = re.search(r'[\d.,]+', text.replace(' ', ''))
            if match:
                text = match.group()

        elif field_name in ['date', 'due_date']:
            # Datum extrahieren (verschiedene Formate)
            # DD.MM.YYYY oder DD.MM.YY
            match = re.search(r'\d{1,2}\.\d{1,2}\.\d{2,4}', text)
            if match:
                text = match.group()

        elif field_name in ['customer_number', 'invoice_number', 'contract_number', 'reference']:
            # Nummern: Zeilen und extra Spaces entfernen
            text = ' '.join(text.split())

        return text

    def apply_template_to_document(self, document: Document,
                                    image: Image.Image) -> Dict[str, str]:
        """
        Wendet gelernte Templates auf ein Dokument an und aktualisiert die Felder.

        Args:
            document: Das Document-Objekt
            image: Das Dokument als Bild

        Returns:
            Dict mit extrahierten Feldwerten
        """
        # Passendes Template finden
        template = self.find_matching_template(
            document.ocr_text or "",
            document.sender
        )

        if not template:
            return {}

        # Felder extrahieren
        extracted = self.extract_fields_with_template(image, template)

        # Template-Statistik aktualisieren
        with get_db() as session:
            tpl = session.get(LayoutTemplate, template['id'])
            if tpl:
                tpl.times_used = (tpl.times_used or 0) + 1
                session.commit()

        return extracted

    def update_document_with_extracted_fields(self, document_id: int,
                                               extracted_fields: Dict[str, str]):
        """Aktualisiert ein Dokument mit den extrahierten Feldwerten"""
        if not extracted_fields:
            return

        with get_db() as session:
            doc = session.get(Document, document_id)
            if not doc:
                return

            # Felder aktualisieren (nur wenn leer)
            field_mapping = {
                'sender': 'sender',
                'sender_address': 'sender_address',
                'amount': 'invoice_amount',
                'iban': 'iban',
                'customer_number': 'customer_number',
                'invoice_number': 'invoice_number',
                'reference': 'reference_number',
                'contract_number': 'contract_number',
            }

            updated = False
            for field_name, value in extracted_fields.items():
                doc_field = field_mapping.get(field_name)
                if doc_field and value:
                    current = getattr(doc, doc_field, None)
                    if not current:  # Nur wenn leer
                        if doc_field == 'invoice_amount':
                            try:
                                value = float(value.replace(',', '.'))
                            except:
                                continue
                        setattr(doc, doc_field, value)
                        updated = True

            # Datumsfelder separat behandeln
            if 'date' in extracted_fields and not doc.document_date:
                date_str = extracted_fields['date']
                parsed = self._parse_date(date_str)
                if parsed:
                    doc.document_date = parsed
                    updated = True

            if 'due_date' in extracted_fields and not doc.invoice_due_date:
                date_str = extracted_fields['due_date']
                parsed = self._parse_date(date_str)
                if parsed:
                    doc.invoice_due_date = parsed
                    updated = True

            if updated:
                session.commit()

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parst ein Datum aus verschiedenen Formaten"""
        formats = [
            '%d.%m.%Y',
            '%d.%m.%y',
            '%d/%m/%Y',
            '%Y-%m-%d',
        ]

        for fmt in formats:
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except ValueError:
                continue

        return None

    def record_correction(self, template_id: int, field_name: str,
                          expected_value: str, actual_value: str):
        """
        Zeichnet eine Korrektur auf, um das Template zu verbessern.
        """
        with get_db() as session:
            template = session.get(LayoutTemplate, template_id)
            if template:
                template.times_corrected = (template.times_corrected or 0) + 1

                # Confidence anpassen
                if template.times_used and template.times_used > 0:
                    error_rate = template.times_corrected / template.times_used
                    template.confidence = max(0.3, 1.0 - error_rate)

                session.commit()


def get_field_learning_service(user_id: int) -> FieldLearningService:
    """Factory für FieldLearningService"""
    return FieldLearningService(user_id)
