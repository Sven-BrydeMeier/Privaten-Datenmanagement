"""
Backup & Restore Service
Erstellt und verwaltet Backups der Dokumente und Datenbank
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path
import json
import shutil
import zipfile
import tempfile

from database.models import Document, Folder, Tag, get_session
from database.extended_models import BackupLog


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
