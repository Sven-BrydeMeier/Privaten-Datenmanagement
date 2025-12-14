"""
Finance Dashboard Service
Finanzübersicht mit Trends und Analysen
"""
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from collections import defaultdict
import calendar

from database.models import (
    get_session, Document, BankTransaction, BankConnection,
    Receipt, InvoiceStatus
)


class FinanceService:
    """Service für Finanzanalysen und Dashboard"""

    # Ausgaben-Kategorien für Gruppierung
    EXPENSE_CATEGORIES = {
        "Wohnen": ["miete", "strom", "gas", "heizung", "wasser", "nebenkosten", "hausverwaltung"],
        "Versicherungen": ["versicherung", "haftpflicht", "hausrat", "kfz", "kranken", "lebens"],
        "Transport": ["tankstelle", "benzin", "diesel", "bahn", "bus", "taxi", "uber", "auto"],
        "Kommunikation": ["telekom", "vodafone", "o2", "1&1", "internet", "handy", "mobilfunk"],
        "Unterhaltung": ["netflix", "spotify", "amazon prime", "disney", "kino", "streaming"],
        "Einkauf": ["amazon", "ebay", "zalando", "otto", "supermarkt", "rewe", "aldi", "lidl", "edeka"],
        "Gesundheit": ["apotheke", "arzt", "krankenhaus", "medikament"],
        "Bildung": ["schule", "universität", "kurs", "weiterbildung", "bücher"],
        "Restaurant": ["restaurant", "essen", "lieferando", "lieferheld", "pizza"],
        "Sonstiges": []
    }

    def __init__(self):
        pass

    def get_financial_overview(
        self,
        user_id: int,
        months_back: int = 12
    ) -> Dict[str, Any]:
        """
        Erstellt eine Finanzübersicht

        Args:
            user_id: Benutzer-ID
            months_back: Anzahl Monate zurück

        Returns:
            Dict mit Finanzübersicht
        """
        session = get_session()
        try:
            start_date = datetime.now() - timedelta(days=months_back * 30)

            # Banktransaktionen laden
            transactions = session.query(BankTransaction).filter(
                BankTransaction.user_id == user_id,
                BankTransaction.booking_date >= start_date
            ).order_by(BankTransaction.booking_date.desc()).all()

            # Rechnungen laden
            invoices = session.query(Document).filter(
                Document.user_id == user_id,
                Document.invoice_amount.isnot(None),
                Document.document_date >= start_date,
                Document.is_deleted == False
            ).all()

            # Berechnungen
            total_income = sum(t.amount for t in transactions if t.amount > 0)
            total_expenses = abs(sum(t.amount for t in transactions if t.amount < 0))
            balance = total_income - total_expenses

            # Offene Rechnungen
            open_invoices = [inv for inv in invoices
                            if inv.invoice_status in [InvoiceStatus.OPEN, None]]
            open_amount = sum(inv.invoice_amount or 0 for inv in open_invoices)

            # Überfällige Rechnungen
            overdue_invoices = [inv for inv in invoices
                               if inv.invoice_status == InvoiceStatus.OVERDUE]
            overdue_amount = sum(inv.invoice_amount or 0 for inv in overdue_invoices)

            return {
                "period_months": months_back,
                "total_income": round(total_income, 2),
                "total_expenses": round(total_expenses, 2),
                "balance": round(balance, 2),
                "transaction_count": len(transactions),
                "open_invoices_count": len(open_invoices),
                "open_invoices_amount": round(open_amount, 2),
                "overdue_invoices_count": len(overdue_invoices),
                "overdue_invoices_amount": round(overdue_amount, 2),
                "savings_rate": round((balance / total_income * 100) if total_income > 0 else 0, 1)
            }

        finally:
            session.close()

    def get_monthly_breakdown(
        self,
        user_id: int,
        year: int = None
    ) -> Dict[str, Any]:
        """
        Monatliche Aufschlüsselung von Einnahmen und Ausgaben

        Args:
            user_id: Benutzer-ID
            year: Jahr (Standard: aktuelles Jahr)

        Returns:
            Dict mit monatlichen Daten
        """
        session = get_session()
        try:
            if year is None:
                year = datetime.now().year

            start_date = datetime(year, 1, 1)
            end_date = datetime(year, 12, 31, 23, 59, 59)

            transactions = session.query(BankTransaction).filter(
                BankTransaction.user_id == user_id,
                BankTransaction.booking_date >= start_date,
                BankTransaction.booking_date <= end_date
            ).all()

            # Monate initialisieren
            months = []
            for month in range(1, 13):
                months.append({
                    "month": month,
                    "name": calendar.month_name[month],
                    "income": 0.0,
                    "expenses": 0.0,
                    "balance": 0.0,
                    "transaction_count": 0
                })

            # Transaktionen auf Monate verteilen
            for t in transactions:
                if t.booking_date:
                    month_idx = t.booking_date.month - 1
                    months[month_idx]["transaction_count"] += 1
                    if t.amount > 0:
                        months[month_idx]["income"] += t.amount
                    else:
                        months[month_idx]["expenses"] += abs(t.amount)

            # Balance und Rundung
            for month in months:
                month["balance"] = round(month["income"] - month["expenses"], 2)
                month["income"] = round(month["income"], 2)
                month["expenses"] = round(month["expenses"], 2)

            # Jahressummen
            total_income = sum(m["income"] for m in months)
            total_expenses = sum(m["expenses"] for m in months)

            return {
                "year": year,
                "months": months,
                "total_income": round(total_income, 2),
                "total_expenses": round(total_expenses, 2),
                "total_balance": round(total_income - total_expenses, 2),
                "average_monthly_income": round(total_income / 12, 2),
                "average_monthly_expenses": round(total_expenses / 12, 2)
            }

        finally:
            session.close()

    def get_expense_categories(
        self,
        user_id: int,
        months_back: int = 3
    ) -> Dict[str, Any]:
        """
        Ausgaben nach Kategorien gruppiert

        Args:
            user_id: Benutzer-ID
            months_back: Anzahl Monate

        Returns:
            Dict mit kategorisierten Ausgaben
        """
        session = get_session()
        try:
            start_date = datetime.now() - timedelta(days=months_back * 30)

            # Nur Ausgaben (negative Beträge)
            transactions = session.query(BankTransaction).filter(
                BankTransaction.user_id == user_id,
                BankTransaction.booking_date >= start_date,
                BankTransaction.amount < 0
            ).all()

            categories = defaultdict(lambda: {"total": 0.0, "count": 0, "transactions": []})

            for t in transactions:
                category = self._categorize_transaction(t)
                categories[category]["total"] += abs(t.amount)
                categories[category]["count"] += 1
                categories[category]["transactions"].append({
                    "id": t.id,
                    "date": t.booking_date.isoformat() if t.booking_date else None,
                    "amount": abs(t.amount),
                    "description": t.creditor_name or t.remittance_info
                })

            # Als Liste sortieren
            result = []
            for cat, data in categories.items():
                result.append({
                    "category": cat,
                    "total": round(data["total"], 2),
                    "count": data["count"],
                    "average": round(data["total"] / data["count"], 2) if data["count"] > 0 else 0,
                    "transactions": sorted(data["transactions"],
                                          key=lambda x: x["amount"], reverse=True)[:5]
                })

            result.sort(key=lambda x: x["total"], reverse=True)

            return {
                "period_months": months_back,
                "categories": result,
                "total_expenses": round(sum(c["total"] for c in result), 2)
            }

        finally:
            session.close()

    def _categorize_transaction(self, transaction: BankTransaction) -> str:
        """Kategorisiert eine Transaktion basierend auf Beschreibung"""
        # Wenn bereits kategorisiert
        if transaction.category:
            return transaction.category

        # Text für Matching
        text = " ".join([
            (transaction.creditor_name or ""),
            (transaction.remittance_info or ""),
            (transaction.reference or "")
        ]).lower()

        # Durch Kategorien iterieren
        for category, keywords in self.EXPENSE_CATEGORIES.items():
            for keyword in keywords:
                if keyword in text:
                    return category

        return "Sonstiges"

    def get_spending_trends(
        self,
        user_id: int,
        months_back: int = 6
    ) -> Dict[str, Any]:
        """
        Analysiert Ausgabentrends über mehrere Monate

        Returns:
            Dict mit Trend-Analysen
        """
        session = get_session()
        try:
            # Monatliche Daten sammeln
            monthly_data = []
            for i in range(months_back):
                month_start = datetime.now().replace(day=1) - timedelta(days=30 * i)
                month_start = month_start.replace(day=1, hour=0, minute=0, second=0)

                # Letzter Tag des Monats
                if month_start.month == 12:
                    month_end = month_start.replace(year=month_start.year + 1, month=1, day=1)
                else:
                    month_end = month_start.replace(month=month_start.month + 1, day=1)
                month_end = month_end - timedelta(seconds=1)

                transactions = session.query(BankTransaction).filter(
                    BankTransaction.user_id == user_id,
                    BankTransaction.booking_date >= month_start,
                    BankTransaction.booking_date <= month_end,
                    BankTransaction.amount < 0
                ).all()

                total = sum(abs(t.amount) for t in transactions)
                monthly_data.append({
                    "month": month_start.strftime("%Y-%m"),
                    "month_name": month_start.strftime("%B %Y"),
                    "total": round(total, 2),
                    "count": len(transactions)
                })

            # Trend berechnen
            monthly_data.reverse()  # Älteste zuerst

            if len(monthly_data) >= 2:
                first_half = sum(m["total"] for m in monthly_data[:len(monthly_data)//2])
                second_half = sum(m["total"] for m in monthly_data[len(monthly_data)//2:])

                if first_half > 0:
                    trend_percent = ((second_half - first_half) / first_half) * 100
                else:
                    trend_percent = 0

                trend_direction = "steigend" if trend_percent > 5 else "fallend" if trend_percent < -5 else "stabil"
            else:
                trend_percent = 0
                trend_direction = "unbekannt"

            # Durchschnitt und Maximum
            totals = [m["total"] for m in monthly_data]
            average = sum(totals) / len(totals) if totals else 0
            maximum = max(totals) if totals else 0
            minimum = min(totals) if totals else 0

            return {
                "months": monthly_data,
                "trend_direction": trend_direction,
                "trend_percent": round(trend_percent, 1),
                "average_monthly": round(average, 2),
                "highest_month": round(maximum, 2),
                "lowest_month": round(minimum, 2)
            }

        finally:
            session.close()

    def get_top_merchants(
        self,
        user_id: int,
        months_back: int = 3,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Top Händler/Empfänger nach Ausgaben

        Returns:
            Liste der Top-Händler
        """
        session = get_session()
        try:
            start_date = datetime.now() - timedelta(days=months_back * 30)

            transactions = session.query(BankTransaction).filter(
                BankTransaction.user_id == user_id,
                BankTransaction.booking_date >= start_date,
                BankTransaction.amount < 0
            ).all()

            merchants = defaultdict(lambda: {"total": 0.0, "count": 0})

            for t in transactions:
                name = t.creditor_name or "Unbekannt"
                merchants[name]["total"] += abs(t.amount)
                merchants[name]["count"] += 1

            # Sortieren und limitieren
            result = []
            for name, data in merchants.items():
                result.append({
                    "name": name,
                    "total": round(data["total"], 2),
                    "count": data["count"],
                    "average": round(data["total"] / data["count"], 2)
                })

            result.sort(key=lambda x: x["total"], reverse=True)

            return result[:limit]

        finally:
            session.close()

    def get_recurring_expenses(self, user_id: int) -> List[Dict[str, Any]]:
        """
        Erkennt wiederkehrende Ausgaben

        Returns:
            Liste erkannter wiederkehrender Zahlungen
        """
        session = get_session()
        try:
            # Transaktionen der letzten 6 Monate
            start_date = datetime.now() - timedelta(days=180)

            transactions = session.query(BankTransaction).filter(
                BankTransaction.user_id == user_id,
                BankTransaction.booking_date >= start_date,
                BankTransaction.amount < 0
            ).order_by(BankTransaction.booking_date.asc()).all()

            # Nach Empfänger gruppieren
            by_merchant = defaultdict(list)
            for t in transactions:
                name = t.creditor_name or "Unbekannt"
                by_merchant[name].append({
                    "date": t.booking_date,
                    "amount": abs(t.amount)
                })

            recurring = []

            for merchant, entries in by_merchant.items():
                if len(entries) < 2:
                    continue

                # Intervalle zwischen Zahlungen berechnen
                intervals = []
                for i in range(1, len(entries)):
                    if entries[i]["date"] and entries[i-1]["date"]:
                        diff = (entries[i]["date"] - entries[i-1]["date"]).days
                        intervals.append(diff)

                if not intervals:
                    continue

                avg_interval = sum(intervals) / len(intervals)
                amounts = [e["amount"] for e in entries]
                avg_amount = sum(amounts) / len(amounts)

                # Prüfen ob regelmäßig (±5 Tage Toleranz)
                is_regular = all(abs(i - avg_interval) <= 5 for i in intervals)

                # Frequenz bestimmen
                if 25 <= avg_interval <= 35:
                    frequency = "monatlich"
                elif 85 <= avg_interval <= 95:
                    frequency = "vierteljährlich"
                elif 175 <= avg_interval <= 185:
                    frequency = "halbjährlich"
                elif 355 <= avg_interval <= 375:
                    frequency = "jährlich"
                else:
                    frequency = f"ca. alle {int(avg_interval)} Tage"

                if is_regular or len(entries) >= 3:
                    # Nächste Zahlung schätzen
                    last_date = max(e["date"] for e in entries if e["date"])
                    next_expected = last_date + timedelta(days=int(avg_interval))

                    recurring.append({
                        "merchant": merchant,
                        "frequency": frequency,
                        "average_amount": round(avg_amount, 2),
                        "occurrence_count": len(entries),
                        "last_payment": last_date.isoformat() if last_date else None,
                        "next_expected": next_expected.isoformat() if next_expected else None,
                        "monthly_equivalent": round(avg_amount * 30 / avg_interval, 2) if avg_interval > 0 else 0,
                        "is_regular": is_regular
                    })

            # Nach monatlichem Äquivalent sortieren
            recurring.sort(key=lambda x: x["monthly_equivalent"], reverse=True)

            return recurring

        finally:
            session.close()

    def get_invoice_statistics(self, user_id: int) -> Dict[str, Any]:
        """Statistiken zu Rechnungen"""
        session = get_session()
        try:
            # Alle Rechnungen
            invoices = session.query(Document).filter(
                Document.user_id == user_id,
                Document.invoice_amount.isnot(None),
                Document.is_deleted == False
            ).all()

            # Status-Verteilung
            status_counts = defaultdict(int)
            status_amounts = defaultdict(float)

            for inv in invoices:
                status = inv.invoice_status.value if inv.invoice_status else "open"
                status_counts[status] += 1
                status_amounts[status] += inv.invoice_amount or 0

            # Durchschnittliche Zahlungsdauer
            paid_invoices = [inv for inv in invoices if inv.invoice_paid_date and inv.invoice_due_date]
            if paid_invoices:
                payment_delays = []
                for inv in paid_invoices:
                    delay = (inv.invoice_paid_date - inv.invoice_due_date).days
                    payment_delays.append(delay)
                avg_delay = sum(payment_delays) / len(payment_delays)
            else:
                avg_delay = 0

            return {
                "total_invoices": len(invoices),
                "status_distribution": dict(status_counts),
                "amount_by_status": {k: round(v, 2) for k, v in status_amounts.items()},
                "average_payment_delay_days": round(avg_delay, 1),
                "total_open_amount": round(status_amounts.get("open", 0) + status_amounts.get("overdue", 0), 2)
            }

        finally:
            session.close()

    def get_cash_flow_forecast(
        self,
        user_id: int,
        months_ahead: int = 3
    ) -> Dict[str, Any]:
        """
        Cashflow-Prognose basierend auf wiederkehrenden Zahlungen

        Returns:
            Dict mit Prognose
        """
        recurring = self.get_recurring_expenses(user_id)
        overview = self.get_monthly_breakdown(user_id)

        # Durchschnittliches Einkommen schätzen
        avg_income = overview["average_monthly_income"]

        # Erwartete monatliche Ausgaben
        expected_monthly_expenses = sum(r["monthly_equivalent"] for r in recurring)

        forecast = []
        for i in range(1, months_ahead + 1):
            forecast_date = datetime.now() + timedelta(days=30 * i)
            forecast.append({
                "month": forecast_date.strftime("%B %Y"),
                "expected_income": round(avg_income, 2),
                "expected_expenses": round(expected_monthly_expenses, 2),
                "expected_balance": round(avg_income - expected_monthly_expenses, 2)
            })

        return {
            "recurring_expenses_monthly": round(expected_monthly_expenses, 2),
            "average_income_monthly": round(avg_income, 2),
            "forecast": forecast,
            "savings_potential": round(avg_income - expected_monthly_expenses, 2)
        }


def get_finance_service() -> FinanceService:
    """Factory-Funktion für den FinanceService"""
    return FinanceService()
