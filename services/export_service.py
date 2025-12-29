"""
Export-Service für DATEV und andere Formate
"""
from datetime import datetime, date
from typing import List, Optional, BinaryIO
import csv
import io
import json
import zipfile
from pathlib import Path

from database.db import get_db
from database.models import Document, Receipt, InvoiceStatus


class ExportService:
    """Service für Datenexport in verschiedenen Formaten"""

    # DATEV-Buchungsschlüssel (häufig verwendete)
    DATEV_KEYS = {
        'Rechnung': '1000',  # Wareneingang
        'Miete': '4210',
        'Strom': '4240',
        'Versicherung': '4360',
        'Telefon': '4920',
        'Büromaterial': '4930',
        'Porto': '4910',
        'Sonstiges': '4900'
    }

    @staticmethod
    def export_datev_csv(
        user_id: int,
        from_date: date,
        to_date: date,
        include_receipts: bool = True,
        include_invoices: bool = True
    ) -> str:
        """
        Exportiert Buchungsdaten im DATEV-kompatiblen CSV-Format.

        Format: DATEV-Buchungsstapel (ASCII)
        """
        output = io.StringIO()

        # DATEV-Header
        header = [
            "DATEV-Format",
            "1.0",
            datetime.now().strftime("%Y%m%d"),
            "",
            "",
            "",
            "",
            ""
        ]

        # Buchungssatz-Header
        buchung_header = [
            "Umsatz",
            "Soll/Haben",
            "WKZ",
            "Kurs",
            "Basisumsatz",
            "Konto",
            "Gegenkonto",
            "BU-Schlüssel",
            "Belegdatum",
            "Belegfeld 1",
            "Belegfeld 2",
            "Skonto",
            "Buchungstext",
            "Kostenstelle 1",
            "Kostenstelle 2",
            "Stück",
            "Gewicht"
        ]

        writer = csv.writer(output, delimiter=';', quotechar='"')

        # Header schreiben
        writer.writerow(buchung_header)

        with get_db() as session:
            # Rechnungen exportieren
            if include_invoices:
                invoices = session.query(Document).filter(
                    Document.user_id == user_id,
                    Document.invoice_amount.isnot(None),
                    Document.invoice_amount > 0,
                    Document.invoice_status == InvoiceStatus.PAID,
                    Document.invoice_paid_date >= datetime.combine(from_date, datetime.min.time()),
                    Document.invoice_paid_date <= datetime.combine(to_date, datetime.max.time())
                ).all()

                for inv in invoices:
                    # Kategorie zu Buchungsschlüssel
                    bu_key = ExportService.DATEV_KEYS.get(inv.category, '4900')

                    row = [
                        f"{inv.invoice_amount:.2f}".replace('.', ','),  # Umsatz
                        "S",  # Soll
                        "EUR",  # Währung
                        "",  # Kurs
                        "",  # Basisumsatz
                        bu_key,  # Konto (Aufwandskonto)
                        "1200",  # Gegenkonto (Bank)
                        "",  # BU-Schlüssel
                        inv.invoice_paid_date.strftime("%d%m") if inv.invoice_paid_date else "",
                        inv.invoice_number or "",  # Belegfeld 1
                        inv.sender or "",  # Belegfeld 2
                        "",  # Skonto
                        f"{inv.sender or ''} {inv.title or ''}".strip()[:60],  # Buchungstext
                        "",  # Kostenstelle 1
                        "",  # Kostenstelle 2
                        "",  # Stück
                        ""   # Gewicht
                    ]
                    writer.writerow(row)

            # Bons exportieren
            if include_receipts:
                receipts = session.query(Receipt).filter(
                    Receipt.user_id == user_id,
                    Receipt.date >= datetime.combine(from_date, datetime.min.time()),
                    Receipt.date <= datetime.combine(to_date, datetime.max.time())
                ).all()

                for receipt in receipts:
                    bu_key = ExportService.DATEV_KEYS.get(receipt.category, '4900')

                    row = [
                        f"{receipt.total_amount:.2f}".replace('.', ','),
                        "S",
                        "EUR",
                        "",
                        "",
                        bu_key,
                        "1200",
                        "",
                        receipt.date.strftime("%d%m"),
                        "",
                        receipt.merchant or "",
                        "",
                        f"{receipt.merchant or ''} {receipt.category or ''}".strip()[:60],
                        "",
                        "",
                        "",
                        ""
                    ]
                    writer.writerow(row)

        return output.getvalue()

    @staticmethod
    def export_excel(
        user_id: int,
        from_date: date,
        to_date: date,
        include_receipts: bool = True,
        include_invoices: bool = True
    ) -> bytes:
        """Exportiert Daten als Excel-Datei"""
        try:
            import pandas as pd
            from io import BytesIO

            data = []

            with get_db() as session:
                if include_invoices:
                    invoices = session.query(Document).filter(
                        Document.user_id == user_id,
                        Document.invoice_amount.isnot(None),
                        Document.document_date >= datetime.combine(from_date, datetime.min.time()),
                        Document.document_date <= datetime.combine(to_date, datetime.max.time())
                    ).all()

                    for inv in invoices:
                        data.append({
                            'Typ': 'Rechnung',
                            'Datum': inv.document_date or inv.created_at,
                            'Absender': inv.sender or '',
                            'Beschreibung': inv.title or inv.filename,
                            'Betrag': inv.invoice_amount or 0,
                            'Kategorie': inv.category or '',
                            'Status': 'Bezahlt' if inv.invoice_status == InvoiceStatus.PAID else 'Offen',
                            'Bezahlt am': inv.invoice_paid_date,
                            'Bezahlt mit': inv.paid_with_bank_account or '',
                            'IBAN': inv.iban or '',
                            'Rechnungsnummer': inv.invoice_number or '',
                            'Kundennummer': inv.customer_number or ''
                        })

                if include_receipts:
                    receipts = session.query(Receipt).filter(
                        Receipt.user_id == user_id,
                        Receipt.date >= datetime.combine(from_date, datetime.min.time()),
                        Receipt.date <= datetime.combine(to_date, datetime.max.time())
                    ).all()

                    for receipt in receipts:
                        data.append({
                            'Typ': 'Bon',
                            'Datum': receipt.date,
                            'Absender': receipt.merchant or '',
                            'Beschreibung': receipt.category or 'Einkauf',
                            'Betrag': receipt.total_amount,
                            'Kategorie': receipt.category or '',
                            'Status': 'Bezahlt',
                            'Bezahlt am': receipt.date,
                            'Bezahlt mit': '',
                            'IBAN': '',
                            'Rechnungsnummer': '',
                            'Kundennummer': ''
                        })

            if not data:
                # Leere Excel-Datei
                df = pd.DataFrame(columns=[
                    'Typ', 'Datum', 'Absender', 'Beschreibung', 'Betrag',
                    'Kategorie', 'Status', 'Bezahlt am', 'Bezahlt mit',
                    'IBAN', 'Rechnungsnummer', 'Kundennummer'
                ])
            else:
                df = pd.DataFrame(data)
                df = df.sort_values('Datum', ascending=False)

            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Finanzen', index=False)

                # Formatierung
                worksheet = writer.sheets['Finanzen']

                # Spaltenbreiten anpassen
                for column in worksheet.columns:
                    max_length = 0
                    column_letter = column[0].column_letter
                    for cell in column:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass
                    adjusted_width = min(max_length + 2, 50)
                    worksheet.column_dimensions[column_letter].width = adjusted_width

            return output.getvalue()

        except ImportError:
            raise ImportError("pandas und openpyxl werden für Excel-Export benötigt")

    @staticmethod
    def export_json(
        user_id: int,
        from_date: date,
        to_date: date,
        include_receipts: bool = True,
        include_invoices: bool = True
    ) -> str:
        """Exportiert Daten als JSON"""
        data = {
            'export_date': datetime.now().isoformat(),
            'period': {
                'from': from_date.isoformat(),
                'to': to_date.isoformat()
            },
            'invoices': [],
            'receipts': []
        }

        with get_db() as session:
            if include_invoices:
                invoices = session.query(Document).filter(
                    Document.user_id == user_id,
                    Document.invoice_amount.isnot(None),
                    Document.document_date >= datetime.combine(from_date, datetime.min.time()),
                    Document.document_date <= datetime.combine(to_date, datetime.max.time())
                ).all()

                for inv in invoices:
                    data['invoices'].append({
                        'id': inv.id,
                        'date': inv.document_date.isoformat() if inv.document_date else None,
                        'sender': inv.sender,
                        'title': inv.title or inv.filename,
                        'amount': inv.invoice_amount,
                        'currency': inv.invoice_currency or 'EUR',
                        'category': inv.category,
                        'status': inv.invoice_status.value if inv.invoice_status else None,
                        'paid_date': inv.invoice_paid_date.isoformat() if inv.invoice_paid_date else None,
                        'paid_with': inv.paid_with_bank_account,
                        'invoice_number': inv.invoice_number,
                        'customer_number': inv.customer_number,
                        'iban': inv.iban,
                        'bic': inv.bic
                    })

            if include_receipts:
                receipts = session.query(Receipt).filter(
                    Receipt.user_id == user_id,
                    Receipt.date >= datetime.combine(from_date, datetime.min.time()),
                    Receipt.date <= datetime.combine(to_date, datetime.max.time())
                ).all()

                for receipt in receipts:
                    data['receipts'].append({
                        'id': receipt.id,
                        'date': receipt.date.isoformat() if receipt.date else None,
                        'merchant': receipt.merchant,
                        'amount': receipt.total_amount,
                        'currency': receipt.currency or 'EUR',
                        'category': receipt.category,
                        'items': receipt.items,
                        'notes': receipt.notes
                    })

        return json.dumps(data, indent=2, ensure_ascii=False)

    @staticmethod
    def get_summary(
        user_id: int,
        from_date: date,
        to_date: date
    ) -> dict:
        """Erstellt eine Zusammenfassung für den Export-Zeitraum"""
        summary = {
            'period': {
                'from': from_date.isoformat(),
                'to': to_date.isoformat()
            },
            'invoices': {
                'count': 0,
                'total': 0.0,
                'paid': 0,
                'open': 0,
                'by_category': {}
            },
            'receipts': {
                'count': 0,
                'total': 0.0,
                'by_category': {}
            }
        }

        with get_db() as session:
            # Rechnungen
            invoices = session.query(Document).filter(
                Document.user_id == user_id,
                Document.invoice_amount.isnot(None),
                Document.document_date >= datetime.combine(from_date, datetime.min.time()),
                Document.document_date <= datetime.combine(to_date, datetime.max.time())
            ).all()

            summary['invoices']['count'] = len(invoices)
            for inv in invoices:
                amount = inv.invoice_amount or 0
                summary['invoices']['total'] += amount

                if inv.invoice_status == InvoiceStatus.PAID:
                    summary['invoices']['paid'] += 1
                else:
                    summary['invoices']['open'] += 1

                cat = inv.category or 'Sonstiges'
                if cat not in summary['invoices']['by_category']:
                    summary['invoices']['by_category'][cat] = {'count': 0, 'total': 0}
                summary['invoices']['by_category'][cat]['count'] += 1
                summary['invoices']['by_category'][cat]['total'] += amount

            # Bons
            receipts = session.query(Receipt).filter(
                Receipt.user_id == user_id,
                Receipt.date >= datetime.combine(from_date, datetime.min.time()),
                Receipt.date <= datetime.combine(to_date, datetime.max.time())
            ).all()

            summary['receipts']['count'] = len(receipts)
            for receipt in receipts:
                amount = receipt.total_amount or 0
                summary['receipts']['total'] += amount

                cat = receipt.category or 'Sonstiges'
                if cat not in summary['receipts']['by_category']:
                    summary['receipts']['by_category'][cat] = {'count': 0, 'total': 0}
                summary['receipts']['by_category'][cat]['count'] += 1
                summary['receipts']['by_category'][cat]['total'] += amount

        return summary


# Singleton-Instanz
_export_service = None


def get_export_service() -> ExportService:
    """Gibt die Singleton-Instanz des Export-Service zurück"""
    global _export_service
    if _export_service is None:
        _export_service = ExportService()
    return _export_service
