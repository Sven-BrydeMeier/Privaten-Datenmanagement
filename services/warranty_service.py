"""
Garantie-Tracker Service
Verwaltet Garantien und Gewährleistungen mit Ablauferinnerungen
"""
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy import and_, or_

from database.models import Document, get_session
from database.extended_models import Warranty, WarrantyStatus, InventoryItem


class WarrantyService:
    """Service für Garantieverwaltung"""

    def __init__(self, user_id: int):
        self.user_id = user_id

    def create_warranty(self, product_name: str, purchase_date: datetime,
                        warranty_end: datetime, **kwargs) -> Warranty:
        """Erstellt eine neue Garantie"""
        with get_session() as session:
            warranty = Warranty(
                user_id=self.user_id,
                product_name=product_name,
                purchase_date=purchase_date,
                warranty_end=warranty_end,
                warranty_start=kwargs.get("warranty_start", purchase_date),
                manufacturer=kwargs.get("manufacturer"),
                model_number=kwargs.get("model_number"),
                serial_number=kwargs.get("serial_number"),
                purchase_price=kwargs.get("purchase_price"),
                currency=kwargs.get("currency", "EUR"),
                retailer=kwargs.get("retailer"),
                document_id=kwargs.get("document_id"),
                receipt_document_id=kwargs.get("receipt_document_id"),
                inventory_item_id=kwargs.get("inventory_item_id"),
                warranty_contact=kwargs.get("warranty_contact"),
                warranty_phone=kwargs.get("warranty_phone"),
                warranty_email=kwargs.get("warranty_email"),
                warranty_url=kwargs.get("warranty_url"),
                extended_warranty_end=kwargs.get("extended_warranty_end"),
                notes=kwargs.get("notes"),
                reminder_days_before=kwargs.get("reminder_days_before", 30)
            )

            # Status berechnen
            warranty.status = self._calculate_status(warranty_end)

            session.add(warranty)
            session.commit()
            session.refresh(warranty)
            return warranty

    def get_warranty(self, warranty_id: int) -> Optional[Warranty]:
        """Holt eine spezifische Garantie"""
        with get_session() as session:
            return session.query(Warranty).filter(
                Warranty.id == warranty_id,
                Warranty.user_id == self.user_id
            ).first()

    def get_all_warranties(self, include_expired: bool = True) -> List[Warranty]:
        """Holt alle Garantien"""
        with get_session() as session:
            query = session.query(Warranty).filter(
                Warranty.user_id == self.user_id
            )

            if not include_expired:
                query = query.filter(Warranty.warranty_end >= datetime.now())

            return query.order_by(Warranty.warranty_end.asc()).all()

    def get_expiring_soon(self, days: int = 30) -> List[Warranty]:
        """Holt bald ablaufende Garantien"""
        with get_session() as session:
            cutoff_date = datetime.now() + timedelta(days=days)

            return session.query(Warranty).filter(
                Warranty.user_id == self.user_id,
                Warranty.warranty_end >= datetime.now(),
                Warranty.warranty_end <= cutoff_date,
                Warranty.status != WarrantyStatus.CLAIMED
            ).order_by(Warranty.warranty_end.asc()).all()

    def get_expired(self) -> List[Warranty]:
        """Holt abgelaufene Garantien"""
        with get_session() as session:
            return session.query(Warranty).filter(
                Warranty.user_id == self.user_id,
                Warranty.warranty_end < datetime.now(),
                Warranty.status != WarrantyStatus.CLAIMED
            ).order_by(Warranty.warranty_end.desc()).all()

    def get_active(self) -> List[Warranty]:
        """Holt aktive Garantien"""
        with get_session() as session:
            return session.query(Warranty).filter(
                Warranty.user_id == self.user_id,
                Warranty.warranty_end >= datetime.now(),
                Warranty.status.in_([WarrantyStatus.ACTIVE, WarrantyStatus.EXPIRING_SOON])
            ).order_by(Warranty.warranty_end.asc()).all()

    def update_warranty(self, warranty_id: int, **kwargs) -> bool:
        """Aktualisiert eine Garantie"""
        with get_session() as session:
            warranty = session.query(Warranty).filter(
                Warranty.id == warranty_id,
                Warranty.user_id == self.user_id
            ).first()

            if not warranty:
                return False

            for key, value in kwargs.items():
                if hasattr(warranty, key):
                    setattr(warranty, key, value)

            # Status neu berechnen
            if "warranty_end" in kwargs:
                warranty.status = self._calculate_status(kwargs["warranty_end"])

            warranty.updated_at = datetime.now()
            session.commit()
            return True

    def delete_warranty(self, warranty_id: int) -> bool:
        """Löscht eine Garantie"""
        with get_session() as session:
            warranty = session.query(Warranty).filter(
                Warranty.id == warranty_id,
                Warranty.user_id == self.user_id
            ).first()

            if not warranty:
                return False

            session.delete(warranty)
            session.commit()
            return True

    def mark_as_claimed(self, warranty_id: int, notes: str = None) -> bool:
        """Markiert Garantie als in Anspruch genommen"""
        with get_session() as session:
            warranty = session.query(Warranty).filter(
                Warranty.id == warranty_id,
                Warranty.user_id == self.user_id
            ).first()

            if not warranty:
                return False

            warranty.status = WarrantyStatus.CLAIMED
            if notes:
                warranty.notes = (warranty.notes or "") + f"\n\n[Garantiefall {datetime.now().strftime('%d.%m.%Y')}]: {notes}"

            warranty.updated_at = datetime.now()
            session.commit()
            return True

    def update_all_statuses(self) -> int:
        """Aktualisiert Status aller Garantien"""
        count = 0
        with get_session() as session:
            warranties = session.query(Warranty).filter(
                Warranty.user_id == self.user_id,
                Warranty.status != WarrantyStatus.CLAIMED
            ).all()

            for warranty in warranties:
                new_status = self._calculate_status(warranty.warranty_end)
                if warranty.status != new_status:
                    warranty.status = new_status
                    warranty.updated_at = datetime.now()
                    count += 1

            session.commit()

        return count

    def get_statistics(self) -> Dict[str, Any]:
        """Holt Statistiken zu Garantien"""
        with get_session() as session:
            all_warranties = session.query(Warranty).filter(
                Warranty.user_id == self.user_id
            ).all()

            active = len([w for w in all_warranties if w.status == WarrantyStatus.ACTIVE])
            expiring = len([w for w in all_warranties if w.status == WarrantyStatus.EXPIRING_SOON])
            expired = len([w for w in all_warranties if w.status == WarrantyStatus.EXPIRED])
            claimed = len([w for w in all_warranties if w.status == WarrantyStatus.CLAIMED])

            total_value = sum(w.purchase_price or 0 for w in all_warranties if w.status in [WarrantyStatus.ACTIVE, WarrantyStatus.EXPIRING_SOON])

            return {
                "total": len(all_warranties),
                "active": active,
                "expiring_soon": expiring,
                "expired": expired,
                "claimed": claimed,
                "total_protected_value": total_value,
                "next_expiring": min(
                    [w for w in all_warranties if w.warranty_end >= datetime.now()],
                    key=lambda x: x.warranty_end,
                    default=None
                )
            }

    def search_warranties(self, query: str) -> List[Warranty]:
        """Sucht in Garantien"""
        with get_session() as session:
            search_term = f"%{query}%"
            return session.query(Warranty).filter(
                Warranty.user_id == self.user_id,
                or_(
                    Warranty.product_name.ilike(search_term),
                    Warranty.manufacturer.ilike(search_term),
                    Warranty.retailer.ilike(search_term),
                    Warranty.serial_number.ilike(search_term),
                    Warranty.model_number.ilike(search_term)
                )
            ).all()

    def _calculate_status(self, warranty_end: datetime) -> WarrantyStatus:
        """Berechnet Status basierend auf Ablaufdatum"""
        now = datetime.now()
        days_until_expiry = (warranty_end - now).days

        if days_until_expiry < 0:
            return WarrantyStatus.EXPIRED
        elif days_until_expiry <= 30:
            return WarrantyStatus.EXPIRING_SOON
        else:
            return WarrantyStatus.ACTIVE

    def get_due_reminders(self) -> List[Warranty]:
        """Holt Garantien, für die eine Erinnerung fällig ist"""
        with get_session() as session:
            warranties = session.query(Warranty).filter(
                Warranty.user_id == self.user_id,
                Warranty.reminder_sent == False,
                Warranty.status.in_([WarrantyStatus.ACTIVE, WarrantyStatus.EXPIRING_SOON])
            ).all()

            due_reminders = []
            now = datetime.now()

            for warranty in warranties:
                reminder_date = warranty.warranty_end - timedelta(days=warranty.reminder_days_before or 30)
                if now >= reminder_date:
                    due_reminders.append(warranty)

            return due_reminders

    def mark_reminder_sent(self, warranty_id: int) -> bool:
        """Markiert Erinnerung als gesendet"""
        with get_session() as session:
            warranty = session.query(Warranty).filter(
                Warranty.id == warranty_id,
                Warranty.user_id == self.user_id
            ).first()

            if warranty:
                warranty.reminder_sent = True
                session.commit()
                return True

            return False
