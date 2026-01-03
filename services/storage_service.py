"""
Cloud Storage Service für Dokumenten-Dateien

Unterstützt:
- Supabase Storage (empfohlen)
- AWS S3 (kompatibel)
- Lokaler Speicher (Fallback)

Verwendung:
1. In Supabase: Storage → Create Bucket "documents"
2. In Streamlit Secrets hinzufügen:
   SUPABASE_URL = "https://xxx.supabase.co"
   SUPABASE_KEY = "eyJhbGc..."
   SUPABASE_STORAGE_BUCKET = "documents"
"""
import os
import io
import logging
import hashlib
from pathlib import Path
from typing import Optional, Tuple, BinaryIO, Union
from datetime import datetime

logger = logging.getLogger(__name__)

# Versuche Supabase zu importieren
try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False
    logger.info("Supabase nicht verfügbar")

# Lokaler Fallback-Pfad
from config.settings import DOCUMENTS_DIR


class StorageService:
    """
    Hybrid Storage Service mit Cloud Storage (primär) und lokalem Speicher (Fallback).
    """

    def __init__(self):
        self._supabase_client: Optional[Client] = None
        self._bucket_name = "documents"
        self._initialized = False
        self._use_cloud = False

    def _init_storage(self):
        """Initialisiert Storage-Verbindung."""
        if self._initialized:
            return

        self._initialized = True

        if not SUPABASE_AVAILABLE:
            logger.info("Supabase-Bibliothek nicht installiert, verwende lokalen Speicher")
            return

        # Versuche Supabase-Credentials aus verschiedenen Quellen
        supabase_url = None
        supabase_key = None

        # 1. Streamlit Secrets
        try:
            import streamlit as st
            if hasattr(st, 'secrets'):
                supabase_url = st.secrets.get('SUPABASE_URL')
                supabase_key = st.secrets.get('SUPABASE_KEY') or st.secrets.get('SUPABASE_ANON_KEY')
                self._bucket_name = st.secrets.get('SUPABASE_STORAGE_BUCKET', 'documents')
        except Exception:
            pass

        # 2. Umgebungsvariablen
        if not supabase_url:
            supabase_url = os.environ.get('SUPABASE_URL')
            supabase_key = os.environ.get('SUPABASE_KEY') or os.environ.get('SUPABASE_ANON_KEY')
            self._bucket_name = os.environ.get('SUPABASE_STORAGE_BUCKET', 'documents')

        if supabase_url and supabase_key:
            try:
                self._supabase_client = create_client(supabase_url, supabase_key)
                # Test connection by listing buckets
                self._supabase_client.storage.list_buckets()
                self._use_cloud = True
                logger.info(f"Supabase Storage verbunden (Bucket: {self._bucket_name})")
            except Exception as e:
                logger.warning(f"Supabase Storage Fehler: {e}, verwende lokalen Speicher")
                self._supabase_client = None
        else:
            logger.info("Keine Supabase-Credentials konfiguriert, verwende lokalen Speicher")

    @property
    def is_cloud_storage(self) -> bool:
        """Prüft ob Cloud Storage verwendet wird."""
        self._init_storage()
        return self._use_cloud

    def _get_storage_path(self, user_id: int, filename: str, subfolder: str = "") -> str:
        """Generiert den Storage-Pfad für eine Datei."""
        # Format: user_{id}/{subfolder}/{filename}
        if subfolder:
            return f"user_{user_id}/{subfolder}/{filename}"
        return f"user_{user_id}/{filename}"

    def _get_local_path(self, user_id: int, filename: str, subfolder: str = "") -> Path:
        """Generiert den lokalen Pfad für eine Datei."""
        user_dir = DOCUMENTS_DIR / f"user_{user_id}"
        if subfolder:
            user_dir = user_dir / subfolder
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir / filename

    def upload_file(
        self,
        file_data: Union[bytes, BinaryIO],
        filename: str,
        user_id: int,
        subfolder: str = "",
        content_type: str = "application/octet-stream"
    ) -> Tuple[bool, str]:
        """
        Lädt eine Datei in den Storage hoch.

        Args:
            file_data: Dateiinhalt als Bytes oder File-like Object
            filename: Dateiname
            user_id: Benutzer-ID
            subfolder: Optionaler Unterordner
            content_type: MIME-Type

        Returns:
            Tuple (success: bool, path_or_error: str)
        """
        self._init_storage()

        # Stelle sicher dass wir Bytes haben
        if hasattr(file_data, 'read'):
            file_data = file_data.read()

        storage_path = self._get_storage_path(user_id, filename, subfolder)

        # Cloud Storage (Supabase)
        if self._use_cloud and self._supabase_client:
            try:
                # Upload zu Supabase
                response = self._supabase_client.storage.from_(self._bucket_name).upload(
                    path=storage_path,
                    file=file_data,
                    file_options={"content-type": content_type}
                )
                logger.info(f"Datei in Cloud hochgeladen: {storage_path}")
                return True, f"cloud://{self._bucket_name}/{storage_path}"
            except Exception as e:
                error_msg = str(e)
                # Wenn Datei bereits existiert, versuche Update
                if "already exists" in error_msg.lower() or "duplicate" in error_msg.lower():
                    try:
                        self._supabase_client.storage.from_(self._bucket_name).update(
                            path=storage_path,
                            file=file_data,
                            file_options={"content-type": content_type}
                        )
                        return True, f"cloud://{self._bucket_name}/{storage_path}"
                    except Exception as e2:
                        logger.error(f"Cloud Update Fehler: {e2}")
                        # Fallback auf lokal
                else:
                    logger.error(f"Cloud Upload Fehler: {e}")
                    # Fallback auf lokal

        # Lokaler Speicher (Fallback)
        try:
            local_path = self._get_local_path(user_id, filename, subfolder)
            with open(local_path, 'wb') as f:
                f.write(file_data)
            logger.info(f"Datei lokal gespeichert: {local_path}")
            return True, str(local_path)
        except Exception as e:
            logger.error(f"Lokaler Speicher Fehler: {e}")
            return False, str(e)

    def download_file(self, path: str, user_id: int = None) -> Tuple[bool, Union[bytes, str]]:
        """
        Lädt eine Datei aus dem Storage herunter.

        Args:
            path: Pfad zur Datei (cloud:// oder lokaler Pfad)
            user_id: Benutzer-ID (für Zugriffskontrolle)

        Returns:
            Tuple (success: bool, data_or_error: bytes|str)
        """
        self._init_storage()

        # Cloud Storage
        if path.startswith("cloud://"):
            if not self._supabase_client:
                return False, "Cloud Storage nicht verfügbar"

            try:
                # Extrahiere Bucket und Pfad
                parts = path.replace("cloud://", "").split("/", 1)
                bucket = parts[0]
                file_path = parts[1] if len(parts) > 1 else ""

                response = self._supabase_client.storage.from_(bucket).download(file_path)
                return True, response
            except Exception as e:
                logger.error(f"Cloud Download Fehler: {e}")
                return False, str(e)

        # Lokaler Speicher
        try:
            local_path = Path(path)
            if not local_path.exists():
                return False, "Datei nicht gefunden"

            # Sicherheitsprüfung: Datei muss im DOCUMENTS_DIR sein
            try:
                local_path.resolve().relative_to(DOCUMENTS_DIR.resolve())
            except ValueError:
                return False, "Zugriff verweigert"

            with open(local_path, 'rb') as f:
                return True, f.read()
        except Exception as e:
            logger.error(f"Lokaler Download Fehler: {e}")
            return False, str(e)

    def delete_file(self, path: str) -> bool:
        """
        Löscht eine Datei aus dem Storage.

        Args:
            path: Pfad zur Datei

        Returns:
            True wenn erfolgreich
        """
        self._init_storage()

        # Cloud Storage
        if path.startswith("cloud://"):
            if not self._supabase_client:
                return False

            try:
                parts = path.replace("cloud://", "").split("/", 1)
                bucket = parts[0]
                file_path = parts[1] if len(parts) > 1 else ""

                self._supabase_client.storage.from_(bucket).remove([file_path])
                logger.info(f"Cloud-Datei gelöscht: {path}")
                return True
            except Exception as e:
                logger.error(f"Cloud Delete Fehler: {e}")
                return False

        # Lokaler Speicher
        try:
            local_path = Path(path)
            if local_path.exists():
                local_path.unlink()
                logger.info(f"Lokale Datei gelöscht: {path}")
                return True
            return False
        except Exception as e:
            logger.error(f"Lokaler Delete Fehler: {e}")
            return False

    def get_public_url(self, path: str, expires_in: int = 3600) -> Optional[str]:
        """
        Generiert eine öffentliche URL für eine Datei (nur Cloud Storage).

        Args:
            path: Cloud-Pfad
            expires_in: Gültigkeit in Sekunden

        Returns:
            URL oder None
        """
        self._init_storage()

        if not path.startswith("cloud://") or not self._supabase_client:
            return None

        try:
            parts = path.replace("cloud://", "").split("/", 1)
            bucket = parts[0]
            file_path = parts[1] if len(parts) > 1 else ""

            response = self._supabase_client.storage.from_(bucket).create_signed_url(
                file_path, expires_in
            )
            return response.get('signedURL')
        except Exception as e:
            logger.error(f"URL-Generierung Fehler: {e}")
            return None

    def list_files(self, user_id: int, subfolder: str = "") -> list:
        """
        Listet alle Dateien eines Benutzers auf.

        Returns:
            Liste von Datei-Informationen
        """
        self._init_storage()
        files = []

        storage_path = f"user_{user_id}"
        if subfolder:
            storage_path = f"{storage_path}/{subfolder}"

        # Cloud Storage
        if self._use_cloud and self._supabase_client:
            try:
                response = self._supabase_client.storage.from_(self._bucket_name).list(storage_path)
                for item in response:
                    if item.get('name'):
                        files.append({
                            'name': item['name'],
                            'path': f"cloud://{self._bucket_name}/{storage_path}/{item['name']}",
                            'size': item.get('metadata', {}).get('size', 0),
                            'created_at': item.get('created_at'),
                            'storage_type': 'cloud'
                        })
            except Exception as e:
                logger.warning(f"Cloud list Fehler: {e}")

        # Lokaler Speicher
        local_dir = self._get_local_path(user_id, "", subfolder).parent
        if subfolder:
            local_dir = local_dir / subfolder

        if local_dir.exists():
            for item in local_dir.iterdir():
                if item.is_file():
                    files.append({
                        'name': item.name,
                        'path': str(item),
                        'size': item.stat().st_size,
                        'created_at': datetime.fromtimestamp(item.stat().st_ctime).isoformat(),
                        'storage_type': 'local'
                    })

        return files

    def get_status(self) -> dict:
        """Gibt Storage-Status zurück."""
        self._init_storage()

        status = {
            'type': 'supabase' if self._use_cloud else 'local',
            'connected': self._use_cloud,
            'bucket': self._bucket_name if self._use_cloud else None,
            'local_path': str(DOCUMENTS_DIR),
            'warning': None if self._use_cloud else 'Lokaler Speicher wird bei Neustart gelöscht!'
        }

        # Prüfe lokalen Speicherplatz
        try:
            import shutil
            total, used, free = shutil.disk_usage(DOCUMENTS_DIR)
            status['local_free_gb'] = round(free / (1024**3), 2)
        except Exception:
            pass

        return status


# Singleton-Instanz
_storage_service = None


def get_storage_service() -> StorageService:
    """Gibt die Storage-Service Singleton-Instanz zurück."""
    global _storage_service
    if _storage_service is None:
        _storage_service = StorageService()
    return _storage_service
