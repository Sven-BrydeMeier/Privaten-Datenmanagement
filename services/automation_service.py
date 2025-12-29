"""
Rule-Based Document Automation Service
Automatische Verarbeitung von Dokumenten basierend auf Regeln
"""
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import re
import json

from database.models import (
    get_session, Document, Folder, ClassificationRule,
    CalendarEvent, Notification, EventType, InvoiceStatus
)


class AutomationRule:
    """Basisklasse für Automatisierungsregeln"""

    def __init__(self, rule_data: Dict[str, Any]):
        self.id = rule_data.get("id")
        self.name = rule_data.get("name", "Unbenannte Regel")
        self.description = rule_data.get("description", "")
        self.is_active = rule_data.get("is_active", True)
        self.conditions = rule_data.get("conditions", {})
        self.actions = rule_data.get("actions", {})

    def matches(self, document: Document) -> bool:
        """Prüft ob die Regel auf das Dokument zutrifft"""
        raise NotImplementedError

    def execute(self, document: Document, session) -> Dict[str, Any]:
        """Führt die Regel-Aktionen aus"""
        raise NotImplementedError


class AutomationService:
    """Service für regelbasierte Dokumentenautomatisierung"""

    def __init__(self):
        pass

    def get_default_rules(self) -> List[Dict[str, Any]]:
        """Gibt Standard-Automatisierungsregeln zurück"""
        return [
            {
                "id": "invoice_deadline",
                "name": "Rechnungs-Erinnerung",
                "description": "Erstellt Erinnerungen für fällige Rechnungen",
                "is_active": True,
                "conditions": {
                    "category": ["Rechnung", "Mahnung"],
                    "has_due_date": True
                },
                "actions": {
                    "create_reminder": True,
                    "reminder_days_before": [7, 3, 1]
                }
            },
            {
                "id": "contract_notice",
                "name": "Vertrags-Kündigungsfrist",
                "description": "Warnt vor ablaufenden Kündigungsfristen",
                "is_active": True,
                "conditions": {
                    "category": ["Vertrag", "Versicherung"],
                    "has_contract_end": True
                },
                "actions": {
                    "create_reminder": True,
                    "reminder_days_before": [60, 30, 14]
                }
            },
            {
                "id": "auto_folder_sender",
                "name": "Automatische Ordnerzuweisung",
                "description": "Ordnet Dokumente automatisch basierend auf Absender zu",
                "is_active": True,
                "conditions": {
                    "has_sender": True
                },
                "actions": {
                    "auto_folder": True,
                    "create_folder_if_missing": True
                }
            },
            {
                "id": "overdue_invoice_alert",
                "name": "Überfällige Rechnungen markieren",
                "description": "Markiert Rechnungen als überfällig nach Fälligkeit",
                "is_active": True,
                "conditions": {
                    "category": ["Rechnung"],
                    "invoice_status": ["open"],
                    "due_date_passed": True
                },
                "actions": {
                    "set_invoice_status": "overdue",
                    "create_notification": True
                }
            },
            {
                "id": "insurance_reminder",
                "name": "Versicherungs-Jahresbeitrag",
                "description": "Erinnert an jährliche Versicherungszahlungen",
                "is_active": True,
                "conditions": {
                    "category": ["Versicherung", "Lebensversicherung"]
                },
                "actions": {
                    "track_recurring": True,
                    "create_yearly_reminder": True
                }
            }
        ]

    def process_new_document(
        self,
        document_id: int,
        user_id: int
    ) -> Dict[str, Any]:
        """
        Verarbeitet ein neues Dokument mit allen aktiven Regeln

        Args:
            document_id: ID des Dokuments
            user_id: Benutzer-ID

        Returns:
            Dict mit angewandten Regeln und Aktionen
        """
        session = get_session()
        try:
            doc = session.query(Document).filter_by(
                id=document_id,
                user_id=user_id
            ).first()

            if not doc:
                return {"error": "Dokument nicht gefunden"}

            results = {
                "document_id": document_id,
                "rules_applied": [],
                "actions_taken": []
            }

            rules = self.get_default_rules()

            for rule in rules:
                if not rule["is_active"]:
                    continue

                if self._check_conditions(doc, rule["conditions"]):
                    actions = self._execute_actions(doc, rule["actions"], user_id, session)
                    if actions:
                        results["rules_applied"].append(rule["name"])
                        results["actions_taken"].extend(actions)

            session.commit()
            return results

        except Exception as e:
            session.rollback()
            return {"error": str(e)}
        finally:
            session.close()

    def _check_conditions(self, doc: Document, conditions: Dict) -> bool:
        """Prüft ob alle Bedingungen erfüllt sind"""

        # Kategorie-Prüfung
        if "category" in conditions:
            if doc.category not in conditions["category"]:
                return False

        # Absender vorhanden
        if conditions.get("has_sender"):
            if not doc.sender:
                return False

        # Fälligkeitsdatum vorhanden
        if conditions.get("has_due_date"):
            if not doc.invoice_due_date:
                return False

        # Vertragsende vorhanden
        if conditions.get("has_contract_end"):
            if not doc.contract_end:
                return False

        # Rechnungsstatus
        if "invoice_status" in conditions:
            if doc.invoice_status:
                if doc.invoice_status.value not in conditions["invoice_status"]:
                    return False
            elif "open" not in conditions["invoice_status"]:
                return False

        # Fälligkeit überschritten
        if conditions.get("due_date_passed"):
            if not doc.invoice_due_date or doc.invoice_due_date > datetime.now():
                return False

        return True

    def _execute_actions(
        self,
        doc: Document,
        actions: Dict,
        user_id: int,
        session
    ) -> List[str]:
        """Führt die definierten Aktionen aus"""
        executed = []

        # Erinnerungen erstellen
        if actions.get("create_reminder"):
            days_before = actions.get("reminder_days_before", [7, 1])
            ref_date = doc.invoice_due_date or doc.contract_end

            if ref_date:
                for days in days_before:
                    reminder_date = ref_date - timedelta(days=days)
                    if reminder_date > datetime.now():
                        self._create_calendar_reminder(
                            doc, user_id, reminder_date, days, session
                        )
                        executed.append(f"Erinnerung {days} Tage vorher erstellt")

        # Automatische Ordnerzuweisung
        if actions.get("auto_folder") and doc.sender:
            result = self._auto_assign_folder(doc, user_id, session,
                                              actions.get("create_folder_if_missing", False))
            if result:
                executed.append(result)

        # Rechnungsstatus setzen
        if "set_invoice_status" in actions:
            new_status = actions["set_invoice_status"]
            if new_status == "overdue":
                doc.invoice_status = InvoiceStatus.OVERDUE
                executed.append("Als überfällig markiert")

        # Benachrichtigung erstellen
        if actions.get("create_notification"):
            self._create_notification(doc, user_id, session)
            executed.append("Benachrichtigung erstellt")

        # Jährliche Erinnerung
        if actions.get("create_yearly_reminder") and doc.document_date:
            self._create_yearly_reminder(doc, user_id, session)
            executed.append("Jährliche Erinnerung erstellt")

        return executed

    def _create_calendar_reminder(
        self,
        doc: Document,
        user_id: int,
        reminder_date: datetime,
        days_before: int,
        session
    ):
        """Erstellt einen Kalender-Eintrag als Erinnerung"""
        # Prüfe ob bereits vorhanden
        existing = session.query(CalendarEvent).filter_by(
            document_id=doc.id,
            start_date=reminder_date,
            event_type=EventType.DEADLINE
        ).first()

        if existing:
            return

        title = f"⚠️ {doc.title or doc.filename}"
        if days_before == 1:
            title = f"❗ MORGEN: {doc.title or doc.filename}"
        elif days_before <= 3:
            title = f"⏰ In {days_before} Tagen: {doc.title or doc.filename}"

        description = f"Fällig: {doc.invoice_due_date or doc.contract_end}"
        if doc.invoice_amount:
            description += f"\nBetrag: {doc.invoice_amount:.2f} EUR"

        event = CalendarEvent(
            user_id=user_id,
            document_id=doc.id,
            title=title,
            description=description,
            event_type=EventType.DEADLINE,
            start_date=reminder_date,
            all_day=True,
            reminder_days_before=0
        )
        session.add(event)

    def _auto_assign_folder(
        self,
        doc: Document,
        user_id: int,
        session,
        create_if_missing: bool
    ) -> Optional[str]:
        """Ordnet Dokument automatisch einem Ordner zu"""
        if doc.folder_id:
            return None  # Bereits in einem Ordner

        sender = doc.sender or ""

        # Suche passenden Ordner
        folder = session.query(Folder).filter(
            Folder.user_id == user_id,
            Folder.name.ilike(f"%{sender}%")
        ).first()

        if not folder and create_if_missing and sender:
            # Erstelle neuen Ordner für Absender
            folder = Folder(
                user_id=user_id,
                name=sender,
                is_system=False,
                icon="📁"
            )
            session.add(folder)
            session.flush()

        if folder:
            doc.folder_id = folder.id
            return f"Ordner zugewiesen: {folder.name}"

        return None

    def _create_notification(
        self,
        doc: Document,
        user_id: int,
        session
    ):
        """Erstellt eine Benachrichtigung"""
        title = f"Aktion erforderlich: {doc.title or doc.filename}"
        message = f"Kategorie: {doc.category}"

        if doc.invoice_due_date:
            message += f"\nFällig: {doc.invoice_due_date.strftime('%d.%m.%Y')}"
        if doc.invoice_amount:
            message += f"\nBetrag: {doc.invoice_amount:.2f} EUR"

        notification = Notification(
            user_id=user_id,
            document_id=doc.id,
            title=title,
            message=message,
            notification_type="invoice" if doc.category == "Rechnung" else "document",
            scheduled_for=datetime.now()
        )
        session.add(notification)

    def _create_yearly_reminder(
        self,
        doc: Document,
        user_id: int,
        session
    ):
        """Erstellt eine jährliche Erinnerung"""
        # Nächstes Datum basierend auf Original-Dokumentdatum
        original_date = doc.document_date or doc.created_at
        next_date = original_date.replace(year=datetime.now().year)

        if next_date < datetime.now():
            next_date = next_date.replace(year=datetime.now().year + 1)

        # Erinnerung 14 Tage vorher
        reminder_date = next_date - timedelta(days=14)

        event = CalendarEvent(
            user_id=user_id,
            document_id=doc.id,
            title=f"📅 Jährlich: {doc.title or doc.sender}",
            description=f"Jährliche Zahlung für {doc.sender}",
            event_type=EventType.REMINDER,
            start_date=reminder_date,
            all_day=True,
            is_recurring=True,
            recurrence_rule="FREQ=YEARLY"
        )
        session.add(event)

    def run_scheduled_tasks(self, user_id: int) -> Dict[str, Any]:
        """
        Führt geplante Automatisierungsaufgaben aus

        Returns:
            Dict mit durchgeführten Aktionen
        """
        session = get_session()
        try:
            results = {
                "overdue_marked": 0,
                "reminders_sent": 0,
                "documents_processed": 0
            }

            # 1. Überfällige Rechnungen markieren
            overdue_docs = session.query(Document).filter(
                Document.user_id == user_id,
                Document.invoice_due_date < datetime.now(),
                Document.invoice_status.in_([InvoiceStatus.OPEN, None]),
                Document.is_deleted == False
            ).all()

            for doc in overdue_docs:
                doc.invoice_status = InvoiceStatus.OVERDUE
                results["overdue_marked"] += 1

            # 2. Anstehende Erinnerungen prüfen
            upcoming_events = session.query(CalendarEvent).filter(
                CalendarEvent.user_id == user_id,
                CalendarEvent.start_date <= datetime.now() + timedelta(days=1),
                CalendarEvent.start_date >= datetime.now(),
                CalendarEvent.reminder_sent == False
            ).all()

            for event in upcoming_events:
                # Benachrichtigung erstellen
                notification = Notification(
                    user_id=user_id,
                    document_id=event.document_id,
                    event_id=event.id,
                    title=f"⏰ {event.title}",
                    message=event.description,
                    notification_type="reminder",
                    scheduled_for=datetime.now()
                )
                session.add(notification)
                event.reminder_sent = True
                results["reminders_sent"] += 1

            session.commit()
            return {"success": True, "results": results}

        except Exception as e:
            session.rollback()
            return {"error": str(e)}
        finally:
            session.close()

    def get_automation_statistics(self, user_id: int) -> Dict[str, Any]:
        """Gibt Statistiken zur Automatisierung zurück"""
        session = get_session()
        try:
            # Aktive Erinnerungen
            active_reminders = session.query(CalendarEvent).filter(
                CalendarEvent.user_id == user_id,
                CalendarEvent.start_date >= datetime.now(),
                CalendarEvent.event_type.in_([EventType.DEADLINE, EventType.REMINDER])
            ).count()

            # Überfällige Dokumente
            overdue_count = session.query(Document).filter(
                Document.user_id == user_id,
                Document.invoice_status == InvoiceStatus.OVERDUE,
                Document.is_deleted == False
            ).count()

            # Ungelesene Benachrichtigungen
            unread_notifications = session.query(Notification).filter(
                Notification.user_id == user_id,
                Notification.is_read == False
            ).count()

            # Dokumente ohne Ordner
            unorganized = session.query(Document).filter(
                Document.user_id == user_id,
                Document.folder_id.is_(None),
                Document.is_deleted == False
            ).count()

            return {
                "active_reminders": active_reminders,
                "overdue_documents": overdue_count,
                "unread_notifications": unread_notifications,
                "unorganized_documents": unorganized
            }

        finally:
            session.close()


def get_automation_service() -> AutomationService:
    """Factory-Funktion für den AutomationService"""
    return AutomationService()
