"""
Versicherungs-Manager Service
Verwaltet Versicherungspolicen, Kosten und Schadensmeldungen
"""
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy import and_, or_, func
from decimal import Decimal

from database.models import Document, get_session
from database.extended_models import (
    Insurance, InsuranceClaim, InsuranceType, SubscriptionInterval
)


class InsuranceService:
    """Service für Versicherungsverwaltung"""

    def __init__(self, user_id: int):
        self.user_id = user_id

    # ==================== VERSICHERUNGEN ====================

    def create_insurance(self, insurance_type: InsuranceType, company: str,
                         premium_amount: float, start_date: datetime, **kwargs) -> Insurance:
        """Erstellt eine neue Versicherung"""
        with get_session() as session:
            insurance = Insurance(
                user_id=self.user_id,
                insurance_type=insurance_type,
                company=company,
                premium_amount=premium_amount,
                start_date=start_date,
                premium_interval=kwargs.get("premium_interval", SubscriptionInterval.MONTHLY),
                currency=kwargs.get("currency", "EUR"),
                policy_number=kwargs.get("policy_number"),
                policy_name=kwargs.get("policy_name"),
                deductible=kwargs.get("deductible"),
                coverage_amount=kwargs.get("coverage_amount"),
                coverage_description=kwargs.get("coverage_description"),
                end_date=kwargs.get("end_date"),
                auto_renew=kwargs.get("auto_renew", True),
                notice_period_days=kwargs.get("notice_period_days", 90),
                agent_name=kwargs.get("agent_name"),
                agent_phone=kwargs.get("agent_phone"),
                agent_email=kwargs.get("agent_email"),
                claims_phone=kwargs.get("claims_phone"),
                document_id=kwargs.get("document_id"),
                notes=kwargs.get("notes"),
                reminder_days_before=kwargs.get("reminder_days_before", 60)
            )

            session.add(insurance)
            session.commit()
            session.refresh(insurance)
            return insurance

    def get_insurance(self, insurance_id: int) -> Optional[Insurance]:
        """Holt eine spezifische Versicherung"""
        with get_session() as session:
            return session.query(Insurance).filter(
                Insurance.id == insurance_id,
                Insurance.user_id == self.user_id
            ).first()

    def get_all_insurances(self, active_only: bool = False) -> List[Insurance]:
        """Holt alle Versicherungen"""
        with get_session() as session:
            query = session.query(Insurance).filter(
                Insurance.user_id == self.user_id
            )

            if active_only:
                query = query.filter(Insurance.is_active == True)

            return query.order_by(Insurance.company.asc()).all()

    def get_by_type(self, insurance_type: InsuranceType) -> List[Insurance]:
        """Holt Versicherungen nach Typ"""
        with get_session() as session:
            return session.query(Insurance).filter(
                Insurance.user_id == self.user_id,
                Insurance.insurance_type == insurance_type,
                Insurance.is_active == True
            ).all()

    def update_insurance(self, insurance_id: int, **kwargs) -> bool:
        """Aktualisiert eine Versicherung"""
        with get_session() as session:
            insurance = session.query(Insurance).filter(
                Insurance.id == insurance_id,
                Insurance.user_id == self.user_id
            ).first()

            if not insurance:
                return False

            for key, value in kwargs.items():
                if hasattr(insurance, key):
                    setattr(insurance, key, value)

            insurance.updated_at = datetime.now()
            session.commit()
            return True

    def delete_insurance(self, insurance_id: int) -> bool:
        """Löscht eine Versicherung"""
        with get_session() as session:
            insurance = session.query(Insurance).filter(
                Insurance.id == insurance_id,
                Insurance.user_id == self.user_id
            ).first()

            if not insurance:
                return False

            session.delete(insurance)
            session.commit()
            return True

    def deactivate_insurance(self, insurance_id: int) -> bool:
        """Deaktiviert eine Versicherung"""
        return self.update_insurance(insurance_id, is_active=False)

    # ==================== SCHADENSMELDUNGEN ====================

    def create_claim(self, insurance_id: int, incident_date: datetime,
                     description: str, **kwargs) -> InsuranceClaim:
        """Erstellt eine Schadensmeldung"""
        with get_session() as session:
            claim = InsuranceClaim(
                insurance_id=insurance_id,
                user_id=self.user_id,
                incident_date=incident_date,
                description=description,
                claim_number=kwargs.get("claim_number"),
                claimed_amount=kwargs.get("claimed_amount"),
                document_ids=kwargs.get("document_ids"),
                status="submitted"
            )

            session.add(claim)
            session.commit()
            session.refresh(claim)
            return claim

    def get_claims(self, insurance_id: int = None) -> List[InsuranceClaim]:
        """Holt Schadensmeldungen"""
        with get_session() as session:
            query = session.query(InsuranceClaim).filter(
                InsuranceClaim.user_id == self.user_id
            )

            if insurance_id:
                query = query.filter(InsuranceClaim.insurance_id == insurance_id)

            return query.order_by(InsuranceClaim.created_at.desc()).all()

    def update_claim_status(self, claim_id: int, status: str,
                            notes: str = None, amounts: Dict = None) -> bool:
        """Aktualisiert Status einer Schadensmeldung"""
        with get_session() as session:
            claim = session.query(InsuranceClaim).filter(
                InsuranceClaim.id == claim_id,
                InsuranceClaim.user_id == self.user_id
            ).first()

            if not claim:
                return False

            claim.status = status
            if notes:
                claim.status_notes = notes
            if amounts:
                if "approved" in amounts:
                    claim.approved_amount = amounts["approved"]
                if "paid" in amounts:
                    claim.paid_amount = amounts["paid"]

            claim.updated_at = datetime.now()
            session.commit()
            return True

    # ==================== KOSTENANALYSE ====================

    def get_monthly_cost(self) -> float:
        """Berechnet monatliche Gesamtkosten"""
        with get_session() as session:
            insurances = session.query(Insurance).filter(
                Insurance.user_id == self.user_id,
                Insurance.is_active == True
            ).all()

            total = 0.0
            for ins in insurances:
                total += self._to_monthly(ins.premium_amount, ins.premium_interval)

            return round(total, 2)

    def get_yearly_cost(self) -> float:
        """Berechnet jährliche Gesamtkosten"""
        return round(self.get_monthly_cost() * 12, 2)

    def get_cost_by_type(self) -> Dict[str, float]:
        """Berechnet Kosten nach Versicherungstyp"""
        with get_session() as session:
            insurances = session.query(Insurance).filter(
                Insurance.user_id == self.user_id,
                Insurance.is_active == True
            ).all()

            costs = {}
            for ins in insurances:
                type_name = ins.insurance_type.value
                monthly = self._to_monthly(ins.premium_amount, ins.premium_interval)
                costs[type_name] = costs.get(type_name, 0) + monthly

            return {k: round(v, 2) for k, v in costs.items()}

    def get_cost_by_company(self) -> Dict[str, float]:
        """Berechnet Kosten nach Versicherungsunternehmen"""
        with get_session() as session:
            insurances = session.query(Insurance).filter(
                Insurance.user_id == self.user_id,
                Insurance.is_active == True
            ).all()

            costs = {}
            for ins in insurances:
                monthly = self._to_monthly(ins.premium_amount, ins.premium_interval)
                costs[ins.company] = costs.get(ins.company, 0) + monthly

            return {k: round(v, 2) for k, v in costs.items()}

    def _to_monthly(self, amount: float, interval: SubscriptionInterval) -> float:
        """Konvertiert Betrag in monatlichen Wert"""
        if interval == SubscriptionInterval.WEEKLY:
            return amount * 4.33
        elif interval == SubscriptionInterval.MONTHLY:
            return amount
        elif interval == SubscriptionInterval.QUARTERLY:
            return amount / 3
        elif interval == SubscriptionInterval.SEMI_ANNUALLY:
            return amount / 6
        elif interval == SubscriptionInterval.ANNUALLY:
            return amount / 12
        return amount

    # ==================== ERINNERUNGEN ====================

    def get_upcoming_renewals(self, days: int = 90) -> List[Insurance]:
        """Holt bald auslaufende Versicherungen"""
        with get_session() as session:
            cutoff_date = datetime.now() + timedelta(days=days)

            return session.query(Insurance).filter(
                Insurance.user_id == self.user_id,
                Insurance.is_active == True,
                Insurance.end_date != None,
                Insurance.end_date <= cutoff_date
            ).order_by(Insurance.end_date.asc()).all()

    def get_cancellation_deadlines(self) -> List[Dict]:
        """Holt anstehende Kündigungsfristen"""
        with get_session() as session:
            insurances = session.query(Insurance).filter(
                Insurance.user_id == self.user_id,
                Insurance.is_active == True,
                Insurance.end_date != None
            ).all()

            deadlines = []
            now = datetime.now()

            for ins in insurances:
                if ins.end_date and ins.notice_period_days:
                    cancel_deadline = ins.end_date - timedelta(days=ins.notice_period_days)
                    if cancel_deadline > now:
                        deadlines.append({
                            "insurance": ins,
                            "deadline": cancel_deadline,
                            "days_remaining": (cancel_deadline - now).days
                        })

            return sorted(deadlines, key=lambda x: x["deadline"])

    # ==================== STATISTIKEN ====================

    def get_statistics(self) -> Dict[str, Any]:
        """Holt Statistiken zu Versicherungen"""
        with get_session() as session:
            all_insurances = session.query(Insurance).filter(
                Insurance.user_id == self.user_id
            ).all()

            active = [i for i in all_insurances if i.is_active]
            claims = session.query(InsuranceClaim).filter(
                InsuranceClaim.user_id == self.user_id
            ).all()

            total_coverage = sum(i.coverage_amount or 0 for i in active)
            total_claims_paid = sum(c.paid_amount or 0 for c in claims)

            return {
                "total_insurances": len(all_insurances),
                "active_insurances": len(active),
                "monthly_cost": self.get_monthly_cost(),
                "yearly_cost": self.get_yearly_cost(),
                "total_coverage": total_coverage,
                "total_claims": len(claims),
                "total_claims_paid": total_claims_paid,
                "types_covered": list(set(i.insurance_type.value for i in active)),
                "companies": list(set(i.company for i in active))
            }

    def get_coverage_gaps(self) -> List[str]:
        """Identifiziert fehlende Versicherungstypen"""
        recommended = [
            InsuranceType.LIABILITY,
            InsuranceType.HOUSEHOLD,
            InsuranceType.HEALTH
        ]

        with get_session() as session:
            active_types = session.query(Insurance.insurance_type).filter(
                Insurance.user_id == self.user_id,
                Insurance.is_active == True
            ).distinct().all()

            active_types = [t[0] for t in active_types]

            gaps = []
            for rec_type in recommended:
                if rec_type not in active_types:
                    gaps.append(rec_type.value)

            return gaps
