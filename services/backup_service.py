"""
Backup & Restore Service
Erstellt und verwaltet Backups der Dokumente und Datenbank

Enthält zwei Modi:
1. Standard-Backup: Exportiert Metadaten als JSON + Dateien (für Benutzer-Backups)
2. Entwickler-Snapshot: Kopiert die komplette Datenbank + alle Dateien (für Entwicklung)
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path
import json
import shutil
import zipfile
import tempfile
import sqlite3
import os

from database.models import Document, Folder, Tag, get_session
from database.extended_models import BackupLog
from config.settings import DATABASE_PATH, DATA_DIR, DOCUMENTS_DIR, INDEX_DIR, CONFIG_FILE


class BackupService:
    """Service für Backup und Restore"""

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.backup_dir = Path("data/backups")
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def create_backup(self, backup_type: str = "full",
                      include_files: bool = True,
                      encrypt: bool = False) -> Dict[str, Any]:
        """
        Erstellt ein Backup

        Args:
            backup_type: "full", "incremental", "documents_only", "metadata_only"
            include_files: Ob Dateien eingeschlossen werden sollen
            encrypt: Ob das Backup verschlüsselt werden soll (TODO)
        """
        result = {
            "success": False,
            "backup_path": None,
            "documents_count": 0,
            "total_size": 0,
            "errors": []
        }

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"backup_{self.user_id}_{backup_type}_{timestamp}"
        backup_path = self.backup_dir / str(self.user_id) / backup_name
        backup_path.mkdir(parents=True, exist_ok=True)

        try:
            # Metadata exportieren
            metadata = self._export_metadata()
            metadata_path = backup_path / "metadata.json"
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False, default=str)

            result["documents_count"] = len(metadata.get("documents", []))

            # Dateien kopieren
            if include_files and backup_type != "metadata_only":
                files_path = backup_path / "files"
                files_path.mkdir(exist_ok=True)

                with get_session() as session:
                    docs = session.query(Document).filter(
                        Document.user_id == self.user_id,
                        Document.is_deleted == False
                    ).all()

                    for doc in docs:
                        if doc.file_path:
                            source = Path(doc.file_path)
                            if source.exists():
                                dest = files_path / f"{doc.id}_{source.name}"
                                shutil.copy2(source, dest)
                                result["total_size"] += source.stat().st_size

            # ZIP erstellen
            zip_path = backup_path.parent / f"{backup_name}.zip"
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for file_path in backup_path.rglob('*'):
                    if file_path.is_file():
                        arcname = file_path.relative_to(backup_path)
                        zipf.write(file_path, arcname)

            # Temporäre Dateien aufräumen
            shutil.rmtree(backup_path)

            result["success"] = True
            result["backup_path"] = str(zip_path)

            # Backup-Log erstellen
            self._log_backup(
                backup_type=backup_type,
                backup_path=str(zip_path),
                backup_size=zip_path.stat().st_size,
                documents_count=result["documents_count"],
                status="completed"
            )

        except Exception as e:
            result["errors"].append(str(e))
            self._log_backup(
                backup_type=backup_type,
                status="failed",
                error_message=str(e)
            )

        return result

    def restore_backup(self, backup_path: str,
                       restore_files: bool = True,
                       merge: bool = False) -> Dict[str, Any]:
        """
        Stellt ein Backup wieder her

        Args:
            backup_path: Pfad zur Backup-Datei
            restore_files: Ob Dateien wiederhergestellt werden sollen
            merge: True = Mit bestehenden Daten zusammenführen, False = Ersetzen
        """
        result = {
            "success": False,
            "documents_restored": 0,
            "files_restored": 0,
            "errors": []
        }

        try:
            backup_file = Path(backup_path)
            if not backup_file.exists():
                result["errors"].append("Backup-Datei nicht gefunden")
                return result

            # ZIP entpacken
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)

                with zipfile.ZipFile(backup_file, 'r') as zipf:
                    zipf.extractall(temp_path)

                # Metadata laden
                metadata_path = temp_path / "metadata.json"
                if not metadata_path.exists():
                    result["errors"].append("Keine Metadata-Datei im Backup")
                    return result

                with open(metadata_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)

                # Daten wiederherstellen
                result["documents_restored"] = self._restore_metadata(metadata, merge)

                # Dateien wiederherstellen
                if restore_files:
                    files_path = temp_path / "files"
                    if files_path.exists():
                        result["files_restored"] = self._restore_files(files_path, metadata)

            result["success"] = True

        except Exception as e:
            result["errors"].append(str(e))

        return result

    def _export_metadata(self) -> Dict[str, Any]:
        """Exportiert alle Metadaten"""
        with get_session() as session:
            # Dokumente
            docs = session.query(Document).filter(
                Document.user_id == self.user_id
            ).all()

            documents = []
            for doc in docs:
                documents.append({
                    "id": doc.id,
                    "title": doc.title,
                    "filename": doc.filename,
                    "file_path": doc.file_path,
                    "mime_type": doc.mime_type,
                    "file_size": doc.file_size,
                    "category": doc.category,
                    "sender": doc.sender,
                    "document_date": doc.document_date,
                    "ocr_text": doc.ocr_text,
                    "ai_summary": doc.ai_summary,
                    "invoice_amount": doc.invoice_amount,
                    "invoice_number": doc.invoice_number,
                    "folder_id": doc.folder_id,
                    "created_at": doc.created_at,
                    "tags": [t.name for t in doc.tags]
                })

            # Ordner
            folders = session.query(Folder).filter(
                Folder.user_id == self.user_id
            ).all()

            folder_data = [{
                "id": f.id,
                "name": f.name,
                "parent_id": f.parent_id,
                "icon": f.icon,
                "color": f.color
            } for f in folders]

            # Tags
            tags = session.query(Tag).all()
            tag_data = [{"id": t.id, "name": t.name, "color": t.color} for t in tags]

            return {
                "version": "1.0",
                "exported_at": datetime.now().isoformat(),
                "user_id": self.user_id,
                "documents": documents,
                "folders": folder_data,
                "tags": tag_data
            }

    def _restore_metadata(self, metadata: Dict, merge: bool) -> int:
        """Stellt Metadaten wieder her"""
        restored = 0

        with get_session() as session:
            if not merge:
                # Bestehende Dokumente löschen
                session.query(Document).filter(
                    Document.user_id == self.user_id
                ).delete()

            # Tags erstellen/finden
            tag_map = {}
            for tag_data in metadata.get("tags", []):
                existing = session.query(Tag).filter(
                    Tag.name == tag_data["name"]
                ).first()

                if existing:
                    tag_map[tag_data["name"]] = existing
                else:
                    new_tag = Tag(name=tag_data["name"], color=tag_data.get("color"))
                    session.add(new_tag)
                    session.flush()
                    tag_map[tag_data["name"]] = new_tag

            # Ordner erstellen
            folder_map = {}
            for folder_data in metadata.get("folders", []):
                existing = session.query(Folder).filter(
                    Folder.user_id == self.user_id,
                    Folder.name == folder_data["name"]
                ).first()

                if existing:
                    folder_map[folder_data["id"]] = existing.id
                else:
                    new_folder = Folder(
                        user_id=self.user_id,
                        name=folder_data["name"],
                        icon=folder_data.get("icon"),
                        color=folder_data.get("color")
                    )
                    session.add(new_folder)
                    session.flush()
                    folder_map[folder_data["id"]] = new_folder.id

            # Dokumente erstellen
            for doc_data in metadata.get("documents", []):
                doc = Document(
                    user_id=self.user_id,
                    title=doc_data.get("title"),
                    filename=doc_data.get("filename"),
                    file_path=doc_data.get("file_path"),
                    mime_type=doc_data.get("mime_type"),
                    file_size=doc_data.get("file_size"),
                    category=doc_data.get("category"),
                    sender=doc_data.get("sender"),
                    ocr_text=doc_data.get("ocr_text"),
                    ai_summary=doc_data.get("ai_summary"),
                    invoice_amount=doc_data.get("invoice_amount"),
                    invoice_number=doc_data.get("invoice_number"),
                    folder_id=folder_map.get(doc_data.get("folder_id"))
                )

                # Tags zuweisen
                for tag_name in doc_data.get("tags", []):
                    if tag_name in tag_map:
                        doc.tags.append(tag_map[tag_name])

                session.add(doc)
                restored += 1

            session.commit()

        return restored

    def _restore_files(self, files_path: Path, metadata: Dict) -> int:
        """Stellt Dateien wieder her"""
        restored = 0
        upload_dir = Path("data/uploads") / str(self.user_id)
        upload_dir.mkdir(parents=True, exist_ok=True)

        for file_path in files_path.iterdir():
            if file_path.is_file():
                # Dokument-ID aus Dateinamen extrahieren
                try:
                    doc_id = int(file_path.name.split("_")[0])

                    # Neuen Pfad erstellen
                    dest = upload_dir / file_path.name
                    shutil.copy2(file_path, dest)

                    # Pfad in DB aktualisieren
                    with get_session() as session:
                        doc = session.query(Document).filter(
                            Document.user_id == self.user_id
                        ).order_by(Document.id.desc()).first()

                        if doc:
                            doc.file_path = str(dest)
                            session.commit()

                    restored += 1

                except (ValueError, IndexError):
                    continue

        return restored

    def _log_backup(self, backup_type: str, backup_path: str = None,
                    backup_size: int = None, documents_count: int = 0,
                    status: str = "completed", error_message: str = None):
        """Loggt ein Backup"""
        with get_session() as session:
            log = BackupLog(
                user_id=self.user_id,
                backup_type=backup_type,
                backup_path=backup_path,
                backup_size=backup_size,
                documents_count=documents_count,
                total_items=documents_count,
                status=status,
                error_message=error_message,
                completed_at=datetime.now() if status == "completed" else None
            )
            session.add(log)
            session.commit()

    def get_backup_history(self, limit: int = 20) -> List[BackupLog]:
        """Holt Backup-Historie"""
        with get_session() as session:
            return session.query(BackupLog).filter(
                BackupLog.user_id == self.user_id
            ).order_by(BackupLog.created_at.desc()).limit(limit).all()

    def list_backups(self) -> List[Dict]:
        """Listet alle verfügbaren Backups"""
        backups = []
        user_backup_dir = self.backup_dir / str(self.user_id)

        if user_backup_dir.exists():
            for file_path in user_backup_dir.glob("*.zip"):
                backups.append({
                    "filename": file_path.name,
                    "path": str(file_path),
                    "size": file_path.stat().st_size,
                    "created": datetime.fromtimestamp(file_path.stat().st_mtime)
                })

        return sorted(backups, key=lambda x: x["created"], reverse=True)

    def delete_backup(self, backup_path: str) -> bool:
        """Löscht ein Backup"""
        try:
            path = Path(backup_path)
            if path.exists() and str(self.user_id) in str(path):
                path.unlink()
                return True
        except:
            pass
        return False


# ==================== ENTWICKLER-SNAPSHOT FUNKTIONEN ====================

class DeveloperSnapshot:
    """
    Erstellt komplette Snapshots des Datenverzeichnisses für Entwicklungszwecke.

    Im Gegensatz zum normalen Backup wird hier die komplette Datenbank-Datei
    und alle Uploads direkt kopiert - kein JSON-Export nötig.
    """

    def __init__(self):
        self.snapshot_dir = DATA_DIR / "snapshots"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

    def create_snapshot(self, name: str = None, include_index: bool = False) -> Dict[str, Any]:
        """
        Erstellt einen kompletten Snapshot der Datenbank und aller Dateien.

        Args:
            name: Optionaler Name für den Snapshot
            include_index: Ob der Suchindex eingeschlossen werden soll

        Returns:
            Dict mit Ergebnis-Informationen
        """
        result = {
            "success": False,
            "snapshot_path": None,
            "database_size": 0,
            "files_count": 0,
            "total_size": 0,
            "errors": []
        }

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        snapshot_name = name or f"snapshot_{timestamp}"
        snapshot_name = snapshot_name.replace(" ", "_").replace("/", "_")

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)

                # 1. Datenbank kopieren (mit SQLite-sicherem Backup)
                db_backup_path = temp_path / "docmanagement.db"
                self._backup_database(db_backup_path)
                result["database_size"] = db_backup_path.stat().st_size

                # 2. Dokumente-Verzeichnis kopieren
                docs_backup_path = temp_path / "documents"
                if DOCUMENTS_DIR.exists():
                    shutil.copytree(DOCUMENTS_DIR, docs_backup_path, dirs_exist_ok=True)
                    result["files_count"] = sum(1 for _ in docs_backup_path.rglob('*') if _.is_file())

                # 3. Config kopieren (falls vorhanden)
                if CONFIG_FILE.exists():
                    shutil.copy2(CONFIG_FILE, temp_path / "config.json")

                # 4. Suchindex kopieren (optional, kann groß sein)
                if include_index and INDEX_DIR.exists():
                    index_backup_path = temp_path / "search_index"
                    shutil.copytree(INDEX_DIR, index_backup_path, dirs_exist_ok=True)

                # 5. Manifest erstellen
                manifest = {
                    "version": "2.0",
                    "type": "developer_snapshot",
                    "created_at": datetime.now().isoformat(),
                    "name": snapshot_name,
                    "database_size": result["database_size"],
                    "files_count": result["files_count"],
                    "include_index": include_index,
                    "python_version": os.sys.version,
                }
                with open(temp_path / "manifest.json", "w", encoding="utf-8") as f:
                    json.dump(manifest, f, indent=2, ensure_ascii=False)

                # 6. Als ZIP komprimieren
                zip_path = self.snapshot_dir / f"{snapshot_name}.zip"
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zipf:
                    for file_path in temp_path.rglob('*'):
                        if file_path.is_file():
                            arcname = file_path.relative_to(temp_path)
                            zipf.write(file_path, arcname)

                result["success"] = True
                result["snapshot_path"] = str(zip_path)
                result["total_size"] = zip_path.stat().st_size

        except Exception as e:
            result["errors"].append(str(e))

        return result

    def _backup_database(self, dest_path: Path):
        """
        Erstellt ein sicheres Backup der SQLite-Datenbank.
        Verwendet die SQLite Online Backup API für Konsistenz.
        """
        source_conn = sqlite3.connect(str(DATABASE_PATH))
        dest_conn = sqlite3.connect(str(dest_path))

        try:
            source_conn.backup(dest_conn)
        finally:
            dest_conn.close()
            source_conn.close()

    def restore_snapshot(self, snapshot_path: str, confirm: bool = False) -> Dict[str, Any]:
        """
        Stellt einen Snapshot wieder her.

        ACHTUNG: Dies überschreibt alle aktuellen Daten!

        Args:
            snapshot_path: Pfad zur Snapshot-ZIP-Datei
            confirm: Muss True sein, um die Wiederherstellung zu bestätigen

        Returns:
            Dict mit Ergebnis-Informationen
        """
        result = {
            "success": False,
            "documents_restored": 0,
            "errors": []
        }

        if not confirm:
            result["errors"].append("Bestätigung erforderlich: confirm=True")
            return result

        snapshot_file = Path(snapshot_path)
        if not snapshot_file.exists():
            result["errors"].append(f"Snapshot nicht gefunden: {snapshot_path}")
            return result

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)

                # ZIP entpacken
                with zipfile.ZipFile(snapshot_file, 'r') as zipf:
                    zipf.extractall(temp_path)

                # Manifest prüfen
                manifest_path = temp_path / "manifest.json"
                if manifest_path.exists():
                    with open(manifest_path, "r", encoding="utf-8") as f:
                        manifest = json.load(f)
                    if manifest.get("type") != "developer_snapshot":
                        result["errors"].append("Ungültiger Snapshot-Typ")
                        return result

                # Aktuelle Datenbank schließen (wichtig für SQLite)
                from database.db import engine
                engine.dispose()

                # 1. Datenbank wiederherstellen
                db_backup = temp_path / "docmanagement.db"
                if db_backup.exists():
                    # Alte DB sichern
                    if DATABASE_PATH.exists():
                        backup_old = DATABASE_PATH.with_suffix('.db.old')
                        shutil.copy2(DATABASE_PATH, backup_old)
                    # Neue DB kopieren
                    shutil.copy2(db_backup, DATABASE_PATH)

                # 2. Dokumente wiederherstellen
                docs_backup = temp_path / "documents"
                if docs_backup.exists():
                    # Altes Verzeichnis löschen
                    if DOCUMENTS_DIR.exists():
                        shutil.rmtree(DOCUMENTS_DIR)
                    # Neues Verzeichnis kopieren
                    shutil.copytree(docs_backup, DOCUMENTS_DIR)
                    result["documents_restored"] = sum(1 for _ in DOCUMENTS_DIR.rglob('*') if _.is_file())

                # 3. Config wiederherstellen
                config_backup = temp_path / "config.json"
                if config_backup.exists():
                    shutil.copy2(config_backup, CONFIG_FILE)

                # 4. Suchindex wiederherstellen (falls vorhanden)
                index_backup = temp_path / "search_index"
                if index_backup.exists():
                    if INDEX_DIR.exists():
                        shutil.rmtree(INDEX_DIR)
                    shutil.copytree(index_backup, INDEX_DIR)

                result["success"] = True

        except Exception as e:
            result["errors"].append(str(e))

        return result

    def list_snapshots(self) -> List[Dict]:
        """Listet alle verfügbaren Snapshots"""
        snapshots = []

        if self.snapshot_dir.exists():
            for file_path in self.snapshot_dir.glob("*.zip"):
                try:
                    # Manifest aus ZIP lesen
                    manifest = None
                    with zipfile.ZipFile(file_path, 'r') as zipf:
                        if 'manifest.json' in zipf.namelist():
                            with zipf.open('manifest.json') as f:
                                manifest = json.load(f)

                    snapshots.append({
                        "filename": file_path.name,
                        "path": str(file_path),
                        "size": file_path.stat().st_size,
                        "created": datetime.fromtimestamp(file_path.stat().st_mtime),
                        "name": manifest.get("name") if manifest else file_path.stem,
                        "files_count": manifest.get("files_count", 0) if manifest else 0,
                        "database_size": manifest.get("database_size", 0) if manifest else 0,
                    })
                except Exception:
                    # Fehlerhafte ZIP ignorieren
                    continue

        return sorted(snapshots, key=lambda x: x["created"], reverse=True)

    def delete_snapshot(self, snapshot_path: str) -> bool:
        """Löscht einen Snapshot"""
        try:
            path = Path(snapshot_path)
            if path.exists() and path.parent == self.snapshot_dir:
                path.unlink()
                return True
        except:
            pass
        return False

    def get_snapshot_info(self, snapshot_path: str) -> Optional[Dict]:
        """Holt detaillierte Informationen über einen Snapshot"""
        try:
            with zipfile.ZipFile(snapshot_path, 'r') as zipf:
                if 'manifest.json' in zipf.namelist():
                    with zipf.open('manifest.json') as f:
                        manifest = json.load(f)

                    # Dateiliste hinzufügen
                    files = []
                    for name in zipf.namelist():
                        info = zipf.getinfo(name)
                        files.append({
                            "name": name,
                            "size": info.file_size,
                            "compressed": info.compress_size
                        })

                    manifest["files"] = files
                    manifest["total_compressed_size"] = Path(snapshot_path).stat().st_size
                    return manifest
        except Exception:
            pass
        return None


def get_snapshot_service() -> DeveloperSnapshot:
    """Singleton für den Snapshot-Service"""
    return DeveloperSnapshot()
