"""
Document Chat Service
KI-basierte Konversation über Dokumentinhalte mit Aktions-Vorschlägen
"""
from datetime import datetime
from typing import List, Dict, Any, Optional
import json
import re

from database.models import get_session, Document
from config.settings import get_settings, get_api_key


class DocumentChatService:
    """Service für KI-gestützte Dokumenten-Konversation mit Aktions-Vorschlägen"""

    # Aktionstypen die erkannt werden können
    ACTION_TYPES = {
        "cancellation": {
            "keywords": ["kündigen", "kündigung", "abo beenden", "vertrag beenden", "abbestellen"],
            "template": "Kündigung Allgemein",
            "label": "Kündigung vorbereiten",
            "icon": "✉️"
        },
        "objection": {
            "keywords": ["widerspruch", "widersprechen", "einspruch", "anfechten"],
            "template": "Widerspruch",
            "label": "Widerspruch verfassen",
            "icon": "⚖️"
        },
        "complaint": {
            "keywords": ["reklamation", "reklamieren", "beschwerde", "mangel", "defekt"],
            "template": "Reklamation",
            "label": "Reklamation schreiben",
            "icon": "📝"
        },
        "sepa_revoke": {
            "keywords": ["lastschrift", "rückbuchung", "sepa widerruf", "abbuchung"],
            "template": "SEPA-Lastschrift Widerruf",
            "label": "SEPA-Widerruf erstellen",
            "icon": "🏦"
        }
    }

    # System-Prompt für den Chat-Assistenten mit Aktions-Empfehlungen
    SYSTEM_PROMPT = """Du bist ein hilfreicher Assistent für Dokumentenverwaltung.
Du analysierst Dokumente und beantwortest Fragen dazu präzise und auf Deutsch.

Deine Aufgaben:
- Fragen zum Dokumentinhalt beantworten
- Zusammenfassungen erstellen
- Wichtige Informationen extrahieren (Fristen, Beträge, Kontaktdaten)
- Bei Verträgen auf Kündigungsfristen hinweisen
- Bei Rechnungen den Zahlungsstatus erklären
- Handlungsempfehlungen geben

WICHTIG - Aktions-Vorschläge:
Wenn es sinnvoll ist, schlage dem Benutzer konkrete Aktionen vor und frage nach, ob er diese durchführen möchte:
- Bei Abos/Verträgen: "Möchten Sie diesen Vertrag kündigen? Ich kann ein Kündigungsschreiben vorbereiten."
- Bei Bescheiden: "Möchten Sie Widerspruch einlegen? Ich kann das Schreiben erstellen."
- Bei fehlerhaften Produkten: "Soll ich eine Reklamation vorbereiten?"
- Bei unberechtigten Abbuchungen: "Möchten Sie die Lastschrift widerrufen?"

Wenn du eine Aktion vorschlägst, markiere dies am Ende deiner Antwort mit:
[AKTION:typ] wobei typ einer der folgenden ist: cancellation, objection, complaint, sepa_revoke

Sei präzise und hilfreich. Wenn du etwas nicht im Dokument findest, sage das ehrlich."""

    def __init__(self):
        self.settings = get_settings()
        # API-Keys direkt aus Secrets/Umgebungsvariablen laden
        self.anthropic_api_key = get_api_key('anthropic_api_key')
        self.openai_api_key = get_api_key('openai_api_key')

    def chat(
        self,
        document_id: int,
        user_id: int,
        message: str,
        conversation_history: List[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Führt eine Chat-Konversation über ein Dokument

        Args:
            document_id: ID des Dokuments
            user_id: Benutzer-ID
            message: Benutzer-Nachricht
            conversation_history: Bisherige Konversation

        Returns:
            Dict mit Antwort und aktualisierter Konversation
        """
        session = get_session()
        try:
            # Dokument laden
            doc = session.query(Document).filter_by(
                id=document_id,
                user_id=user_id
            ).first()

            if not doc:
                return {"error": "Dokument nicht gefunden"}

            # Dokumentkontext erstellen
            doc_context = self._build_document_context(doc)

            # Conversation aufbauen
            history = conversation_history or []

            # Mit verfügbarer KI-API antworten
            if self.anthropic_api_key:
                return self._chat_with_anthropic(doc_context, message, history)
            elif self.openai_api_key:
                return self._chat_with_openai(doc_context, message, history)
            else:
                return {"error": "Keine KI-API konfiguriert. Bitte OpenAI oder Anthropic API-Schlüssel in den Einstellungen hinterlegen."}

        finally:
            session.close()

    def _build_document_context(self, doc: Document) -> str:
        """Erstellt Kontext aus Dokumentdaten"""
        parts = []

        parts.append(f"=== DOKUMENT ===")
        parts.append(f"Titel: {doc.title or doc.filename}")

        if doc.sender:
            parts.append(f"Absender: {doc.sender}")
        if doc.document_date:
            parts.append(f"Datum: {doc.document_date.strftime('%d.%m.%Y')}")
        if doc.category:
            parts.append(f"Kategorie: {doc.category}")

        # Rechnungsinformationen
        if doc.invoice_amount:
            parts.append(f"\n--- Rechnungsdetails ---")
            parts.append(f"Betrag: {doc.invoice_amount:.2f} {doc.invoice_currency or 'EUR'}")
            if doc.invoice_number:
                parts.append(f"Rechnungsnummer: {doc.invoice_number}")
            if doc.invoice_due_date:
                parts.append(f"Fällig am: {doc.invoice_due_date.strftime('%d.%m.%Y')}")
            if doc.invoice_status:
                parts.append(f"Status: {doc.invoice_status.value}")
            if doc.iban:
                parts.append(f"IBAN: {doc.iban}")

        # Vertragsinformationen
        if doc.contract_number or doc.contract_start or doc.contract_end:
            parts.append(f"\n--- Vertragsdetails ---")
            if doc.contract_number:
                parts.append(f"Vertragsnummer: {doc.contract_number}")
            if doc.contract_start:
                parts.append(f"Vertragsbeginn: {doc.contract_start.strftime('%d.%m.%Y')}")
            if doc.contract_end:
                parts.append(f"Vertragsende: {doc.contract_end.strftime('%d.%m.%Y')}")
            if doc.contract_notice_period:
                parts.append(f"Kündigungsfrist: {doc.contract_notice_period} Tage")

        # Referenznummern
        if doc.reference_number or doc.customer_number:
            parts.append(f"\n--- Referenzen ---")
            if doc.reference_number:
                parts.append(f"Aktenzeichen: {doc.reference_number}")
            if doc.customer_number:
                parts.append(f"Kundennummer: {doc.customer_number}")

        # KI-Zusammenfassung
        if doc.ai_summary:
            parts.append(f"\n--- KI-Zusammenfassung ---")
            parts.append(doc.ai_summary)

        # OCR-Text (Volltext)
        if doc.ocr_text:
            parts.append(f"\n--- Dokumenttext ---")
            # Text kürzen wenn zu lang
            text = doc.ocr_text
            if len(text) > 8000:
                text = text[:8000] + "\n... (Text gekürzt)"
            parts.append(text)

        return "\n".join(parts)

    def _chat_with_anthropic(
        self,
        doc_context: str,
        message: str,
        history: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """Chat mit Anthropic Claude"""
        try:
            from anthropic import Anthropic

            client = Anthropic(api_key=self.anthropic_api_key)

            # Messages aufbauen
            messages = []

            # Konversationsgeschichte
            for entry in history[-10:]:  # Letzte 10 Nachrichten
                messages.append({
                    "role": entry["role"],
                    "content": entry["content"]
                })

            # Neue Nachricht
            messages.append({
                "role": "user",
                "content": f"""Hier ist das Dokument, über das wir sprechen:

{doc_context}

---

Meine Frage: {message}"""
            })

            response = client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=2000,
                system=self.SYSTEM_PROMPT,
                messages=messages
            )

            assistant_message = response.content[0].text

            # Konversation aktualisieren
            updated_history = history + [
                {"role": "user", "content": message},
                {"role": "assistant", "content": assistant_message}
            ]

            return {
                "success": True,
                "response": assistant_message,
                "conversation": updated_history,
                "model": "claude-3.5-sonnet"
            }

        except ImportError:
            return {"error": "Anthropic-Paket nicht installiert"}
        except Exception as e:
            return {"error": f"Anthropic-Fehler: {str(e)}"}

    def _chat_with_openai(
        self,
        doc_context: str,
        message: str,
        history: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """Chat mit OpenAI GPT"""
        try:
            from openai import OpenAI

            client = OpenAI(api_key=self.openai_api_key)

            # Messages aufbauen
            messages = [{"role": "system", "content": self.SYSTEM_PROMPT}]

            # Dokumentkontext als erste Nachricht
            messages.append({
                "role": "user",
                "content": f"Hier ist das Dokument, über das ich Fragen habe:\n\n{doc_context}"
            })
            messages.append({
                "role": "assistant",
                "content": "Ich habe das Dokument analysiert. Sie können mir jetzt Fragen dazu stellen."
            })

            # Konversationsgeschichte
            for entry in history[-10:]:
                messages.append({
                    "role": entry["role"],
                    "content": entry["content"]
                })

            # Neue Nachricht
            messages.append({"role": "user", "content": message})

            response = client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                max_tokens=2000,
                temperature=0.7
            )

            assistant_message = response.choices[0].message.content

            # Konversation aktualisieren
            updated_history = history + [
                {"role": "user", "content": message},
                {"role": "assistant", "content": assistant_message}
            ]

            return {
                "success": True,
                "response": assistant_message,
                "conversation": updated_history,
                "model": "gpt-4o"
            }

        except ImportError:
            return {"error": "OpenAI-Paket nicht installiert"}
        except Exception as e:
            return {"error": f"OpenAI-Fehler: {str(e)}"}

    def get_quick_summary(self, document_id: int, user_id: int) -> Dict[str, Any]:
        """Erstellt eine schnelle Zusammenfassung"""
        return self.chat(
            document_id=document_id,
            user_id=user_id,
            message="Fasse dieses Dokument kurz und prägnant zusammen. Was sind die wichtigsten Punkte?",
            conversation_history=[]
        )

    def extract_action_items(self, document_id: int, user_id: int) -> Dict[str, Any]:
        """Extrahiert Handlungsempfehlungen aus dem Dokument"""
        return self.chat(
            document_id=document_id,
            user_id=user_id,
            message="Welche Aktionen muss ich aufgrund dieses Dokuments durchführen? Liste alle Fristen und erforderlichen Handlungen auf.",
            conversation_history=[]
        )

    def compare_documents(
        self,
        doc_ids: List[int],
        user_id: int,
        comparison_question: str = None
    ) -> Dict[str, Any]:
        """Vergleicht mehrere Dokumente"""
        session = get_session()
        try:
            docs = session.query(Document).filter(
                Document.id.in_(doc_ids),
                Document.user_id == user_id
            ).all()

            if len(docs) < 2:
                return {"error": "Mindestens 2 Dokumente für Vergleich erforderlich"}

            # Kontext für alle Dokumente erstellen
            contexts = []
            for i, doc in enumerate(docs, 1):
                context = self._build_document_context(doc)
                contexts.append(f"=== DOKUMENT {i} ===\n{context}")

            combined_context = "\n\n".join(contexts)

            question = comparison_question or "Vergleiche diese Dokumente. Was sind die wichtigsten Unterschiede und Gemeinsamkeiten?"

            # Chat mit kombiniertem Kontext
            if self.anthropic_api_key:
                return self._chat_comparison_anthropic(combined_context, question)
            elif self.openai_api_key:
                return self._chat_comparison_openai(combined_context, question)
            else:
                return {"error": "Keine KI-API konfiguriert"}

        finally:
            session.close()

    def _chat_comparison_anthropic(self, context: str, question: str) -> Dict[str, Any]:
        """Dokumentvergleich mit Anthropic"""
        try:
            from anthropic import Anthropic

            client = Anthropic(api_key=self.anthropic_api_key)

            response = client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=3000,
                system=self.SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": f"{context}\n\n---\n\n{question}"
                }]
            )

            return {
                "success": True,
                "response": response.content[0].text,
                "model": "claude-3.5-sonnet"
            }

        except Exception as e:
            return {"error": str(e)}

    def _chat_comparison_openai(self, context: str, question: str) -> Dict[str, Any]:
        """Dokumentvergleich mit OpenAI"""
        try:
            from openai import OpenAI

            client = OpenAI(api_key=self.openai_api_key)

            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": f"{context}\n\n---\n\n{question}"}
                ],
                max_tokens=3000
            )

            return {
                "success": True,
                "response": response.choices[0].message.content,
                "model": "gpt-4o"
            }

        except Exception as e:
            return {"error": str(e)}

    def chat_multi(
        self,
        document_ids: List[int],
        user_id: int,
        message: str,
        conversation_history: List[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Chat über mehrere Dokumente gleichzeitig

        Args:
            document_ids: Liste der Dokument-IDs
            user_id: Benutzer-ID
            message: Benutzer-Nachricht
            conversation_history: Bisherige Konversation

        Returns:
            Dict mit Antwort und aktualisierter Konversation
        """
        session = get_session()
        try:
            # Dokumente laden (max 20 für Performance)
            docs = session.query(Document).filter(
                Document.id.in_(document_ids[:20]),
                Document.user_id == user_id
            ).all()

            if not docs:
                return {"error": "Keine Dokumente gefunden"}

            # Kontext für alle Dokumente erstellen
            doc_contexts = []
            for i, doc in enumerate(docs, 1):
                # Kompakterer Kontext für Multi-Dokument
                parts = [f"[Dokument {i}]"]
                parts.append(f"Titel: {doc.title or doc.filename}")
                if doc.sender:
                    parts.append(f"Absender: {doc.sender}")
                if doc.document_date:
                    parts.append(f"Datum: {doc.document_date.strftime('%d.%m.%Y')}")
                if doc.category:
                    parts.append(f"Kategorie: {doc.category}")
                if doc.invoice_amount:
                    parts.append(f"Betrag: {doc.invoice_amount:.2f} EUR")
                if doc.ai_summary:
                    parts.append(f"Zusammenfassung: {doc.ai_summary}")
                if doc.ocr_text:
                    # Kürzerer Text für Multi-Dokument
                    text = doc.ocr_text[:2000] if len(doc.ocr_text) > 2000 else doc.ocr_text
                    parts.append(f"Text: {text}")

                doc_contexts.append("\n".join(parts))

            combined_context = "\n\n---\n\n".join(doc_contexts)

            # Info über Anzahl
            total_count = len(document_ids)
            shown_count = len(docs)
            if total_count > shown_count:
                combined_context += f"\n\n(Hinweis: Es wurden {shown_count} von {total_count} Dokumenten analysiert)"

            # Conversation aufbauen
            history = conversation_history or []

            # System-Prompt für Multi-Dokument
            multi_prompt = """Du bist ein hilfreicher Assistent für Dokumentenverwaltung.
Du analysierst MEHRERE Dokumente gleichzeitig und beantwortest Fragen dazu.

Bei Fragen zu mehreren Dokumenten:
- Gib Übersichten und Zusammenfassungen
- Identifiziere wichtige Dokumente
- Finde Muster und Zusammenhänge
- Liste offene Beträge oder Fristen
- Verweise auf spezifische Dokumente mit [Dokument X]

Sei präzise und strukturiert."""

            # Mit verfügbarer KI-API antworten
            if self.anthropic_api_key:
                return self._chat_multi_anthropic(combined_context, message, history, multi_prompt)
            elif self.openai_api_key:
                return self._chat_multi_openai(combined_context, message, history, multi_prompt)
            else:
                return {"error": "Keine KI-API konfiguriert"}

        finally:
            session.close()

    def _chat_multi_anthropic(
        self,
        doc_context: str,
        message: str,
        history: List[Dict[str, str]],
        system_prompt: str
    ) -> Dict[str, Any]:
        """Multi-Dokument Chat mit Anthropic"""
        try:
            from anthropic import Anthropic

            client = Anthropic(api_key=self.anthropic_api_key)

            messages = []
            for entry in history[-6:]:  # Weniger Historie bei Multi-Dokument
                messages.append({
                    "role": entry["role"],
                    "content": entry["content"]
                })

            messages.append({
                "role": "user",
                "content": f"""Hier sind die Dokumente:

{doc_context}

---

Frage: {message}"""
            })

            response = client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=3000,
                system=system_prompt,
                messages=messages
            )

            assistant_message = response.content[0].text

            updated_history = history + [
                {"role": "user", "content": message},
                {"role": "assistant", "content": assistant_message}
            ]

            return {
                "success": True,
                "response": assistant_message,
                "conversation": updated_history,
                "model": "claude-3.5-sonnet"
            }

        except Exception as e:
            return {"error": str(e)}

    def _chat_multi_openai(
        self,
        doc_context: str,
        message: str,
        history: List[Dict[str, str]],
        system_prompt: str
    ) -> Dict[str, Any]:
        """Multi-Dokument Chat mit OpenAI"""
        try:
            from openai import OpenAI

            client = OpenAI(api_key=self.openai_api_key)

            messages = [{"role": "system", "content": system_prompt}]

            for entry in history[-6:]:
                messages.append({
                    "role": entry["role"],
                    "content": entry["content"]
                })

            messages.append({
                "role": "user",
                "content": f"""Hier sind die Dokumente:

{doc_context}

---

Frage: {message}"""
            })

            response = client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                max_tokens=3000
            )

            assistant_message = response.choices[0].message.content

            updated_history = history + [
                {"role": "user", "content": message},
                {"role": "assistant", "content": assistant_message}
            ]

            return {
                "success": True,
                "response": assistant_message,
                "conversation": updated_history,
                "model": "gpt-4o"
            }

        except Exception as e:
            return {"error": str(e)}


def get_document_chat_service() -> DocumentChatService:
    """Factory-Funktion für den DocumentChatService"""
    return DocumentChatService()


class DocumentActionService:
    """Service für Aktionen basierend auf Dokumenten (Kündigungen, Widersprüche, etc.)"""

    def __init__(self, user_id: int):
        self.user_id = user_id

    def parse_action_from_response(self, response: str) -> Optional[Dict[str, Any]]:
        """
        Erkennt Aktions-Vorschläge in der KI-Antwort

        Args:
            response: Die KI-Antwort

        Returns:
            Dict mit Aktionstyp und Metadaten oder None
        """
        # Suche nach [AKTION:typ] Markierung
        pattern = r'\[AKTION:(\w+)\]'
        match = re.search(pattern, response)

        if match:
            action_type = match.group(1)
            if action_type in DocumentChatService.ACTION_TYPES:
                action_info = DocumentChatService.ACTION_TYPES[action_type]
                return {
                    "type": action_type,
                    "template_name": action_info["template"],
                    "label": action_info["label"],
                    "icon": action_info["icon"]
                }

        # Fallback: Keyword-basierte Erkennung
        response_lower = response.lower()
        for action_type, action_info in DocumentChatService.ACTION_TYPES.items():
            for keyword in action_info["keywords"]:
                if keyword in response_lower and ("möchten" in response_lower or "soll ich" in response_lower):
                    return {
                        "type": action_type,
                        "template_name": action_info["template"],
                        "label": action_info["label"],
                        "icon": action_info["icon"]
                    }

        return None

    def extract_document_data_for_template(self, document_id: int) -> Dict[str, Any]:
        """
        Extrahiert Daten aus einem Dokument für Template-Vorausfüllung

        Args:
            document_id: ID des Dokuments

        Returns:
            Dict mit extrahierten Daten für Template-Platzhalter
        """
        session = get_session()
        try:
            doc = session.query(Document).filter_by(
                id=document_id,
                user_id=self.user_id
            ).first()

            if not doc:
                return {}

            # Daten aus Dokument extrahieren
            data = {
                "datum": datetime.now().strftime("%d.%m.%Y"),
                "empfaenger_name": doc.sender or "",
                "vertragsnummer": doc.contract_number or "",
                "kundennummer": doc.customer_number or "",
                "aktenzeichen": doc.reference_number or "",
                "betrag": str(doc.invoice_amount) if doc.invoice_amount else "",
                "iban": doc.iban or "",
            }

            # Vertragsart aus Kategorie ableiten
            category_to_vertragsart = {
                "Versicherung": "Versicherungsvertrag",
                "Telefon & Internet": "Telekommunikationsvertrag",
                "Abonnement": "Abonnement",
                "Mitgliedschaft": "Mitgliedschaft",
                "Strom & Gas": "Energieliefervertrag",
            }
            data["vertragsart"] = category_to_vertragsart.get(doc.category, "Vertrag")

            # Bescheid-Datum aus Dokumentdatum
            if doc.document_date:
                data["bescheid_datum"] = doc.document_date.strftime("%d.%m.%Y")
                data["abbuchungsdatum"] = doc.document_date.strftime("%d.%m.%Y")
                data["kaufdatum"] = doc.document_date.strftime("%d.%m.%Y")

            return data

        finally:
            session.close()

    def generate_letter(
        self,
        document_id: int,
        action_type: str,
        user_data: Dict[str, str] = None
    ) -> Dict[str, Any]:
        """
        Generiert ein Schreiben basierend auf Dokument und Aktionstyp

        Args:
            document_id: ID des Quelldokuments
            action_type: Art der Aktion (cancellation, objection, etc.)
            user_data: Benutzerdaten (Name, Adresse, etc.)

        Returns:
            Dict mit generiertem Schreiben und Metadaten
        """
        from services.template_service import TemplateService

        if action_type not in DocumentChatService.ACTION_TYPES:
            return {"error": f"Unbekannter Aktionstyp: {action_type}"}

        action_info = DocumentChatService.ACTION_TYPES[action_type]
        template_name = action_info["template"]

        # Template-Service initialisieren
        template_service = TemplateService(self.user_id)
        template_service.initialize_default_templates()

        # Template finden
        templates = template_service.get_all_templates(category="letter")
        template = None
        for t in templates:
            if t.name == template_name:
                template = t
                break

        if not template:
            return {"error": f"Vorlage '{template_name}' nicht gefunden"}

        # Dokumentdaten extrahieren
        doc_data = self.extract_document_data_for_template(document_id)

        # Mit Benutzerdaten zusammenführen
        values = {**doc_data}
        if user_data:
            values.update(user_data)

        # Template rendern
        rendered = template_service.render_template(template.id, values)

        # Fehlende Platzhalter identifizieren
        missing = []
        for placeholder in template.placeholders or []:
            key = placeholder["key"]
            if not values.get(key) and "{{" + key + "}}" in rendered:
                missing.append(placeholder)

        return {
            "success": True,
            "letter_content": rendered,
            "template_name": template_name,
            "template_id": template.id,
            "missing_fields": missing,
            "extracted_data": doc_data,
            "action_type": action_type,
            "action_label": action_info["label"]
        }

    def get_user_profile_data(self) -> Dict[str, str]:
        """
        Lädt gespeicherte Benutzerdaten für Briefvorlagen

        Returns:
            Dict mit Benutzerdaten (Name, Adresse, etc.)
        """
        # Aus den Einstellungen oder User-Profil laden
        settings = get_settings()

        return {
            "absender_name": getattr(settings, 'user_display_name', '') or '',
            "absender_adresse": getattr(settings, 'user_address', '') or '',
            "absender_plz": getattr(settings, 'user_postal_code', '') or '',
            "absender_ort": getattr(settings, 'user_city', '') or '',
        }


def get_document_action_service(user_id: int) -> DocumentActionService:
    """Factory-Funktion für den DocumentActionService"""
    return DocumentActionService(user_id)
