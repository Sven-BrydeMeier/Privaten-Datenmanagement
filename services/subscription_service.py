"""
Abo-Verwaltung Service
Verwaltet Abonnements und wiederkehrende Zahlungen
"""
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy import and_, or_, func

from database.models import get_session
from database.extended_models import Subscription, SubscriptionInterval


class SubscriptionService:
    """Service für Abo-Verwaltung"""

    # Kategorien für Abos
    CATEGORIES = {
        "streaming": "Streaming & Entertainment",
        "software": "Software & Apps",
        "music": "Musik",
        "fitness": "Fitness & Sport",
        "news": "Nachrichten & Magazine",
        "cloud": "Cloud-Speicher",
        "gaming": "Gaming",
        "education": "Bildung",
        "productivity": "Produktivität",
        "other": "Sonstiges"
    }

    def __init__(self, user_id: int):
        self.user_id = user_id

    def create_subscription(self, name: str, amount: float,
                            billing_interval: SubscriptionInterval,
                            start_date: datetime, **kwargs) -> Subscription:
        """Erstellt ein neues Abonnement"""
        with get_session() as session:
            # Nächstes Abrechnungsdatum berechnen
            next_billing = self._calculate_next_billing(start_date, billing_interval)

            subscription = Subscription(
                user_id=self.user_id,
                name=name,
                amount=amount,
                billing_interval=billing_interval,
                start_date=start_date,
                next_billing_date=next_billing,
                provider=kwargs.get("provider"),
                category=kwargs.get("category"),
                currency=kwargs.get("currency", "EUR"),
                payment_method=kwargs.get("payment_method"),
                bank_account_id=kwargs.get("bank_account_id"),
                end_date=kwargs.get("end_date"),
                trial_end_date=kwargs.get("trial_end_date"),
                cancellation_url=kwargs.get("cancellation_url"),
                notice_period_days=kwargs.get("notice_period_days"),
                login_email=kwargs.get("login_email"),
                website_url=kwargs.get("website_url"),
                shared_with=kwargs.get("shared_with"),
                max_users=kwargs.get("max_users"),
                notes=kwargs.get("notes"),
                document_id=kwargs.get("document_id"),
                reminder_days_before=kwargs.get("reminder_days_before", 7)
            )

            session.add(subscription)
            session.commit()
            session.refresh(subscription)
            return subscription

    def get_subscription(self, subscription_id: int) -> Optional[Subscription]:
        """Holt ein spezifisches Abonnement"""
        with get_session() as session:
            return session.query(Subscription).filter(
                Subscription.id == subscription_id,
                Subscription.user_id == self.user_id
            ).first()

    def get_all_subscriptions(self, active_only: bool = False) -> List[Subscription]:
        """Holt alle Abonnements"""
        with get_session() as session:
            query = session.query(Subscription).filter(
                Subscription.user_id == self.user_id
            )

            if active_only:
                query = query.filter(
                    Subscription.is_active == True,
                    Subscription.cancellation_date == None
                )

            return query.order_by(Subscription.next_billing_date.asc()).all()

    def get_by_category(self, category: str) -> List[Subscription]:
        """Holt Abonnements nach Kategorie"""
        with get_session() as session:
            return session.query(Subscription).filter(
                Subscription.user_id == self.user_id,
                Subscription.category == category,
                Subscription.is_active == True
            ).all()

    def update_subscription(self, subscription_id: int, **kwargs) -> bool:
        """Aktualisiert ein Abonnement"""
        with get_session() as session:
            sub = session.query(Subscription).filter(
                Subscription.id == subscription_id,
                Subscription.user_id == self.user_id
            ).first()

            if not sub:
                return False

            for key, value in kwargs.items():
                if hasattr(sub, key):
                    setattr(sub, key, value)

            # Nächstes Abrechnungsdatum neu berechnen wenn nötig
            if "billing_interval" in kwargs or "start_date" in kwargs:
                sub.next_billing_date = self._calculate_next_billing(
                    sub.start_date, sub.billing_interval
                )

            sub.updated_at = datetime.now()
            session.commit()
            return True

    def delete_subscription(self, subscription_id: int) -> bool:
        """Löscht ein Abonnement"""
        with get_session() as session:
            sub = session.query(Subscription).filter(
                Subscription.id == subscription_id,
                Subscription.user_id == self.user_id
            ).first()

            if not sub:
                return False

            session.delete(sub)
            session.commit()
            return True

    def cancel_subscription(self, subscription_id: int,
                            cancellation_date: datetime = None) -> bool:
        """Markiert Abo als gekündigt"""
        with get_session() as session:
            sub = session.query(Subscription).filter(
                Subscription.id == subscription_id,
                Subscription.user_id == self.user_id
            ).first()

            if not sub:
                return False

            sub.cancellation_date = cancellation_date or datetime.now()
            sub.updated_at = datetime.now()
            session.commit()
            return True

    def pause_subscription(self, subscription_id: int) -> bool:
        """Pausiert ein Abonnement"""
        return self.update_subscription(subscription_id, is_paused=True)

    def resume_subscription(self, subscription_id: int) -> bool:
        """Setzt ein pausiertes Abonnement fort"""
        return self.update_subscription(subscription_id, is_paused=False)

    # ==================== KOSTENANALYSE ====================

    def get_monthly_total(self) -> float:
        """Berechnet monatliche Gesamtkosten"""
        with get_session() as session:
            subs = session.query(Subscription).filter(
                Subscription.user_id == self.user_id,
                Subscription.is_active == True,
                Subscription.is_paused == False,
                Subscription.cancellation_date == None
            ).all()

            total = sum(self._to_monthly(s.amount, s.billing_interval) for s in subs)
            return round(total, 2)

    def get_yearly_total(self) -> float:
        """Berechnet jährliche Gesamtkosten"""
        return round(self.get_monthly_total() * 12, 2)

    def get_cost_by_category(self) -> Dict[str, float]:
        """Berechnet Kosten nach Kategorie"""
        with get_session() as session:
            subs = session.query(Subscription).filter(
                Subscription.user_id == self.user_id,
                Subscription.is_active == True,
                Subscription.cancellation_date == None
            ).all()

            costs = {}
            for sub in subs:
                cat = sub.category or "other"
                monthly = self._to_monthly(sub.amount, sub.billing_interval)
                costs[cat] = costs.get(cat, 0) + monthly

            return {k: round(v, 2) for k, v in sorted(costs.items(), key=lambda x: -x[1])}

    def get_upcoming_payments(self, days: int = 30) -> List[Dict]:
        """Holt anstehende Zahlungen"""
        with get_session() as session:
            cutoff = datetime.now() + timedelta(days=days)

            subs = session.query(Subscription).filter(
                Subscription.user_id == self.user_id,
                Subscription.is_active == True,
                Subscription.is_paused == False,
                Subscription.next_billing_date != None,
                Subscription.next_billing_date <= cutoff
            ).order_by(Subscription.next_billing_date.asc()).all()

            return [{
                "subscription": sub,
                "date": sub.next_billing_date,
                "amount": sub.amount,
                "days_until": (sub.next_billing_date - datetime.now()).days
            } for sub in subs]

    def get_trial_ending_soon(self, days: int = 7) -> List[Subscription]:
        """Holt Abos deren Probezeit bald endet"""
        with get_session() as session:
            cutoff = datetime.now() + timedelta(days=days)

            return session.query(Subscription).filter(
                Subscription.user_id == self.user_id,
                Subscription.is_active == True,
                Subscription.trial_end_date != None,
                Subscription.trial_end_date >= datetime.now(),
                Subscription.trial_end_date <= cutoff
            ).order_by(Subscription.trial_end_date.asc()).all()

    # ==================== STATISTIKEN ====================

    def get_statistics(self) -> Dict[str, Any]:
        """Holt Statistiken zu Abonnements"""
        with get_session() as session:
            all_subs = session.query(Subscription).filter(
                Subscription.user_id == self.user_id
            ).all()

            active = [s for s in all_subs if s.is_active and not s.cancellation_date]
            paused = [s for s in all_subs if s.is_paused]
            cancelled = [s for s in all_subs if s.cancellation_date]

            # Teuerste Abos
            most_expensive = sorted(
                active,
                key=lambda s: self._to_monthly(s.amount, s.billing_interval),
                reverse=True
            )[:5]

            return {
                "total": len(all_subs),
                "active": len(active),
                "paused": len(paused),
                "cancelled": len(cancelled),
                "monthly_cost": self.get_monthly_total(),
                "yearly_cost": self.get_yearly_total(),
                "categories": len(set(s.category for s in active if s.category)),
                "most_expensive": most_expensive,
                "cost_by_category": self.get_cost_by_category()
            }

    def get_potential_savings(self) -> List[Dict]:
        """Identifiziert potenzielle Einsparungen"""
        with get_session() as session:
            subs = session.query(Subscription).filter(
                Subscription.user_id == self.user_id,
                Subscription.is_active == True
            ).all()

            suggestions = []

            # Ähnliche Abos finden
            categories = {}
            for sub in subs:
                cat = sub.category or "other"
                if cat not in categories:
                    categories[cat] = []
                categories[cat].append(sub)

            for cat, cat_subs in categories.items():
                if len(cat_subs) > 1:
                    total = sum(self._to_monthly(s.amount, s.billing_interval) for s in cat_subs)
                    suggestions.append({
                        "type": "duplicate_category",
                        "category": cat,
                        "count": len(cat_subs),
                        "monthly_cost": round(total, 2),
                        "subscriptions": cat_subs,
                        "suggestion": f"Sie haben {len(cat_subs)} Abos in der Kategorie '{self.CATEGORIES.get(cat, cat)}'. Prüfen Sie, ob alle benötigt werden."
                    })

            # Teure Abos
            for sub in subs:
                monthly = self._to_monthly(sub.amount, sub.billing_interval)
                if monthly > 20:
                    suggestions.append({
                        "type": "expensive",
                        "subscription": sub,
                        "monthly_cost": round(monthly, 2),
                        "suggestion": f"'{sub.name}' kostet {monthly:.2f}€/Monat. Gibt es günstigere Alternativen?"
                    })

            return suggestions

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

    def _calculate_next_billing(self, start_date: datetime,
                                 interval: SubscriptionInterval) -> datetime:
        """Berechnet nächstes Abrechnungsdatum"""
        now = datetime.now()

        if start_date > now:
            return start_date

        delta_map = {
            SubscriptionInterval.WEEKLY: timedelta(weeks=1),
            SubscriptionInterval.MONTHLY: timedelta(days=30),
            SubscriptionInterval.QUARTERLY: timedelta(days=90),
            SubscriptionInterval.SEMI_ANNUALLY: timedelta(days=180),
            SubscriptionInterval.ANNUALLY: timedelta(days=365)
        }

        delta = delta_map.get(interval, timedelta(days=30))
        next_date = start_date

        while next_date <= now:
            next_date += delta

        return next_date

    def update_next_billing_dates(self) -> int:
        """Aktualisiert alle Abrechnungsdaten"""
        count = 0
        with get_session() as session:
            subs = session.query(Subscription).filter(
                Subscription.user_id == self.user_id,
                Subscription.is_active == True
            ).all()

            now = datetime.now()
            for sub in subs:
                if sub.next_billing_date and sub.next_billing_date < now:
                    sub.next_billing_date = self._calculate_next_billing(
                        sub.next_billing_date, sub.billing_interval
                    )
                    count += 1

            session.commit()

        return count
