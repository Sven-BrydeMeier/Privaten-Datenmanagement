"""
Haushalts-Inventar Service
Verwaltet Inventar mit Wertberechnung und Versicherungsnachweis
"""
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy import or_
import uuid

from database.models import Document, get_session
from database.extended_models import InventoryItem, Warranty


class InventoryService:
    """Service für Haushalts-Inventar"""

    # Kategorien für Inventar
    CATEGORIES = {
        "electronics": "Elektronik",
        "furniture": "Möbel",
        "appliances": "Haushaltsgeräte",
        "kitchen": "Küche",
        "clothing": "Kleidung",
        "jewelry": "Schmuck",
        "sports": "Sport & Freizeit",
        "tools": "Werkzeug",
        "garden": "Garten",
        "art": "Kunst & Deko",
        "books": "Bücher & Medien",
        "toys": "Spielzeug",
        "vehicles": "Fahrzeuge",
        "other": "Sonstiges"
    }

    # Räume
    ROOMS = [
        "Wohnzimmer", "Schlafzimmer", "Kinderzimmer", "Küche",
        "Badezimmer", "Arbeitszimmer", "Flur", "Keller",
        "Dachboden", "Garage", "Garten", "Balkon"
    ]

    def __init__(self, user_id: int):
        self.user_id = user_id

    def create_item(self, name: str, **kwargs) -> InventoryItem:
        """Erstellt einen neuen Inventargegenstand"""
        with get_session() as session:
            # QR-Code generieren
            qr_code = f"INV-{uuid.uuid4().hex[:8].upper()}"

            item = InventoryItem(
                user_id=self.user_id,
                name=name,
                qr_code=qr_code,
                description=kwargs.get("description"),
                category=kwargs.get("category"),
                manufacturer=kwargs.get("manufacturer"),
                model=kwargs.get("model"),
                serial_number=kwargs.get("serial_number"),
                purchase_date=kwargs.get("purchase_date"),
                purchase_price=kwargs.get("purchase_price"),
                currency=kwargs.get("currency", "EUR"),
                retailer=kwargs.get("retailer"),
                current_value=kwargs.get("current_value") or kwargs.get("purchase_price"),
                depreciation_rate=kwargs.get("depreciation_rate", 0.1),
                location=kwargs.get("location"),
                room=kwargs.get("room"),
                condition=kwargs.get("condition", "good"),
                image_paths=kwargs.get("image_paths"),
                document_id=kwargs.get("document_id"),
                notes=kwargs.get("notes")
            )

            session.add(item)
            session.commit()
            session.refresh(item)
            return item

    def get_item(self, item_id: int) -> Optional[InventoryItem]:
        """Holt einen spezifischen Gegenstand"""
        with get_session() as session:
            return session.query(InventoryItem).filter(
                InventoryItem.id == item_id,
                InventoryItem.user_id == self.user_id
            ).first()

    def get_item_by_qr(self, qr_code: str) -> Optional[InventoryItem]:
        """Holt Gegenstand per QR-Code"""
        with get_session() as session:
            return session.query(InventoryItem).filter(
                InventoryItem.qr_code == qr_code,
                InventoryItem.user_id == self.user_id
            ).first()

    def get_all_items(self, include_disposed: bool = False) -> List[InventoryItem]:
        """Holt alle Inventargegenstände"""
        with get_session() as session:
            query = session.query(InventoryItem).filter(
                InventoryItem.user_id == self.user_id
            )

            if not include_disposed:
                query = query.filter(InventoryItem.is_active == True)

            return query.order_by(InventoryItem.name.asc()).all()

    def get_by_category(self, category: str) -> List[InventoryItem]:
        """Holt Gegenstände nach Kategorie"""
        with get_session() as session:
            return session.query(InventoryItem).filter(
                InventoryItem.user_id == self.user_id,
                InventoryItem.category == category,
                InventoryItem.is_active == True
            ).order_by(InventoryItem.name.asc()).all()

    def get_by_room(self, room: str) -> List[InventoryItem]:
        """Holt Gegenstände nach Raum"""
        with get_session() as session:
            return session.query(InventoryItem).filter(
                InventoryItem.user_id == self.user_id,
                InventoryItem.room == room,
                InventoryItem.is_active == True
            ).order_by(InventoryItem.name.asc()).all()

    def update_item(self, item_id: int, **kwargs) -> bool:
        """Aktualisiert einen Gegenstand"""
        with get_session() as session:
            item = session.query(InventoryItem).filter(
                InventoryItem.id == item_id,
                InventoryItem.user_id == self.user_id
            ).first()

            if not item:
                return False

            for key, value in kwargs.items():
                if hasattr(item, key):
                    setattr(item, key, value)

            item.updated_at = datetime.now()
            session.commit()
            return True

    def delete_item(self, item_id: int) -> bool:
        """Löscht einen Gegenstand"""
        with get_session() as session:
            item = session.query(InventoryItem).filter(
                InventoryItem.id == item_id,
                InventoryItem.user_id == self.user_id
            ).first()

            if not item:
                return False

            session.delete(item)
            session.commit()
            return True

    def dispose_item(self, item_id: int, reason: str) -> bool:
        """Markiert Gegenstand als entsorgt/verkauft"""
        with get_session() as session:
            item = session.query(InventoryItem).filter(
                InventoryItem.id == item_id,
                InventoryItem.user_id == self.user_id
            ).first()

            if not item:
                return False

            item.is_active = False
            item.disposed_date = datetime.now()
            item.disposed_reason = reason
            item.updated_at = datetime.now()
            session.commit()
            return True

    def search_items(self, query: str) -> List[InventoryItem]:
        """Sucht in Inventar"""
        with get_session() as session:
            search_term = f"%{query}%"
            return session.query(InventoryItem).filter(
                InventoryItem.user_id == self.user_id,
                InventoryItem.is_active == True,
                or_(
                    InventoryItem.name.ilike(search_term),
                    InventoryItem.manufacturer.ilike(search_term),
                    InventoryItem.model.ilike(search_term),
                    InventoryItem.serial_number.ilike(search_term),
                    InventoryItem.description.ilike(search_term)
                )
            ).all()

    # ==================== WERTBERECHNUNG ====================

    def calculate_current_value(self, item: InventoryItem) -> float:
        """Berechnet aktuellen Wert mit Abschreibung"""
        if not item.purchase_price or not item.purchase_date:
            return item.current_value or 0

        years = (datetime.now() - item.purchase_date).days / 365
        depreciation_rate = item.depreciation_rate or 0.1

        # Lineare Abschreibung
        current = item.purchase_price * (1 - (depreciation_rate * years))
        return max(0, round(current, 2))

    def update_all_values(self) -> int:
        """Aktualisiert alle Werte"""
        count = 0
        with get_session() as session:
            items = session.query(InventoryItem).filter(
                InventoryItem.user_id == self.user_id,
                InventoryItem.is_active == True
            ).all()

            for item in items:
                new_value = self.calculate_current_value(item)
                if item.current_value != new_value:
                    item.current_value = new_value
                    count += 1

            session.commit()

        return count

    def get_total_value(self) -> float:
        """Berechnet Gesamtwert des Inventars"""
        with get_session() as session:
            items = session.query(InventoryItem).filter(
                InventoryItem.user_id == self.user_id,
                InventoryItem.is_active == True
            ).all()

            return sum(self.calculate_current_value(item) for item in items)

    def get_value_by_category(self) -> Dict[str, float]:
        """Berechnet Wert nach Kategorie"""
        with get_session() as session:
            items = session.query(InventoryItem).filter(
                InventoryItem.user_id == self.user_id,
                InventoryItem.is_active == True
            ).all()

            values = {}
            for item in items:
                cat = item.category or "other"
                values[cat] = values.get(cat, 0) + self.calculate_current_value(item)

            return {k: round(v, 2) for k, v in sorted(values.items(), key=lambda x: -x[1])}

    def get_value_by_room(self) -> Dict[str, float]:
        """Berechnet Wert nach Raum"""
        with get_session() as session:
            items = session.query(InventoryItem).filter(
                InventoryItem.user_id == self.user_id,
                InventoryItem.is_active == True
            ).all()

            values = {}
            for item in items:
                room = item.room or "Unbekannt"
                values[room] = values.get(room, 0) + self.calculate_current_value(item)

            return {k: round(v, 2) for k, v in sorted(values.items(), key=lambda x: -x[1])}

    # ==================== STATISTIKEN ====================

    def get_statistics(self) -> Dict[str, Any]:
        """Holt Statistiken zum Inventar"""
        with get_session() as session:
            all_items = session.query(InventoryItem).filter(
                InventoryItem.user_id == self.user_id
            ).all()

            active = [i for i in all_items if i.is_active]
            disposed = [i for i in all_items if not i.is_active]

            total_purchase = sum(i.purchase_price or 0 for i in active)
            total_current = self.get_total_value()

            # Verknüpfte Garantien
            warranties = session.query(Warranty).filter(
                Warranty.user_id == self.user_id,
                Warranty.inventory_item_id.in_([i.id for i in active])
            ).all()

            return {
                "total_items": len(all_items),
                "active_items": len(active),
                "disposed_items": len(disposed),
                "total_purchase_value": round(total_purchase, 2),
                "total_current_value": round(total_current, 2),
                "depreciation": round(total_purchase - total_current, 2),
                "items_with_warranty": len(warranties),
                "categories": len(set(i.category for i in active if i.category)),
                "rooms": len(set(i.room for i in active if i.room)),
                "value_by_category": self.get_value_by_category(),
                "value_by_room": self.get_value_by_room()
            }

    def get_insurance_report(self) -> Dict[str, Any]:
        """Erstellt Bericht für Versicherung"""
        with get_session() as session:
            items = session.query(InventoryItem).filter(
                InventoryItem.user_id == self.user_id,
                InventoryItem.is_active == True
            ).all()

            report = {
                "generated_at": datetime.now().isoformat(),
                "total_items": len(items),
                "total_value": self.get_total_value(),
                "by_category": {},
                "high_value_items": [],
                "items": []
            }

            for item in items:
                value = self.calculate_current_value(item)

                # Kategoriezusammenfassung
                cat = item.category or "other"
                if cat not in report["by_category"]:
                    report["by_category"][cat] = {"count": 0, "value": 0}
                report["by_category"][cat]["count"] += 1
                report["by_category"][cat]["value"] += value

                # High-Value Items (> 500€)
                if value > 500:
                    report["high_value_items"].append({
                        "name": item.name,
                        "manufacturer": item.manufacturer,
                        "model": item.model,
                        "serial_number": item.serial_number,
                        "purchase_date": item.purchase_date.isoformat() if item.purchase_date else None,
                        "purchase_price": item.purchase_price,
                        "current_value": value
                    })

                # Alle Items
                report["items"].append({
                    "id": item.id,
                    "name": item.name,
                    "category": cat,
                    "room": item.room,
                    "manufacturer": item.manufacturer,
                    "model": item.model,
                    "serial_number": item.serial_number,
                    "purchase_date": item.purchase_date.isoformat() if item.purchase_date else None,
                    "purchase_price": item.purchase_price,
                    "current_value": value,
                    "condition": item.condition
                })

            return report

    def get_items_without_receipt(self) -> List[InventoryItem]:
        """Holt Gegenstände ohne verknüpften Kaufbeleg"""
        with get_session() as session:
            return session.query(InventoryItem).filter(
                InventoryItem.user_id == self.user_id,
                InventoryItem.is_active == True,
                InventoryItem.document_id == None
            ).all()

    def get_items_needing_warranty(self) -> List[InventoryItem]:
        """Holt Gegenstände die Garantie haben könnten aber keine eingetragen ist"""
        with get_session() as session:
            items = session.query(InventoryItem).filter(
                InventoryItem.user_id == self.user_id,
                InventoryItem.is_active == True,
                InventoryItem.category.in_(["electronics", "appliances"])
            ).all()

            # Prüfen ob Garantie vorhanden
            result = []
            for item in items:
                warranty = session.query(Warranty).filter(
                    Warranty.inventory_item_id == item.id
                ).first()
                if not warranty and item.purchase_date:
                    # Kaufdatum < 2 Jahre
                    if (datetime.now() - item.purchase_date).days < 730:
                        result.append(item)

            return result
