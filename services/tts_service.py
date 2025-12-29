"""
Text-to-Speech Service für Dokumente vorlesen
Unterstützt OpenAI TTS API und Browser-natives TTS
"""
import os
import tempfile
import base64
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path

from config.settings import get_settings, DATA_DIR


class TTSService:
    """Service für Text-to-Speech"""

    # OpenAI TTS Stimmen
    VOICES = {
        "alloy": "Alloy (neutral)",
        "echo": "Echo (männlich)",
        "fable": "Fable (britisch)",
        "onyx": "Onyx (tief, männlich)",
        "nova": "Nova (weiblich)",
        "shimmer": "Shimmer (weiblich, warm)"
    }

    # TTS Modelle
    MODELS = {
        "tts-1": "Standard (schneller)",
        "tts-1-hd": "HD (höhere Qualität)"
    }

    def __init__(self):
        self.settings = get_settings()
        self.audio_cache_dir = DATA_DIR / "tts_cache"
        self.audio_cache_dir.mkdir(parents=True, exist_ok=True)

    def text_to_speech(
        self,
        text: str,
        voice: str = "nova",
        model: str = "tts-1",
        speed: float = 1.0
    ) -> Dict[str, Any]:
        """
        Konvertiert Text zu Sprache mit OpenAI TTS

        Args:
            text: Der vorzulesende Text
            voice: Stimme (alloy, echo, fable, onyx, nova, shimmer)
            model: Modell (tts-1 oder tts-1-hd)
            speed: Geschwindigkeit (0.25 bis 4.0)

        Returns:
            Dict mit Audio-Daten oder Fehler
        """
        if not self.settings.openai_api_key:
            return {"error": "OpenAI API-Schlüssel nicht konfiguriert"}

        if not text or not text.strip():
            return {"error": "Kein Text zum Vorlesen"}

        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.settings.openai_api_key)

            # Text kürzen wenn zu lang (max ca. 4096 Zeichen für TTS)
            if len(text) > 4000:
                text = text[:4000] + "... (Text gekürzt)"

            response = client.audio.speech.create(
                model=model,
                voice=voice,
                input=text,
                speed=speed
            )

            # Audio-Daten als Bytes
            audio_bytes = response.content

            return {
                "success": True,
                "audio_bytes": audio_bytes,
                "format": "mp3",
                "voice": voice,
                "text_length": len(text)
            }

        except ImportError:
            return {"error": "OpenAI-Paket nicht installiert"}
        except Exception as e:
            return {"error": f"TTS-Fehler: {str(e)}"}

    def read_document(
        self,
        document_id: int,
        voice: str = "nova",
        model: str = "tts-1",
        speed: float = 1.0
    ) -> Dict[str, Any]:
        """
        Liest ein Dokument vor

        Args:
            document_id: ID des Dokuments
            voice: Stimme
            model: TTS-Modell
            speed: Geschwindigkeit

        Returns:
            Dict mit Audio-Daten oder Fehler
        """
        from database.models import get_session, Document

        session = get_session()
        try:
            doc = session.query(Document).filter_by(id=document_id).first()

            if not doc:
                return {"error": "Dokument nicht gefunden"}

            # Text zum Vorlesen zusammenstellen
            text_parts = []

            if doc.title:
                text_parts.append(f"Titel: {doc.title}")

            if doc.sender:
                text_parts.append(f"Von: {doc.sender}")

            if doc.document_date:
                text_parts.append(f"Datum: {doc.document_date.strftime('%d. %B %Y')}")

            if doc.category:
                text_parts.append(f"Kategorie: {doc.category}")

            if doc.ai_summary:
                text_parts.append(f"Zusammenfassung: {doc.ai_summary}")

            # Haupttext (OCR oder extrahierter Text)
            main_text = doc.ocr_text or doc.subject or ""
            if main_text:
                text_parts.append(f"Inhalt: {main_text}")

            if not text_parts:
                return {"error": "Kein Text zum Vorlesen verfügbar"}

            full_text = "\n\n".join(text_parts)

            return self.text_to_speech(full_text, voice, model, speed)

        finally:
            session.close()

    def get_audio_base64(self, audio_bytes: bytes) -> str:
        """
        Konvertiert Audio-Bytes zu Base64 für HTML-Audio-Element

        Args:
            audio_bytes: Audio als Bytes

        Returns:
            Base64-kodierter String
        """
        return base64.b64encode(audio_bytes).decode('utf-8')

    def create_audio_html(self, audio_bytes: bytes, autoplay: bool = False) -> str:
        """
        Erstellt HTML-Audio-Element für Streamlit

        Args:
            audio_bytes: Audio als Bytes
            autoplay: Automatisch abspielen

        Returns:
            HTML-String
        """
        b64 = self.get_audio_base64(audio_bytes)
        autoplay_attr = "autoplay" if autoplay else ""

        return f"""
        <audio controls {autoplay_attr} style="width: 100%;">
            <source src="data:audio/mp3;base64,{b64}" type="audio/mp3">
            Ihr Browser unterstützt das Audio-Element nicht.
        </audio>
        """

    def get_browser_tts_script(
        self,
        text: str,
        lang: str = "de-DE",
        rate: float = 1.0,
        pitch: float = 1.0
    ) -> str:
        """
        Erstellt JavaScript für Browser-natives TTS (Fallback)

        Args:
            text: Vorzulesender Text
            lang: Sprache (z.B. de-DE, en-US)
            rate: Geschwindigkeit (0.1 - 10)
            pitch: Tonhöhe (0 - 2)

        Returns:
            JavaScript-Code
        """
        # Escape Text für JavaScript
        escaped_text = text.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")

        return f"""
        <script>
        function speakText() {{
            if ('speechSynthesis' in window) {{
                // Stoppe laufende Sprache
                window.speechSynthesis.cancel();

                const utterance = new SpeechSynthesisUtterance('{escaped_text}');
                utterance.lang = '{lang}';
                utterance.rate = {rate};
                utterance.pitch = {pitch};

                // Versuche deutsche Stimme zu finden
                const voices = window.speechSynthesis.getVoices();
                const germanVoice = voices.find(v => v.lang.startsWith('de'));
                if (germanVoice) {{
                    utterance.voice = germanVoice;
                }}

                window.speechSynthesis.speak(utterance);
            }} else {{
                alert('Ihr Browser unterstützt Text-to-Speech nicht.');
            }}
        }}

        function stopSpeaking() {{
            if ('speechSynthesis' in window) {{
                window.speechSynthesis.cancel();
            }}
        }}
        </script>
        <button onclick="speakText()" style="padding: 10px 20px; margin: 5px; cursor: pointer;">
            🔊 Vorlesen starten
        </button>
        <button onclick="stopSpeaking()" style="padding: 10px 20px; margin: 5px; cursor: pointer;">
            ⏹️ Stoppen
        </button>
        """

    def save_to_cache(self, audio_bytes: bytes, document_id: int) -> Path:
        """
        Speichert Audio im Cache

        Args:
            audio_bytes: Audio-Daten
            document_id: Dokument-ID

        Returns:
            Pfad zur Datei
        """
        cache_path = self.audio_cache_dir / f"doc_{document_id}.mp3"
        with open(cache_path, "wb") as f:
            f.write(audio_bytes)
        return cache_path

    def get_from_cache(self, document_id: int) -> Optional[bytes]:
        """
        Holt Audio aus Cache wenn vorhanden

        Args:
            document_id: Dokument-ID

        Returns:
            Audio-Bytes oder None
        """
        cache_path = self.audio_cache_dir / f"doc_{document_id}.mp3"
        if cache_path.exists():
            with open(cache_path, "rb") as f:
                return f.read()
        return None


def get_tts_service() -> TTSService:
    """Factory-Funktion für den TTSService"""
    return TTSService()
