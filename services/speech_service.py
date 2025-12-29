"""
Sprach-zu-Text Service für Diktierfunktion
Unterstützt OpenAI Whisper API und lokale Whisper-Modelle
"""
import os
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
import io

from config.settings import get_settings, DATA_DIR


class SpeechService:
    """Service für Sprach-zu-Text Konvertierung"""

    def __init__(self):
        self.settings = get_settings()
        self.transcriptions_dir = DATA_DIR / "transcriptions"
        self.transcriptions_dir.mkdir(parents=True, exist_ok=True)

    def transcribe_audio(self, audio_data: bytes, language: str = "de") -> Dict[str, Any]:
        """
        Transkribiert Audio-Daten zu Text

        Args:
            audio_data: Audio als Bytes (WAV, MP3, etc.)
            language: Sprache für die Transkription (default: Deutsch)

        Returns:
            Dict mit 'text', 'duration', 'language' und ggf. 'segments'
        """
        if not self.settings.openai_api_key:
            return {"error": "OpenAI API-Schlüssel nicht konfiguriert"}

        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.settings.openai_api_key)

            # Audio-Daten in temporäre Datei schreiben
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
                tmp_file.write(audio_data)
                tmp_path = tmp_file.name

            try:
                # Whisper API aufrufen
                with open(tmp_path, "rb") as audio_file:
                    response = client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio_file,
                        language=language,
                        response_format="verbose_json"
                    )

                return {
                    "text": response.text,
                    "duration": getattr(response, 'duration', None),
                    "language": language,
                    "segments": getattr(response, 'segments', [])
                }
            finally:
                # Temporäre Datei löschen
                os.unlink(tmp_path)

        except ImportError:
            return {"error": "OpenAI-Paket nicht installiert"}
        except Exception as e:
            return {"error": f"Transkriptionsfehler: {str(e)}"}

    def transcribe_file(self, file_path: str, language: str = "de") -> Dict[str, Any]:
        """
        Transkribiert eine Audio-Datei

        Args:
            file_path: Pfad zur Audio-Datei
            language: Sprache

        Returns:
            Transkriptionsergebnis
        """
        with open(file_path, "rb") as f:
            audio_data = f.read()
        return self.transcribe_audio(audio_data, language)

    def save_transcription(
        self,
        text: str,
        title: Optional[str] = None,
        category: str = "Notiz",
        audio_data: Optional[bytes] = None
    ) -> Dict[str, Any]:
        """
        Speichert eine Transkription als Dokument

        Args:
            text: Transkribierter Text
            title: Optionaler Titel
            category: Kategorie der Transkription
            audio_data: Original-Audio (optional)

        Returns:
            Dict mit Speicherinformationen
        """
        from database.models import get_session, Document, User
        from services.document_service import DocumentService

        timestamp = datetime.now()

        if not title:
            title = f"Diktat vom {timestamp.strftime('%d.%m.%Y %H:%M')}"

        # Text als .txt Datei speichern
        filename = f"diktat_{timestamp.strftime('%Y%m%d_%H%M%S')}.txt"
        file_path = self.transcriptions_dir / filename

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"# {title}\n")
            f.write(f"Erstellt: {timestamp.strftime('%d.%m.%Y %H:%M:%S')}\n")
            f.write(f"Kategorie: {category}\n")
            f.write("-" * 50 + "\n\n")
            f.write(text)

        # Audio speichern wenn vorhanden
        audio_path = None
        if audio_data:
            audio_filename = f"diktat_{timestamp.strftime('%Y%m%d_%H%M%S')}.wav"
            audio_path = self.transcriptions_dir / audio_filename
            with open(audio_path, "wb") as f:
                f.write(audio_data)

        # Als Dokument in DB speichern
        session = get_session()
        try:
            # Hole System-Benutzer oder ersten Benutzer
            user = session.query(User).first()
            if not user:
                return {
                    "success": False,
                    "error": "Kein Benutzer gefunden"
                }

            doc = Document(
                title=title,
                filename=filename,
                file_path=str(file_path),
                mime_type="text/plain",
                file_size=len(text.encode('utf-8')),
                category=category,
                ocr_text=text,
                user_id=user.id
            )
            session.add(doc)
            session.commit()

            return {
                "success": True,
                "document_id": doc.id,
                "file_path": str(file_path),
                "audio_path": str(audio_path) if audio_path else None,
                "title": title
            }
        except Exception as e:
            session.rollback()
            return {
                "success": False,
                "error": str(e)
            }
        finally:
            session.close()

    def get_saved_transcriptions(self, limit: int = 50) -> List[Dict]:
        """
        Holt die letzten gespeicherten Transkriptionen

        Args:
            limit: Maximale Anzahl

        Returns:
            Liste von Transkriptionen
        """
        from database.models import get_session, Document

        session = get_session()
        try:
            docs = session.query(Document).filter(
                Document.file_path.like("%/transcriptions/%")
            ).order_by(Document.created_at.desc()).limit(limit).all()

            return [{
                "id": doc.id,
                "title": doc.title,
                "date": doc.created_at,
                "category": doc.category,
                "text": doc.ocr_text[:200] + "..." if len(doc.ocr_text or "") > 200 else doc.ocr_text
            } for doc in docs]
        finally:
            session.close()


class LocalWhisperService:
    """
    Lokaler Whisper Service für offline Transkription
    Benötigt: pip install openai-whisper
    """

    def __init__(self, model_size: str = "base"):
        """
        Initialisiert lokales Whisper-Modell

        Args:
            model_size: Modellgröße (tiny, base, small, medium, large)
        """
        self.model_size = model_size
        self.model = None

    def load_model(self):
        """Lädt das Whisper-Modell (beim ersten Aufruf)"""
        if self.model is None:
            try:
                import whisper
                self.model = whisper.load_model(self.model_size)
            except ImportError:
                raise ImportError(
                    "Lokales Whisper nicht installiert. "
                    "Installieren Sie mit: pip install openai-whisper"
                )
        return self.model

    def transcribe(self, audio_path: str, language: str = "de") -> Dict[str, Any]:
        """
        Transkribiert Audio lokal mit Whisper

        Args:
            audio_path: Pfad zur Audio-Datei
            language: Sprache

        Returns:
            Transkriptionsergebnis
        """
        try:
            model = self.load_model()
            result = model.transcribe(audio_path, language=language)

            return {
                "text": result["text"],
                "language": result.get("language", language),
                "segments": result.get("segments", [])
            }
        except Exception as e:
            return {"error": f"Lokale Transkription fehlgeschlagen: {str(e)}"}


def get_speech_service() -> SpeechService:
    """Factory-Funktion für den SpeechService"""
    return SpeechService()
