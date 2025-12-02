"""
Persistentes Speichersystem für RHM Posteingang
- Verschlüsselte API-Key-Speicherung
- Aktenregister-Speicherung mit Merge-Funktion
"""

import json
import pandas as pd
from pathlib import Path
from typing import Dict, Optional
from cryptography.fernet import Fernet
import base64
import hashlib


class PersistentStorage:
    def __init__(self, storage_dir: Path = None):
        """
        Initialisiert persistenten Speicher.

        Args:
            storage_dir: Verzeichnis für Speicherung (default: .streamlit/storage)
        """
        if storage_dir is None:
            storage_dir = Path.home() / '.streamlit' / 'rhm_storage'

        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # Dateipfade
        self.api_keys_file = self.storage_dir / 'api_keys.enc'
        self.aktenregister_file = self.storage_dir / 'aktenregister.xlsx'
        self.key_file = self.storage_dir / '.key'

        # Verschlüsselungsschlüssel laden oder erstellen
        self.cipher = self._get_cipher()

    def _get_cipher(self) -> Fernet:
        """Lädt oder erstellt Verschlüsselungsschlüssel"""
        if self.key_file.exists():
            with open(self.key_file, 'rb') as f:
                key = f.read()
        else:
            # Generiere neuen Schlüssel
            key = Fernet.generate_key()
            with open(self.key_file, 'wb') as f:
                f.write(key)
            # Setze Dateiberechtigungen (nur Owner kann lesen)
            self.key_file.chmod(0o600)

        return Fernet(key)

    # ==================== API-KEYS ====================

    def save_api_key(self, provider: str, api_key: str) -> None:
        """
        Speichert API-Key verschlüsselt.
        Überschreibt vorhandenen Key für diesen Provider.

        Args:
            provider: 'openai', 'claude', oder 'gemini'
            api_key: Der API-Schlüssel
        """
        # Lade vorhandene Keys
        keys = self.load_api_keys()

        # Aktualisiere/Füge hinzu
        keys[provider] = api_key

        # Verschlüssele und speichere
        json_data = json.dumps(keys)
        encrypted = self.cipher.encrypt(json_data.encode())

        with open(self.api_keys_file, 'wb') as f:
            f.write(encrypted)

        # Setze Dateiberechtigungen
        self.api_keys_file.chmod(0o600)

    def load_api_keys(self) -> Dict[str, str]:
        """
        Lädt gespeicherte API-Keys.

        Returns:
            Dict mit provider -> api_key
        """
        if not self.api_keys_file.exists():
            return {}

        try:
            with open(self.api_keys_file, 'rb') as f:
                encrypted = f.read()

            decrypted = self.cipher.decrypt(encrypted)
            keys = json.loads(decrypted.decode())
            return keys
        except Exception as e:
            # Bei Fehler: Leeres Dict zurückgeben
            return {}

    def delete_api_key(self, provider: str) -> None:
        """Löscht API-Key für einen Provider"""
        keys = self.load_api_keys()
        if provider in keys:
            del keys[provider]

            if keys:
                # Speichere verbleibende Keys
                json_data = json.dumps(keys)
                encrypted = self.cipher.encrypt(json_data.encode())
                with open(self.api_keys_file, 'wb') as f:
                    f.write(encrypted)
            else:
                # Keine Keys mehr: Lösche Datei
                self.api_keys_file.unlink(missing_ok=True)

    def has_api_key(self, provider: str) -> bool:
        """Prüft ob API-Key für Provider existiert"""
        keys = self.load_api_keys()
        return provider in keys and bool(keys[provider])

    # ==================== AKTENREGISTER ====================

    def save_aktenregister(self, new_df: pd.DataFrame, merge: bool = True) -> pd.DataFrame:
        """
        Speichert Aktenregister.

        Args:
            new_df: Neues DataFrame
            merge: True = Merge mit vorhandenen Daten, False = Ersetze

        Returns:
            Gespeichertes (ggf. gemergtes) DataFrame
        """
        if merge and self.aktenregister_file.exists():
            # Lade vorhandene Daten
            existing_df = pd.read_excel(self.aktenregister_file, sheet_name='akten', header=1)

            # Merge: Neue Zeilen hinzufügen, existierende aktualisieren
            # Annahme: 'Akte' ist der eindeutige Identifier
            if 'Akte' in existing_df.columns and 'Akte' in new_df.columns:
                # Aktualisiere existierende Einträge
                merged_df = pd.concat([existing_df, new_df]).drop_duplicates(subset=['Akte'], keep='last')
                merged_df = merged_df.reset_index(drop=True)
            else:
                # Kein Akte-Spalte: Einfach zusammenfügen
                merged_df = pd.concat([existing_df, new_df]).drop_duplicates()
                merged_df = merged_df.reset_index(drop=True)

            result_df = merged_df
        else:
            result_df = new_df

        # Speichere als Excel mit korrektem Format
        with pd.ExcelWriter(self.aktenregister_file, engine='openpyxl') as writer:
            # Leere Zeile als Header (wie Original)
            header_df = pd.DataFrame([[''] * len(result_df.columns)], columns=result_df.columns)
            combined = pd.concat([header_df, result_df], ignore_index=True)
            combined.to_excel(writer, sheet_name='akten', index=False, header=True)

        return result_df

    def load_aktenregister(self) -> Optional[pd.DataFrame]:
        """
        Lädt gespeichertes Aktenregister.

        Returns:
            DataFrame oder None wenn nicht vorhanden
        """
        if not self.aktenregister_file.exists():
            return None

        try:
            df = pd.read_excel(self.aktenregister_file, sheet_name='akten', header=1)
            return df
        except Exception as e:
            return None

    def has_aktenregister(self) -> bool:
        """Prüft ob Aktenregister existiert"""
        return self.aktenregister_file.exists()

    def delete_aktenregister(self) -> None:
        """Löscht gespeichertes Aktenregister"""
        self.aktenregister_file.unlink(missing_ok=True)

    def get_aktenregister_stats(self) -> Dict:
        """Gibt Statistiken zum Aktenregister zurück"""
        if not self.has_aktenregister():
            return {'exists': False}

        df = self.load_aktenregister()
        if df is None:
            return {'exists': False}

        return {
            'exists': True,
            'count': len(df),
            'last_modified': self.aktenregister_file.stat().st_mtime
        }
