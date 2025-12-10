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
