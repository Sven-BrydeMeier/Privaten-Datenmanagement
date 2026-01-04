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

import re
from bs4 import BeautifulSoup

from database.models import Document, Folder, DocumentStatus
from database.db import get_db
from database.extended_models import (
    CloudSyncConnection, CloudSyncLog, CloudProvider, SyncStatus
)

logger = logging.getLogger(__name__)


# ==================== PUBLIC GOOGLE DRIVE KONSTANTEN ====================
# Direkte Download-URL für öffentliche Dateien
GOOGLE_DRIVE_DOWNLOAD_URL = "https://drive.google.com/uc?export=download&id={file_id}"
# URL für öffentliche Ordner-Ansicht
GOOGLE_DRIVE_FOLDER_URL = "https://drive.google.com/drive/folders/{folder_id}"
# Alternative API für öffentliche Ordner
GOOGLE_DRIVE_PUBLIC_API = "https://www.googleapis.com/drive/v3/files"


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
        self.file_extensions = connection.file_extensions
        self.max_file_size_mb = connection.max_file_size_mb


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

    # ==================== PUBLIC DROPBOX API ====================

    def _dropbox_public_list_folder(self, shared_link: str, path: str = "") -> Dict:
        """
        Listet Dateien in einem öffentlich geteilten Dropbox-Ordner.
        Verwendet die Dropbox API für Shared Links (kein OAuth erforderlich).
        """
        try:
            # Dropbox Shared Link Metadata API
            headers = {
                "Content-Type": "application/json",
            }

            # Erst Metadaten des Shared Links holen
            metadata_response = requests.post(
                "https://api.dropboxapi.com/2/sharing/get_shared_link_metadata",
                headers=headers,
                json={
                    "url": shared_link,
                    "path": path
                },
                timeout=30
            )

            if metadata_response.status_code != 200:
                # Versuche alternative Web-Scraping Methode
                return self._dropbox_public_scrape(shared_link)

            metadata = metadata_response.json()

            # Wenn es ein Ordner ist, Liste den Inhalt
            if metadata.get(".tag") == "folder":
                list_response = requests.post(
                    "https://api.dropboxapi.com/2/files/list_folder",
                    headers=headers,
                    json={
                        "shared_link": {"url": shared_link},
                        "path": path
                    },
                    timeout=30
                )

                if list_response.status_code == 200:
                    data = list_response.json()
                    files = []
                    for entry in data.get("entries", []):
                        files.append({
                            "id": entry.get("id", ""),
                            "name": entry.get("name", ""),
                            "path": entry.get("path_display", ""),
                            "mimeType": "application/vnd.dropbox.folder" if entry.get(".tag") == "folder" else self._guess_mime_type(entry.get("name", "")),
                            "size": entry.get("size", 0)
                        })
                    return {"files": files, "success": True}

            return {"files": [], "success": True, "message": "Kein Ordner oder leer"}

        except Exception as e:
            logger.error(f"Dropbox Public API Fehler: {e}")
            return self._dropbox_public_scrape(shared_link)

    def _dropbox_public_scrape(self, shared_link: str) -> Dict:
        """
        Fallback: Web-Scraping für öffentliche Dropbox-Ordner.
        """
        try:
            # Füge ?dl=0 hinzu für Web-Ansicht
            if "?dl=" not in shared_link:
                shared_link = shared_link.rstrip("/") + "?dl=0"

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            }

            response = requests.get(shared_link, headers=headers, timeout=30, allow_redirects=True)

            if response.status_code != 200:
                return {"error": f"HTTP {response.status_code}", "success": False}

            html = response.text
            files = []
            seen = set()

            # Dropbox verwendet JSON-Daten im HTML
            # Suche nach Datei-Einträgen
            import re

            # Pattern für Dropbox Datei-Einträge
            # Format: {"filename":"xxx","bytes":123,"icon":"page_white_acrobat",...}
            file_pattern = r'"filename"\s*:\s*"([^"]+)"[^}]*"bytes"\s*:\s*(\d+)'
            for match in re.finditer(file_pattern, html):
                name = match.group(1)
                size = int(match.group(2))
                if name not in seen:
                    seen.add(name)
                    files.append({
                        "id": name,
                        "name": name,
                        "path": name,
                        "mimeType": self._guess_mime_type(name),
                        "size": size
                    })

            # Alternative: Suche nach sl-preview Links
            preview_pattern = r'href="(/previews/[^"]+)"[^>]*>([^<]+)<'
            for match in re.finditer(preview_pattern, html):
                name = match.group(2).strip()
                if name and name not in seen and len(name) > 2:
                    seen.add(name)
                    files.append({
                        "id": name,
                        "name": name,
                        "path": name,
                        "mimeType": self._guess_mime_type(name),
                        "size": 0
                    })

            if files:
                logger.info(f"Dropbox Scraping: {len(files)} Dateien gefunden")
                return {"files": files, "success": True}
            else:
                logger.warning("Dropbox Scraping: Keine Dateien gefunden")
                return {"files": [], "success": True}

        except Exception as e:
            logger.error(f"Dropbox Scraping Fehler: {e}")
            return {"error": str(e), "success": False}

    def _dropbox_public_download_file(self, shared_link: str, path: str) -> Tuple[bytes, bool]:
        """
        Lädt eine Datei von einem öffentlich geteilten Dropbox-Ordner herunter.
        """
        try:
            # Dropbox Direct Download Link
            download_url = shared_link.replace("?dl=0", "?dl=1").replace("www.dropbox.com", "dl.dropboxusercontent.com")

            if path:
                # Wenn Pfad angegeben, füge ihn hinzu
                download_url = f"{download_url}&path={path}"

            response = requests.get(download_url, timeout=60, allow_redirects=True)

            if response.status_code == 200:
                return response.content, True
            else:
                logger.error(f"Dropbox Download fehlgeschlagen: {response.status_code}")
                return b'', False

        except Exception as e:
            logger.error(f"Dropbox Download Fehler: {e}")
            return b'', False

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
        """Extrahiert Folder-ID aus Google Drive Link oder Text"""
        import re

        if not link:
            return None

        # Format: https://drive.google.com/drive/folders/FOLDER_ID
        # oder: https://drive.google.com/drive/u/0/folders/FOLDER_ID
        parsed = urlparse(link)
        path_parts = parsed.path.split("/")

        try:
            if "folders" in path_parts:
                idx = path_parts.index("folders")
                if idx + 1 < len(path_parts):
                    folder_id = path_parts[idx + 1].split("?")[0]
                    if len(folder_id) > 10:
                        logger.info(f"Folder-ID aus URL extrahiert: {folder_id}")
                        return folder_id
        except:
            pass

        # Fallback: Suche nach "Folder-ID: XXXX" im Text (für Copy-Paste Fehler)
        folder_id_match = re.search(r'Folder-ID:\s*([a-zA-Z0-9_-]{20,})', link)
        if folder_id_match:
            folder_id = folder_id_match.group(1)
            logger.info(f"Folder-ID aus 'Folder-ID:' Pattern extrahiert: {folder_id}")
            return folder_id

        # Fallback: Suche nach /folders/XXXX im Text
        folders_match = re.search(r'/folders/([a-zA-Z0-9_-]{20,})', link)
        if folders_match:
            folder_id = folders_match.group(1)
            logger.info(f"Folder-ID aus '/folders/' Pattern extrahiert: {folder_id}")
            return folder_id

        # Fallback: Wenn der String selbst wie eine Folder-ID aussieht
        if re.match(r'^[a-zA-Z0-9_-]{20,}$', link.strip()):
            folder_id = link.strip()
            logger.info(f"String direkt als Folder-ID verwendet: {folder_id}")
            return folder_id

        logger.warning(f"Keine Folder-ID gefunden in: {link[:100]}...")
        return None

    # ==================== PUBLIC GOOGLE DRIVE API ====================

    def _get_google_api_key(self) -> Optional[str]:
        """Holt den Google API Key aus Streamlit Secrets oder Umgebungsvariablen"""
        # Versuche Streamlit Secrets
        try:
            import streamlit as st
            if hasattr(st, 'secrets'):
                # Versuche verschiedene Formate
                if 'GOOGLE_API_KEY' in st.secrets:
                    return st.secrets['GOOGLE_API_KEY']
                if 'google' in st.secrets and 'api_key' in st.secrets['google']:
                    return st.secrets['google']['api_key']
        except Exception:
            pass

        # Fallback auf Umgebungsvariable
        return os.environ.get('GOOGLE_API_KEY')

    def _google_api_list_folder(self, folder_id: str, api_key: str) -> Dict:
        """
        Listet Dateien über die offizielle Google Drive API.
        Zuverlässigste Methode wenn ein API Key verfügbar ist.
        """
        try:
            items = []
            token = None
            BASE = "https://www.googleapis.com/drive/v3/files"

            while True:
                params = {
                    "q": f"'{folder_id}' in parents and trashed=false",
                    "fields": "nextPageToken, files(id,name,mimeType,size)",
                    "pageSize": 1000,
                    "supportsAllDrives": "true",
                    "includeItemsFromAllDrives": "true",
                    "key": api_key,
                }
                if token:
                    params["pageToken"] = token

                response = requests.get(BASE, params=params, timeout=30)

                if response.status_code == 403:
                    logger.warning("Google API: Zugriff verweigert (403) - Key ungültig oder Ordner nicht öffentlich")
                    return {"error": "API Key ungültig oder Ordner nicht öffentlich", "success": False}
                elif response.status_code == 404:
                    logger.warning("Google API: Ordner nicht gefunden (404)")
                    return {"error": "Ordner nicht gefunden", "success": False}

                response.raise_for_status()
                data = response.json()

                for file_info in data.get("files", []):
                    items.append({
                        "id": file_info.get("id"),
                        "name": file_info.get("name"),
                        "mimeType": file_info.get("mimeType", "application/octet-stream"),
                        "size": int(file_info.get("size", 0)) if file_info.get("size") else 0
                    })

                token = data.get("nextPageToken")
                if not token:
                    break

            logger.info(f"Google API: {len(items)} Dateien/Ordner gefunden in {folder_id}")
            return {"files": items, "success": True}

        except requests.exceptions.RequestException as e:
            logger.error(f"Google API Fehler: {e}")
            return {"error": str(e), "success": False}

    def _google_public_list_folder(self, folder_id: str) -> Dict:
        """
        Listet Dateien in einem öffentlich freigegebenen Google Drive-Ordner.
        Verwendet mehrere Methoden in Reihenfolge der Zuverlässigkeit.
        """
        logger.info(f"_google_public_list_folder aufgerufen für: {folder_id}")

        # Methode 0: Versuche die offizielle Google Drive API (beste Methode)
        api_key = self._get_google_api_key()
        logger.info(f"API Key verfügbar: {bool(api_key)}")
        if api_key:
            logger.info(f"Verwende Google Drive API mit API Key: {api_key[:10]}...")
            api_result = self._google_api_list_folder(folder_id, api_key)
            logger.info(f"API Ergebnis: success={api_result.get('success')}, files={len(api_result.get('files', []))}")
            if api_result.get("success") and api_result.get("files") is not None:
                return api_result
            logger.warning(f"API-Methode fehlgeschlagen: {api_result.get('error')}, versuche Fallback...")

        # Methode 1: Versuche die Embed-API (zuverlässiger als Web-Scraping)
        embed_result = self._google_public_list_folder_embed(folder_id)
        if embed_result.get("success") and embed_result.get("files"):
            return embed_result

        # Methode 2: Fallback auf Web-Scraping der öffentlichen Seite
        return self._google_public_list_folder_scrape(folder_id)

    def _google_public_list_folder_embed(self, folder_id: str) -> Dict:
        """
        Listet Dateien über die Google Drive Embed-Ansicht.
        Diese Methode ist zuverlässiger, da sie ein einfacheres HTML-Format verwendet.
        """
        try:
            # Die Embed-URL zeigt eine vereinfachte Ansicht
            embed_url = f"https://drive.google.com/embeddedfolderview?id={folder_id}#list"

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }

            response = requests.get(embed_url, headers=headers, timeout=30, allow_redirects=True)

            if response.status_code != 200:
                return {"error": f"HTTP {response.status_code}", "success": False}

            html_content = response.text
            files = []
            seen_ids = set()

            # Die Embed-Ansicht hat ein einfacheres Format
            soup = BeautifulSoup(html_content, 'html.parser')

            # Suche nach flip-entry Elementen (Dateien und Ordner)
            entries = soup.find_all(['div', 'tr'], class_=re.compile(r'flip-entry|goog-inline-block'))

            for entry in entries:
                # Finde die ID
                file_id = entry.get('id', '')
                if not file_id or len(file_id) < 20:
                    # Suche in Links
                    link = entry.find('a', href=True)
                    if link:
                        href = link.get('href', '')
                        # Extrahiere ID aus verschiedenen URL-Formaten
                        id_match = re.search(r'(?:id=|/d/|folders/)([a-zA-Z0-9_-]{20,})', href)
                        if id_match:
                            file_id = id_match.group(1)

                if not file_id or len(file_id) < 20 or file_id in seen_ids:
                    continue

                # Finde den Namen
                name_elem = entry.find(class_=re.compile(r'flip-entry-title|entry-title'))
                if name_elem:
                    name = name_elem.get_text(strip=True)
                else:
                    name = entry.get_text(strip=True)[:100]  # Fallback

                if not name or len(name) < 1:
                    continue

                seen_ids.add(file_id)

                # Bestimme den Typ
                is_folder = 'folder' in entry.get('class', []) or 'folder' in str(entry).lower()
                mime_type = "application/vnd.google-apps.folder" if is_folder else self._guess_mime_type(name)

                files.append({
                    "id": file_id,
                    "name": name,
                    "mimeType": mime_type,
                    "size": 0
                })

            # Alternative: Suche nach Links direkt
            if not files:
                all_links = soup.find_all('a', href=re.compile(r'(file/d/|folders/|id=)'))
                for link in all_links:
                    href = link.get('href', '')
                    id_match = re.search(r'(?:id=|/d/|folders/)([a-zA-Z0-9_-]{20,})', href)
                    if id_match:
                        file_id = id_match.group(1)
                        if file_id not in seen_ids:
                            name = link.get_text(strip=True) or f"item_{file_id[:8]}"
                            if len(name) > 1:
                                seen_ids.add(file_id)
                                is_folder = 'folders/' in href
                                files.append({
                                    "id": file_id,
                                    "name": name,
                                    "mimeType": "application/vnd.google-apps.folder" if is_folder else self._guess_mime_type(name),
                                    "size": 0
                                })

            if files:
                logger.info(f"Embed-Methode: {len(files)} Dateien/Ordner gefunden")
                return {"files": files, "success": True}

            return {"files": [], "success": False}

        except Exception as e:
            logger.warning(f"Embed-Methode fehlgeschlagen: {e}")
            return {"error": str(e), "success": False}

    def _google_public_list_folder_scrape(self, folder_id: str) -> Dict:
        """
        Listet Dateien via Web-Scraping der öffentlichen Ordner-Seite.
        Fallback-Methode wenn Embed nicht funktioniert.
        """
        try:
            # Versuche, die öffentliche Ordnerseite zu laden
            url = GOOGLE_DRIVE_FOLDER_URL.format(folder_id=folder_id)
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
            }

            response = requests.get(url, headers=headers, timeout=30, allow_redirects=True)

            if response.status_code != 200:
                return {"error": f"HTTP {response.status_code}: Ordner nicht zugänglich"}

            response_text = response.text
            response_text_lower = response_text.lower()

            # Prüfe ob Ordner existiert
            if 'sorry, the file you have requested does not exist' in response_text_lower:
                return {"error": "Ordner nicht gefunden. Bitte prüfen Sie die URL."}

            # Prüfe auf explizite Zugriffsverweigerung
            if 'you need access' in response_text_lower or 'zugriff anfordern' in response_text_lower:
                return {"error": "Keine Berechtigung. Bitte den Ordner öffentlich freigeben."}

            # ZUERST versuchen, Dateien zu parsen - "sign in" kann auch auf öffentlichen Seiten erscheinen
            files = self._parse_google_drive_folder_page(response_text)

            if not files:
                # Alternative Methode: Versuche JSON-Daten aus der Seite zu extrahieren
                files = self._extract_drive_data_from_html(response_text)

            # Wenn Dateien gefunden wurden, ist der Ordner zugänglich
            if files:
                return {"files": files, "success": True}

            # Keine Dateien gefunden - jetzt prüfen ob es ein Zugriffsproblem ist
            # Prüfe auf Weiterleitung zur Anmeldeseite (URL-basiert, nicht content-basiert)
            if 'accounts.google.com' in response.url:
                return {
                    "error": "Ordner erfordert Anmeldung. Bitte stellen Sie sicher, dass der Ordner öffentlich freigegeben ist: "
                             "Rechtsklick → Freigeben → 'Jeder mit dem Link' auswählen"
                }

            # Prüfe auf spezifische Fehlermeldungen die auf private Ordner hindeuten
            private_indicators = [
                'request access',
                'zugriff beantragen',
                'not have permission',
                'keine berechtigung',
                'private folder',
                'privater ordner'
            ]

            if any(indicator in response_text_lower for indicator in private_indicators):
                return {
                    "error": "Ordner ist privat. Bitte den Ordner öffentlich freigeben: "
                             "Rechtsklick → Freigeben → 'Jeder mit dem Link' auswählen"
                }

            # Ordner scheint leer zu sein oder Format nicht erkannt
            logger.warning(f"Keine Dateien gefunden in Ordner {folder_id}. "
                          f"Möglicherweise ist der Ordner leer oder das Format hat sich geändert.")

            # Speichere HTML für Debugging (nur in Dev-Umgebung)
            debug_path = Path("data/debug")
            debug_path.mkdir(parents=True, exist_ok=True)
            debug_file = debug_path / f"gdrive_debug_{folder_id[:10]}.html"
            try:
                with open(debug_file, "w", encoding="utf-8") as f:
                    f.write(response_text[:50000])  # Nur die ersten 50KB
                logger.info(f"Debug-HTML gespeichert unter: {debug_file}")
            except Exception:
                pass

            return {"files": [], "success": True}

        except requests.exceptions.Timeout:
            return {"error": "Zeitüberschreitung beim Laden des Ordners"}
        except requests.exceptions.RequestException as e:
            return {"error": f"Netzwerkfehler: {str(e)}"}
        except Exception as e:
            logger.error(f"Fehler beim Laden des öffentlichen Ordners: {e}")
            return {"error": f"Fehler: {str(e)}"}

    def _parse_google_drive_folder_page(self, html_content: str) -> List[Dict]:
        """
        Parsed die Google Drive Ordnerseite und extrahiert Datei- und Ordner-Informationen.
        """
        files = []

        try:
            soup = BeautifulSoup(html_content, 'html.parser')

            # Methode 1: Suche nach Links mit file/d/ (Dateien)
            file_links = soup.find_all('a', href=re.compile(r'(file/d/|open\?id=|uc\?id=)'))

            for link in file_links:
                href = link.get('href', '')
                file_id = None

                if 'file/d/' in href:
                    match = re.search(r'file/d/([a-zA-Z0-9_-]+)', href)
                    if match:
                        file_id = match.group(1)
                elif 'id=' in href:
                    match = re.search(r'id=([a-zA-Z0-9_-]+)', href)
                    if match:
                        file_id = match.group(1)

                if file_id and file_id not in [f.get('id') for f in files]:
                    name = link.get_text(strip=True) or f"file_{file_id}"
                    files.append({
                        "id": file_id,
                        "name": name,
                        "mimeType": self._guess_mime_type(name),
                        "size": 0
                    })

            # Methode 2: Suche nach Links mit folders/ (Unterordner)
            # Ignoriere Navigation/UI-Links
            ignore_names = ['anmelden', 'sign in', 'login', 'signin', 'abmelden',
                           'sign out', 'logout', 'hilfe', 'help', 'support',
                           'drive', 'google', 'home', 'settings', 'einstellungen']

            folder_links = soup.find_all('a', href=re.compile(r'folders/'))
            for link in folder_links:
                href = link.get('href', '')
                match = re.search(r'folders/([a-zA-Z0-9_-]+)', href)
                if match:
                    folder_id = match.group(1)
                    # Google Drive IDs sind typischerweise 25+ Zeichen lang
                    if len(folder_id) < 20:
                        continue
                    if folder_id not in [f.get('id') for f in files]:
                        name = link.get_text(strip=True) or f"folder_{folder_id}"
                        # Filtere UI/Navigation-Elemente aus
                        name_lower = name.lower()
                        if any(ignore in name_lower for ignore in ignore_names):
                            continue
                        # Nur hinzufügen wenn es nach einem echten Ordnernamen aussieht
                        if name and len(name) > 1 and not name.startswith('folder_'):
                            files.append({
                                "id": folder_id,
                                "name": name,
                                "mimeType": "application/vnd.google-apps.folder",
                                "size": 0
                            })

            # Methode 3: Suche nach data-id Attributen
            elements_with_data_id = soup.find_all(attrs={"data-id": True})
            for elem in elements_with_data_id:
                file_id = elem.get('data-id')
                # Validiere ID-Länge (Google IDs sind 20+ Zeichen)
                if not file_id or len(file_id) < 20:
                    continue
                if file_id not in [f.get('id') for f in files]:
                    name = elem.get_text(strip=True) or elem.get('data-tooltip', '') or f"item_{file_id}"
                    # Filtere UI-Elemente
                    name_lower = name.lower()
                    if any(ignore in name_lower for ignore in ignore_names):
                        continue
                    # Bestimme ob Ordner oder Datei
                    is_folder = 'folder' in elem.get('class', []) or not '.' in name
                    files.append({
                        "id": file_id,
                        "name": name,
                        "mimeType": "application/vnd.google-apps.folder" if is_folder else self._guess_mime_type(name),
                        "size": 0
                    })

        except Exception as e:
            logger.error(f"Fehler beim Parsen der Drive-Seite: {e}")

        return files

    def _extract_drive_data_from_html(self, html_content: str) -> List[Dict]:
        """
        Extrahiert Datei-Informationen aus eingebetteten JSON-Daten in der Google Drive Seite.
        Verwendet mehrere Strategien, da Google das Format regelmäßig ändert.
        """
        files = []
        seen_ids = set()

        def is_valid_name(name):
            """Prüft ob ein Name ein gültiger Datei/Ordnername ist"""
            if not name or len(name) < 2 or len(name) > 200:
                return False
            # Filtere URLs, JS-Code und System-Strings
            invalid = ['http', 'https', 'clients', '.com', '.google',
                       'sign in', 'anmelden', 'null', 'undefined',
                       'function', 'return', 'var ', 'const ', 'window.',
                       '();', '{}', 'prototype', 'throw', 'catch',
                       'script', 'style', 'meta', 'link']
            name_lower = name.lower()
            if any(inv in name_lower for inv in invalid):
                return False
            # Muss mindestens einen Buchstaben enthalten
            if not re.search(r'[a-zA-ZäöüÄÖÜß]', name):
                return False
            return True

        def is_file_extension(name):
            """Prüft ob der Name eine Dateiendung hat"""
            return bool(re.search(r'\.\w{2,5}$', name))

        try:
            # ============ NEUE STRATEGIE: Suche nach Google's Datenstrukturen ============

            # Google Drive verwendet oft dieses Format in Script-Tags:
            # null,["FILE_ID","FILENAME",["MIMETYPE"],...
            # oder: ["FILE_ID",["PARENT_ID","FILENAME",...

            # Strategie 0: Suche nach MIME-Type-Zuordnungen im HTML
            # Format: "FILE_ID"... "application/vnd.google-apps.folder" oder andere MIME-Types
            mime_patterns = [
                (r'"([a-zA-Z0-9_-]{25,})"[^"]{0,200}"application/vnd\.google-apps\.folder"', 'folder'),
                (r'"([a-zA-Z0-9_-]{25,})"[^"]{0,200}"application/pdf"', 'application/pdf'),
                (r'"([a-zA-Z0-9_-]{25,})"[^"]{0,200}"image/(?:jpeg|png|gif)"', 'image'),
            ]

            id_to_type = {}
            for pattern, file_type in mime_patterns:
                for match in re.finditer(pattern, html_content):
                    file_id = match.group(1)
                    if file_id not in id_to_type:
                        id_to_type[file_id] = file_type

            # Strategie 1: Suche nach Dateinamen mit Erweiterungen
            ext_pattern = r'"([a-zA-Z0-9_-]{20,})"[,\]\[null"]*"([^"]+\.(?:pdf|jpg|jpeg|png|gif|doc|docx|xls|xlsx|ppt|pptx|txt|csv|zip|PDF|JPG|PNG|DOC|XLS))"'
            for file_id, name in re.findall(ext_pattern, html_content):
                if file_id not in seen_ids and is_valid_name(name):
                    seen_ids.add(file_id)
                    files.append({
                        "id": file_id,
                        "name": name,
                        "mimeType": self._guess_mime_type(name),
                        "size": 0
                    })

            # Strategie 2: Name mit Erweiterung gefolgt von ID (umgekehrtes Format)
            rev_pattern = r'"([^"]+\.(?:pdf|jpg|jpeg|png|doc|docx|xls|xlsx|txt|PDF|JPG|PNG))"[,\]\[null"]*"([a-zA-Z0-9_-]{20,})"'
            for name, file_id in re.findall(rev_pattern, html_content):
                if file_id not in seen_ids and is_valid_name(name):
                    seen_ids.add(file_id)
                    files.append({
                        "id": file_id,
                        "name": name,
                        "mimeType": self._guess_mime_type(name),
                        "size": 0
                    })

            # Strategie 3: Suche alle .pdf Erwähnungen ZUERST (vor Ordnern)
            pdf_names = re.findall(r'"([^"]{3,80}\.pdf)"', html_content, re.IGNORECASE)
            for name in pdf_names:
                if is_valid_name(name) and name not in [f.get('name') for f in files]:
                    # Suche ID in der Nähe
                    idx = html_content.find(f'"{name}"')
                    if idx >= 0:
                        context = html_content[max(0,idx-150):idx+150]
                        id_match = re.search(r'"([a-zA-Z0-9_-]{25,})"', context)
                        if id_match:
                            file_id = id_match.group(1)
                            if file_id not in seen_ids:
                                seen_ids.add(file_id)
                                files.append({
                                    "id": file_id,
                                    "name": name,
                                    "mimeType": "application/pdf",
                                    "size": 0
                                })

            # Strategie 4: Suche nach data-id Attributen mit Namen in aria-label/title
            for match in re.finditer(r'data-id="([a-zA-Z0-9_-]{20,})"', html_content):
                file_id = match.group(1)
                if file_id not in seen_ids:
                    # Hole größeren Kontext um das Attribut
                    start = max(0, match.start() - 500)
                    end = min(len(html_content), match.end() + 500)
                    context = html_content[start:end]

                    # Suche nach aria-label, data-tooltip oder title
                    label = re.search(r'(?:aria-label|data-tooltip|title)="([^"]+)"', context)
                    if label and is_valid_name(label.group(1)):
                        name = label.group(1)
                        seen_ids.add(file_id)

                        # Bestimme Typ basierend auf MIME-Type-Map oder Dateiendung
                        if file_id in id_to_type:
                            if id_to_type[file_id] == 'folder':
                                mime_type = "application/vnd.google-apps.folder"
                            else:
                                mime_type = id_to_type[file_id]
                        elif is_file_extension(name):
                            mime_type = self._guess_mime_type(name)
                        else:
                            mime_type = "application/vnd.google-apps.folder"

                        files.append({
                            "id": file_id,
                            "name": name,
                            "mimeType": mime_type,
                            "size": 0
                        })

            # Strategie 5: Kompakte JSON-Struktur ["ID","Name"]
            compact_pattern = r'\["([a-zA-Z0-9_-]{25,})",\s*"([^"]{2,100})"'
            for file_id, name in re.findall(compact_pattern, html_content):
                if file_id not in seen_ids and is_valid_name(name):
                    # Zusätzliche Prüfung: Name sollte keine JS-Syntax sein
                    if not re.match(r'^[a-z]+\(|^[A-Z_]+$|^\d+$', name):
                        seen_ids.add(file_id)

                        # Bestimme Typ
                        if file_id in id_to_type:
                            if id_to_type[file_id] == 'folder':
                                mime_type = "application/vnd.google-apps.folder"
                            else:
                                mime_type = id_to_type[file_id]
                        elif is_file_extension(name):
                            mime_type = self._guess_mime_type(name)
                        else:
                            mime_type = "application/vnd.google-apps.folder"

                        files.append({
                            "id": file_id,
                            "name": name,
                            "mimeType": mime_type,
                            "size": 0
                        })

            # Strategie 6: Suche nach Ordner-Links in href
            folder_pattern = r'href="[^"]*?/folders/([a-zA-Z0-9_-]{20,})[^"]*"[^>]*>([^<]+)<'
            for file_id, name in re.findall(folder_pattern, html_content):
                name = name.strip()
                if file_id not in seen_ids and is_valid_name(name):
                    seen_ids.add(file_id)
                    files.append({
                        "id": file_id,
                        "name": name,
                        "mimeType": "application/vnd.google-apps.folder",
                        "size": 0
                    })

            # Logge Ergebnis für Debugging
            if files:
                folders = len([f for f in files if f.get('mimeType') == 'application/vnd.google-apps.folder'])
                docs = len(files) - folders
                logger.info(f"Gefunden: {len(files)} Einträge ({folders} Ordner, {docs} Dateien) via HTML-Extraktion")
            else:
                logger.warning(f"Keine Dateien via HTML-Extraktion gefunden. HTML-Länge: {len(html_content)}")

        except Exception as e:
            logger.error(f"Fehler beim Extrahieren von Drive-Daten: {e}")

        return files

    def _extract_from_json(self, data, files: List[Dict], seen_ids: set, depth: int = 0):
        """Rekursive Extraktion von Dateien aus JSON-Daten"""
        if depth > 10:  # Maximale Rekursionstiefe
            return

        if isinstance(data, dict):
            # Prüfe ob dieses Dict eine Datei/Ordner-Info enthält
            if 'id' in data and 'name' in data:
                file_id = data['id']
                name = data['name']
                if file_id not in seen_ids and len(file_id) >= 20:
                    seen_ids.add(file_id)
                    mime_type = data.get('mimeType', self._guess_mime_type(name))
                    files.append({
                        "id": file_id,
                        "name": name,
                        "mimeType": mime_type,
                        "size": data.get('size', 0)
                    })
            # Rekursiv durch alle Werte
            for value in data.values():
                self._extract_from_json(value, files, seen_ids, depth + 1)

        elif isinstance(data, list):
            for item in data:
                self._extract_from_json(item, files, seen_ids, depth + 1)

    def _guess_mime_type(self, filename: str) -> str:
        """Schätzt MIME-Type basierend auf Dateinamen"""
        ext = Path(filename).suffix.lower() if '.' in filename else ''
        mime_map = {
            '.pdf': 'application/pdf',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.doc': 'application/msword',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.xls': 'application/vnd.ms-excel',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.txt': 'text/plain',
            '.csv': 'text/csv'
        }
        return mime_map.get(ext, 'application/octet-stream')

    def _google_public_download_file(self, file_id: str) -> Tuple[bytes, bool]:
        """
        Lädt eine Datei von einem öffentlichen Google Drive herunter.

        Returns:
            Tuple von (file_content, success)
        """
        try:
            # Direkte Download-URL
            download_url = GOOGLE_DRIVE_DOWNLOAD_URL.format(file_id=file_id)

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }

            # Erste Anfrage - kann eine Bestätigungsseite zurückgeben
            session = requests.Session()
            response = session.get(download_url, headers=headers, stream=True, timeout=60)

            # Prüfe auf Virus-Scan-Warnung (große Dateien)
            if 'download_warning' in response.url or b'confirm=' in response.content[:1000]:
                # Extrahiere Bestätigungs-Token
                confirm_token = None

                for key, value in response.cookies.items():
                    if key.startswith('download_warning'):
                        confirm_token = value
                        break

                if not confirm_token:
                    # Versuche Token aus HTML zu extrahieren
                    match = re.search(r'confirm=([a-zA-Z0-9_-]+)', response.text)
                    if match:
                        confirm_token = match.group(1)

                if confirm_token:
                    # Zweite Anfrage mit Bestätigung
                    confirm_url = f"{download_url}&confirm={confirm_token}"
                    response = session.get(confirm_url, headers=headers, stream=True, timeout=60)

            # Prüfe ob Download erfolgreich
            content_type = response.headers.get('Content-Type', '')

            if 'text/html' in content_type:
                # Wahrscheinlich eine Fehlerseite
                if 'Access denied' in response.text or 'denied' in response.text.lower():
                    logger.warning(f"Zugriff verweigert für Datei {file_id}")
                    return b'', False
                elif 'quota' in response.text.lower():
                    logger.warning(f"Download-Quota überschritten für Datei {file_id}")
                    return b'', False

            # Lade vollständigen Inhalt
            content = response.content

            if len(content) == 0:
                return b'', False

            return content, True

        except requests.exceptions.Timeout:
            logger.error(f"Timeout beim Download von Datei {file_id}")
            return b'', False
        except Exception as e:
            logger.error(f"Fehler beim Download von Datei {file_id}: {e}")
            return b'', False

    def _collect_dropbox_files_public(self, connection: CloudSyncConnection,
                                       session) -> List[Dict]:
        """
        Sammelt Dateien aus einem öffentlich geteilten Dropbox-Ordner.
        """
        files = []
        shared_link = connection.remote_folder_path

        if not shared_link:
            logger.error("Kein Dropbox Shared Link angegeben")
            return files

        logger.info(f"Lade öffentlichen Dropbox-Ordner: {shared_link}")

        # Lade Ordnerinhalt
        response = self._dropbox_public_list_folder(shared_link)

        if "error" in response:
            logger.error(f"Fehler beim Laden des Dropbox-Ordners: {response['error']}")
            return files

        file_list = response.get("files", [])
        logger.info(f"Gefunden: {len(file_list)} Einträge in Dropbox-Ordner")

        for file_info in file_list:
            mime_type = file_info.get("mimeType", "")
            filename = file_info.get("name", "")
            file_path = file_info.get("path", filename)

            # Ordner überspringen (keine rekursive Unterstützung für öffentliche Dropbox)
            if 'folder' in mime_type.lower():
                logger.info(f"Unterordner übersprungen: {filename}")
                continue

            ext = Path(filename).suffix.lower()

            # Dateiendung prüfen
            if connection.file_extensions and ext and ext not in connection.file_extensions:
                continue

            # Prüfen ob bereits synchronisiert
            from database.extended_models import CloudSyncLog
            existing_log = session.query(CloudSyncLog).filter(
                CloudSyncLog.connection_id == connection.id,
                CloudSyncLog.remote_file_id == file_path
            ).first()

            if existing_log:
                continue

            files.append({
                "name": filename,
                "path": file_path,
                "id": file_path,
                "size": file_info.get("size", 0),
                "hash": None,
                "modified": None,
                "mime_type": mime_type,
                "provider": "dropbox_public",
                "shared_link": shared_link
            })

            logger.info(f"Datei gefunden: {filename}")

        logger.info(f"Insgesamt {len(files)} Dateien in öffentlichem Dropbox-Ordner gefunden")
        return files

    def _collect_google_drive_files_public(self, connection: CloudSyncConnection,
                                            session) -> List[Dict]:
        """
        Sammelt Dateien aus einem öffentlichen Google Drive-Ordner.
        Durchsucht REKURSIV alle Unterordner.
        """
        files = []

        # Versuche Folder-ID zu extrahieren
        folder_id = None

        logger.info(f"Google Drive Public: remote_folder_id={connection.remote_folder_id}, remote_folder_path={connection.remote_folder_path}")

        # Prüfe ob remote_folder_id eine URL ist oder eine echte ID
        if connection.remote_folder_id:
            if 'drive.google.com' in connection.remote_folder_id:
                # Es ist eine URL, extrahiere die ID
                folder_id = self._google_get_folder_id_from_link(connection.remote_folder_id)
                logger.info(f"Extrahierte Folder-ID aus remote_folder_id URL: {folder_id}")
            elif len(connection.remote_folder_id) > 10 and not connection.remote_folder_id.startswith('http'):
                # Sieht wie eine echte Folder-ID aus
                folder_id = connection.remote_folder_id
                logger.info(f"Verwende remote_folder_id als Folder-ID: {folder_id}")

        # Fallback auf remote_folder_path
        if not folder_id and connection.remote_folder_path:
            folder_id = self._google_get_folder_id_from_link(connection.remote_folder_path)
            logger.info(f"Extrahierte Folder-ID aus remote_folder_path: {folder_id}")

        if not folder_id:
            logger.error("Keine Ordner-ID gefunden - weder in remote_folder_id noch remote_folder_path")
            return files

        logger.info(f"Starte rekursive Sammlung mit Folder-ID: {folder_id}")

        # Rekursiv alle Dateien sammeln
        self._collect_public_folder_recursive(
            folder_id=folder_id,
            folder_path="",  # Root-Ordner
            connection=connection,
            session=session,
            files=files
        )

        logger.info(f"Insgesamt {len(files)} Dateien in öffentlichem Ordner gefunden")
        return files

    def _collect_public_folder_recursive(self, folder_id: str, folder_path: str,
                                          connection: CloudSyncConnection,
                                          session, files: List[Dict],
                                          depth: int = 0, max_depth: int = 50):
        """
        Sammelt rekursiv Dateien aus öffentlichen Google Drive Ordnern.

        Args:
            folder_id: Google Drive Ordner-ID
            folder_path: Aktueller Pfad für die Kategorisierung (z.B. "Versicherung/Leben")
            connection: CloudSyncConnection
            session: DB Session
            files: Liste zum Sammeln der Dateien
            depth: Aktuelle Rekursionstiefe
            max_depth: Maximale Rekursionstiefe (Standard: 50)
        """
        if depth > max_depth:
            logger.debug(f"Ordnertiefe {depth} erreicht bei: {folder_path}")
            return

        logger.info(f"Durchsuche Ordner: {folder_path or 'Root'} (ID: {folder_id})")

        # Lade Ordnerinhalt
        response = self._google_public_list_folder(folder_id)

        if "error" in response:
            logger.error(f"Fehler beim Laden des Ordners {folder_path}: {response['error']}")
            return

        file_list = response.get("files", [])
        logger.info(f"Gefunden: {len(file_list)} Einträge in {folder_path or 'Root'}")

        for file_info in file_list:
            mime_type = file_info.get("mimeType", "")
            filename = file_info.get("name", "")
            file_id = file_info.get("id", "")

            logger.debug(f"Prüfe: {filename} (MIME: {mime_type}, ID: {file_id})")

            # Unterordner rekursiv durchsuchen
            is_folder = mime_type == "application/vnd.google-apps.folder"
            has_no_extension = '.' not in filename
            if is_folder or (has_no_extension and not mime_type.startswith("application/")):
                # Könnte ein Ordner sein - versuche rekursiv zu laden
                subfolder_path = f"{folder_path}/{filename}" if folder_path else filename
                logger.info(f"Unterordner gefunden: {subfolder_path}")

                self._collect_public_folder_recursive(
                    folder_id=file_id,
                    folder_path=subfolder_path,
                    connection=connection,
                    session=session,
                    files=files,
                    depth=depth + 1,
                    max_depth=max_depth
                )
                continue

            # Google Docs/Sheets etc. überspringen
            if mime_type.startswith("application/vnd.google-apps"):
                logger.debug(f"Überspringe Google App-Datei: {filename} ({mime_type})")
                continue

            ext = Path(filename).suffix.lower()

            # Dateiendung prüfen
            if connection.file_extensions and ext and ext not in connection.file_extensions:
                logger.debug(f"Überspringe wegen Dateiendung: {filename} ({ext} nicht in {connection.file_extensions})")
                continue

            # Prüfen ob bereits synchronisiert
            existing_log = session.query(CloudSyncLog).filter(
                CloudSyncLog.connection_id == connection.id,
                CloudSyncLog.remote_file_id == file_id
            ).first()

            if existing_log:
                logger.debug(f"Überspringe bereits synchronisiert: {filename}")
                continue

            logger.info(f"Datei erkannt (wird importiert): {filename} ({mime_type})")

            # Vollständigen Pfad für die Datei erstellen
            full_path = f"{folder_path}/{filename}" if folder_path else filename

            files.append({
                "name": filename,
                "path": full_path,  # WICHTIG: Vollständiger Pfad für Kategorisierung
                "id": file_id,
                "size": file_info.get("size", 0),
                "hash": None,
                "modified": None,
                "mime_type": mime_type,
                "provider": "google_drive_public",
                "source_folder": folder_path  # Quellordner für Dokumenten-Intelligenz
            })

            logger.info(f"Datei gefunden: {full_path}")

        return files

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

            # Prüfen ob Access Token vorhanden (außer bei öffentlichen Ordnern)
            is_public_google_drive = (
                connection.provider == CloudProvider.GOOGLE_DRIVE and
                not connection.access_token and
                (connection.remote_folder_id or connection.remote_folder_path)
            )

            is_public_dropbox = (
                connection.provider == CloudProvider.DROPBOX and
                not connection.access_token and
                connection.remote_folder_path and
                ('dropbox.com' in connection.remote_folder_path)
            )

            if not connection.access_token and not is_public_google_drive and not is_public_dropbox:
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

                try:
                    if connection.provider == CloudProvider.DROPBOX:
                        # Öffentliche oder authentifizierte Dropbox
                        if is_public_dropbox:
                            files_to_sync = self._collect_dropbox_files_public(connection, session)
                        else:
                            files_to_sync = self._collect_dropbox_files(connection, session)
                    elif connection.provider == CloudProvider.GOOGLE_DRIVE:
                        # Öffentliche Ordner verwenden andere Methode
                        if is_public_google_drive:
                            logger.info("Starte öffentliche Google Drive Sammlung...")
                            files_to_sync = self._collect_google_drive_files_public(connection, session)
                            logger.info(f"Sammlung abgeschlossen: {len(files_to_sync)} Dateien")
                        else:
                            files_to_sync = self._collect_google_drive_files(connection, session)
                    else:
                        result["phase"] = "error"
                        result["error"] = f"Provider {connection.provider} nicht unterstützt"
                        result["errors"].append(result["error"])
                        yield result
                        return
                except Exception as collect_error:
                    logger.error(f"Fehler beim Sammeln der Dateien: {collect_error}")
                    result["phase"] = "error"
                    result["error"] = f"Fehler beim Scannen: {str(collect_error)}"
                    result["errors"].append(result["error"])
                    yield result
                    return

                result["files_total"] = len(files_to_sync)
                logger.info(f"Dateien gefunden: {result['files_total']}")

                if result["files_total"] == 0:
                    result["phase"] = "completed"
                    result["success"] = True
                    result["error"] = None
                    connection.status = SyncStatus.COMPLETED
                    connection.last_sync_at = datetime.now()
                    session.commit()
                    yield result
                    return

                result["phase"] = "downloading"
                yield result.copy()

                # Phase 2: Dateien herunterladen und importieren
                for idx, file_info in enumerate(files_to_sync):
                    elapsed = time.time() - start_time
                    result["elapsed_seconds"] = elapsed
                    result["current_file"] = file_info.get("name", "Unbekannt")
                    result["current_file_size"] = file_info.get("size", 0)
                    result["files_processed"] = idx
                    result["source_folder"] = file_info.get("source_folder", "")

                    # Fortschritt berechnen
                    if result["files_total"] > 0:
                        result["progress_percent"] = int((idx / result["files_total"]) * 100)

                        # Restzeit schätzen
                        if idx > 0:
                            avg_time_per_file = elapsed / idx
                            remaining_files = result["files_total"] - idx
                            result["estimated_remaining_seconds"] = avg_time_per_file * remaining_files

                    # Status: Download startet
                    result["current_step"] = "downloading"
                    result["current_step_detail"] = f"Lade {file_info.get('name')} herunter..."
                    yield result.copy()

                    # Datei verarbeiten
                    try:
                        sync_status, processing_steps = self._process_file_with_status(
                            connection, session, file_info, process_documents, result
                        )

                        # Yield für jeden Verarbeitungsschritt
                        for step in processing_steps:
                            result["current_step"] = step.get("step", "processing")
                            result["current_step_detail"] = step.get("detail", "")
                            yield result.copy()

                        if sync_status == "synced":
                            result["files_synced"] += 1
                            result["synced_files"].append(file_info.get("name"))
                            # Commit nach jedem erfolgreichen Import!
                            try:
                                session.commit()
                            except Exception as commit_err:
                                logger.error(f"Commit Fehler für {file_info.get('name')}: {commit_err}")
                                session.rollback()
                                result["files_error"] += 1
                                result["errors"].append(f"{file_info.get('name')}: Commit fehlgeschlagen")
                        elif sync_status == "skipped":
                            result["files_skipped"] += 1
                        else:
                            result["files_error"] += 1
                            # Rollback bei Fehler, damit nächste Datei funktioniert
                            try:
                                session.rollback()
                            except:
                                pass
                            # Füge letzten Fehler-Schritt zu Fehlerliste hinzu
                            error_detail = "Unbekannter Fehler"
                            for step in reversed(processing_steps):
                                if step.get("step") == "error" or "❌" in step.get("detail", ""):
                                    error_detail = step.get("detail", error_detail)
                                    break
                            result["errors"].append(f"{file_info.get('name')}: {error_detail}")

                    except Exception as e:
                        logger.error(f"Fehler beim Import von {file_info.get('name')}: {e}")
                        result["files_error"] += 1
                        result["errors"].append(f"{file_info.get('name')}: {str(e)}")
                        # Rollback bei Exception
                        try:
                            session.rollback()
                        except:
                            pass

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

        # Versuche Folder-ID zu extrahieren (kann URL oder echte ID sein)
        folder_id = None
        if connection.remote_folder_id:
            if 'drive.google.com' in connection.remote_folder_id:
                folder_id = self._google_get_folder_id_from_link(connection.remote_folder_id)
            elif len(connection.remote_folder_id) > 10 and not connection.remote_folder_id.startswith('http'):
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
        Verarbeitet eine einzelne Datei (Wrapper ohne Status-Rückgabe).

        Returns:
            'synced', 'skipped', oder 'error'
        """
        status, _ = self._process_file_with_status(connection, session, file_info, process_documents, {})
        return status

    def _process_file_with_status(self, connection: CloudSyncConnection, session,
                                   file_info: Dict, process_documents: bool,
                                   progress_result: Dict) -> Tuple[str, List[Dict]]:
        """
        Verarbeitet eine einzelne Datei mit detaillierten Status-Updates.

        Returns:
            Tuple von (status: 'synced'/'skipped'/'error', processing_steps: Liste von Status-Updates)
        """
        processing_steps = []

        try:
            provider = file_info.get("provider", "")
            filename = file_info.get("name", "unknown")

            logger.info(f"Verarbeite Datei: {filename} (Provider: {provider})")

            # Schritt 1: Download
            processing_steps.append({
                "step": "downloading",
                "detail": f"📥 Lade herunter: {filename}"
            })

            if provider == "dropbox":
                file_content, metadata = self._dropbox_download_file(
                    connection.access_token,
                    file_info.get("path")
                )
            elif provider == "google_drive_public":
                logger.info(f"Starte öffentlichen Download für: {filename}")
                file_content, success = self._google_public_download_file(
                    file_info.get("id")
                )
                if not success:
                    logger.error(f"Download fehlgeschlagen für {filename}")
                    processing_steps.append({
                        "step": "error",
                        "detail": f"❌ Download fehlgeschlagen: {filename}"
                    })
                    return "error", processing_steps
                logger.info(f"Download erfolgreich: {len(file_content)} Bytes")
            else:
                file_content = self._google_download_file(
                    connection.access_token,
                    file_info.get("id")
                )

            processing_steps.append({
                "step": "downloaded",
                "detail": f"✅ Heruntergeladen: {len(file_content):,} Bytes"
            })

            # Quellordner-Pfad für intelligente Kategorisierung
            source_folder_path = file_info.get("source_folder") or file_info.get("path") or ""

            logger.info(f"Importiere Datei: {filename} aus Ordner: {source_folder_path}")

            # Schritt 2: Speichern
            processing_steps.append({
                "step": "saving",
                "detail": f"💾 Speichere Datei lokal..."
            })

            # Dokument erstellen mit Status-Tracking
            doc, import_steps = self._import_file_with_status(
                session, connection,
                filename,
                file_content,
                file_info.get("size", len(file_content)),
                file_info.get("hash"),
                source_folder_path,
                process_documents
            )

            # Import-Schritte hinzufügen
            processing_steps.extend(import_steps)

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

            processing_steps.append({
                "step": "completed",
                "detail": f"✅ Fertig: {filename}"
            })

            return "synced", processing_steps

        except Exception as e:
            logger.error(f"Fehler beim Verarbeiten von {file_info.get('name')}: {e}")
            processing_steps.append({
                "step": "error",
                "detail": f"❌ Fehler: {str(e)}"
            })
            return "error", processing_steps

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

        # Folder-ID aus Pfad/Link extrahieren (kann URL oder echte ID sein)
        folder_id = None
        if connection.remote_folder_id:
            if 'drive.google.com' in connection.remote_folder_id:
                folder_id = self._google_get_folder_id_from_link(connection.remote_folder_id)
            elif len(connection.remote_folder_id) > 10 and not connection.remote_folder_id.startswith('http'):
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
        """
        Importiert eine Datei ins Dokumentenmanagement mit intelligenter Analyse.

        - Speichert Datei lokal
        - Führt OCR durch (falls PDF/Bild)
        - Analysiert Inhalt und extrahiert Metadaten
        - Erstellt automatisch passende Ordnerstruktur
        - Verknüpft mit Versicherungen/Verträgen
        """
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

        # Dokument in DB erstellen (vorerst mit Basis-Infos)
        doc = Document(
            user_id=self.user_id,
            folder_id=connection.local_folder_id,
            title=Path(filename).stem,
            filename=filename,
            file_path=str(file_path),
            file_size=file_size,
            mime_type=self._get_mime_type(filename),
            content_hash=content_hash,
            status=DocumentStatus.PENDING if process_documents else DocumentStatus.COMPLETED,
            category="Cloud-Import"
        )

        session.add(doc)
        session.flush()  # Um ID zu erhalten

        # Intelligente Dokumentenverarbeitung wenn aktiviert
        if process_documents:
            try:
                self._process_document_intelligent(
                    session, doc, content, remote_path, filename
                )
            except Exception as e:
                logger.error(f"Intelligente Verarbeitung fehlgeschlagen für {filename}: {e}")
                # Fehler nicht propagieren - Dokument wurde bereits gespeichert

        return doc

    def _import_file_with_status(self, session, connection: CloudSyncConnection,
                                  filename: str, content: bytes, file_size: int,
                                  content_hash: str, remote_path: str,
                                  process_documents: bool) -> Tuple[Optional[Document], List[Dict]]:
        """
        Importiert eine Datei mit Status-Updates für die Fortschrittsanzeige.
        Verwendet StorageService für Cloud-Speicher wenn verfügbar.

        Returns:
            Tuple von (Document, Liste von Status-Updates)
        """
        processing_steps = []

        # Verwende Storage Service für hybride Speicherung
        try:
            from services.storage_service import get_storage_service
            storage = get_storage_service()
        except ImportError:
            storage = None

        # Eindeutigen Dateinamen erstellen
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_filename = f"{timestamp}_{filename}"

        # Datei speichern (Cloud oder Lokal)
        if storage:
            success, file_path = storage.upload_file(
                file_data=content,
                filename=safe_filename,
                user_id=self.user_id,
                subfolder="cloud_sync",
                content_type=self._get_mime_type(filename)
            )

            if success:
                if file_path.startswith("cloud://"):
                    processing_steps.append({
                        "step": "saved",
                        "detail": f"☁️ Datei in Cloud gespeichert"
                    })
                else:
                    processing_steps.append({
                        "step": "saved",
                        "detail": f"💾 Datei lokal gespeichert"
                    })
            else:
                logger.error(f"Speichern fehlgeschlagen: {file_path}")
                return None, [{"step": "error", "detail": f"❌ Speichern fehlgeschlagen"}]
        else:
            # Fallback: Direkt lokal speichern
            upload_dir = Path("data/uploads") / str(self.user_id) / "cloud_sync"
            upload_dir.mkdir(parents=True, exist_ok=True)
            file_path = str(upload_dir / safe_filename)

            with open(file_path, "wb") as f:
                f.write(content)

            processing_steps.append({
                "step": "saved",
                "detail": f"💾 Datei lokal gespeichert"
            })

        # Dokument in DB erstellen
        # is_encrypted=False: Cloud-importierte Dateien werden nicht verschlüsselt
        doc = Document(
            user_id=self.user_id,
            folder_id=connection.local_folder_id,
            title=Path(filename).stem,
            filename=filename,
            file_path=str(file_path),
            file_size=file_size,
            mime_type=self._get_mime_type(filename),
            content_hash=content_hash,
            status=DocumentStatus.PENDING if process_documents else DocumentStatus.COMPLETED,
            category="Cloud-Import",
            is_encrypted=False,
            encryption_iv=None
        )

        session.add(doc)
        session.flush()

        # Intelligente Dokumentenverarbeitung wenn aktiviert
        if process_documents:
            try:
                intelligent_steps = self._process_document_intelligent_with_status(
                    session, doc, content, remote_path, filename
                )
                processing_steps.extend(intelligent_steps)
            except Exception as e:
                logger.error(f"Intelligente Verarbeitung fehlgeschlagen für {filename}: {e}")
                processing_steps.append({
                    "step": "processing_error",
                    "detail": f"⚠️ Verarbeitung teilweise fehlgeschlagen"
                })

        return doc, processing_steps

    def _process_document_intelligent_with_status(self, session, doc: Document,
                                                   content: bytes, remote_path: str,
                                                   filename: str) -> List[Dict]:
        """
        Führt intelligente Dokumentenverarbeitung mit Status-Updates durch.
        Verwendet Cache-Service für OCR-Ergebnisse.

        Returns:
            Liste von Status-Updates für Fortschrittsanzeige
        """
        processing_steps = []
        ocr_text = ""

        # Cache Service für OCR-Ergebnisse
        try:
            from services.cache_service import get_cache_service
            cache = get_cache_service()
            content_hash = cache._hash_content(content)
        except ImportError:
            cache = None
            content_hash = None

        # 1. OCR durchführen (mit Cache-Prüfung)
        processing_steps.append({
            "step": "ocr_starting",
            "detail": f"🔍 Starte Texterkennung (OCR)..."
        })

        # Prüfe Cache für OCR-Ergebnis
        cached_ocr = None
        if cache and content_hash:
            cached_ocr = cache.get_ocr_result(content_hash)
            if cached_ocr:
                processing_steps.append({
                    "step": "ocr_cached",
                    "detail": f"⚡ OCR aus Cache geladen"
                })
                ocr_text = cached_ocr
                doc.ocr_text = ocr_text
                doc.ocr_confidence = 0.95  # Hohe Konfidenz für Cache

        if not cached_ocr:
            try:
                from services.ocr import OCRService
                from PIL import Image
                import io
                ocr_service = OCRService()

                mime_type = doc.mime_type or self._get_mime_type(filename)

                if mime_type == "application/pdf":
                    processing_steps.append({
                        "step": "ocr_pdf",
                        "detail": f"📄 Verarbeite PDF mit OCR..."
                    })
                    # extract_text_from_pdf erwartet bytes und gibt List[Tuple[str, float]] zurück
                    ocr_results = ocr_service.extract_text_from_pdf(content)
                    if ocr_results:
                        # Texte aller Seiten zusammenfügen
                        ocr_text = "\n\n".join([text for text, conf in ocr_results if text])
                        avg_confidence = sum([conf for text, conf in ocr_results]) / len(ocr_results) if ocr_results else 0
                        doc.ocr_text = ocr_text
                        doc.ocr_confidence = avg_confidence
                    else:
                        ocr_text = ""
                        doc.ocr_confidence = 0

                    # Cache OCR-Ergebnis
                    if cache and content_hash and ocr_text:
                        cache.set_ocr_result(content_hash, ocr_text)

                    text_length = len(ocr_text)
                    processing_steps.append({
                        "step": "ocr_complete",
                        "detail": f"✅ OCR abgeschlossen: {text_length:,} Zeichen extrahiert"
                    })

                elif mime_type.startswith("image/"):
                    processing_steps.append({
                        "step": "ocr_image",
                        "detail": f"🖼️ Verarbeite Bild mit OCR..."
                    })
                    # Bild aus Bytes laden
                    image = Image.open(io.BytesIO(content))
                    ocr_text, confidence = ocr_service.extract_text_from_image(image)
                    doc.ocr_text = ocr_text
                    doc.ocr_confidence = confidence

                    # Cache OCR-Ergebnis
                    if cache and content_hash and ocr_text:
                        cache.set_ocr_result(content_hash, ocr_text)

                    text_length = len(ocr_text)
                    processing_steps.append({
                        "step": "ocr_complete",
                        "detail": f"✅ OCR abgeschlossen: {text_length:,} Zeichen extrahiert"
                    })
                else:
                    processing_steps.append({
                        "step": "ocr_skipped",
                        "detail": f"⏭️ OCR übersprungen (kein PDF/Bild)"
                    })

            except ImportError:
                logger.warning("OCR Service nicht verfügbar")
                processing_steps.append({
                    "step": "ocr_unavailable",
                    "detail": f"⚠️ OCR Service nicht verfügbar"
                })
            except Exception as e:
                logger.error(f"OCR fehlgeschlagen: {e}")
                processing_steps.append({
                    "step": "ocr_error",
                    "detail": f"⚠️ OCR Fehler: {str(e)[:50]}"
                })

        # 2. Intelligente Analyse mit Document Intelligence Service
        if ocr_text and len(ocr_text) > 50:
            processing_steps.append({
                "step": "analyzing",
                "detail": f"🧠 Analysiere Dokumentinhalt..."
            })

            try:
                from services.document_intelligence_service import DocumentIntelligenceService

                # AI Service laden falls verfügbar
                ai_service = None
                try:
                    from services.ai_service import AIService
                    ai_service = AIService()
                    processing_steps.append({
                        "step": "ai_loaded",
                        "detail": f"🤖 KI-Service geladen"
                    })
                except:
                    pass

                intel_service = DocumentIntelligenceService(
                    self.user_id, ai_service=ai_service
                )

                # Analysiere Dokument
                processing_steps.append({
                    "step": "extracting_metadata",
                    "detail": f"📋 Extrahiere Metadaten..."
                })

                metadata = intel_service.analyze_document(
                    ocr_text,
                    source_folder_path=remote_path,
                    filename=filename
                )

                # Status-Update für gefundene Metadaten
                found_items = []
                if metadata.sender:
                    found_items.append(f"Absender: {metadata.sender}")
                if metadata.document_date:
                    found_items.append(f"Datum: {metadata.document_date.strftime('%d.%m.%Y')}")
                if metadata.insurance_number:
                    found_items.append(f"Vers.-Nr: {metadata.insurance_number}")
                if metadata.document_type:
                    found_items.append(f"Typ: {metadata.document_type}")

                if found_items:
                    processing_steps.append({
                        "step": "metadata_found",
                        "detail": f"✅ Gefunden: {', '.join(found_items[:3])}"
                    })

                # Aktualisiere Dokument mit extrahierten Metadaten
                if metadata.sender:
                    doc.sender = metadata.sender

                if metadata.document_date:
                    doc.document_date = metadata.document_date

                if metadata.insurance_number:
                    doc.insurance_number = metadata.insurance_number

                if metadata.contract_number:
                    doc.contract_number = metadata.contract_number

                if metadata.customer_number:
                    doc.customer_number = metadata.customer_number

                if metadata.amount:
                    doc.invoice_amount = metadata.amount

                if metadata.document_type:
                    doc.category = metadata.document_type.capitalize()

                # 3. Erstelle Ordnerstruktur und verschiebe Dokument
                if metadata.suggested_folder_path:
                    processing_steps.append({
                        "step": "creating_folder",
                        "detail": f"📁 Erstelle Ordner: {metadata.suggested_folder_path}"
                    })

                    folder_id = intel_service.create_folder_structure(
                        metadata.suggested_folder_path
                    )
                    if folder_id:
                        doc.folder_id = folder_id
                        logger.info(f"Dokument {filename} in Ordner {metadata.suggested_folder_path} verschoben")
                        processing_steps.append({
                            "step": "folder_assigned",
                            "detail": f"✅ In Ordner eingeordnet"
                        })

                # 4. Generiere besseren Titel
                title_parts = []
                if metadata.document_date:
                    title_parts.append(metadata.document_date.strftime("%Y-%m-%d"))
                if metadata.sender:
                    title_parts.append(metadata.sender)
                if metadata.document_type:
                    type_names = {
                        "versicherung": "Versicherung",
                        "vertrag": "Vertrag",
                        "rechnung": "Rechnung",
                        "abonnement": "Abo"
                    }
                    title_parts.append(type_names.get(metadata.document_type, ""))
                if metadata.insurance_number:
                    title_parts.append(metadata.insurance_number)

                if title_parts:
                    doc.title = " - ".join([p for p in title_parts if p])
                    processing_steps.append({
                        "step": "title_generated",
                        "detail": f"📝 Titel: {doc.title[:40]}..."
                    })

                doc.status = DocumentStatus.COMPLETED

                processing_steps.append({
                    "step": "analysis_complete",
                    "detail": f"✅ Intelligente Analyse abgeschlossen"
                })

            except ImportError:
                logger.warning("Document Intelligence Service nicht verfügbar")
                processing_steps.append({
                    "step": "intel_unavailable",
                    "detail": f"⚠️ Dokumenten-Intelligenz nicht verfügbar"
                })
            except Exception as e:
                logger.error(f"Dokumenten-Intelligenz fehlgeschlagen: {e}")
                processing_steps.append({
                    "step": "intel_error",
                    "detail": f"⚠️ Analysefehler: {str(e)[:40]}"
                })
        else:
            processing_steps.append({
                "step": "analysis_skipped",
                "detail": f"⏭️ Analyse übersprungen (zu wenig Text)"
            })

        return processing_steps

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
            "files_found": result.get("files_total", 0),
            "files_synced": result.get("files_synced", 0),
            "files_skipped": result.get("files_skipped", 0),
            "files_error": result.get("files_error", 0),
            "synced_files": result.get("synced_files", []),
            "errors": result.get("errors", [])
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
