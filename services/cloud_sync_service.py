"""
Cloud-Sync Service für Dropbox und Google Drive
Ermöglicht automatische Synchronisation von Dokumenten aus Cloud-Ordnern
"""
import os
import hashlib
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
import requests
from urllib.parse import urlencode, urlparse, parse_qs

from database.models import Document, Folder
from database.db import get_db
from database.extended_models import (
    CloudSyncConnection, CloudSyncLog, CloudProvider, SyncStatus
)

logger = logging.getLogger(__name__)


class CloudSyncConnectionWrapper:
    """Wrapper für CloudSyncConnection mit vereinfachtem Attributzugriff"""

    def __init__(self, connection: CloudSyncConnection):
        self.id = connection.id
        self.user_id = connection.user_id
        self.provider = connection.provider
        self.provider_name = connection.provider_name
        self.is_active = connection.is_active
        self.sync_interval_minutes = connection.sync_interval_minutes

        # Aliase für einfacheren Zugriff
        self.folder_path = connection.remote_folder_path
        self.folder_id = connection.remote_folder_id
        self.sync_status = connection.status
        self.last_sync = connection.last_sync_at
        self.last_sync_error = connection.last_sync_error

        # Originale Attribute
        self.remote_folder_path = connection.remote_folder_path
        self.remote_folder_id = connection.remote_folder_id
        self.access_token = connection.access_token
        self.status = connection.status
        self.last_sync_at = connection.last_sync_at
        self.total_files_synced = connection.total_files_synced
        self.auto_sync_enabled = connection.auto_sync_enabled
        self.created_at = connection.created_at
        self.updated_at = connection.updated_at


class CloudSyncLogWrapper:
    """Wrapper für CloudSyncLog mit vereinfachtem Attributzugriff"""

    def __init__(self, log: CloudSyncLog):
        self.id = log.id
        self.connection_id = log.connection_id
        self.user_id = log.user_id
        self.status = log.sync_status
        self.created_at = log.synced_at
        self.files_synced = 1 if log.sync_status == "synced" else 0
        self.files_skipped = 1 if log.sync_status == "skipped" else 0
        self.original_filename = log.original_filename
        self.error_message = log.error_message


class CloudSyncService:
    """Service für Cloud-Synchronisation"""

    # API-Endpunkte
    DROPBOX_AUTH_URL = "https://www.dropbox.com/oauth2/authorize"
    DROPBOX_TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"
    DROPBOX_API_URL = "https://api.dropboxapi.com/2"
    DROPBOX_CONTENT_URL = "https://content.dropboxapi.com/2"

    GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
    GOOGLE_API_URL = "https://www.googleapis.com/drive/v3"

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.log_file_path = Path("data/sync_logs")
        self.log_file_path.mkdir(parents=True, exist_ok=True)

    # ==================== OAUTH AUTHENTIFIZIERUNG ====================

    def get_dropbox_auth_url(self, client_id: str, redirect_uri: str) -> str:
        """Erstellt Dropbox OAuth URL"""
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "token_access_type": "offline"
        }
        return f"{self.DROPBOX_AUTH_URL}?{urlencode(params)}"

    def get_google_auth_url(self, client_id: str, redirect_uri: str) -> str:
        """Erstellt Google Drive OAuth URL"""
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "https://www.googleapis.com/auth/drive.readonly",
            "access_type": "offline",
            "prompt": "consent"
        }
        return f"{self.GOOGLE_AUTH_URL}?{urlencode(params)}"

    def exchange_dropbox_code(self, code: str, client_id: str,
                              client_secret: str, redirect_uri: str) -> Dict:
        """Tauscht Dropbox Auth-Code gegen Tokens"""
        response = requests.post(self.DROPBOX_TOKEN_URL, data={
            "code": code,
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri
        })
        return response.json()

    def exchange_google_code(self, code: str, client_id: str,
                             client_secret: str, redirect_uri: str) -> Dict:
        """Tauscht Google Auth-Code gegen Tokens"""
        response = requests.post(self.GOOGLE_TOKEN_URL, data={
            "code": code,
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri
        })
        return response.json()

    def refresh_dropbox_token(self, refresh_token: str, client_id: str,
                              client_secret: str) -> Dict:
        """Erneuert Dropbox Access Token"""
        response = requests.post(self.DROPBOX_TOKEN_URL, data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret
        })
        return response.json()

    def refresh_google_token(self, refresh_token: str, client_id: str,
                             client_secret: str) -> Dict:
        """Erneuert Google Access Token"""
        response = requests.post(self.GOOGLE_TOKEN_URL, data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret
        })
        return response.json()

    # ==================== VERBINDUNG ERSTELLEN ====================

    def create_connection(self, provider: CloudProvider,
                          folder_id: str = None,
                          folder_path: str = None,
                          access_token: str = None,
                          refresh_token: str = None,
                          token_expires_at: datetime = None,
                          local_folder_id: int = None,
                          sync_interval_minutes: int = None,
                          provider_name: str = None) -> 'CloudSyncConnectionWrapper':
        """Erstellt eine neue Cloud-Sync-Verbindung"""
        with get_db() as session:
            connection = CloudSyncConnection(
                user_id=self.user_id,
                provider=provider,
                provider_name=provider_name or provider.value,
                remote_folder_path=folder_path or folder_id or "",
                remote_folder_id=folder_id,
                access_token=access_token or "",
                refresh_token=refresh_token,
                token_expires_at=token_expires_at,
                local_folder_id=local_folder_id,
                sync_interval_minutes=sync_interval_minutes,
                auto_sync_enabled=sync_interval_minutes is not None,
                status=SyncStatus.PENDING,
                file_extensions=[".pdf", ".jpg", ".jpeg", ".png", ".gif", ".doc",
                                ".docx", ".xls", ".xlsx", ".txt"]
            )
            session.add(connection)
            session.commit()
            session.refresh(connection)
            # Return wrapped connection with easier attribute access
            return CloudSyncConnectionWrapper(connection)

    def get_connections(self, active_only: bool = False) -> List['CloudSyncConnectionWrapper']:
        """Holt alle Verbindungen eines Benutzers"""
        with get_db() as session:
            query = session.query(CloudSyncConnection).filter(
                CloudSyncConnection.user_id == self.user_id
            )
            if active_only:
                query = query.filter(CloudSyncConnection.is_active == True)
            connections = query.all()
            # Convert to wrapper objects for easier attribute access
            return [CloudSyncConnectionWrapper(c) for c in connections]

    def get_connection(self, connection_id: int) -> Optional['CloudSyncConnectionWrapper']:
        """Holt eine spezifische Verbindung"""
        with get_db() as session:
            conn = session.query(CloudSyncConnection).filter(
                CloudSyncConnection.id == connection_id,
                CloudSyncConnection.user_id == self.user_id
            ).first()
            if conn:
                return CloudSyncConnectionWrapper(conn)
            return None

    def update_connection(self, connection_id: int, **kwargs) -> bool:
        """Aktualisiert Verbindungseinstellungen"""
        with get_db() as session:
            connection = session.query(CloudSyncConnection).filter(
                CloudSyncConnection.id == connection_id,
                CloudSyncConnection.user_id == self.user_id
            ).first()
            if not connection:
                return False

            for key, value in kwargs.items():
                if hasattr(connection, key):
                    setattr(connection, key, value)

            connection.updated_at = datetime.now()
            session.commit()
            return True

    def delete_connection(self, connection_id: int) -> bool:
        """Löscht eine Verbindung"""
        with get_db() as session:
            connection = session.query(CloudSyncConnection).filter(
                CloudSyncConnection.id == connection_id,
                CloudSyncConnection.user_id == self.user_id
            ).first()
            if not connection:
                return False

            session.delete(connection)
            session.commit()
            return True

    # ==================== DROPBOX API ====================

    def _dropbox_list_folder(self, access_token: str, path: str,
                             cursor: str = None) -> Dict:
        """Listet Dateien in einem Dropbox-Ordner"""
        headers = {"Authorization": f"Bearer {access_token}"}

        if cursor:
            # Fortsetzung eines vorherigen Aufrufs
            response = requests.post(
                f"{self.DROPBOX_API_URL}/files/list_folder/continue",
                headers=headers,
                json={"cursor": cursor}
            )
        else:
            response = requests.post(
                f"{self.DROPBOX_API_URL}/files/list_folder",
                headers=headers,
                json={
                    "path": path if path != "/" else "",
                    "recursive": False,
                    "include_deleted": False,
                    "include_has_explicit_shared_members": False
                }
            )

        return response.json()

    def _dropbox_download_file(self, access_token: str, path: str) -> Tuple[bytes, Dict]:
        """Lädt eine Datei von Dropbox herunter"""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Dropbox-API-Arg": json.dumps({"path": path})
        }

        response = requests.post(
            f"{self.DROPBOX_CONTENT_URL}/files/download",
            headers=headers
        )

        metadata = json.loads(response.headers.get("Dropbox-API-Result", "{}"))
        return response.content, metadata

    def _dropbox_get_file_metadata(self, access_token: str, path: str) -> Dict:
        """Holt Metadaten einer Dropbox-Datei"""
        headers = {"Authorization": f"Bearer {access_token}"}

        response = requests.post(
            f"{self.DROPBOX_API_URL}/files/get_metadata",
            headers=headers,
            json={"path": path}
        )

        return response.json()

    # ==================== GOOGLE DRIVE API ====================

    def _google_list_folder(self, access_token: str, folder_id: str = None,
                            page_token: str = None) -> Dict:
        """Listet Dateien in einem Google Drive-Ordner"""
        headers = {"Authorization": f"Bearer {access_token}"}

        params = {
            "pageSize": 100,
            "fields": "nextPageToken, files(id, name, mimeType, size, modifiedTime, md5Checksum)"
        }

        if folder_id:
            params["q"] = f"'{folder_id}' in parents and trashed = false"
        else:
            params["q"] = "trashed = false"

        if page_token:
            params["pageToken"] = page_token

        response = requests.get(
            f"{self.GOOGLE_API_URL}/files",
            headers=headers,
            params=params
        )

        return response.json()

    def _google_download_file(self, access_token: str, file_id: str) -> bytes:
        """Lädt eine Datei von Google Drive herunter"""
        headers = {"Authorization": f"Bearer {access_token}"}

        response = requests.get(
            f"{self.GOOGLE_API_URL}/files/{file_id}",
            headers=headers,
            params={"alt": "media"}
        )

        return response.content

    def _google_get_folder_id_from_link(self, link: str) -> Optional[str]:
        """Extrahiert Folder-ID aus Google Drive Link"""
        # Format: https://drive.google.com/drive/folders/FOLDER_ID
        # oder: https://drive.google.com/drive/u/0/folders/FOLDER_ID
        parsed = urlparse(link)
        path_parts = parsed.path.split("/")

        try:
            if "folders" in path_parts:
                idx = path_parts.index("folders")
                if idx + 1 < len(path_parts):
                    return path_parts[idx + 1].split("?")[0]
        except:
            pass

        return None

    # ==================== SYNCHRONISATION ====================

    def sync_connection(self, connection_id: int,
                        process_documents: bool = True) -> Dict[str, Any]:
        """
        Führt Synchronisation für eine Verbindung durch (ohne Fortschrittsanzeige)
        """
        # Sammle alle Updates und gib nur das finale Ergebnis zurück
        final_result = None
        for progress in self.sync_connection_with_progress(connection_id, process_documents):
            final_result = progress
        return final_result or {"success": False, "error": "Keine Ergebnisse"}

    def sync_connection_with_progress(self, connection_id: int,
                                       process_documents: bool = True):
        """
        Führt Synchronisation mit Fortschritts-Updates durch (Generator).

        Yields:
            Dict mit Fortschrittsinformationen:
            - phase: 'scanning', 'downloading', 'completed', 'error'
            - current_file: Name der aktuell verarbeiteten Datei
            - current_file_size: Größe der aktuellen Datei
            - files_total: Gesamtanzahl gefundener Dateien
            - files_processed: Bisher verarbeitete Dateien
            - files_synced: Erfolgreich synchronisierte Dateien
            - files_skipped: Übersprungene Dateien
            - progress_percent: Fortschritt in Prozent (0-100)
            - elapsed_seconds: Verstrichene Zeit
            - estimated_remaining_seconds: Geschätzte Restzeit
            - success: True wenn abgeschlossen und erfolgreich
            - error: Fehlermeldung falls vorhanden
        """
        import time
        start_time = time.time()

        result = {
            "phase": "initializing",
            "current_file": None,
            "current_file_size": 0,
            "files_total": 0,
            "files_processed": 0,
            "files_synced": 0,
            "files_skipped": 0,
            "files_error": 0,
            "progress_percent": 0,
            "elapsed_seconds": 0,
            "estimated_remaining_seconds": None,
            "success": False,
            "new_files": 0,
            "skipped_files": 0,
            "errors": [],
            "error": None,
            "synced_files": []
        }

        yield result.copy()

        with get_db() as session:
            connection = session.query(CloudSyncConnection).filter(
                CloudSyncConnection.id == connection_id,
                CloudSyncConnection.user_id == self.user_id
            ).first()

            if not connection:
                result["phase"] = "error"
                result["error"] = "Verbindung nicht gefunden"
                result["errors"].append(result["error"])
                yield result
                return

            if not connection.is_active:
                result["phase"] = "error"
                result["error"] = "Verbindung ist deaktiviert"
                result["errors"].append(result["error"])
                yield result
                return

            # Prüfen ob Access Token vorhanden
            if not connection.access_token:
                result["phase"] = "error"
                result["error"] = "Kein Access Token konfiguriert. Bitte API-Konfiguration in Einstellungen prüfen."
                result["errors"].append(result["error"])
                result["success"] = True  # Nicht als Fehler behandeln, nur Hinweis
                yield result
                return

            # Status auf "syncing" setzen
            connection.status = SyncStatus.SYNCING
            session.commit()

            try:
                # Phase 1: Dateien scannen
                result["phase"] = "scanning"
                yield result.copy()

                if connection.provider == CloudProvider.DROPBOX:
                    # Erst alle Dateien sammeln
                    files_to_sync = self._collect_dropbox_files(connection, session)
                elif connection.provider == CloudProvider.GOOGLE_DRIVE:
                    files_to_sync = self._collect_google_drive_files(connection, session)
                else:
                    result["phase"] = "error"
                    result["error"] = f"Provider {connection.provider} nicht unterstützt"
                    result["errors"].append(result["error"])
                    yield result
                    return

                result["files_total"] = len(files_to_sync)
                result["phase"] = "downloading"
                yield result.copy()

                # Phase 2: Dateien herunterladen und importieren
                for idx, file_info in enumerate(files_to_sync):
                    elapsed = time.time() - start_time
                    result["elapsed_seconds"] = elapsed
                    result["current_file"] = file_info.get("name", "Unbekannt")
                    result["current_file_size"] = file_info.get("size", 0)
                    result["files_processed"] = idx

                    # Fortschritt berechnen
                    if result["files_total"] > 0:
                        result["progress_percent"] = int((idx / result["files_total"]) * 100)

                        # Restzeit schätzen
                        if idx > 0:
                            avg_time_per_file = elapsed / idx
                            remaining_files = result["files_total"] - idx
                            result["estimated_remaining_seconds"] = avg_time_per_file * remaining_files

                    yield result.copy()

                    # Datei verarbeiten
                    try:
                        sync_status = self._process_file(
                            connection, session, file_info, process_documents
                        )

                        if sync_status == "synced":
                            result["files_synced"] += 1
                            result["synced_files"].append(file_info.get("name"))
                        elif sync_status == "skipped":
                            result["files_skipped"] += 1
                        else:
                            result["files_error"] += 1

                    except Exception as e:
                        logger.error(f"Fehler beim Import von {file_info.get('name')}: {e}")
                        result["files_error"] += 1
                        result["errors"].append(f"{file_info.get('name')}: {str(e)}")

                # Phase 3: Abschluss
                result["phase"] = "completed"
                result["files_processed"] = result["files_total"]
                result["progress_percent"] = 100
                result["new_files"] = result["files_synced"]
                result["skipped_files"] = result["files_skipped"]
                result["success"] = len(result["errors"]) == 0
                result["elapsed_seconds"] = time.time() - start_time
                result["estimated_remaining_seconds"] = 0

                # Status aktualisieren
                connection.status = SyncStatus.COMPLETED
                connection.last_sync_at = datetime.now()
                connection.last_sync_error = None
                connection.total_files_synced += result["files_synced"]

            except Exception as e:
                logger.error(f"Sync-Fehler für Verbindung {connection_id}: {e}")
                connection.status = SyncStatus.ERROR
                connection.last_sync_error = str(e)
                result["phase"] = "error"
                result["error"] = str(e)
                result["errors"].append(str(e))

            session.commit()

        # Sync-Log schreiben
        self._write_sync_log(connection_id, result)

        # Wenn Fehler vorhanden, erste Fehlermeldung setzen
        if result["errors"] and not result["error"]:
            result["error"] = result["errors"][0]

        yield result

    def _collect_dropbox_files(self, connection: CloudSyncConnection,
                                session) -> List[Dict]:
        """Sammelt alle zu synchronisierenden Dropbox-Dateien"""
        files = []
        cursor = connection.last_cursor
        has_more = True

        while has_more:
            response = self._dropbox_list_folder(
                connection.access_token,
                connection.remote_folder_path,
                cursor
            )

            if "error" in response:
                break

            entries = response.get("entries", [])

            for entry in entries:
                if entry.get(".tag") != "file":
                    continue

                filename = entry.get("name", "")
                ext = Path(filename).suffix.lower()

                # Dateiendung prüfen
                if connection.file_extensions and ext not in connection.file_extensions:
                    continue

                # Dateigröße prüfen
                file_size = entry.get("size", 0)
                max_size = (connection.max_file_size_mb or 50) * 1024 * 1024
                if file_size > max_size:
                    continue

                # Prüfen ob bereits synchronisiert
                content_hash = entry.get("content_hash")
                existing_log = session.query(CloudSyncLog).filter(
                    CloudSyncLog.connection_id == connection.id,
                    CloudSyncLog.remote_file_hash == content_hash
                ).first()

                if existing_log:
                    continue

                files.append({
                    "name": filename,
                    "path": entry.get("path_display"),
                    "id": entry.get("id"),
                    "size": file_size,
                    "hash": content_hash,
                    "modified": entry.get("server_modified"),
                    "provider": "dropbox"
                })

            cursor = response.get("cursor")
            has_more = response.get("has_more", False)

        # Cursor speichern
        if cursor:
            connection.last_cursor = cursor

        return files

    def _collect_google_drive_files(self, connection: CloudSyncConnection,
                                     session) -> List[Dict]:
        """Sammelt alle zu synchronisierenden Google Drive-Dateien"""
        files = []

        folder_id = connection.remote_folder_id
        if not folder_id and connection.remote_folder_path:
            folder_id = self._google_get_folder_id_from_link(connection.remote_folder_path)

        page_token = None
        has_more = True

        while has_more:
            response = self._google_list_folder(
                connection.access_token,
                folder_id,
                page_token
            )

            if "error" in response:
                break

            file_list = response.get("files", [])

            for file_info in file_list:
                mime_type = file_info.get("mimeType", "")
                if mime_type.startswith("application/vnd.google-apps"):
                    continue

                filename = file_info.get("name", "")
                ext = Path(filename).suffix.lower()

                # Dateiendung prüfen
                if connection.file_extensions and ext not in connection.file_extensions:
                    continue

                # Dateigröße prüfen
                file_size = int(file_info.get("size", 0))
                max_size = (connection.max_file_size_mb or 50) * 1024 * 1024
                if file_size > max_size:
                    continue

                # Prüfen ob bereits synchronisiert
                file_hash = file_info.get("md5Checksum")
                existing_log = session.query(CloudSyncLog).filter(
                    CloudSyncLog.connection_id == connection.id,
                    CloudSyncLog.remote_file_hash == file_hash
                ).first()

                if existing_log:
                    continue

                files.append({
                    "name": filename,
                    "path": filename,
                    "id": file_info.get("id"),
                    "size": file_size,
                    "hash": file_hash,
                    "modified": file_info.get("modifiedTime"),
                    "mime_type": mime_type,
                    "provider": "google_drive"
                })

            page_token = response.get("nextPageToken")
            has_more = page_token is not None

        return files

    def _process_file(self, connection: CloudSyncConnection, session,
                      file_info: Dict, process_documents: bool) -> str:
        """
        Verarbeitet eine einzelne Datei.

        Returns:
            'synced', 'skipped', oder 'error'
        """
        try:
            if file_info.get("provider") == "dropbox":
                file_content, metadata = self._dropbox_download_file(
                    connection.access_token,
                    file_info.get("path")
                )
            else:
                file_content = self._google_download_file(
                    connection.access_token,
                    file_info.get("id")
                )

            # Dokument erstellen
            doc = self._import_file(
                session, connection,
                file_info.get("name"),
                file_content,
                file_info.get("size"),
                file_info.get("hash"),
                file_info.get("path") or file_info.get("id"),
                process_documents
            )

            # Sync-Log erstellen
            modified_time = file_info.get("modified")
            if modified_time and isinstance(modified_time, str):
                try:
                    modified_time = datetime.fromisoformat(modified_time.replace("Z", "+00:00"))
                except:
                    modified_time = None

            sync_log = CloudSyncLog(
                connection_id=connection.id,
                user_id=self.user_id,
                remote_file_path=file_info.get("path") or file_info.get("name"),
                remote_file_id=file_info.get("id"),
                remote_file_hash=file_info.get("hash"),
                file_size=file_info.get("size"),
                file_modified_at=modified_time,
                document_id=doc.id if doc else None,
                local_file_path=doc.file_path if doc else None,
                sync_status="synced",
                original_filename=file_info.get("name"),
                mime_type=file_info.get("mime_type") or self._get_mime_type(file_info.get("name"))
            )
            session.add(sync_log)

            return "synced"

        except Exception as e:
            logger.error(f"Fehler beim Verarbeiten von {file_info.get('name')}: {e}")
            return "error"

    def _sync_dropbox(self, connection: CloudSyncConnection,
                      session, process_documents: bool) -> Dict:
        """Synchronisiert Dropbox-Ordner"""
        result = {
            "files_found": 0,
            "files_synced": 0,
            "files_skipped": 0,
            "files_error": 0,
            "errors": [],
            "synced_files": []
        }

        cursor = connection.last_cursor
        has_more = True

        while has_more:
            response = self._dropbox_list_folder(
                connection.access_token,
                connection.remote_folder_path,
                cursor
            )

            if "error" in response:
                result["errors"].append(response.get("error_summary", "Dropbox API Fehler"))
                break

            entries = response.get("entries", [])

            for entry in entries:
                if entry.get(".tag") != "file":
                    continue

                result["files_found"] += 1

                # Dateiendung prüfen
                filename = entry.get("name", "")
                ext = Path(filename).suffix.lower()

                if connection.file_extensions and ext not in connection.file_extensions:
                    result["files_skipped"] += 1
                    continue

                # Dateigröße prüfen
                file_size = entry.get("size", 0)
                max_size = (connection.max_file_size_mb or 50) * 1024 * 1024

                if file_size > max_size:
                    result["files_skipped"] += 1
                    continue

                # Prüfen ob bereits synchronisiert (über Hash)
                content_hash = entry.get("content_hash")

                existing_log = session.query(CloudSyncLog).filter(
                    CloudSyncLog.connection_id == connection.id,
                    CloudSyncLog.remote_file_hash == content_hash
                ).first()

                if existing_log:
                    result["files_skipped"] += 1
                    continue

                # Datei herunterladen und importieren
                try:
                    file_content, metadata = self._dropbox_download_file(
                        connection.access_token,
                        entry.get("path_display")
                    )

                    # Dokument erstellen
                    doc = self._import_file(
                        session, connection, filename, file_content,
                        file_size, content_hash, entry.get("path_display"),
                        process_documents
                    )

                    # Sync-Log erstellen
                    sync_log = CloudSyncLog(
                        connection_id=connection.id,
                        user_id=self.user_id,
                        remote_file_path=entry.get("path_display"),
                        remote_file_id=entry.get("id"),
                        remote_file_hash=content_hash,
                        file_size=file_size,
                        file_modified_at=datetime.fromisoformat(
                            entry.get("server_modified", "").replace("Z", "+00:00")
                        ) if entry.get("server_modified") else None,
                        document_id=doc.id if doc else None,
                        local_file_path=doc.file_path if doc else None,
                        sync_status="synced",
                        original_filename=filename,
                        mime_type=self._get_mime_type(filename)
                    )
                    session.add(sync_log)

                    result["files_synced"] += 1
                    result["synced_files"].append(filename)

                except Exception as e:
                    logger.error(f"Fehler beim Import von {filename}: {e}")
                    result["files_error"] += 1
                    result["errors"].append(f"{filename}: {str(e)}")

            # Cursor für nächste Seite
            cursor = response.get("cursor")
            has_more = response.get("has_more", False)

        # Cursor speichern für Delta-Sync
        if cursor:
            connection.last_cursor = cursor

        return result

    def _sync_google_drive(self, connection: CloudSyncConnection,
                           session, process_documents: bool) -> Dict:
        """Synchronisiert Google Drive-Ordner"""
        result = {
            "files_found": 0,
            "files_synced": 0,
            "files_skipped": 0,
            "files_error": 0,
            "errors": [],
            "synced_files": []
        }

        # Folder-ID aus Pfad/Link extrahieren
        folder_id = connection.remote_folder_id
        if not folder_id and connection.remote_folder_path:
            folder_id = self._google_get_folder_id_from_link(connection.remote_folder_path)

        page_token = None
        has_more = True

        while has_more:
            response = self._google_list_folder(
                connection.access_token,
                folder_id,
                page_token
            )

            if "error" in response:
                result["errors"].append(response.get("error", {}).get("message", "Google API Fehler"))
                break

            files = response.get("files", [])

            for file_info in files:
                # Google Docs/Sheets etc. überspringen (nur echte Dateien)
                mime_type = file_info.get("mimeType", "")
                if mime_type.startswith("application/vnd.google-apps"):
                    continue

                result["files_found"] += 1

                filename = file_info.get("name", "")
                ext = Path(filename).suffix.lower()

                # Dateiendung prüfen
                if connection.file_extensions and ext not in connection.file_extensions:
                    result["files_skipped"] += 1
                    continue

                # Dateigröße prüfen
                file_size = int(file_info.get("size", 0))
                max_size = (connection.max_file_size_mb or 50) * 1024 * 1024

                if file_size > max_size:
                    result["files_skipped"] += 1
                    continue

                # Prüfen ob bereits synchronisiert
                file_hash = file_info.get("md5Checksum")

                existing_log = session.query(CloudSyncLog).filter(
                    CloudSyncLog.connection_id == connection.id,
                    CloudSyncLog.remote_file_hash == file_hash
                ).first()

                if existing_log:
                    result["files_skipped"] += 1
                    continue

                # Datei herunterladen und importieren
                try:
                    file_content = self._google_download_file(
                        connection.access_token,
                        file_info.get("id")
                    )

                    doc = self._import_file(
                        session, connection, filename, file_content,
                        file_size, file_hash, file_info.get("id"),
                        process_documents
                    )

                    # Sync-Log erstellen
                    modified_time = file_info.get("modifiedTime")
                    sync_log = CloudSyncLog(
                        connection_id=connection.id,
                        user_id=self.user_id,
                        remote_file_path=filename,
                        remote_file_id=file_info.get("id"),
                        remote_file_hash=file_hash,
                        file_size=file_size,
                        file_modified_at=datetime.fromisoformat(
                            modified_time.replace("Z", "+00:00")
                        ) if modified_time else None,
                        document_id=doc.id if doc else None,
                        local_file_path=doc.file_path if doc else None,
                        sync_status="synced",
                        original_filename=filename,
                        mime_type=mime_type
                    )
                    session.add(sync_log)

                    result["files_synced"] += 1
                    result["synced_files"].append(filename)

                except Exception as e:
                    logger.error(f"Fehler beim Import von {filename}: {e}")
                    result["files_error"] += 1
                    result["errors"].append(f"{filename}: {str(e)}")

            page_token = response.get("nextPageToken")
            has_more = page_token is not None

        return result

    def _import_file(self, session, connection: CloudSyncConnection,
                     filename: str, content: bytes, file_size: int,
                     content_hash: str, remote_path: str,
                     process_documents: bool) -> Optional[Document]:
        """Importiert eine Datei ins Dokumentenmanagement"""
        # Speicherpfad erstellen
        upload_dir = Path("data/uploads") / str(self.user_id) / "cloud_sync"
        upload_dir.mkdir(parents=True, exist_ok=True)

        # Eindeutigen Dateinamen erstellen
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_filename = f"{timestamp}_{filename}"
        file_path = upload_dir / safe_filename

        # Datei speichern
        with open(file_path, "wb") as f:
            f.write(content)

        # Dokument in DB erstellen
        doc = Document(
            user_id=self.user_id,
            folder_id=connection.local_folder_id,
            title=Path(filename).stem,
            filename=filename,
            file_path=str(file_path),
            file_size=file_size,
            mime_type=self._get_mime_type(filename),
            content_hash=content_hash,
            status="pending" if process_documents else "completed",
            category="Cloud-Import"
        )

        session.add(doc)
        session.flush()  # Um ID zu erhalten

        return doc

    def _get_mime_type(self, filename: str) -> str:
        """Ermittelt MIME-Type aus Dateinamen"""
        ext = Path(filename).suffix.lower()
        mime_types = {
            ".pdf": "application/pdf",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xls": "application/vnd.ms-excel",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".txt": "text/plain",
            ".csv": "text/csv"
        }
        return mime_types.get(ext, "application/octet-stream")

    def _write_sync_log(self, connection_id: int, result: Dict):
        """Schreibt Sync-Ergebnis in Log-Datei"""
        log_file = self.log_file_path / f"sync_{connection_id}_{datetime.now().strftime('%Y%m%d')}.log"

        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "connection_id": connection_id,
            "user_id": self.user_id,
            "files_found": result["files_found"],
            "files_synced": result["files_synced"],
            "files_skipped": result["files_skipped"],
            "files_error": result["files_error"],
            "synced_files": result["synced_files"],
            "errors": result["errors"]
        }

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    # ==================== SYNC-LOGS ====================

    def get_sync_logs(self, connection_id: int = None,
                      limit: int = 100) -> List[CloudSyncLogWrapper]:
        """Holt Sync-Logs"""
        with get_db() as session:
            query = session.query(CloudSyncLog).filter(
                CloudSyncLog.user_id == self.user_id
            )

            if connection_id:
                query = query.filter(CloudSyncLog.connection_id == connection_id)

            logs = query.order_by(CloudSyncLog.synced_at.desc()).limit(limit).all()
            return [CloudSyncLogWrapper(log) for log in logs]

    def get_sync_statistics(self, connection_id: int = None) -> Dict:
        """Holt Statistiken zur Synchronisation"""
        with get_db() as session:
            query = session.query(CloudSyncLog).filter(
                CloudSyncLog.user_id == self.user_id
            )

            if connection_id:
                query = query.filter(CloudSyncLog.connection_id == connection_id)

            logs = query.all()

            total_synced = len([l for l in logs if l.sync_status == "synced"])
            total_skipped = len([l for l in logs if l.sync_status == "skipped"])
            total_errors = len([l for l in logs if l.sync_status == "error"])
            total_bytes = sum(l.file_size or 0 for l in logs if l.sync_status == "synced")

            return {
                "total_synced": total_synced,
                "total_skipped": total_skipped,
                "total_errors": total_errors,
                "total_bytes": total_bytes,
                "total_mb": round(total_bytes / (1024 * 1024), 2)
            }

    def get_log_file_content(self, connection_id: int, date: str = None) -> str:
        """Liest Inhalt einer Log-Datei"""
        if date is None:
            date = datetime.now().strftime("%Y%m%d")

        log_file = self.log_file_path / f"sync_{connection_id}_{date}.log"

        if log_file.exists():
            with open(log_file, "r", encoding="utf-8") as f:
                return f.read()

        return ""

    # ==================== AUTOMATISCHE SYNCHRONISATION ====================

    def get_connections_due_for_sync(self) -> List[CloudSyncConnection]:
        """Holt Verbindungen die synchronisiert werden müssen"""
        with get_db() as session:
            connections = session.query(CloudSyncConnection).filter(
                CloudSyncConnection.user_id == self.user_id,
                CloudSyncConnection.is_active == True,
                CloudSyncConnection.auto_sync_enabled == True
            ).all()

            due_connections = []
            now = datetime.now()

            for conn in connections:
                if conn.last_sync_at is None:
                    due_connections.append(conn)
                else:
                    next_sync = conn.last_sync_at + timedelta(
                        minutes=conn.sync_interval_minutes or 15
                    )
                    if now >= next_sync:
                        due_connections.append(conn)

            return due_connections

    def sync_all_due(self, process_documents: bool = True) -> Dict[str, Any]:
        """Synchronisiert alle fälligen Verbindungen"""
        results = {
            "connections_synced": 0,
            "total_files_synced": 0,
            "total_files_error": 0,
            "connection_results": []
        }

        due_connections = self.get_connections_due_for_sync()

        for conn in due_connections:
            result = self.sync_connection(conn.id, process_documents)
            results["connections_synced"] += 1
            results["total_files_synced"] += result["files_synced"]
            results["total_files_error"] += result["files_error"]
            results["connection_results"].append({
                "connection_id": conn.id,
                "provider": conn.provider.value,
                "result": result
            })

        return results


# ==================== HELPER FUNKTIONEN ====================

def parse_cloud_link(link: str) -> Tuple[Optional[CloudProvider], Optional[str]]:
    """
    Parsed einen Cloud-Link und gibt Provider und Ordner-ID zurück

    Unterstützte Formate:
    - Dropbox: https://www.dropbox.com/sh/xxx oder https://www.dropbox.com/scl/fo/xxx
    - Google Drive: https://drive.google.com/drive/folders/xxx
    """
    parsed = urlparse(link)

    if "dropbox.com" in parsed.netloc:
        # Dropbox-Link
        path = parsed.path
        return CloudProvider.DROPBOX, path

    elif "drive.google.com" in parsed.netloc:
        # Google Drive-Link
        path_parts = parsed.path.split("/")
        if "folders" in path_parts:
            idx = path_parts.index("folders")
            if idx + 1 < len(path_parts):
                folder_id = path_parts[idx + 1].split("?")[0]
                return CloudProvider.GOOGLE_DRIVE, folder_id

    return None, None
