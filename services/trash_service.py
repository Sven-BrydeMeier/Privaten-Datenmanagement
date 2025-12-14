"""
Papierkorb-Service für Soft Delete von Dokumenten
Dokumente werden nicht sofort gelöscht, sondern in den Papierkorb verschoben
und nach einer konfigurierbaren Zeit endgültig gelöscht.
"""
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from pathlib import Path

from config.settings import get_settings


class TrashService:
    """Service für Papierkorb-Funktionalität"""

    def __init__(self):
        self.settings = get_settings()

    def get_retention_hours(self) -> int:
        """Gibt die Aufbewahrungszeit im Papierkorb in Stunden zurück"""
        return getattr(self.settings, 'trash_retention_hours', 48)

    def move_to_trash(self, document_id: int, user_id: int) -> Dict[str, Any]:
        """
        Verschiebt ein Dokument in den Papierkorb (Soft Delete)

        Args:
            document_id: ID des Dokuments
            user_id: ID des Benutzers

        Returns:
            Dict mit Ergebnis
        """
        from database.models import get_session, Document

        session = get_session()
        try:
            doc = session.query(Document).filter_by(
                id=document_id,
                user_id=user_id
            ).first()

            if not doc:
                return {"success": False, "error": "Dokument nicht gefunden"}

            if doc.is_deleted:
                return {"success": False, "error": "Dokument ist bereits im Papierkorb"}

            # Speichere vorherigen Ordner für Wiederherstellung
            doc.previous_folder_id = doc.folder_id
            doc.folder_id = None  # Aus Ordner entfernen
            doc.is_deleted = True
            doc.deleted_at = datetime.now()

            session.commit()

            return {
                "success": True,
                "message": f"Dokument '{doc.title or doc.filename}' in Papierkorb verschoben",
                "expires_at": doc.deleted_at + timedelta(hours=self.get_retention_hours())
            }

        except Exception as e:
            session.rollback()
            return {"success": False, "error": str(e)}
        finally:
            session.close()

    def restore_from_trash(self, document_id: int, user_id: int) -> Dict[str, Any]:
        """
        Stellt ein Dokument aus dem Papierkorb wieder her

        Args:
            document_id: ID des Dokuments
            user_id: ID des Benutzers

        Returns:
            Dict mit Ergebnis
        """
        from database.models import get_session, Document, Folder

        session = get_session()
        try:
            doc = session.query(Document).filter_by(
                id=document_id,
                user_id=user_id,
                is_deleted=True
            ).first()

            if not doc:
                return {"success": False, "error": "Dokument nicht im Papierkorb gefunden"}

            # Prüfe ob vorheriger Ordner noch existiert
            target_folder_id = doc.previous_folder_id
            if target_folder_id:
                folder = session.query(Folder).filter_by(
                    id=target_folder_id,
                    user_id=user_id
                ).first()
                if not folder:
                    target_folder_id = None  # Ordner existiert nicht mehr

            # Wiederherstellen
            doc.folder_id = target_folder_id
            doc.is_deleted = False
            doc.deleted_at = None
            doc.previous_folder_id = None

            session.commit()

            return {
                "success": True,
                "message": f"Dokument '{doc.title or doc.filename}' wiederhergestellt",
                "folder_id": target_folder_id
            }

        except Exception as e:
            session.rollback()
            return {"success": False, "error": str(e)}
        finally:
            session.close()

    def permanent_delete(self, document_id: int, user_id: int) -> Dict[str, Any]:
        """
        Löscht ein Dokument endgültig (nur aus Papierkorb möglich)

        Args:
            document_id: ID des Dokuments
            user_id: ID des Benutzers

        Returns:
            Dict mit Ergebnis
        """
        from database.models import get_session, Document

        session = get_session()
        try:
            doc = session.query(Document).filter_by(
                id=document_id,
                user_id=user_id,
                is_deleted=True
            ).first()

            if not doc:
                return {"success": False, "error": "Dokument nicht im Papierkorb gefunden"}

            # Physische Datei löschen
            if doc.file_path and os.path.exists(doc.file_path):
                try:
                    os.remove(doc.file_path)
                except Exception as e:
                    pass  # Datei konnte nicht gelöscht werden, trotzdem DB-Eintrag entfernen

            title = doc.title or doc.filename

            # Aus Datenbank löschen
            session.delete(doc)
            session.commit()

            return {
                "success": True,
                "message": f"Dokument '{title}' endgültig gelöscht"
            }

        except Exception as e:
            session.rollback()
            return {"success": False, "error": str(e)}
        finally:
            session.close()

    def get_trash_items(self, user_id: int) -> List[Dict[str, Any]]:
        """
        Holt alle Dokumente im Papierkorb

        Args:
            user_id: ID des Benutzers

        Returns:
            Liste von Dokumenten im Papierkorb
        """
        from database.models import get_session, Document

        session = get_session()
        try:
            docs = session.query(Document).filter_by(
                user_id=user_id,
                is_deleted=True
            ).order_by(Document.deleted_at.desc()).all()

            retention_hours = self.get_retention_hours()
            items = []

            for doc in docs:
                expires_at = doc.deleted_at + timedelta(hours=retention_hours)
                remaining = expires_at - datetime.now()

                items.append({
                    "id": doc.id,
                    "title": doc.title or doc.filename,
                    "filename": doc.filename,
                    "category": doc.category,
                    "deleted_at": doc.deleted_at,
                    "expires_at": expires_at,
                    "remaining_hours": max(0, remaining.total_seconds() / 3600),
                    "previous_folder_id": doc.previous_folder_id,
                    "file_size": doc.file_size,
                })

            return items

        finally:
            session.close()

    def empty_trash(self, user_id: int) -> Dict[str, Any]:
        """
        Leert den gesamten Papierkorb

        Args:
            user_id: ID des Benutzers

        Returns:
            Dict mit Ergebnis
        """
        from database.models import get_session, Document

        session = get_session()
        try:
            docs = session.query(Document).filter_by(
                user_id=user_id,
                is_deleted=True
            ).all()

            count = len(docs)

            for doc in docs:
                # Physische Datei löschen
                if doc.file_path and os.path.exists(doc.file_path):
                    try:
                        os.remove(doc.file_path)
                    except:
                        pass
                session.delete(doc)

            session.commit()

            return {
                "success": True,
                "message": f"{count} Dokument(e) endgültig gelöscht",
                "deleted_count": count
            }

        except Exception as e:
            session.rollback()
            return {"success": False, "error": str(e)}
        finally:
            session.close()

    def cleanup_expired(self) -> Dict[str, Any]:
        """
        Löscht alle abgelaufenen Dokumente aus dem Papierkorb
        Diese Methode sollte regelmäßig aufgerufen werden (z.B. beim App-Start)

        Returns:
            Dict mit Ergebnis
        """
        from database.models import get_session, Document

        session = get_session()
        try:
            retention_hours = self.get_retention_hours()
            expiry_threshold = datetime.now() - timedelta(hours=retention_hours)

            # Finde alle abgelaufenen Dokumente
            expired_docs = session.query(Document).filter(
                Document.is_deleted == True,
                Document.deleted_at < expiry_threshold
            ).all()

            count = len(expired_docs)
            deleted_titles = []

            for doc in expired_docs:
                deleted_titles.append(doc.title or doc.filename)

                # Physische Datei löschen
                if doc.file_path and os.path.exists(doc.file_path):
                    try:
                        os.remove(doc.file_path)
                    except:
                        pass
                session.delete(doc)

            session.commit()

            return {
                "success": True,
                "deleted_count": count,
                "deleted_titles": deleted_titles
            }

        except Exception as e:
            session.rollback()
            return {"success": False, "error": str(e), "deleted_count": 0}
        finally:
            session.close()

    def get_trash_stats(self, user_id: int) -> Dict[str, Any]:
        """
        Statistiken zum Papierkorb

        Args:
            user_id: ID des Benutzers

        Returns:
            Dict mit Statistiken
        """
        from database.models import get_session, Document
        from sqlalchemy import func

        session = get_session()
        try:
            result = session.query(
                func.count(Document.id),
                func.sum(Document.file_size)
            ).filter_by(
                user_id=user_id,
                is_deleted=True
            ).first()

            count = result[0] or 0
            total_size = result[1] or 0

            return {
                "count": count,
                "total_size_bytes": total_size,
                "total_size_mb": round(total_size / (1024 * 1024), 2) if total_size else 0,
                "retention_hours": self.get_retention_hours()
            }

        finally:
            session.close()


def get_trash_service() -> TrashService:
    """Factory-Funktion für den TrashService"""
    return TrashService()
