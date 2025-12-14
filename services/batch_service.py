"""
Stapelverarbeitung Service
Verarbeitet mehrere Dokumente gleichzeitig
"""
from datetime import datetime
from typing import Optional, List, Dict, Any, Callable
from pathlib import Path
import threading
import queue
import time

from database.models import Document, Folder, Tag, get_session


class BatchService:
    """Service für Stapelverarbeitung von Dokumenten"""

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.progress = {}
        self.results = {}

    def batch_move(self, document_ids: List[int], target_folder_id: int) -> Dict[str, Any]:
        """Verschiebt mehrere Dokumente in einen Ordner"""
        result = {"success": 0, "failed": 0, "errors": []}

        with get_session() as session:
            for doc_id in document_ids:
                try:
                    doc = session.query(Document).filter(
                        Document.id == doc_id,
                        Document.user_id == self.user_id
                    ).first()

                    if doc:
                        doc.folder_id = target_folder_id
                        doc.updated_at = datetime.now()
                        result["success"] += 1
                    else:
                        result["failed"] += 1
                        result["errors"].append(f"Dokument {doc_id} nicht gefunden")

                except Exception as e:
                    result["failed"] += 1
                    result["errors"].append(f"Dokument {doc_id}: {str(e)}")

            session.commit()

        return result

    def batch_delete(self, document_ids: List[int], soft_delete: bool = True) -> Dict[str, Any]:
        """Löscht mehrere Dokumente"""
        result = {"success": 0, "failed": 0, "errors": []}

        with get_session() as session:
            for doc_id in document_ids:
                try:
                    doc = session.query(Document).filter(
                        Document.id == doc_id,
                        Document.user_id == self.user_id
                    ).first()

                    if doc:
                        if soft_delete:
                            doc.is_deleted = True
                            doc.deleted_at = datetime.now()
                            doc.previous_folder_id = doc.folder_id
                        else:
                            # Datei löschen
                            if doc.file_path:
                                file_path = Path(doc.file_path)
                                if file_path.exists():
                                    file_path.unlink()
                            session.delete(doc)

                        result["success"] += 1
                    else:
                        result["failed"] += 1

                except Exception as e:
                    result["failed"] += 1
                    result["errors"].append(str(e))

            session.commit()

        return result

    def batch_restore(self, document_ids: List[int]) -> Dict[str, Any]:
        """Stellt mehrere gelöschte Dokumente wieder her"""
        result = {"success": 0, "failed": 0, "errors": []}

        with get_session() as session:
            for doc_id in document_ids:
                try:
                    doc = session.query(Document).filter(
                        Document.id == doc_id,
                        Document.user_id == self.user_id,
                        Document.is_deleted == True
                    ).first()

                    if doc:
                        doc.is_deleted = False
                        doc.deleted_at = None
                        doc.folder_id = doc.previous_folder_id
                        doc.previous_folder_id = None
                        result["success"] += 1
                    else:
                        result["failed"] += 1

                except Exception as e:
                    result["failed"] += 1
                    result["errors"].append(str(e))

            session.commit()

        return result

    def batch_tag(self, document_ids: List[int], tag_ids: List[int],
                  action: str = "add") -> Dict[str, Any]:
        """Fügt Tags zu mehreren Dokumenten hinzu oder entfernt sie"""
        result = {"success": 0, "failed": 0, "errors": []}

        with get_session() as session:
            tags = session.query(Tag).filter(Tag.id.in_(tag_ids)).all()

            for doc_id in document_ids:
                try:
                    doc = session.query(Document).filter(
                        Document.id == doc_id,
                        Document.user_id == self.user_id
                    ).first()

                    if doc:
                        if action == "add":
                            for tag in tags:
                                if tag not in doc.tags:
                                    doc.tags.append(tag)
                        elif action == "remove":
                            for tag in tags:
                                if tag in doc.tags:
                                    doc.tags.remove(tag)
                        elif action == "replace":
                            doc.tags = tags

                        result["success"] += 1
                    else:
                        result["failed"] += 1

                except Exception as e:
                    result["failed"] += 1
                    result["errors"].append(str(e))

            session.commit()

        return result

    def batch_update_category(self, document_ids: List[int],
                              category: str) -> Dict[str, Any]:
        """Aktualisiert Kategorie mehrerer Dokumente"""
        result = {"success": 0, "failed": 0, "errors": []}

        with get_session() as session:
            for doc_id in document_ids:
                try:
                    doc = session.query(Document).filter(
                        Document.id == doc_id,
                        Document.user_id == self.user_id
                    ).first()

                    if doc:
                        doc.category = category
                        doc.updated_at = datetime.now()
                        result["success"] += 1
                    else:
                        result["failed"] += 1

                except Exception as e:
                    result["failed"] += 1
                    result["errors"].append(str(e))

            session.commit()

        return result

    def batch_update_status(self, document_ids: List[int],
                            workflow_status: str) -> Dict[str, Any]:
        """Aktualisiert Workflow-Status mehrerer Dokumente"""
        result = {"success": 0, "failed": 0, "errors": []}

        with get_session() as session:
            for doc_id in document_ids:
                try:
                    doc = session.query(Document).filter(
                        Document.id == doc_id,
                        Document.user_id == self.user_id
                    ).first()

                    if doc:
                        doc.workflow_status = workflow_status
                        doc.updated_at = datetime.now()
                        result["success"] += 1
                    else:
                        result["failed"] += 1

                except Exception as e:
                    result["failed"] += 1
                    result["errors"].append(str(e))

            session.commit()

        return result

    def batch_export(self, document_ids: List[int],
                     export_path: str) -> Dict[str, Any]:
        """Exportiert mehrere Dokumente in einen Ordner"""
        result = {"success": 0, "failed": 0, "errors": [], "files": []}

        export_dir = Path(export_path)
        export_dir.mkdir(parents=True, exist_ok=True)

        with get_session() as session:
            for doc_id in document_ids:
                try:
                    doc = session.query(Document).filter(
                        Document.id == doc_id,
                        Document.user_id == self.user_id
                    ).first()

                    if doc and doc.file_path:
                        source = Path(doc.file_path)
                        if source.exists():
                            dest = export_dir / doc.filename
                            # Bei Namenskollision umbenennen
                            counter = 1
                            while dest.exists():
                                stem = source.stem
                                suffix = source.suffix
                                dest = export_dir / f"{stem}_{counter}{suffix}"
                                counter += 1

                            import shutil
                            shutil.copy2(source, dest)
                            result["success"] += 1
                            result["files"].append(str(dest))
                        else:
                            result["failed"] += 1
                            result["errors"].append(f"Datei nicht gefunden: {doc_id}")
                    else:
                        result["failed"] += 1

                except Exception as e:
                    result["failed"] += 1
                    result["errors"].append(str(e))

        return result

    def batch_process_ocr(self, document_ids: List[int],
                          ocr_function: Callable) -> Dict[str, Any]:
        """Führt OCR für mehrere Dokumente aus"""
        result = {"success": 0, "failed": 0, "errors": [], "processed": []}

        with get_session() as session:
            for doc_id in document_ids:
                try:
                    doc = session.query(Document).filter(
                        Document.id == doc_id,
                        Document.user_id == self.user_id
                    ).first()

                    if doc and doc.file_path:
                        # OCR ausführen
                        ocr_text = ocr_function(doc.file_path)

                        if ocr_text:
                            doc.ocr_text = ocr_text
                            doc.updated_at = datetime.now()
                            result["success"] += 1
                            result["processed"].append(doc_id)
                        else:
                            result["failed"] += 1
                    else:
                        result["failed"] += 1

                except Exception as e:
                    result["failed"] += 1
                    result["errors"].append(f"Dokument {doc_id}: {str(e)}")

            session.commit()

        return result

    def get_batch_statistics(self, document_ids: List[int]) -> Dict[str, Any]:
        """Holt Statistiken für ausgewählte Dokumente"""
        with get_session() as session:
            docs = session.query(Document).filter(
                Document.id.in_(document_ids),
                Document.user_id == self.user_id
            ).all()

            total_size = sum(d.file_size or 0 for d in docs)
            categories = {}
            statuses = {}

            for doc in docs:
                cat = doc.category or "Keine Kategorie"
                categories[cat] = categories.get(cat, 0) + 1

                status = doc.workflow_status or "new"
                statuses[status] = statuses.get(status, 0) + 1

            return {
                "count": len(docs),
                "total_size": total_size,
                "total_size_mb": round(total_size / (1024 * 1024), 2),
                "categories": categories,
                "statuses": statuses,
                "with_ocr": len([d for d in docs if d.ocr_text]),
                "without_ocr": len([d for d in docs if not d.ocr_text])
            }
