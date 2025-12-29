"""
Invoice-Bank Transaction Matching Service
Automatischer Abgleich von Rechnungen mit Banktransaktionen
"""
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from difflib import SequenceMatcher
import re

from database.models import (
    get_session, Document, BankTransaction, BankConnection,
    InvoiceStatus
)


class InvoiceMatchingService:
    """Service für den Abgleich von Rechnungen mit Banktransaktionen"""

    # Matching-Konfiguration
    AMOUNT_TOLERANCE_PERCENT = 1.0  # 1% Toleranz für Betragsabgleich
    AMOUNT_TOLERANCE_ABSOLUTE = 0.10  # 10 Cent absolute Toleranz
    DATE_RANGE_DAYS_BEFORE = 7  # Suche 7 Tage vor Rechnungsdatum
    DATE_RANGE_DAYS_AFTER = 60  # Suche 60 Tage nach Rechnungsdatum
    MIN_NAME_SIMILARITY = 0.6  # Mindestähnlichkeit für Namen

    def __init__(self):
        pass

    def find_matches_for_invoice(
        self,
        document_id: int,
        user_id: int,
        amount_tolerance_percent: float = None,
        date_range_days: int = None
    ) -> Dict[str, Any]:
        """
        Findet passende Banktransaktionen für eine Rechnung

        Args:
            document_id: ID der Rechnung
            user_id: Benutzer-ID
            amount_tolerance_percent: Toleranz für Betrag (optional)
            date_range_days: Suchzeitraum in Tagen (optional)

        Returns:
            Dict mit gefundenen Matches und Score
        """
        session = get_session()
        try:
            # Rechnung laden
            doc = session.query(Document).filter_by(
                id=document_id,
                user_id=user_id
            ).first()

            if not doc:
                return {"error": "Dokument nicht gefunden", "matches": []}

            if not doc.invoice_amount:
                return {"error": "Kein Rechnungsbetrag vorhanden", "matches": []}

            # Parameter
            tolerance = amount_tolerance_percent or self.AMOUNT_TOLERANCE_PERCENT
            date_range = date_range_days or self.DATE_RANGE_DAYS_AFTER

            # Zeitrahmen bestimmen
            ref_date = doc.invoice_due_date or doc.document_date or doc.created_at
            start_date = ref_date - timedelta(days=self.DATE_RANGE_DAYS_BEFORE)
            end_date = ref_date + timedelta(days=date_range)

            # Kandidaten-Transaktionen suchen
            # Rechnungen sind typischerweise Ausgaben (negative Transaktionen)
            target_amount = -abs(doc.invoice_amount)
            amount_min = target_amount * (1 + tolerance / 100)
            amount_max = target_amount * (1 - tolerance / 100)

            # Auch absolute Toleranz berücksichtigen
            amount_min = min(amount_min, target_amount - self.AMOUNT_TOLERANCE_ABSOLUTE)
            amount_max = max(amount_max, target_amount + self.AMOUNT_TOLERANCE_ABSOLUTE)

            candidates = session.query(BankTransaction).filter(
                BankTransaction.user_id == user_id,
                BankTransaction.booking_date >= start_date,
                BankTransaction.booking_date <= end_date,
                BankTransaction.amount >= amount_min,
                BankTransaction.amount <= amount_max,
                BankTransaction.document_id.is_(None)  # Noch nicht zugeordnet
            ).all()

            # Matches bewerten
            matches = []
            for transaction in candidates:
                score, details = self._calculate_match_score(doc, transaction)
                if score > 0:
                    matches.append({
                        "transaction_id": transaction.id,
                        "score": score,
                        "details": details,
                        "transaction": {
                            "id": transaction.id,
                            "date": transaction.booking_date.isoformat() if transaction.booking_date else None,
                            "amount": transaction.amount,
                            "creditor": transaction.creditor_name,
                            "debtor": transaction.debtor_name,
                            "reference": transaction.remittance_info,
                            "is_booked": transaction.is_booked
                        }
                    })

            # Nach Score sortieren
            matches.sort(key=lambda x: x["score"], reverse=True)

            return {
                "document_id": document_id,
                "invoice_amount": doc.invoice_amount,
                "invoice_sender": doc.sender,
                "invoice_date": doc.document_date.isoformat() if doc.document_date else None,
                "due_date": doc.invoice_due_date.isoformat() if doc.invoice_due_date else None,
                "matches": matches[:10],  # Top 10 Matches
                "total_candidates": len(candidates)
            }

        finally:
            session.close()

    def _calculate_match_score(
        self,
        doc: Document,
        transaction: BankTransaction
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Berechnet den Match-Score zwischen Rechnung und Transaktion

        Returns:
            Tuple von (Score 0-100, Detail-Dict)
        """
        score = 0
        details = {
            "amount_match": False,
            "date_match": False,
            "name_match": False,
            "reference_match": False,
            "iban_match": False
        }

        # 1. Betragsabgleich (40 Punkte)
        target_amount = -abs(doc.invoice_amount)
        amount_diff = abs(transaction.amount - target_amount)
        amount_diff_percent = (amount_diff / abs(target_amount)) * 100 if target_amount else 0

        if amount_diff <= self.AMOUNT_TOLERANCE_ABSOLUTE or amount_diff_percent <= self.AMOUNT_TOLERANCE_PERCENT:
            score += 40
            details["amount_match"] = True
        elif amount_diff_percent <= 5:
            score += 20

        # 2. Datumsabgleich (20 Punkte)
        ref_date = doc.invoice_due_date or doc.document_date
        if ref_date and transaction.booking_date:
            days_diff = abs((transaction.booking_date - ref_date).days)
            if days_diff <= 3:
                score += 20
                details["date_match"] = True
            elif days_diff <= 7:
                score += 15
            elif days_diff <= 14:
                score += 10
            elif days_diff <= 30:
                score += 5

        # 3. Namensabgleich (25 Punkte)
        sender_name = (doc.sender or "").lower()
        creditor_name = (transaction.creditor_name or "").lower()

        if sender_name and creditor_name:
            similarity = SequenceMatcher(None, sender_name, creditor_name).ratio()
            if similarity >= 0.9:
                score += 25
                details["name_match"] = True
            elif similarity >= 0.7:
                score += 18
            elif similarity >= self.MIN_NAME_SIMILARITY:
                score += 10

        # 4. Referenz/Rechnungsnummer im Verwendungszweck (10 Punkte)
        reference = (transaction.remittance_info or "").lower()
        if doc.invoice_number and doc.invoice_number.lower() in reference:
            score += 10
            details["reference_match"] = True
        elif doc.reference_number and doc.reference_number.lower() in reference:
            score += 8
        elif doc.customer_number and doc.customer_number.lower() in reference:
            score += 5

        # 5. IBAN-Abgleich (5 Punkte)
        if doc.iban and transaction.creditor_iban:
            if doc.iban.replace(" ", "") == transaction.creditor_iban.replace(" ", ""):
                score += 5
                details["iban_match"] = True

        return score, details

    def link_transaction_to_document(
        self,
        transaction_id: int,
        document_id: int,
        user_id: int,
        mark_as_paid: bool = True
    ) -> Dict[str, Any]:
        """
        Verknüpft eine Transaktion mit einem Dokument und markiert optional als bezahlt

        Args:
            transaction_id: ID der Transaktion
            document_id: ID des Dokuments
            user_id: Benutzer-ID
            mark_as_paid: Rechnung als bezahlt markieren

        Returns:
            Dict mit Ergebnis
        """
        session = get_session()
        try:
            # Transaktion laden
            transaction = session.query(BankTransaction).filter_by(
                id=transaction_id,
                user_id=user_id
            ).first()

            if not transaction:
                return {"error": "Transaktion nicht gefunden"}

            # Dokument laden
            doc = session.query(Document).filter_by(
                id=document_id,
                user_id=user_id
            ).first()

            if not doc:
                return {"error": "Dokument nicht gefunden"}

            # Verknüpfung erstellen
            transaction.document_id = document_id

            # Rechnung als bezahlt markieren
            if mark_as_paid:
                doc.invoice_status = InvoiceStatus.PAID
                doc.invoice_paid_date = transaction.booking_date or datetime.now()

            session.commit()

            return {
                "success": True,
                "message": f"Transaktion verknüpft. Rechnung als bezahlt markiert." if mark_as_paid else "Transaktion verknüpft.",
                "document_id": document_id,
                "transaction_id": transaction_id
            }

        except Exception as e:
            session.rollback()
            return {"error": f"Fehler beim Verknüpfen: {str(e)}"}
        finally:
            session.close()

    def unlink_transaction(
        self,
        transaction_id: int,
        user_id: int
    ) -> Dict[str, Any]:
        """Entfernt die Verknüpfung einer Transaktion"""
        session = get_session()
        try:
            transaction = session.query(BankTransaction).filter_by(
                id=transaction_id,
                user_id=user_id
            ).first()

            if not transaction:
                return {"error": "Transaktion nicht gefunden"}

            transaction.document_id = None
            session.commit()

            return {"success": True, "message": "Verknüpfung entfernt"}

        except Exception as e:
            session.rollback()
            return {"error": str(e)}
        finally:
            session.close()

    def find_unmatched_invoices(self, user_id: int) -> List[Dict[str, Any]]:
        """Findet alle unbezahlten/nicht zugeordneten Rechnungen"""
        session = get_session()
        try:
            invoices = session.query(Document).filter(
                Document.user_id == user_id,
                Document.invoice_amount.isnot(None),
                Document.invoice_status.in_([InvoiceStatus.OPEN, InvoiceStatus.OVERDUE, None]),
                Document.is_deleted == False
            ).order_by(Document.invoice_due_date.asc().nullslast()).all()

            result = []
            for doc in invoices:
                # Prüfe ob überfällig
                is_overdue = False
                if doc.invoice_due_date and doc.invoice_due_date < datetime.now():
                    is_overdue = True

                result.append({
                    "id": doc.id,
                    "title": doc.title or doc.filename,
                    "sender": doc.sender,
                    "amount": doc.invoice_amount,
                    "currency": doc.invoice_currency or "EUR",
                    "invoice_number": doc.invoice_number,
                    "document_date": doc.document_date.isoformat() if doc.document_date else None,
                    "due_date": doc.invoice_due_date.isoformat() if doc.invoice_due_date else None,
                    "is_overdue": is_overdue,
                    "days_until_due": (doc.invoice_due_date - datetime.now()).days if doc.invoice_due_date else None
                })

            return result

        finally:
            session.close()

    def find_unmatched_transactions(
        self,
        user_id: int,
        days_back: int = 90
    ) -> List[Dict[str, Any]]:
        """Findet alle nicht zugeordneten Transaktionen"""
        session = get_session()
        try:
            start_date = datetime.now() - timedelta(days=days_back)

            transactions = session.query(BankTransaction).filter(
                BankTransaction.user_id == user_id,
                BankTransaction.document_id.is_(None),
                BankTransaction.receipt_id.is_(None),
                BankTransaction.booking_date >= start_date,
                BankTransaction.amount < 0  # Nur Ausgaben
            ).order_by(BankTransaction.booking_date.desc()).all()

            result = []
            for t in transactions:
                result.append({
                    "id": t.id,
                    "date": t.booking_date.isoformat() if t.booking_date else None,
                    "amount": t.amount,
                    "currency": t.currency or "EUR",
                    "creditor": t.creditor_name,
                    "reference": t.remittance_info,
                    "category": t.category
                })

            return result

        finally:
            session.close()

    def auto_match_all(self, user_id: int) -> Dict[str, Any]:
        """
        Automatischer Abgleich aller unbezahlten Rechnungen

        Returns:
            Dict mit Statistik über gefundene Matches
        """
        session = get_session()
        try:
            invoices = self.find_unmatched_invoices(user_id)

            matched = 0
            high_confidence_matches = []
            suggested_matches = []

            for invoice in invoices:
                matches = self.find_matches_for_invoice(invoice["id"], user_id)

                if matches.get("matches"):
                    best_match = matches["matches"][0]

                    # Bei sehr hohem Score automatisch verknüpfen
                    if best_match["score"] >= 80:
                        result = self.link_transaction_to_document(
                            best_match["transaction_id"],
                            invoice["id"],
                            user_id,
                            mark_as_paid=True
                        )
                        if result.get("success"):
                            matched += 1
                            high_confidence_matches.append({
                                "invoice": invoice,
                                "transaction": best_match["transaction"],
                                "score": best_match["score"]
                            })
                    elif best_match["score"] >= 50:
                        # Vorschläge für manuelle Prüfung
                        suggested_matches.append({
                            "invoice": invoice,
                            "transaction": best_match["transaction"],
                            "score": best_match["score"],
                            "details": best_match["details"]
                        })

            return {
                "success": True,
                "total_invoices": len(invoices),
                "auto_matched": matched,
                "high_confidence_matches": high_confidence_matches,
                "suggested_matches": suggested_matches
            }

        finally:
            session.close()

    def get_matching_statistics(self, user_id: int) -> Dict[str, Any]:
        """Gibt Statistiken zum Matching-Status"""
        session = get_session()
        try:
            # Offene Rechnungen
            open_invoices = session.query(Document).filter(
                Document.user_id == user_id,
                Document.invoice_amount.isnot(None),
                Document.invoice_status.in_([InvoiceStatus.OPEN, None]),
                Document.is_deleted == False
            ).count()

            # Überfällige Rechnungen
            overdue_invoices = session.query(Document).filter(
                Document.user_id == user_id,
                Document.invoice_amount.isnot(None),
                Document.invoice_status == InvoiceStatus.OVERDUE,
                Document.is_deleted == False
            ).count()

            # Bezahlte Rechnungen (letzten 90 Tage)
            paid_invoices = session.query(Document).filter(
                Document.user_id == user_id,
                Document.invoice_status == InvoiceStatus.PAID,
                Document.invoice_paid_date >= datetime.now() - timedelta(days=90),
                Document.is_deleted == False
            ).count()

            # Nicht zugeordnete Transaktionen (letzten 90 Tage)
            unmatched_transactions = session.query(BankTransaction).filter(
                BankTransaction.user_id == user_id,
                BankTransaction.document_id.is_(None),
                BankTransaction.receipt_id.is_(None),
                BankTransaction.booking_date >= datetime.now() - timedelta(days=90),
                BankTransaction.amount < 0
            ).count()

            # Offener Betrag
            open_amount = session.query(Document).filter(
                Document.user_id == user_id,
                Document.invoice_amount.isnot(None),
                Document.invoice_status.in_([InvoiceStatus.OPEN, InvoiceStatus.OVERDUE, None]),
                Document.is_deleted == False
            ).with_entities(Document.invoice_amount).all()

            total_open = sum(amt[0] for amt in open_amount if amt[0])

            return {
                "open_invoices": open_invoices,
                "overdue_invoices": overdue_invoices,
                "paid_invoices_90d": paid_invoices,
                "unmatched_transactions_90d": unmatched_transactions,
                "total_open_amount": round(total_open, 2)
            }

        finally:
            session.close()


def get_invoice_matching_service() -> InvoiceMatchingService:
    """Factory-Funktion für den InvoiceMatchingService"""
    return InvoiceMatchingService()
