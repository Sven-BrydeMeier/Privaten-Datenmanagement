"""
Konfigurationsmanagement für die Dokumentenmanagement-App
"""
import os
import json
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional
import streamlit as st

# Basis-Pfade
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
DOCUMENTS_DIR = DATA_DIR / "documents"
TEMP_DIR = DATA_DIR / "temp"
DATABASE_PATH = DATA_DIR / "docmanagement.db"
CONFIG_FILE = DATA_DIR / "config.json"
INDEX_DIR = DATA_DIR / "search_index"

# Sicherstellen, dass Verzeichnisse existieren
for dir_path in [DATA_DIR, DOCUMENTS_DIR, TEMP_DIR, INDEX_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)


@dataclass
class Settings:
    """Anwendungseinstellungen"""
    # API-Schlüssel
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    ocr_api_key: str = ""

    # E-Mail-Einstellungen
    smtp_server: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    imap_server: str = ""
    imap_port: int = 993
    imap_username: str = ""
    imap_password: str = ""

    # Kalender-Sync
    google_calendar_enabled: bool = False
    google_credentials_json: str = ""
    outlook_enabled: bool = False
    outlook_client_id: str = ""
    outlook_client_secret: str = ""

    # Nordigen/GoCardless Bank Account Data
    nordigen_secret_id: str = ""
    nordigen_secret_key: str = ""
    nordigen_redirect_url: str = "http://localhost:8501"  # Streamlit default

    # Benachrichtigungen
    notification_email: str = ""
    notify_days_before_deadline: list = field(default_factory=lambda: [7, 1])
    notify_birthday_days_before: int = 3

    # Verschlüsselung
    encryption_enabled: bool = True

    # UI-Einstellungen
    theme: str = "light"
    language: str = "de"
    items_per_page: int = 20

    # Papierkorb-Einstellungen
    trash_retention_hours: int = 48  # Aufbewahrungszeit in Stunden (Standard: 48h)
    auto_cleanup_trash: bool = True  # Automatische Bereinigung beim Start

    # Google Drive OAuth
    google_drive_client_id: str = ""
    google_drive_client_secret: str = ""
    google_drive_refresh_token: str = ""
    google_drive_access_token: str = ""
    google_drive_token_expiry: str = ""  # ISO-Format DateTime

    # Text-to-Speech Einstellungen
    tts_voice: str = "nova"  # Standard-Stimme (alloy, echo, fable, onyx, nova, shimmer)
    tts_model: str = "tts-1"  # TTS-Modell (tts-1 oder tts-1-hd)
    tts_speed: float = 1.0  # Geschwindigkeit (0.25 - 4.0)
    tts_use_browser: bool = False  # Browser-TTS als Fallback verwenden

    def save(self):
        """Einstellungen in Datei speichern"""
        config_data = asdict(self)
        # Sensitive Daten nicht im Klartext speichern
        # In Produktion sollte dies verschlüsselt werden
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config_data, f, indent=2)

    @classmethod
    def load(cls) -> 'Settings':
        """Einstellungen aus Datei laden"""
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'r') as f:
                    config_data = json.load(f)
                return cls(**config_data)
            except (json.JSONDecodeError, TypeError):
                return cls()
        return cls()


def get_settings() -> Settings:
    """Singleton-Pattern für Einstellungen"""
    if 'settings' not in st.session_state:
        st.session_state.settings = Settings.load()
    return st.session_state.settings


def get_api_key(key_name: str) -> Optional[str]:
    """
    Holt einen API-Key aus Streamlit Secrets oder lokalen Einstellungen.
    Priorität: 1. Streamlit Secrets, 2. Lokale Einstellungen

    Args:
        key_name: Name des Keys (z.B. 'openai_api_key', 'OPENAI_API_KEY')

    Returns:
        API-Key oder None
    """
    # Normalisiere den Key-Namen für verschiedene Formate
    key_variations = [
        key_name,
        key_name.upper(),
        key_name.lower(),
        key_name.replace('_api_key', '').upper() + '_API_KEY',
    ]

    # 1. Versuche Streamlit Secrets
    try:
        if hasattr(st, 'secrets'):
            for key in key_variations:
                if key in st.secrets:
                    return st.secrets[key]
            # Auch verschachtelte Secrets prüfen (z.B. st.secrets.openai.api_key)
            for section in ['openai', 'anthropic', 'google', 'ocr']:
                if section in st.secrets:
                    if 'api_key' in st.secrets[section]:
                        if key_name.lower().startswith(section):
                            return st.secrets[section]['api_key']
    except Exception:
        pass

    # 2. Versuche Umgebungsvariablen
    import os
    for key in key_variations:
        env_val = os.environ.get(key)
        if env_val:
            return env_val

    # 3. Fallback auf lokale Einstellungen
    settings = get_settings()
    settings_map = {
        'openai_api_key': settings.openai_api_key,
        'OPENAI_API_KEY': settings.openai_api_key,
        'anthropic_api_key': settings.anthropic_api_key,
        'ANTHROPIC_API_KEY': settings.anthropic_api_key,
        'ocr_api_key': settings.ocr_api_key,
        'OCR_API_KEY': settings.ocr_api_key,
    }

    return settings_map.get(key_name) or settings_map.get(key_name.lower()) or None


def get_api_key_status() -> dict:
    """
    Prüft den Status aller wichtigen API-Keys.

    Returns:
        Dict mit Key-Namen und deren Status (configured, source)
    """
    status = {}

    keys_to_check = [
        ('openai_api_key', 'OpenAI (ChatGPT)'),
        ('anthropic_api_key', 'Anthropic (Claude)'),
        ('ocr_api_key', 'OCR Service'),
        ('GOOGLE_API_KEY', 'Google Drive'),
    ]

    for key_name, display_name in keys_to_check:
        key_value = get_api_key(key_name)
        if key_value:
            # Bestimme die Quelle
            source = 'unbekannt'
            try:
                if hasattr(st, 'secrets'):
                    for k in [key_name, key_name.upper(), key_name.lower()]:
                        if k in st.secrets:
                            source = 'Streamlit Secrets'
                            break
                    # Prüfe verschachtelte
                    for section in ['openai', 'anthropic', 'google', 'ocr']:
                        if section in st.secrets and 'api_key' in st.secrets[section]:
                            source = 'Streamlit Secrets'
                            break
            except Exception:
                pass

            if source == 'unbekannt':
                import os
                for k in [key_name, key_name.upper()]:
                    if os.environ.get(k):
                        source = 'Umgebungsvariable'
                        break

            if source == 'unbekannt':
                source = 'Lokale Einstellungen'

            status[display_name] = {
                'configured': True,
                'source': source,
                'key_preview': key_value[:8] + '...' if len(key_value) > 8 else '***'
            }
        else:
            status[display_name] = {
                'configured': False,
                'source': None,
                'key_preview': None
            }

    return status


def save_settings(settings: Settings):
    """Einstellungen speichern und Session aktualisieren"""
    settings.save()
    st.session_state.settings = settings


# Kategorien für Dokumente
DOCUMENT_CATEGORIES = [
    "Rechnung",
    "Vertrag",
    "Versicherung",
    "Darlehen",
    "Rentenbescheid",
    "Lebensversicherung",
    "Kontoauszug",
    "Lohnabrechnung",
    "Steuerbescheid",
    "Mahnung",
    "Kündigung",
    "Angebot",
    "Bestellung",
    "Lieferschein",
    "Gutschrift",
    "Sonstiges"
]

# Standard-Ordnerstruktur
DEFAULT_FOLDERS = [
    {"name": "Posteingang", "parent_id": None, "is_system": True},
    {"name": "Verträge", "parent_id": None, "is_system": False},
    {"name": "Darlehen", "parent_id": None, "is_system": False},
    {"name": "Versicherungen", "parent_id": None, "is_system": False},
    {"name": "Rentenbescheide", "parent_id": None, "is_system": False},
    {"name": "Lebensversicherungen", "parent_id": None, "is_system": False},
    {"name": "Finanzen", "parent_id": None, "is_system": False},
    {"name": "Steuern", "parent_id": None, "is_system": False},
    {"name": "Archiv", "parent_id": None, "is_system": True},
    {"name": "Papierkorb", "parent_id": None, "is_system": True},
]

# Bon-Kategorien
RECEIPT_CATEGORIES = [
    "Lebensmittel",
    "Restaurant",
    "Transport",
    "Unterkunft",
    "Unterhaltung",
    "Einkauf",
    "Gesundheit",
    "Bildung",
    "Sonstiges"
]
