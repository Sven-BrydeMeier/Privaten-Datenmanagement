"""
Benachrichtigungs-Service für Erinnerungen und Alerts
"""
from datetime import datetime, timedelta
from typing import Optional, List
from sqlalchemy import and_, or_

from database.db import get_db
from database.models import (
    Notification, Document, CalendarEvent, Contact, InvoiceStatus,
    EventType, User
)
from utils.helpers import send_email_notification, format_currency, format_date
from config.settings import get_settings


class NotificationService:
    """Service für Benachrichtigungen und Erinnerungen"""

    @staticmethod
    def create_notification(
        user_id: int,
        title: str,
        message: str = None,
        notification_type: str = "reminder",
        document_id: int = None,
        event_id: int = None,
        scheduled_for: datetime = None
    ) -> Notification:
        """Erstellt eine neue Benachrichtigung"""
        with get_db() as session:
            notification = Notification(
                user_id=user_id,
                title=title,
                message=message,
                notification_type=notification_type,
                document_id=document_id,
                event_id=event_id,
                scheduled_for=scheduled_for or datetime.now()
            )
            session.add(notification)
            session.commit()
            return notification

    @staticmethod
    def get_unread_notifications(user_id: int, limit: int = 20) -> List[dict]:
        """Holt ungelesene Benachrichtigungen"""
        with get_db() as session:
            notifications = session.query(Notification).filter(
                Notification.user_id == user_id,
                Notification.is_read == False,
                or_(
                    Notification.scheduled_for.is_(None),
                    Notification.scheduled_for <= datetime.now()
                )
            ).order_by(Notification.created_at.desc()).limit(limit).all()

            return [{
                'id': n.id,
                'title': n.title,
                'message': n.message,
                'type': n.notification_type,
                'document_id': n.document_id,
                'event_id': n.event_id,
                'created_at': n.created_at
            } for n in notifications]

    @staticmethod
    def mark_as_read(notification_id: int, user_id: int) -> bool:
        """Markiert eine Benachrichtigung als gelesen"""
        with get_db() as session:
            notification = session.query(Notification).filter(
                Notification.id == notification_id,
                Notification.user_id == user_id
            ).first()

            if notification:
                notification.is_read = True
                session.commit()
                return True
            return False

    @staticmethod
    def mark_all_as_read(user_id: int) -> int:
        """Markiert alle Benachrichtigungen als gelesen"""
        with get_db() as session:
            count = session.query(Notification).filter(
                Notification.user_id == user_id,
                Notification.is_read == False
            ).update({'is_read': True})
            session.commit()
            return count

    @staticmethod
    def generate_deadline_reminders(user_id: int) -> List[Notification]:
        """Generiert Erinnerungen für anstehende Fristen"""
        settings = get_settings()
        notify_days = settings.notify_days_before_deadline or [1, 3, 7]

        created = []
        now = datetime.now()

        with get_db() as session:
            # Kalender-Events prüfen
            for days in notify_days:
                target_date = now + timedelta(days=days)

                events = session.query(CalendarEvent).filter(
                    CalendarEvent.user_id == user_id,
                    CalendarEvent.start_date >= target_date.replace(hour=0, minute=0),
                    CalendarEvent.start_date < target_date.replace(hour=23, minute=59),
                    CalendarEvent.reminder_sent == False
                ).all()

                for event in events:
                    # Prüfen ob bereits eine Benachrichtigung existiert
                    existing = session.query(Notification).filter(
                        Notification.user_id == user_id,
                        Notification.event_id == event.id,
                        Notification.notification_type == 'deadline'
                    ).first()

                    if not existing:
                        notification = Notification(
                            user_id=user_id,
                            event_id=event.id,
                            title=f"⏰ Erinnerung: {event.title}",
                            message=f"In {days} Tagen: {event.title}\n{format_date(event.start_date)}",
                            notification_type='deadline',
                            scheduled_for=now
                        )
                        session.add(notification)
                        created.append(notification)

            session.commit()

        return created

    @staticmethod
    def generate_invoice_reminders(user_id: int) -> List[Notification]:
        """Generiert Erinnerungen für fällige Rechnungen"""
        created = []
        now = datetime.now()

        with get_db() as session:
            # Überfällige Rechnungen
            overdue = session.query(Document).filter(
                Document.user_id == user_id,
                Document.invoice_status == InvoiceStatus.OPEN,
                Document.invoice_due_date.isnot(None),
                Document.invoice_due_date < now
            ).all()

            for invoice in overdue:
                days_overdue = (now.date() - invoice.invoice_due_date.date()).days

                # Nur einmal pro Woche erinnern
                existing = session.query(Notification).filter(
                    Notification.user_id == user_id,
                    Notification.document_id == invoice.id,
                    Notification.notification_type == 'invoice_overdue',
                    Notification.created_at >= now - timedelta(days=7)
                ).first()

                if not existing:
                    notification = Notification(
                        user_id=user_id,
                        document_id=invoice.id,
                        title=f"🔴 Rechnung überfällig: {invoice.sender or 'Unbekannt'}",
                        message=f"{format_currency(invoice.invoice_amount)} - {days_overdue} Tage überfällig",
                        notification_type='invoice_overdue',
                        scheduled_for=now
                    )
                    session.add(notification)
                    created.append(notification)

            # Bald fällige Rechnungen (7 Tage)
            upcoming = session.query(Document).filter(
                Document.user_id == user_id,
                Document.invoice_status == InvoiceStatus.OPEN,
                Document.invoice_due_date.isnot(None),
                Document.invoice_due_date >= now,
                Document.invoice_due_date <= now + timedelta(days=7)
            ).all()

            for invoice in upcoming:
                days_left = (invoice.invoice_due_date.date() - now.date()).days

                existing = session.query(Notification).filter(
                    Notification.user_id == user_id,
                    Notification.document_id == invoice.id,
                    Notification.notification_type == 'invoice_due_soon',
                    Notification.created_at >= now - timedelta(days=3)
                ).first()

                if not existing:
                    notification = Notification(
                        user_id=user_id,
                        document_id=invoice.id,
                        title=f"🟠 Rechnung bald fällig: {invoice.sender or 'Unbekannt'}",
                        message=f"{format_currency(invoice.invoice_amount)} - Fällig in {days_left} Tagen",
                        notification_type='invoice_due_soon',
                        scheduled_for=now
                    )
                    session.add(notification)
                    created.append(notification)

            session.commit()

        return created

    @staticmethod
    def generate_contract_reminders(user_id: int) -> List[Notification]:
        """Generiert Erinnerungen für auslaufende Verträge"""
        created = []
        now = datetime.now()

        with get_db() as session:
            # Verträge die in 30, 60, 90 Tagen enden
            for days in [30, 60, 90]:
                target_date = now + timedelta(days=days)

                contracts = session.query(Document).filter(
                    Document.user_id == user_id,
                    Document.contract_end.isnot(None),
                    Document.contract_end >= target_date.replace(hour=0, minute=0),
                    Document.contract_end < target_date.replace(hour=23, minute=59)
                ).all()

                for contract in contracts:
                    existing = session.query(Notification).filter(
                        Notification.user_id == user_id,
                        Notification.document_id == contract.id,
                        Notification.notification_type == 'contract_expiring'
                    ).first()

                    if not existing:
                        notification = Notification(
                            user_id=user_id,
                            document_id=contract.id,
                            title=f"📋 Vertrag läuft aus: {contract.title or contract.sender or 'Unbekannt'}",
                            message=f"Endet in {days} Tagen am {format_date(contract.contract_end)}",
                            notification_type='contract_expiring',
                            scheduled_for=now
                        )
                        session.add(notification)
                        created.append(notification)

            session.commit()

        return created

    @staticmethod
    def generate_birthday_reminders(user_id: int) -> List[Notification]:
        """Generiert Geburtstags-Erinnerungen"""
        settings = get_settings()
        notify_days = settings.notify_birthday_days_before or 7

        created = []
        now = datetime.now()

        with get_db() as session:
            contacts = session.query(Contact).filter(
                Contact.user_id == user_id,
                Contact.birthday.isnot(None)
            ).all()

            for contact in contacts:
                # Geburtstag dieses Jahr berechnen
                bday = contact.birthday.replace(year=now.year)
                if bday.date() < now.date():
                    bday = bday.replace(year=now.year + 1)

                days_until = (bday.date() - now.date()).days

                if 0 <= days_until <= notify_days:
                    existing = session.query(Notification).filter(
                        Notification.user_id == user_id,
                        Notification.notification_type == 'birthday',
                        Notification.title.contains(contact.name),
                        Notification.created_at >= now - timedelta(days=30)
                    ).first()

                    if not existing:
                        if days_until == 0:
                            title = f"🎂 Heute Geburtstag: {contact.name}"
                        elif days_until == 1:
                            title = f"🎂 Morgen Geburtstag: {contact.name}"
                        else:
                            title = f"🎂 Geburtstag in {days_until} Tagen: {contact.name}"

                        notification = Notification(
                            user_id=user_id,
                            title=title,
                            message=f"{contact.name} hat am {bday.strftime('%d. %B')} Geburtstag",
                            notification_type='birthday',
                            scheduled_for=now
                        )
                        session.add(notification)
                        created.append(notification)

            session.commit()

        return created

    @staticmethod
    def send_email_notifications(user_id: int) -> int:
        """Sendet ausstehende E-Mail-Benachrichtigungen"""
        settings = get_settings()
        if not settings.notification_email:
            return 0

        sent_count = 0

        with get_db() as session:
            notifications = session.query(Notification).filter(
                Notification.user_id == user_id,
                Notification.is_sent_email == False,
                Notification.is_read == False,
                or_(
                    Notification.scheduled_for.is_(None),
                    Notification.scheduled_for <= datetime.now()
                )
            ).limit(10).all()

            for notification in notifications:
                success = send_email_notification(
                    settings.notification_email,
                    notification.title,
                    notification.message or notification.title,
                    None
                )

                if success:
                    notification.is_sent_email = True
                    notification.sent_at = datetime.now()
                    sent_count += 1

            session.commit()

        return sent_count

    @staticmethod
    def run_all_reminders(user_id: int) -> dict:
        """Führt alle Erinnerungs-Generatoren aus"""
        return {
            'deadlines': len(NotificationService.generate_deadline_reminders(user_id)),
            'invoices': len(NotificationService.generate_invoice_reminders(user_id)),
            'contracts': len(NotificationService.generate_contract_reminders(user_id)),
            'birthdays': len(NotificationService.generate_birthday_reminders(user_id))
        }


# Singleton-Instanz
_notification_service = None


def get_notification_service() -> NotificationService:
    """Gibt die Singleton-Instanz des Notification-Service zurück"""
    global _notification_service
    if _notification_service is None:
        _notification_service = NotificationService()
    return _notification_service
