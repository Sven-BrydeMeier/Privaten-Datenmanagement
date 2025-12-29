"""
Contract Dashboard Service
Vertragsverwaltung mit Kostenübersicht und Kündigungsfristen
"""
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from collections import defaultdict
from calendar import monthrange
import calendar

from database.models import get_session, Document


class ContractService:
    """Service für Vertragsverwaltung und Kostenanalyse"""

    def __init__(self):
        pass

    def get_all_contracts(
        self,
        user_id: int,
        include_expired: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Lädt alle Verträge des Benutzers

        Args:
            user_id: Benutzer-ID
            include_expired: Auch abgelaufene Verträge laden

        Returns:
            Liste von Vertrags-Dicts
        """
        session = get_session()
        try:
            query = session.query(Document).filter(
                Document.user_id == user_id,
                Document.category == "Vertrag",
                Document.is_deleted == False
            )

            if not include_expired:
                query = query.filter(
                    (Document.contract_end.is_(None)) |
                    (Document.contract_end >= datetime.now())
                )

            contracts = query.order_by(Document.contract_end.asc().nullslast()).all()

            result = []
            for doc in contracts:
                # Kündigungsfrist berechnen
                notice_deadline = None
                days_until_notice = None
                if doc.contract_end and doc.contract_notice_period:
                    notice_deadline = doc.contract_end - timedelta(days=doc.contract_notice_period)
                    days_until_notice = (notice_deadline - datetime.now()).days

                # Monatliche Kosten schätzen
                monthly_cost = self._estimate_monthly_cost(doc)

                # Status bestimmen
                status = self._get_contract_status(doc)

                result.append({
                    "id": doc.id,
                    "title": doc.title or doc.filename,
                    "sender": doc.sender,
                    "category": doc.category,
                    "contract_number": doc.contract_number,
                    "contract_start": doc.contract_start.isoformat() if doc.contract_start else None,
                    "contract_end": doc.contract_end.isoformat() if doc.contract_end else None,
                    "notice_period_days": doc.contract_notice_period,
                    "notice_deadline": notice_deadline.isoformat() if notice_deadline else None,
                    "days_until_notice": days_until_notice,
                    "invoice_amount": doc.invoice_amount,
                    "monthly_cost": monthly_cost,
                    "status": status,
                    "is_notice_urgent": days_until_notice is not None and days_until_notice <= 30
                })

            return result

        finally:
            session.close()

    def _estimate_monthly_cost(self, doc: Document) -> Optional[float]:
        """Schätzt die monatlichen Kosten basierend auf Rechnungsbetrag"""
        if not doc.invoice_amount:
            return None

        # Versuche Zahlungsintervall aus Titel/Subject zu erkennen
        text = (doc.title or "").lower() + " " + (doc.subject or "").lower()

        if "monat" in text or "monthly" in text:
            return doc.invoice_amount
        elif "quartal" in text or "quarterly" in text or "vierteljähr" in text:
            return doc.invoice_amount / 3
        elif "halbjahr" in text or "halbjähr" in text:
            return doc.invoice_amount / 6
        elif "jahr" in text or "annual" in text or "yearly" in text:
            return doc.invoice_amount / 12
        else:
            # Standardannahme: monatlich
            return doc.invoice_amount

    def _get_contract_status(self, doc: Document) -> str:
        """Bestimmt den Status eines Vertrags"""
        now = datetime.now()

        if doc.contract_end and doc.contract_end < now:
            return "expired"  # Abgelaufen

        if doc.contract_end and doc.contract_notice_period:
            notice_deadline = doc.contract_end - timedelta(days=doc.contract_notice_period)
            if notice_deadline < now:
                return "notice_expired"  # Kündigungsfrist verpasst
            elif notice_deadline <= now + timedelta(days=7):
                return "notice_urgent"  # Kündigungsfrist dringend
            elif notice_deadline <= now + timedelta(days=30):
                return "notice_soon"  # Kündigungsfrist naht

        if not doc.contract_start or doc.contract_start > now:
            return "pending"  # Noch nicht aktiv

        return "active"  # Aktiv

    def get_upcoming_deadlines(
        self,
        user_id: int,
        days_ahead: int = 90
    ) -> List[Dict[str, Any]]:
        """
        Findet Verträge mit bevorstehenden Kündigungsfristen

        Args:
            user_id: Benutzer-ID
            days_ahead: Tage im Voraus prüfen

        Returns:
            Liste von Verträgen mit Fristen
        """
        contracts = self.get_all_contracts(user_id)

        deadlines = []
        cutoff_date = datetime.now() + timedelta(days=days_ahead)

        for contract in contracts:
            if contract["notice_deadline"]:
                deadline = datetime.fromisoformat(contract["notice_deadline"])
                if deadline <= cutoff_date and deadline >= datetime.now():
                    deadlines.append(contract)

        # Nach Frist sortieren
        deadlines.sort(key=lambda x: x["notice_deadline"])

        return deadlines

    def get_cost_overview(self, user_id: int) -> Dict[str, Any]:
        """
        Erstellt eine Kostenübersicht aller aktiven Verträge

        Returns:
            Dict mit Kostenanalyse
        """
        contracts = self.get_all_contracts(user_id)

        # Kosten nach Kategorie
        costs_by_sender = defaultdict(float)
        total_monthly = 0.0
        active_count = 0

        for contract in contracts:
            if contract["status"] in ["active", "notice_soon", "notice_urgent", "notice_expired"]:
                active_count += 1
                if contract["monthly_cost"]:
                    total_monthly += contract["monthly_cost"]
                    sender = contract["sender"] or "Unbekannt"
                    costs_by_sender[sender] += contract["monthly_cost"]

        # Nach Kosten sortieren
        top_costs = sorted(
            [{"sender": k, "monthly_cost": v} for k, v in costs_by_sender.items()],
            key=lambda x: x["monthly_cost"],
            reverse=True
        )

        return {
            "total_monthly": round(total_monthly, 2),
            "total_yearly": round(total_monthly * 12, 2),
            "active_contracts": active_count,
            "costs_by_sender": top_costs[:10],  # Top 10
            "contracts": contracts
        }

    def get_category_breakdown(self, user_id: int) -> Dict[str, Any]:
        """Kostenaufschlüsselung nach Vertragskategorien"""
        session = get_session()
        try:
            # Alle Verträge und vertragsähnliche Dokumente laden
            docs = session.query(Document).filter(
                Document.user_id == user_id,
                Document.is_deleted == False,
                Document.invoice_amount.isnot(None),
                Document.category.in_([
                    "Vertrag", "Versicherung", "Darlehen",
                    "Lebensversicherung", "Rechnung"
                ])
            ).all()

            categories = defaultdict(lambda: {"count": 0, "total": 0.0, "items": []})

            for doc in docs:
                cat = doc.category or "Sonstiges"
                monthly = self._estimate_monthly_cost(doc)

                categories[cat]["count"] += 1
                if monthly:
                    categories[cat]["total"] += monthly
                    categories[cat]["items"].append({
                        "id": doc.id,
                        "title": doc.title or doc.filename,
                        "sender": doc.sender,
                        "monthly_cost": monthly
                    })

            # Als Liste sortieren
            result = []
            for cat, data in categories.items():
                result.append({
                    "category": cat,
                    "count": data["count"],
                    "monthly_total": round(data["total"], 2),
                    "yearly_total": round(data["total"] * 12, 2),
                    "items": sorted(data["items"], key=lambda x: x["monthly_cost"] or 0, reverse=True)
                })

            result.sort(key=lambda x: x["monthly_total"], reverse=True)

            return {
                "categories": result,
                "total_monthly": round(sum(c["monthly_total"] for c in result), 2),
                "total_yearly": round(sum(c["yearly_total"] for c in result), 2)
            }

        finally:
            session.close()

    def get_yearly_projection(self, user_id: int) -> Dict[str, Any]:
        """
        Erstellt eine Jahresprojektion der Vertragskosten

        Returns:
            Dict mit monatlicher Aufschlüsselung
        """
        contracts = self.get_all_contracts(user_id, include_expired=False)

        # Monate initialisieren
        current_year = datetime.now().year
        months = []
        for month in range(1, 13):
            months.append({
                "month": month,
                "name": calendar.month_name[month],
                "total": 0.0,
                "contracts": []
            })

        # Verträge auf Monate verteilen
        for contract in contracts:
            if contract["monthly_cost"] and contract["status"] not in ["expired", "pending"]:
                start_month = 1
                end_month = 12

                # Berücksichtige Vertragsende
                if contract["contract_end"]:
                    end_date = datetime.fromisoformat(contract["contract_end"])
                    if end_date.year == current_year:
                        end_month = end_date.month

                # Berücksichtige Vertragsstart
                if contract["contract_start"]:
                    start_date = datetime.fromisoformat(contract["contract_start"])
                    if start_date.year == current_year:
                        start_month = start_date.month

                for month_idx in range(start_month - 1, end_month):
                    months[month_idx]["total"] += contract["monthly_cost"]
                    months[month_idx]["contracts"].append({
                        "id": contract["id"],
                        "title": contract["title"],
                        "cost": contract["monthly_cost"]
                    })

        # Runden
        for month in months:
            month["total"] = round(month["total"], 2)

        return {
            "year": current_year,
            "months": months,
            "yearly_total": round(sum(m["total"] for m in months), 2),
            "monthly_average": round(sum(m["total"] for m in months) / 12, 2)
        }

    def search_contracts(
        self,
        user_id: int,
        query: str
    ) -> List[Dict[str, Any]]:
        """Sucht in Verträgen nach Stichworten"""
        contracts = self.get_all_contracts(user_id, include_expired=True)

        query_lower = query.lower()
        results = []

        for contract in contracts:
            # Suche in relevanten Feldern
            searchable = " ".join([
                str(contract.get("title", "") or ""),
                str(contract.get("sender", "") or ""),
                str(contract.get("contract_number", "") or "")
            ]).lower()

            if query_lower in searchable:
                results.append(contract)

        return results

    def update_contract_dates(
        self,
        document_id: int,
        user_id: int,
        contract_start: datetime = None,
        contract_end: datetime = None,
        notice_period_days: int = None
    ) -> Dict[str, Any]:
        """Aktualisiert Vertragsdaten eines Dokuments"""
        session = get_session()
        try:
            doc = session.query(Document).filter_by(
                id=document_id,
                user_id=user_id
            ).first()

            if not doc:
                return {"error": "Dokument nicht gefunden"}

            if contract_start is not None:
                doc.contract_start = contract_start
            if contract_end is not None:
                doc.contract_end = contract_end
            if notice_period_days is not None:
                doc.contract_notice_period = notice_period_days

            session.commit()

            return {"success": True, "message": "Vertragsdaten aktualisiert"}

        except Exception as e:
            session.rollback()
            return {"error": str(e)}
        finally:
            session.close()


def get_contract_service() -> ContractService:
    """Factory-Funktion für den ContractService"""
    return ContractService()
