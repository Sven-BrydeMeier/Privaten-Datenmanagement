"""
Document Sharing Service - Temporäre Freigabe-Links
"""
from datetime import datetime, timedelta
from typing import Optional, List
import secrets
import hashlib

from database.db import get_db
from database.models import DocumentShare, Document


class ShareService:
    """Service für Dokument-Freigaben"""

    @staticmethod
    def generate_token() -> str:
        """Generiert einen sicheren, einzigartigen Token"""
        return secrets.token_urlsafe(32)

    @staticmethod
    def create_share_link(
        user_id: int,
        document_id: int,
        description: str = None,
        expires_hours: int = 24,
        max_views: int = None,
        allow_download: bool = True
    ) -> dict:
        """
        Erstellt einen temporären Freigabe-Link für ein Dokument.

        Returns:
            dict mit 'token', 'url', 'expires_at'
        """
        with get_db() as session:
            # Prüfen ob Dokument existiert und dem Benutzer gehört
            document = session.query(Document).filter(
                Document.id == document_id,
                Document.user_id == user_id
            ).first()

            if not document:
                raise ValueError("Dokument nicht gefunden oder keine Berechtigung")

            # Token generieren
            token = ShareService.generate_token()

            # Ablaufzeit berechnen
            expires_at = datetime.now() + timedelta(hours=expires_hours)

            # Share-Eintrag erstellen
            share = DocumentShare(
                document_id=document_id,
                user_id=user_id,
                share_token=token,
                description=description,
                expires_at=expires_at,
                max_views=max_views,
                allow_download=allow_download,
                is_active=True
            )
            session.add(share)
            session.commit()

            return {
                'id': share.id,
                'token': token,
                'expires_at': expires_at,
                'max_views': max_views,
                'allow_download': allow_download
            }

    @staticmethod
    def get_shared_document(token: str) -> Optional[dict]:
        """
        Holt ein geteiltes Dokument anhand des Tokens.

        Returns:
            dict mit Dokument-Informationen oder None
        """
        with get_db() as session:
            share = session.query(DocumentShare).filter(
                DocumentShare.share_token == token,
                DocumentShare.is_active == True
            ).first()

            if not share:
                return None

            # Prüfen ob abgelaufen
            if share.expires_at < datetime.now():
                share.is_active = False
                session.commit()
                return None

            # Prüfen ob max_views erreicht
            if share.max_views and share.view_count >= share.max_views:
                share.is_active = False
                session.commit()
                return None

            # View-Count erhöhen
            share.view_count += 1
            share.last_accessed = datetime.now()
            session.commit()

            document = share.document

            return {
                'id': document.id,
                'title': document.title or document.filename,
                'filename': document.filename,
                'file_path': document.file_path,
                'mime_type': document.mime_type,
                'sender': document.sender,
                'category': document.category,
                'document_date': document.document_date,
                'allow_download': share.allow_download,
                'views_remaining': (share.max_views - share.view_count) if share.max_views else None,
                'expires_at': share.expires_at
            }

    @staticmethod
    def get_user_shares(user_id: int, include_expired: bool = False) -> List[dict]:
        """Holt alle Freigaben eines Benutzers"""
        with get_db() as session:
            query = session.query(DocumentShare).filter(
                DocumentShare.user_id == user_id
            )

            if not include_expired:
                query = query.filter(
                    DocumentShare.is_active == True,
                    DocumentShare.expires_at > datetime.now()
                )

            shares = query.order_by(DocumentShare.created_at.desc()).all()

            return [{
                'id': share.id,
                'token': share.share_token,
                'document_id': share.document_id,
                'document_title': share.document.title or share.document.filename if share.document else 'Unbekannt',
                'description': share.description,
                'expires_at': share.expires_at,
                'max_views': share.max_views,
                'view_count': share.view_count,
                'allow_download': share.allow_download,
                'is_active': share.is_active,
                'created_at': share.created_at,
                'last_accessed': share.last_accessed
            } for share in shares]

    @staticmethod
    def deactivate_share(share_id: int, user_id: int) -> bool:
        """Deaktiviert eine Freigabe"""
        with get_db() as session:
            share = session.query(DocumentShare).filter(
                DocumentShare.id == share_id,
                DocumentShare.user_id == user_id
            ).first()

            if share:
                share.is_active = False
                session.commit()
                return True
            return False

    @staticmethod
    def extend_share(share_id: int, user_id: int, additional_hours: int = 24) -> Optional[dict]:
        """Verlängert eine Freigabe"""
        with get_db() as session:
            share = session.query(DocumentShare).filter(
                DocumentShare.id == share_id,
                DocumentShare.user_id == user_id
            ).first()

            if share:
                share.expires_at = max(share.expires_at, datetime.now()) + timedelta(hours=additional_hours)
                share.is_active = True
                session.commit()

                return {
                    'id': share.id,
                    'token': share.share_token,
                    'expires_at': share.expires_at
                }
            return None

    @staticmethod
    def cleanup_expired_shares(days_old: int = 30) -> int:
        """Löscht alte, abgelaufene Freigaben"""
        cutoff = datetime.now() - timedelta(days=days_old)

        with get_db() as session:
            count = session.query(DocumentShare).filter(
                DocumentShare.expires_at < cutoff,
                DocumentShare.is_active == False
            ).delete()
            session.commit()
            return count

    @staticmethod
    def get_share_stats(user_id: int) -> dict:
        """Statistiken über Freigaben"""
        with get_db() as session:
            total = session.query(DocumentShare).filter(
                DocumentShare.user_id == user_id
            ).count()

            active = session.query(DocumentShare).filter(
                DocumentShare.user_id == user_id,
                DocumentShare.is_active == True,
                DocumentShare.expires_at > datetime.now()
            ).count()

            total_views = session.query(DocumentShare).filter(
                DocumentShare.user_id == user_id
            ).with_entities(
                # Sum of view_count
            ).all()

            views = sum(s.view_count for s in session.query(DocumentShare).filter(
                DocumentShare.user_id == user_id
            ).all())

            return {
                'total_shares': total,
                'active_shares': active,
                'expired_shares': total - active,
                'total_views': views
            }


# Singleton-Instanz
_share_service = None


def get_share_service() -> ShareService:
    """Gibt die Singleton-Instanz des Share-Service zurück"""
    global _share_service
    if _share_service is None:
        _share_service = ShareService()
    return _share_service
