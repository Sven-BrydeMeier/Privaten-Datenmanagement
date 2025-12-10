"""
OCR-Service für Texterkennung aus Dokumenten und Bildern
"""
import io
import re
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from PIL import Image
import streamlit as st

from config.settings import get_settings


class OCRService:
    """Service für Optical Character Recognition"""

    def __init__(self):
        self.settings = get_settings()
        self._tesseract_available = None

    @property
    def tesseract_available(self) -> bool:
        """Prüft ob Tesseract verfügbar ist"""
        if self._tesseract_available is None:
            try:
                import pytesseract
                pytesseract.get_tesseract_version()
                self._tesseract_available = True
            except Exception:
                self._tesseract_available = False
        return self._tesseract_available

    def extract_text_from_image(self, image: Image.Image, lang: str = 'deu+eng') -> Tuple[str, float]:
        """
        Extrahiert Text aus einem Bild.

        Args:
            image: PIL Image
            lang: Sprache(n) für OCR

        Returns:
            Tuple aus (extrahierter Text, Konfidenz)
        """
        if self.tesseract_available:
            return self._extract_with_tesseract(image, lang)
        else:
            # Fallback: KI-basierte OCR (wenn API verfügbar)
            return self._extract_with_ai(image)

    def _extract_with_tesseract(self, image: Image.Image, lang: str) -> Tuple[str, float]:
        """Tesseract-basierte Texterkennung"""
        import pytesseract

        # OCR mit Detailinformationen
        data = pytesseract.image_to_data(image, lang=lang, output_type=pytesseract.Output.DICT)

        # Text zusammenbauen und Konfidenz berechnen
        text_parts = []
        confidences = []

        for i, conf in enumerate(data['conf']):
            if int(conf) > 0:  # Nur Wörter mit Konfidenz > 0
                text_parts.append(data['text'][i])
                confidences.append(int(conf))

        text = ' '.join(text_parts)
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0

        return text, avg_confidence / 100.0

    def _extract_with_ai(self, image: Image.Image) -> Tuple[str, float]:
        """KI-basierte Texterkennung (GPT-4 Vision oder Claude)"""
        # Wird später implementiert wenn API-Keys vorhanden
        return "", 0.0

    def extract_text_from_pdf(self, pdf_bytes: bytes) -> List[Tuple[str, float]]:
        """
        Extrahiert Text aus allen Seiten eines PDFs.

        Args:
            pdf_bytes: PDF als Bytes

        Returns:
            Liste von (Text, Konfidenz) pro Seite
        """
        results = []

        try:
            from PyPDF2 import PdfReader

            # Erst versuchen, eingebetteten Text zu extrahieren
            reader = PdfReader(io.BytesIO(pdf_bytes))
            for page in reader.pages:
                text = page.extract_text()
                if text and len(text.strip()) > 50:
                    # Eingebetteter Text gefunden
                    results.append((text, 1.0))
                else:
                    # Kein Text - OCR nötig
                    results.append(("", 0.0))

            # Wenn zu wenig Text gefunden, OCR auf Bilder anwenden
            if all(conf < 0.5 for _, conf in results):
                results = self._ocr_pdf_images(pdf_bytes)

        except Exception as e:
            st.error(f"PDF-Verarbeitungsfehler: {e}")
            results = []

        return results

    def _ocr_pdf_images(self, pdf_bytes: bytes) -> List[Tuple[str, float]]:
        """Konvertiert PDF zu Bildern und führt OCR durch"""
        results = []

        try:
            from pdf2image import convert_from_bytes

            images = convert_from_bytes(pdf_bytes, dpi=300)
            for image in images:
                text, confidence = self.extract_text_from_image(image)
                results.append((text, confidence))

        except Exception as e:
            st.warning(f"PDF zu Bild Konvertierung fehlgeschlagen: {e}")

        return results

    def extract_metadata(self, text: str) -> Dict:
        """
        Extrahiert strukturierte Metadaten aus Text.

        Args:
            text: OCR-Text

        Returns:
            Dictionary mit extrahierten Metadaten
        """
        metadata = {
            'sender': None,
            'dates': [],
            'amounts': [],
            'ibans': [],
            'contract_numbers': [],
            'deadlines': [],
            'category_hints': []
        }

        # Datum extrahieren (verschiedene deutsche Formate)
        date_patterns = [
            r'\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b',  # 01.12.2024
            r'\b(\d{1,2})\.(\d{1,2})\.(\d{2})\b',   # 01.12.24
            r'\b(\d{4})-(\d{2})-(\d{2})\b',         # 2024-12-01
        ]

        for pattern in date_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                try:
                    if len(match[2]) == 4:  # Volles Jahr
                        date_str = f"{match[0]}.{match[1]}.{match[2]}"
                        date = datetime.strptime(date_str, "%d.%m.%Y")
                    elif len(match[0]) == 4:  # ISO Format
                        date = datetime(int(match[0]), int(match[1]), int(match[2]))
                    else:  # Kurzes Jahr
                        year = 2000 + int(match[2]) if int(match[2]) < 50 else 1900 + int(match[2])
                        date = datetime(year, int(match[1]), int(match[0]))
                    metadata['dates'].append(date)
                except ValueError:
                    pass

        # Beträge extrahieren
        amount_patterns = [
            r'(\d{1,3}(?:\.\d{3})*,\d{2})\s*(?:€|EUR|Euro)',  # 1.234,56 €
            r'(?:€|EUR|Euro)\s*(\d{1,3}(?:\.\d{3})*,\d{2})',  # € 1.234,56
            r'Betrag:?\s*(\d{1,3}(?:\.\d{3})*,\d{2})',        # Betrag: 123,45
            r'Summe:?\s*(\d{1,3}(?:\.\d{3})*,\d{2})',         # Summe: 123,45
            r'Gesamt:?\s*(\d{1,3}(?:\.\d{3})*,\d{2})',        # Gesamt: 123,45
        ]

        for pattern in amount_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                try:
                    # Deutsche Notation zu Float konvertieren
                    amount = float(match.replace('.', '').replace(',', '.'))
                    if amount not in metadata['amounts']:
                        metadata['amounts'].append(amount)
                except ValueError:
                    pass

        # IBAN extrahieren
        iban_pattern = r'\b([A-Z]{2}\d{2}\s*(?:\d{4}\s*){4,7}\d{1,4})\b'
        ibans = re.findall(iban_pattern, text.upper())
        metadata['ibans'] = [iban.replace(' ', '') for iban in ibans]

        # Vertragsnummern
        contract_patterns = [
            r'(?:Vertrags?(?:nummer|nr\.?)|Kunden(?:nummer|nr\.?)|Aktenzeichen)[:\s]*([A-Z0-9\-/]+)',
            r'(?:Ihre\s+)?(?:Nummer|Nr\.?)[:\s]*([A-Z0-9\-/]{6,})',
        ]
        for pattern in contract_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            metadata['contract_numbers'].extend(matches)

        # Fristen erkennen
        deadline_patterns = [
            (r'(?:bitte\s+)?(?:zahlen|überweisen)\s+(?:Sie\s+)?(?:bis|spätestens)\s+(?:zum\s+)?(\d{1,2}\.\d{1,2}\.\d{2,4})', 'payment'),
            (r'Frist[:\s]+(\d{1,2}\.\d{1,2}\.\d{2,4})', 'general'),
            (r'(?:bis|spätestens)\s+(?:zum\s+)?(\d{1,2}\.\d{1,2}\.\d{2,4})', 'general'),
            (r'Kündigungsfrist[:\s]+(\d+)\s*(?:Wochen?|Monate?|Tage?)', 'notice'),
        ]

        for pattern, deadline_type in deadline_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                metadata['deadlines'].append({'date_str': match, 'type': deadline_type})

        # Kategorie-Hinweise
        category_keywords = {
            'Rechnung': ['rechnung', 'invoice', 'zahlungsaufforderung', 'fälligkeit'],
            'Vertrag': ['vertrag', 'vereinbarung', 'konditionen', 'laufzeit'],
            'Versicherung': ['versicherung', 'police', 'schadensmeldung', 'prämie'],
            'Darlehen': ['darlehen', 'kredit', 'tilgung', 'zinsen', 'rate'],
            'Kontoauszug': ['kontoauszug', 'kontobewegungen', 'saldo', 'buchungen'],
            'Lohnabrechnung': ['lohnabrechnung', 'gehaltsabrechnung', 'brutto', 'netto', 'sozialversicherung'],
            'Mahnung': ['mahnung', 'zahlungserinnerung', 'mahngebühr', 'verzug'],
        }

        text_lower = text.lower()
        for category, keywords in category_keywords.items():
            for keyword in keywords:
                if keyword in text_lower:
                    if category not in metadata['category_hints']:
                        metadata['category_hints'].append(category)
                    break

        return metadata

    def detect_separator_page(self, image: Image.Image) -> bool:
        """
        Erkennt ob eine Seite eine Trennseite ist.

        Args:
            image: Seitenbild

        Returns:
            True wenn Trennseite erkannt
        """
        text, confidence = self.extract_text_from_image(image)

        # Prüfen auf "Trennseite" oder ähnliche Marker
        separator_markers = ['trennseite', 'separator', '---', '***', 'neue dokument']
        text_lower = text.lower().strip()

        for marker in separator_markers:
            if marker in text_lower:
                # Prüfen ob die Seite hauptsächlich weiß ist
                if self._is_mostly_white(image):
                    return True

        return False

    def _is_mostly_white(self, image: Image.Image, threshold: float = 0.95) -> bool:
        """Prüft ob ein Bild hauptsächlich weiß ist"""
        # In Graustufen konvertieren
        gray = image.convert('L')

        # Pixel zählen
        pixels = list(gray.getdata())
        white_pixels = sum(1 for p in pixels if p > 240)

        return (white_pixels / len(pixels)) > threshold

    def extract_receipt_data(self, text: str) -> Dict:
        """
        Extrahiert strukturierte Daten aus einem Kassenbon.

        Args:
            text: OCR-Text des Bons

        Returns:
            Dictionary mit Bon-Daten und Positionen
        """
        receipt_data = {
            'merchant': None,
            'date': None,
            'total': None,
            'items': [],
            'payment_method': None,
            'tax_info': [],
            'suggested_category': None
        }

        lines = text.split('\n')
        text_lower = text.lower()

        # Händler erkennen (meist in den ersten Zeilen)
        merchant_indicators = ['gmbh', 'ag', 'kg', 'ohg', 'e.k.', 'gbr', 'markt', 'laden', 'shop', 'filiale']
        for line in lines[:5]:
            line_lower = line.lower().strip()
            if any(ind in line_lower for ind in merchant_indicators) or (len(line.strip()) > 3 and line.strip().isupper()):
                receipt_data['merchant'] = line.strip()
                break

        # Datum extrahieren
        date_patterns = [
            r'(\d{2})[./](\d{2})[./](\d{4})',
            r'(\d{2})[./](\d{2})[./](\d{2})',
        ]
        for pattern in date_patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    day, month, year = match.groups()
                    if len(year) == 2:
                        year = '20' + year
                    receipt_data['date'] = datetime(int(year), int(month), int(day))
                    break
                except:
                    pass

        # Gesamtbetrag finden (typischerweise mit SUMME, TOTAL, GESAMT, etc.)
        total_patterns = [
            r'(?:summe|total|gesamt|zu zahlen|betrag)[:\s]*(\d{1,3}(?:[.,]\d{3})*[.,]\d{2})',
            r'(?:bar|ec|karte)[:\s]*(\d{1,3}(?:[.,]\d{3})*[.,]\d{2})',
            r'(\d{1,3}(?:[.,]\d{3})*[.,]\d{2})\s*(?:eur|€)',
        ]
        for pattern in total_patterns:
            match = re.search(pattern, text_lower)
            if match:
                amount_str = match.group(1).replace('.', '').replace(',', '.')
                try:
                    receipt_data['total'] = float(amount_str)
                    break
                except:
                    pass

        # Einzelne Positionen extrahieren
        # Typisches Format: Artikelname ... Preis
        item_pattern = r'([A-Za-zäöüÄÖÜß\s\-\.]+?)\s+(\d{1,2}[,\.]\d{2})\s*[AaBb]?'

        for line in lines:
            # Überspringe Zeilen mit Gesamtsumme, MwSt etc.
            line_lower = line.lower()
            if any(skip in line_lower for skip in ['summe', 'total', 'gesamt', 'mwst', 'steuer', 'zwischensumme']):
                continue

            match = re.search(item_pattern, line)
            if match:
                name = match.group(1).strip()
                price_str = match.group(2).replace(',', '.')

                # Filter: Name sollte mindestens 2 Zeichen haben
                if len(name) >= 2 and name not in ['', ' ']:
                    try:
                        price = float(price_str)
                        if 0.01 <= price <= 10000:  # Plausibilitätsprüfung
                            receipt_data['items'].append({
                                'name': name,
                                'price': price,
                                'quantity': 1
                            })
                    except:
                        pass

        # Zahlungsmethode erkennen
        payment_keywords = {
            'bar': ['bar', 'bargeld', 'cash'],
            'ec': ['ec', 'girocard', 'maestro', 'debit'],
            'kreditkarte': ['visa', 'mastercard', 'amex', 'kredit'],
            'kontaktlos': ['kontaktlos', 'nfc', 'apple pay', 'google pay']
        }
        for method, keywords in payment_keywords.items():
            if any(kw in text_lower for kw in keywords):
                receipt_data['payment_method'] = method
                break

        # MwSt-Informationen
        tax_pattern = r'(?:mwst|ust|steuer)[:\s]*(\d+(?:[.,]\d+)?)\s*%?\s*[:\s]*(\d{1,3}(?:[.,]\d{3})*[.,]\d{2})?'
        tax_matches = re.findall(tax_pattern, text_lower)
        for match in tax_matches:
            tax_rate = match[0].replace(',', '.')
            tax_amount = match[1].replace('.', '').replace(',', '.') if match[1] else None
            receipt_data['tax_info'].append({
                'rate': float(tax_rate) if tax_rate else None,
                'amount': float(tax_amount) if tax_amount else None
            })

        # Kategorie basierend auf Inhalt vorschlagen
        category_hints = {
            'Lebensmittel': ['milch', 'brot', 'obst', 'gemüse', 'fleisch', 'käse', 'joghurt', 'reis', 'nudeln', 'butter', 'eier', 'wurst', 'bio'],
            'Restaurant': ['speise', 'gericht', 'menü', 'getränk', 'bier', 'wein', 'kaffee', 'trinkgeld', 'bedienung'],
            'Transport': ['benzin', 'diesel', 'tanken', 'parkhaus', 'ticket', 'fahrkarte', 'bahn', 'bus'],
            'Einkauf': ['kleidung', 'schuhe', 'hose', 'hemd', 'jacke', 'möbel', 'elektronik'],
            'Gesundheit': ['apotheke', 'medikament', 'arzt', 'rezept', 'pflaster'],
            'Unterkunft': ['hotel', 'pension', 'übernachtung', 'zimmer'],
        }

        for category, keywords in category_hints.items():
            if any(kw in text_lower for kw in keywords):
                receipt_data['suggested_category'] = category
                break

        if not receipt_data['suggested_category']:
            receipt_data['suggested_category'] = 'Sonstiges'

        return receipt_data


def get_ocr_service() -> OCRService:
    """Singleton für den OCR-Service"""
    if 'ocr_service' not in st.session_state:
        st.session_state.ocr_service = OCRService()
    return st.session_state.ocr_service
