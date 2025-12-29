"""
Dokumenten-Versionierung Service
Verwaltet Versionen von Dokumenten
"""
from datetime import datetime
from typing import Optional, List
from pathlib import Path
import hashlib
import shutil

from database.models import Document, get_session
from database.extended_models import DocumentVersion


class VersionService:
    """Service für Dokumenten-Versionierung"""

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.version_dir = Path("data/versions")
        self.version_dir.mkdir(parents=True, exist_ok=True)

    def create_version(self, document_id: int, change_summary: str = None,
                       version_label: str = None) -> Optional[DocumentVersion]:
        """Erstellt eine neue Version eines Dokuments"""
        with get_session() as session:
            document = session.query(Document).filter(
                Document.id == document_id,
                Document.user_id == self.user_id
            ).first()

            if not document or not document.file_path:
                return None

            # Aktuelle Versionsnummer ermitteln
            last_version = session.query(DocumentVersion).filter(
                DocumentVersion.document_id == document_id
            ).order_by(DocumentVersion.version_number.desc()).first()

            new_version_number = (last_version.version_number + 1) if last_version else 1

            # Datei kopieren
            source_path = Path(document.file_path)
            if not source_path.exists():
                return None

            version_filename = f"{document_id}_v{new_version_number}_{source_path.name}"
            version_path = self.version_dir / str(self.user_id) / version_filename
            version_path.parent.mkdir(parents=True, exist_ok=True)

            shutil.copy2(source_path, version_path)

            # Hash berechnen
            file_hash = self._calculate_hash(version_path)

            # Alle anderen Versionen als nicht-aktuell markieren
            session.query(DocumentVersion).filter(
                DocumentVersion.document_id == document_id
            ).update({"is_current": False})

            # Neue Version erstellen
            version = DocumentVersion(
                document_id=document_id,
                user_id=self.user_id,
                version_number=new_version_number,
                version_label=version_label or f"Version {new_version_number}",
                file_path=str(version_path),
                file_size=version_path.stat().st_size,
                file_hash=file_hash,
                change_summary=change_summary,
                is_current=True
            )

            session.add(version)
            session.commit()
            session.refresh(version)
            return version

    def get_versions(self, document_id: int) -> List[DocumentVersion]:
        """Holt alle Versionen eines Dokuments"""
        with get_session() as session:
            return session.query(DocumentVersion).filter(
                DocumentVersion.document_id == document_id,
                DocumentVersion.user_id == self.user_id
            ).order_by(DocumentVersion.version_number.desc()).all()

    def get_version(self, version_id: int) -> Optional[DocumentVersion]:
        """Holt eine spezifische Version"""
        with get_session() as session:
            return session.query(DocumentVersion).filter(
                DocumentVersion.id == version_id,
                DocumentVersion.user_id == self.user_id
            ).first()

    def get_current_version(self, document_id: int) -> Optional[DocumentVersion]:
        """Holt die aktuelle Version"""
        with get_session() as session:
            return session.query(DocumentVersion).filter(
                DocumentVersion.document_id == document_id,
                DocumentVersion.is_current == True
            ).first()

    def restore_version(self, version_id: int) -> bool:
        """Stellt eine frühere Version wieder her"""
        with get_session() as session:
            version = session.query(DocumentVersion).filter(
                DocumentVersion.id == version_id,
                DocumentVersion.user_id == self.user_id
            ).first()

            if not version:
                return False

            document = session.query(Document).filter(
                Document.id == version.document_id
            ).first()

            if not document:
                return False

            # Aktuelle Version als neue Version speichern (Backup)
            self.create_version(
                document.id,
                f"Backup vor Wiederherstellung von Version {version.version_number}"
            )

            # Datei wiederherstellen
            version_path = Path(version.file_path)
            document_path = Path(document.file_path)

            if version_path.exists():
                shutil.copy2(version_path, document_path)

                # Version als aktuell markieren
                session.query(DocumentVersion).filter(
                    DocumentVersion.document_id == document.id
                ).update({"is_current": False})

                version.is_current = True
                session.commit()
                return True

            return False

    def delete_version(self, version_id: int) -> bool:
        """Löscht eine Version"""
        with get_session() as session:
            version = session.query(DocumentVersion).filter(
                DocumentVersion.id == version_id,
                DocumentVersion.user_id == self.user_id,
                DocumentVersion.is_current == False  # Aktuelle Version nicht löschen
            ).first()

            if not version:
                return False

            # Datei löschen
            version_path = Path(version.file_path)
            if version_path.exists():
                version_path.unlink()

            session.delete(version)
            session.commit()
            return True

    def compare_versions(self, version_id_1: int, version_id_2: int) -> dict:
        """Vergleicht zwei Versionen"""
        with get_session() as session:
            v1 = session.query(DocumentVersion).filter(
                DocumentVersion.id == version_id_1
            ).first()

            v2 = session.query(DocumentVersion).filter(
                DocumentVersion.id == version_id_2
            ).first()

            if not v1 or not v2:
                return {"error": "Version nicht gefunden"}

            return {
                "version_1": {
                    "number": v1.version_number,
                    "label": v1.version_label,
                    "created_at": v1.created_at,
                    "file_size": v1.file_size,
                    "file_hash": v1.file_hash
                },
                "version_2": {
                    "number": v2.version_number,
                    "label": v2.version_label,
                    "created_at": v2.created_at,
                    "file_size": v2.file_size,
                    "file_hash": v2.file_hash
                },
                "size_difference": v2.file_size - v1.file_size if v1.file_size and v2.file_size else 0,
                "same_content": v1.file_hash == v2.file_hash if v1.file_hash and v2.file_hash else None
            }

    def cleanup_old_versions(self, document_id: int, keep_count: int = 10) -> int:
        """Löscht alte Versionen, behält nur die neuesten"""
        with get_session() as session:
            versions = session.query(DocumentVersion).filter(
                DocumentVersion.document_id == document_id,
                DocumentVersion.user_id == self.user_id
            ).order_by(DocumentVersion.version_number.desc()).all()

            deleted_count = 0

            for version in versions[keep_count:]:
                if not version.is_current:
                    version_path = Path(version.file_path)
                    if version_path.exists():
                        version_path.unlink()
                    session.delete(version)
                    deleted_count += 1

            session.commit()
            return deleted_count

    def _calculate_hash(self, file_path: Path) -> str:
        """Berechnet SHA-256 Hash einer Datei"""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def get_version_history(self, document_id: int) -> List[dict]:
        """Holt Versionshistorie als Liste"""
        versions = self.get_versions(document_id)
        return [{
            "id": v.id,
            "number": v.version_number,
            "label": v.version_label,
            "created_at": v.created_at,
            "change_summary": v.change_summary,
            "file_size": v.file_size,
            "is_current": v.is_current
        } for v in versions]
