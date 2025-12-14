"""
Steuer-Report Service
Erstellt steuerrelevante Übersichten und Berichte
"""
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from decimal import Decimal
import json

from database.models import Document, get_session
from database.extended_models import (
    MileageTrip, TripPurpose, Subscription, Insurance
)


class TaxReportService:
    """Service für Steuer-Berichte"""

    # Steuerrelevante Kategorien
    TAX_CATEGORIES = {
        "werbungskosten": [
            "Arbeitsmittel", "Fachliteratur", "Fortbildung",
            "Kontoführung", "Telefon/Internet", "Bürobedarf"
        ],
        "sonderausgaben": [
            "Versicherung", "Spende", "Kirchensteuer",
            "Riester", "Altersvorsorge"
        ],
        "haushaltsnahe": [
            "Handwerker", "Haushaltshilfe", "Gärtner",
            "Reinigung", "Reparatur"
        ],
        "krankheit": [
            "Arzt", "Medikamente", "Brille", "Zahnarzt",
            "Krankenhaus", "Physiotherapie"
        ]
    }

    def __init__(self, user_id: int):
        self.user_id = user_id

    def generate_yearly_report(self, year: int) -> Dict[str, Any]:
        """Generiert Jahres-Steuerbericht"""
        start_date = datetime(year, 1, 1)
        end_date = datetime(year, 12, 31, 23, 59, 59)

        report = {
            "year": year,
            "generated_at": datetime.now().isoformat(),
            "documents": self._get_tax_documents(start_date, end_date),
            "categories": {},
            "mileage": self._get_mileage_summary(year),
            "subscriptions": self._get_deductible_subscriptions(),
            "insurances": self._get_deductible_insurances(),
            "totals": {}
        }

        # Nach Kategorien gruppieren
        for doc in report["documents"]:
            cat = doc.get("tax_category", "sonstige")
            if cat not in report["categories"]:
                report["categories"][cat] = {"items": [], "total": 0}

            report["categories"][cat]["items"].append(doc)
            report["categories"][cat]["total"] += doc.get("amount", 0)

        # Gesamtsummen berechnen
        report["totals"] = {
            "documents": sum(c["total"] for c in report["categories"].values()),
            "mileage": report["mileage"].get("total_deductible", 0),
            "subscriptions": report["subscriptions"].get("total_deductible", 0),
            "insurances": report["insurances"].get("total_deductible", 0)
        }

        report["totals"]["grand_total"] = sum(report["totals"].values())

        return report

    def _get_tax_documents(self, start_date: datetime,
                           end_date: datetime) -> List[Dict]:
        """Holt steuerrelevante Dokumente"""
        with get_session() as session:
            # Dokumente mit Rechnungen
            docs = session.query(Document).filter(
                Document.user_id == self.user_id,
                Document.is_deleted == False,
                Document.document_date >= start_date,
                Document.document_date <= end_date,
                Document.invoice_amount != None
            ).all()

            result = []
            for doc in docs:
                tax_cat = self._categorize_for_tax(doc)

                result.append({
                    "id": doc.id,
                    "title": doc.title,
                    "date": doc.document_date.isoformat() if doc.document_date else None,
                    "sender": doc.sender,
                    "amount": float(doc.invoice_amount) if doc.invoice_amount else 0,
                    "category": doc.category,
                    "tax_category": tax_cat,
                    "invoice_number": doc.invoice_number
                })

            return result

    def _categorize_for_tax(self, doc: Document) -> str:
        """Kategorisiert Dokument für Steuerzwecke"""
        text = f"{doc.sender or ''} {doc.category or ''} {doc.title or ''}".lower()

        for tax_cat, keywords in self.TAX_CATEGORIES.items():
            for keyword in keywords:
                if keyword.lower() in text:
                    return tax_cat

        return "sonstige"

    def _get_mileage_summary(self, year: int) -> Dict[str, Any]:
        """Holt Fahrtkosten-Zusammenfassung"""
        with get_session() as session:
            trips = session.query(MileageTrip).filter(
                MileageTrip.user_id == self.user_id,
                MileageTrip.trip_date >= datetime(year, 1, 1),
                MileageTrip.trip_date <= datetime(year, 12, 31, 23, 59, 59)
            ).all()

            business_km = sum(t.distance_km for t in trips if t.purpose == TripPurpose.BUSINESS)
            commute_km = sum(t.distance_km for t in trips if t.purpose == TripPurpose.COMMUTE)

            # Pauschale: 0.30€/km
            business_deductible = business_km * 0.30
            # Entfernungspauschale: 0.30€/km einfache Strecke
            commute_deductible = commute_km * 0.30 / 2  # Einfache Strecke

            return {
                "business_km": business_km,
                "commute_km": commute_km,
                "total_km": business_km + commute_km,
                "business_deductible": round(business_deductible, 2),
                "commute_deductible": round(commute_deductible, 2),
                "total_deductible": round(business_deductible + commute_deductible, 2),
                "trips_count": len(trips)
            }

    def _get_deductible_subscriptions(self) -> Dict[str, Any]:
        """Holt absetzbare Abonnements"""
        deductible_categories = ["software", "education", "productivity", "cloud"]

        with get_session() as session:
            subs = session.query(Subscription).filter(
                Subscription.user_id == self.user_id,
                Subscription.is_active == True,
                Subscription.category.in_(deductible_categories)
            ).all()

            total = 0
            items = []

            for sub in subs:
                yearly = sub.amount * 12  # Vereinfacht
                total += yearly
                items.append({
                    "name": sub.name,
                    "yearly_cost": round(yearly, 2),
                    "category": sub.category
                })

            return {
                "items": items,
                "total_deductible": round(total, 2)
            }

    def _get_deductible_insurances(self) -> Dict[str, Any]:
        """Holt absetzbare Versicherungen"""
        with get_session() as session:
            insurances = session.query(Insurance).filter(
                Insurance.user_id == self.user_id,
                Insurance.is_active == True
            ).all()

            total = 0
            items = []

            for ins in insurances:
                # Nur bestimmte Versicherungen sind absetzbar
                if ins.insurance_type.value in ["liability", "legal", "disability", "health"]:
                    yearly = ins.premium_amount * 12  # Vereinfacht
                    total += yearly
                    items.append({
                        "company": ins.company,
                        "type": ins.insurance_type.value,
                        "yearly_cost": round(yearly, 2)
                    })

            return {
                "items": items,
                "total_deductible": round(total, 2)
            }

    def get_monthly_breakdown(self, year: int) -> Dict[str, List[Dict]]:
        """Gibt monatliche Aufschlüsselung"""
        breakdown = {}

        with get_session() as session:
            for month in range(1, 13):
                start = datetime(year, month, 1)
                if month == 12:
                    end = datetime(year + 1, 1, 1) - timedelta(seconds=1)
                else:
                    end = datetime(year, month + 1, 1) - timedelta(seconds=1)

                docs = session.query(Document).filter(
                    Document.user_id == self.user_id,
                    Document.is_deleted == False,
                    Document.document_date >= start,
                    Document.document_date <= end,
                    Document.invoice_amount != None
                ).all()

                month_name = start.strftime("%B")
                breakdown[month_name] = {
                    "count": len(docs),
                    "total": sum(float(d.invoice_amount or 0) for d in docs),
                    "documents": [{
                        "title": d.title,
                        "amount": float(d.invoice_amount or 0),
                        "sender": d.sender
                    } for d in docs]
                }

        return breakdown

    def export_for_steuerberater(self, year: int) -> Dict[str, Any]:
        """Exportiert Daten für Steuerberater"""
        report = self.generate_yearly_report(year)

        # Vereinfachtes Format für Export
        export = {
            "steuerjahr": year,
            "erstellt_am": datetime.now().isoformat(),
            "werbungskosten": [],
            "sonderausgaben": [],
            "fahrtkosten": report["mileage"],
            "versicherungen": report["insurances"]["items"],
            "zusammenfassung": report["totals"]
        }

        # Dokumente kategorisieren
        for cat, data in report["categories"].items():
            for item in data["items"]:
                entry = {
                    "datum": item["date"],
                    "beschreibung": item["title"],
                    "betrag": item["amount"],
                    "beleg_nr": item["invoice_number"],
                    "absender": item["sender"]
                }

                if cat in ["werbungskosten"]:
                    export["werbungskosten"].append(entry)
                elif cat in ["sonderausgaben", "krankheit"]:
                    export["sonderausgaben"].append(entry)

        return export

    def get_missing_receipts(self, year: int) -> List[Dict]:
        """Findet fehlende Belege"""
        missing = []

        with get_session() as session:
            # Transaktionen ohne Beleg
            docs = session.query(Document).filter(
                Document.user_id == self.user_id,
                Document.document_date >= datetime(year, 1, 1),
                Document.document_date <= datetime(year, 12, 31),
                Document.invoice_amount != None,
                Document.file_path == None
            ).all()

            for doc in docs:
                missing.append({
                    "id": doc.id,
                    "title": doc.title,
                    "date": doc.document_date,
                    "amount": doc.invoice_amount,
                    "sender": doc.sender
                })

        return missing
