"""
KI-Service für intelligente Dokumentenverarbeitung
Unterstützt OpenAI (GPT) und Anthropic (Claude)
"""
import json
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import streamlit as st

from config.settings import get_settings


class AIService:
    """Service für KI-basierte Textanalyse und -generierung"""

    def __init__(self):
        self.settings = get_settings()
        self._openai_client = None
        self._anthropic_client = None

    @property
    def openai_available(self) -> bool:
        """Prüft ob OpenAI API verfügbar ist"""
        return bool(self.settings.openai_api_key)

    @property
    def anthropic_available(self) -> bool:
        """Prüft ob Anthropic API verfügbar ist"""
        return bool(self.settings.anthropic_api_key)

    @property
    def any_ai_available(self) -> bool:
        """Prüft ob mindestens eine KI-API verfügbar ist"""
        return self.openai_available or self.anthropic_available

    def get_openai_client(self):
        """Lazy-Loading des OpenAI Clients"""
        if self._openai_client is None and self.openai_available:
            from openai import OpenAI
            self._openai_client = OpenAI(api_key=self.settings.openai_api_key)
        return self._openai_client

    def get_anthropic_client(self):
        """Lazy-Loading des Anthropic Clients"""
        if self._anthropic_client is None and self.anthropic_available:
            import anthropic
            self._anthropic_client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)
        return self._anthropic_client

    def test_connection(self) -> Dict[str, bool]:
        """
        Testet die Verbindung zu den KI-APIs.

        Returns:
            Dictionary mit Status pro API
        """
        status = {
            'openai': False,
            'anthropic': False,
            'openai_error': None,
            'anthropic_error': None
        }

        # OpenAI testen
        if self.openai_available:
            try:
                client = self.get_openai_client()
                # Einfacher Test-Request
                client.models.list()
                status['openai'] = True
            except Exception as e:
                status['openai_error'] = str(e)

        # Anthropic testen
        if self.anthropic_available:
            try:
                client = self.get_anthropic_client()
                # Einfacher Test-Request
                response = client.messages.create(
                    model="claude-3-haiku-20240307",
                    max_tokens=10,
                    messages=[{"role": "user", "content": "Test"}]
                )
                status['anthropic'] = True
            except Exception as e:
                status['anthropic_error'] = str(e)

        return status

    def classify_document(self, text: str, possible_categories: List[str]) -> Tuple[str, float]:
        """
        Klassifiziert ein Dokument in eine Kategorie.

        Args:
            text: OCR-Text des Dokuments
            possible_categories: Liste möglicher Kategorien

        Returns:
            Tuple aus (Kategorie, Konfidenz)
        """
        prompt = f"""Analysiere den folgenden Dokumenttext und klassifiziere ihn in eine der folgenden Kategorien:
{', '.join(possible_categories)}

Dokumenttext:
{text[:3000]}

Antworte im JSON-Format:
{{"category": "Kategoriename", "confidence": 0.95, "reasoning": "Kurze Begründung"}}
"""

        try:
            result = self._call_ai(prompt)
            data = json.loads(result)
            return data.get('category', 'Sonstiges'), data.get('confidence', 0.5)
        except Exception as e:
            st.warning(f"KI-Klassifizierung fehlgeschlagen: {e}")
            return 'Sonstiges', 0.0

    def extract_structured_data(self, text: str) -> Dict:
        """
        Extrahiert strukturierte Daten aus einem Dokument.

        Args:
            text: OCR-Text

        Returns:
            Dictionary mit extrahierten Daten
        """
        prompt = f"""Extrahiere strukturierte Informationen aus diesem deutschen Dokument.
Analysiere den Text sorgfältig und identifiziere alle relevanten Informationen.

Dokumenttext:
{text[:5000]}

Antworte im JSON-Format mit diesen Feldern (nur vorhandene Informationen, leere Felder weglassen):
{{
    "sender": "Name/Firma des Absenders (vollständiger Name)",
    "sender_address": "Vollständige Adresse mit Straße, PLZ, Ort",
    "document_date": "YYYY-MM-DD",
    "subject": "Betreff/Titel des Schreibens",
    "category": "Rechnung|Vertrag|Versicherung|Mahnung|Kontoauszug|Lohnabrechnung|Steuerbescheid|Kündigung|Angebot|Sonstiges",
    "is_invoice": true/false,
    "summary": "Kurze Zusammenfassung des Dokumentinhalts in 1-2 Sätzen",
    "reference_number": "Aktenzeichen/Geschäftszeichen/Az.",
    "customer_number": "Kundennummer/Kd-Nr.",
    "insurance_number": "Versicherungsnummer/Policennummer",
    "processing_number": "Bearbeitungsnummer/Vorgangsnummer",
    "contract_number": "Vertragsnummer",
    "invoice_number": "Rechnungsnummer/RE-Nr./Rg-Nr.",
    "invoice_amount": 123.45,
    "invoice_currency": "EUR",
    "invoice_due_date": "YYYY-MM-DD (Zahlungsfrist/Fällig bis)",
    "iban": "DEXX...",
    "bic": "XXXXX",
    "bank_name": "Name der Bank",
    "deadline": "YYYY-MM-DD (andere wichtige Frist)",
    "deadline_type": "payment|response|cancellation|contract_end",
    "key_points": ["Wichtiger Punkt 1", "Wichtiger Punkt 2"]
}}

Wichtig:
- Setze "is_invoice": true wenn es sich um eine Rechnung, Mahnung oder Zahlungsaufforderung handelt
- Suche nach allen Nummern wie "Rechnungsnr:", "RE-Nr:", "Kd-Nr:", "Vers.-Nr:", etc.
- Extrahiere den vollständigen Absendernamen inkl. Rechtsform (GmbH, AG, etc.)
- Bei Rechnungen: Betrag, IBAN, Fälligkeit, Rechnungsnummer extrahieren
- Erstelle eine prägnante Zusammenfassung
"""

        try:
            result = self._call_ai(prompt)
            # JSON aus der Antwort extrahieren (falls zusätzlicher Text vorhanden)
            json_start = result.find('{')
            json_end = result.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                result = result[json_start:json_end]
            return json.loads(result)
        except Exception as e:
            st.warning(f"KI-Extraktion fehlgeschlagen: {e}")
            return {}

    def generate_response_draft(self, document_text: str, context: str = "") -> str:
        """
        Generiert einen Antwortentwurf für ein Dokument.

        Args:
            document_text: Text des Dokuments
            context: Zusätzlicher Kontext

        Returns:
            Antwortentwurf
        """
        prompt = f"""Erstelle einen höflichen, formellen Antwortentwurf auf folgendes Schreiben.
Die Antwort soll auf Deutsch sein und alle notwendigen Formalitäten enthalten.

Originalschreiben:
{document_text[:3000]}

{f'Zusätzlicher Kontext: {context}' if context else ''}

Erstelle eine professionelle Antwort:"""

        try:
            return self._call_ai(prompt)
        except Exception as e:
            st.error(f"Antwortgenerierung fehlgeschlagen: {e}")
            return ""

    def generate_cover_letter(self, requirement_text: str, documents: List[str]) -> str:
        """
        Generiert ein Begleitschreiben für angeforderte Dokumente.

        Args:
            requirement_text: Text der Dokumentenanforderung
            documents: Liste der Dokumentnamen/Beschreibungen

        Returns:
            Begleitschreiben
        """
        doc_list = "\n".join(f"- {doc}" for doc in documents)

        prompt = f"""Erstelle ein höfliches, formelles Begleitschreiben für die Übersendung von Dokumenten.

Ursprüngliche Anforderung:
{requirement_text[:2000]}

Beigefügte Dokumente:
{doc_list}

Das Begleitschreiben soll:
- Auf die Anforderung Bezug nehmen
- Die beigefügten Dokumente auflisten
- Höflich und professionell formuliert sein
- Auf Deutsch sein

Begleitschreiben:"""

        try:
            return self._call_ai(prompt)
        except Exception as e:
            st.error(f"Begleitschreiben-Generierung fehlgeschlagen: {e}")
            return ""

    def analyze_document_requirement(self, requirement_text: str) -> List[Dict]:
        """
        Analysiert eine Dokumentenanforderung und extrahiert die benötigten Dokumente.

        Args:
            requirement_text: Text der Anforderung

        Returns:
            Liste von Dokumentanforderungen mit Suchbegriffen
        """
        prompt = f"""Analysiere diese Dokumentenanforderung und extrahiere alle angeforderten Dokumente.

Anforderungstext:
{requirement_text}

Antworte im JSON-Format als Liste:
[
    {{
        "document_type": "Lohnabrechnung",
        "period": "letzte 3 Monate",
        "search_terms": ["lohnabrechnung", "gehaltsabrechnung"],
        "category": "Lohnabrechnung"
    }},
    ...
]
"""

        try:
            result = self._call_ai(prompt)
            return json.loads(result)
        except Exception as e:
            st.warning(f"Anforderungsanalyse fehlgeschlagen: {e}")
            return []

    def needs_response(self, text: str) -> Tuple[bool, str]:
        """
        Prüft ob ein Dokument eine Antwort erfordert.

        Args:
            text: Dokumenttext

        Returns:
            Tuple aus (erfordert Antwort, Begründung)
        """
        # Schnelle regelbasierte Prüfung erst
        response_indicators = [
            'bitten wir', 'bitte antworten', 'bitte senden',
            'wir benötigen', 'teilen sie uns mit', 'rückmeldung',
            'bis zum', 'frist', 'wir erwarten'
        ]

        text_lower = text.lower()
        for indicator in response_indicators:
            if indicator in text_lower:
                return True, f"Enthält '{indicator}'"

        # Bei Unsicherheit KI befragen
        if self.any_ai_available:
            prompt = f"""Analysiere ob dieses Schreiben eine Antwort/Reaktion des Empfängers erfordert.

Text:
{text[:2000]}

Antworte im JSON-Format:
{{"requires_response": true/false, "reason": "Begründung", "deadline": "YYYY-MM-DD oder null"}}
"""
            try:
                result = self._call_ai(prompt)
                data = json.loads(result)
                return data.get('requires_response', False), data.get('reason', '')
            except (json.JSONDecodeError, Exception):
                pass

        return False, ""

    def _call_ai(self, prompt: str, prefer_claude: bool = True) -> str:
        """
        Ruft die verfügbare KI-API auf.

        Args:
            prompt: Der Prompt
            prefer_claude: Bevorzuge Claude wenn verfügbar

        Returns:
            Antwort der KI
        """
        if prefer_claude and self.anthropic_available:
            return self._call_anthropic(prompt)
        elif self.openai_available:
            return self._call_openai(prompt)
        elif self.anthropic_available:
            return self._call_anthropic(prompt)
        else:
            raise Exception("Keine KI-API konfiguriert")

    def _call_openai(self, prompt: str) -> str:
        """Ruft OpenAI GPT auf"""
        client = self.get_openai_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Du bist ein Assistent für Dokumentenanalyse. Antworte immer im angeforderten Format."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        return response.choices[0].message.content

    def _call_anthropic(self, prompt: str) -> str:
        """Ruft Anthropic Claude auf"""
        client = self.get_anthropic_client()
        response = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text


def get_ai_service() -> AIService:
    """Singleton für den KI-Service"""
    if 'ai_service' not in st.session_state:
        st.session_state.ai_service = AIService()
    return st.session_state.ai_service
