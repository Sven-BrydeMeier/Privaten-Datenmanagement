"""
Document Chat Service
KI-basierte Konversation über Dokumentinhalte
"""
from datetime import datetime
from typing import List, Dict, Any, Optional
import json

from database.models import get_session, Document
from config.settings import get_settings


class DocumentChatService:
    """Service für KI-gestützte Dokumenten-Konversation"""

    # System-Prompt für den Chat-Assistenten
    SYSTEM_PROMPT = """Du bist ein hilfreicher Assistent für Dokumentenverwaltung.
Du analysierst Dokumente und beantwortest Fragen dazu präzise und auf Deutsch.

Deine Aufgaben:
- Fragen zum Dokumentinhalt beantworten
- Zusammenfassungen erstellen
- Wichtige Informationen extrahieren (Fristen, Beträge, Kontaktdaten)
- Bei Verträgen auf Kündigungsfristen hinweisen
- Bei Rechnungen den Zahlungsstatus erklären
- Handlungsempfehlungen geben

Sei präzise und hilfreich. Wenn du etwas nicht im Dokument findest, sage das ehrlich."""

    def __init__(self):
        self.settings = get_settings()

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
            if self.settings.anthropic_api_key:
                return self._chat_with_anthropic(doc_context, message, history)
            elif self.settings.openai_api_key:
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

            client = Anthropic(api_key=self.settings.anthropic_api_key)

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

            client = OpenAI(api_key=self.settings.openai_api_key)

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
            if self.settings.anthropic_api_key:
                return self._chat_comparison_anthropic(combined_context, question)
            elif self.settings.openai_api_key:
                return self._chat_comparison_openai(combined_context, question)
            else:
                return {"error": "Keine KI-API konfiguriert"}

        finally:
            session.close()

    def _chat_comparison_anthropic(self, context: str, question: str) -> Dict[str, Any]:
        """Dokumentvergleich mit Anthropic"""
        try:
            from anthropic import Anthropic

            client = Anthropic(api_key=self.settings.anthropic_api_key)

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

            client = OpenAI(api_key=self.settings.openai_api_key)

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


def get_document_chat_service() -> DocumentChatService:
    """Factory-Funktion für den DocumentChatService"""
    return DocumentChatService()
