"""
Audit-Service für Protokollierung aller wichtigen Aktionen
"""
from datetime import datetime, timedelta
from typing import Optional, List, Any
import json

from database.db import get_db
from database.models import AuditLog


class AuditService:
    """Service für Audit-Logging"""

    # Aktionstypen
    ACTION_CREATE = "create"
    ACTION_UPDATE = "update"
    ACTION_DELETE = "delete"
    ACTION_VIEW = "view"
    ACTION_DOWNLOAD = "download"
    ACTION_SHARE = "share"
    ACTION_LOGIN = "login"
    ACTION_LOGOUT = "logout"

    # Entity-Typen
    ENTITY_DOCUMENT = "document"
    ENTITY_FOLDER = "folder"
    ENTITY_CONTACT = "contact"
    ENTITY_RECEIPT = "receipt"
    ENTITY_EVENT = "calendar_event"
    ENTITY_USER = "user"
    ENTITY_BANK_ACCOUNT = "bank_account"

    @staticmethod
    def log(
        user_id: int,
        entity_type: str,
        entity_id: int,
        action: str,
        action_detail: str = None,
        old_values: dict = None,
        new_values: dict = None,
        ip_address: str = None,
        user_agent: str = None
    ) -> AuditLog:
        """Erstellt einen Audit-Log-Eintrag"""
        with get_db() as session:
            log_entry = AuditLog(
                user_id=user_id,
                entity_type=entity_type,
                entity_id=entity_id,
                action=action,
                action_detail=action_detail,
                old_values=old_values,
                new_values=new_values,
                ip_address=ip_address,
                user_agent=user_agent
            )
            session.add(log_entry)
            session.commit()
            return log_entry

    @staticmethod
    def log_document_action(
        user_id: int,
        document_id: int,
        action: str,
        detail: str = None,
        old_values: dict = None,
        new_values: dict = None
    ) -> AuditLog:
        """Loggt eine Dokumenten-Aktion"""
        return AuditService.log(
            user_id=user_id,
            entity_type=AuditService.ENTITY_DOCUMENT,
            entity_id=document_id,
            action=action,
            action_detail=detail,
            old_values=old_values,
            new_values=new_values
        )

    @staticmethod
    def get_logs(
        user_id: int = None,
        entity_type: str = None,
        entity_id: int = None,
        action: str = None,
        from_date: datetime = None,
        to_date: datetime = None,
        limit: int = 100
    ) -> List[dict]:
        """Holt Audit-Logs mit optionalen Filtern"""
        with get_db() as session:
            query = session.query(AuditLog)

            if user_id:
                query = query.filter(AuditLog.user_id == user_id)
            if entity_type:
                query = query.filter(AuditLog.entity_type == entity_type)
            if entity_id:
                query = query.filter(AuditLog.entity_id == entity_id)
            if action:
                query = query.filter(AuditLog.action == action)
            if from_date:
                query = query.filter(AuditLog.created_at >= from_date)
            if to_date:
                query = query.filter(AuditLog.created_at <= to_date)

            logs = query.order_by(AuditLog.created_at.desc()).limit(limit).all()

            return [{
                'id': log.id,
                'user_id': log.user_id,
                'entity_type': log.entity_type,
                'entity_id': log.entity_id,
                'action': log.action,
                'action_detail': log.action_detail,
                'old_values': log.old_values,
                'new_values': log.new_values,
                'ip_address': log.ip_address,
                'created_at': log.created_at.isoformat() if log.created_at else None
            } for log in logs]

    @staticmethod
    def get_document_history(document_id: int, limit: int = 50) -> List[dict]:
        """Holt die Historie eines Dokuments"""
        return AuditService.get_logs(
            entity_type=AuditService.ENTITY_DOCUMENT,
            entity_id=document_id,
            limit=limit
        )

    @staticmethod
    def get_user_activity(user_id: int, days: int = 30, limit: int = 100) -> List[dict]:
        """Holt die Aktivität eines Benutzers"""
        from_date = datetime.now() - timedelta(days=days)
        return AuditService.get_logs(
            user_id=user_id,
            from_date=from_date,
            limit=limit
        )

    @staticmethod
    def get_action_icon(action: str) -> str:
        """Gibt ein Icon für die Aktion zurück"""
        icons = {
            'create': '➕',
            'update': '✏️',
            'delete': '🗑️',
            'view': '👁️',
            'download': '⬇️',
            'share': '🔗',
            'login': '🔑',
            'logout': '🚪'
        }
        return icons.get(action, '📝')

    @staticmethod
    def get_entity_icon(entity_type: str) -> str:
        """Gibt ein Icon für den Entity-Typ zurück"""
        icons = {
            'document': '📄',
            'folder': '📁',
            'contact': '👤',
            'receipt': '🧾',
            'calendar_event': '📅',
            'user': '👤',
            'bank_account': '🏦'
        }
        return icons.get(entity_type, '📋')

    @staticmethod
    def format_log_entry(log: dict) -> str:
        """Formatiert einen Log-Eintrag für die Anzeige"""
        action_icon = AuditService.get_action_icon(log['action'])
        entity_icon = AuditService.get_entity_icon(log['entity_type'])

        action_text = {
            'create': 'erstellt',
            'update': 'geändert',
            'delete': 'gelöscht',
            'view': 'angesehen',
            'download': 'heruntergeladen',
            'share': 'geteilt',
            'login': 'angemeldet',
            'logout': 'abgemeldet'
        }.get(log['action'], log['action'])

        entity_text = {
            'document': 'Dokument',
            'folder': 'Ordner',
            'contact': 'Kontakt',
            'receipt': 'Bon',
            'calendar_event': 'Termin',
            'user': 'Benutzer',
            'bank_account': 'Bankkonto'
        }.get(log['entity_type'], log['entity_type'])

        detail = f" - {log['action_detail']}" if log['action_detail'] else ""

        return f"{action_icon} {entity_icon} {entity_text} {action_text}{detail}"

    @staticmethod
    def cleanup_old_logs(days: int = 365) -> int:
        """Löscht alte Audit-Logs"""
        cutoff = datetime.now() - timedelta(days=days)

        with get_db() as session:
            count = session.query(AuditLog).filter(
                AuditLog.created_at < cutoff
            ).delete()
            session.commit()
            return count


# Singleton-Instanz
_audit_service = None


def get_audit_service() -> AuditService:
    """Gibt die Singleton-Instanz des Audit-Service zurück"""
    global _audit_service
    if _audit_service is None:
        _audit_service = AuditService()
    return _audit_service
