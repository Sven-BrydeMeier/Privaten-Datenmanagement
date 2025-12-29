"""
Kilometerlogbuch Service
Verwaltet Fahrzeuge und Fahrten für Steuerzwecke
"""
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from database.models import get_session
from database.extended_models import Vehicle, MileageTrip, TripPurpose


class MileageService:
    """Service für Kilometerlogbuch"""

    # Pauschalen (2024)
    KM_RATE_BUSINESS = 0.30  # €/km für Geschäftsfahrten
    KM_RATE_COMMUTE = 0.30   # €/km für Pendlerpauschale (einfache Strecke)

    def __init__(self, user_id: int):
        self.user_id = user_id

    # ==================== FAHRZEUGE ====================

    def create_vehicle(self, name: str, **kwargs) -> Vehicle:
        """Erstellt ein neues Fahrzeug"""
        with get_session() as session:
            vehicle = Vehicle(
                user_id=self.user_id,
                name=name,
                license_plate=kwargs.get("license_plate"),
                make=kwargs.get("make"),
                model=kwargs.get("model"),
                year=kwargs.get("year"),
                vin=kwargs.get("vin"),
                initial_odometer=kwargs.get("initial_odometer", 0),
                current_odometer=kwargs.get("current_odometer", kwargs.get("initial_odometer", 0)),
                fuel_type=kwargs.get("fuel_type"),
                avg_consumption=kwargs.get("avg_consumption"),
                business_use_percentage=kwargs.get("business_use_percentage")
            )

            session.add(vehicle)
            session.commit()
            session.refresh(vehicle)
            return vehicle

    def get_vehicle(self, vehicle_id: int) -> Optional[Vehicle]:
        """Holt ein Fahrzeug"""
        with get_session() as session:
            return session.query(Vehicle).filter(
                Vehicle.id == vehicle_id,
                Vehicle.user_id == self.user_id
            ).first()

    def get_all_vehicles(self, active_only: bool = True) -> List[Vehicle]:
        """Holt alle Fahrzeuge"""
        with get_session() as session:
            query = session.query(Vehicle).filter(
                Vehicle.user_id == self.user_id
            )

            if active_only:
                query = query.filter(Vehicle.is_active == True)

            return query.order_by(Vehicle.name.asc()).all()

    def update_vehicle(self, vehicle_id: int, **kwargs) -> bool:
        """Aktualisiert ein Fahrzeug"""
        with get_session() as session:
            vehicle = session.query(Vehicle).filter(
                Vehicle.id == vehicle_id,
                Vehicle.user_id == self.user_id
            ).first()

            if not vehicle:
                return False

            for key, value in kwargs.items():
                if hasattr(vehicle, key):
                    setattr(vehicle, key, value)

            vehicle.updated_at = datetime.now()
            session.commit()
            return True

    def delete_vehicle(self, vehicle_id: int) -> bool:
        """Löscht ein Fahrzeug (deaktiviert)"""
        return self.update_vehicle(vehicle_id, is_active=False)

    # ==================== FAHRTEN ====================

    def create_trip(self, vehicle_id: int, trip_date: datetime,
                    distance_km: float, purpose: TripPurpose, **kwargs) -> MileageTrip:
        """Erstellt eine neue Fahrt"""
        with get_session() as session:
            trip = MileageTrip(
                vehicle_id=vehicle_id,
                user_id=self.user_id,
                trip_date=trip_date,
                distance_km=distance_km,
                purpose=purpose,
                description=kwargs.get("description"),
                start_location=kwargs.get("start_location"),
                end_location=kwargs.get("end_location"),
                route_description=kwargs.get("route_description"),
                start_odometer=kwargs.get("start_odometer"),
                end_odometer=kwargs.get("end_odometer"),
                fuel_cost=kwargs.get("fuel_cost"),
                toll_cost=kwargs.get("toll_cost"),
                parking_cost=kwargs.get("parking_cost"),
                other_costs=kwargs.get("other_costs"),
                is_tax_deductible=kwargs.get("is_tax_deductible", True),
                reimbursement_rate=kwargs.get("reimbursement_rate", self.KM_RATE_BUSINESS),
                client_name=kwargs.get("client_name"),
                project_name=kwargs.get("project_name"),
                document_id=kwargs.get("document_id"),
                notes=kwargs.get("notes")
            )

            session.add(trip)

            # Kilometerstand aktualisieren
            if kwargs.get("end_odometer"):
                vehicle = session.query(Vehicle).filter(
                    Vehicle.id == vehicle_id
                ).first()
                if vehicle:
                    vehicle.current_odometer = kwargs["end_odometer"]

            session.commit()
            session.refresh(trip)
            return trip

    def get_trip(self, trip_id: int) -> Optional[MileageTrip]:
        """Holt eine Fahrt"""
        with get_session() as session:
            return session.query(MileageTrip).filter(
                MileageTrip.id == trip_id,
                MileageTrip.user_id == self.user_id
            ).first()

    def get_trips(self, vehicle_id: int = None, year: int = None,
                  month: int = None, purpose: TripPurpose = None) -> List[MileageTrip]:
        """Holt Fahrten mit optionalen Filtern"""
        with get_session() as session:
            query = session.query(MileageTrip).filter(
                MileageTrip.user_id == self.user_id
            )

            if vehicle_id:
                query = query.filter(MileageTrip.vehicle_id == vehicle_id)

            if year:
                start = datetime(year, 1, 1)
                end = datetime(year, 12, 31, 23, 59, 59)
                query = query.filter(
                    MileageTrip.trip_date >= start,
                    MileageTrip.trip_date <= end
                )

            if month and year:
                start = datetime(year, month, 1)
                if month == 12:
                    end = datetime(year + 1, 1, 1) - timedelta(seconds=1)
                else:
                    end = datetime(year, month + 1, 1) - timedelta(seconds=1)
                query = query.filter(
                    MileageTrip.trip_date >= start,
                    MileageTrip.trip_date <= end
                )

            if purpose:
                query = query.filter(MileageTrip.purpose == purpose)

            return query.order_by(MileageTrip.trip_date.desc()).all()

    def update_trip(self, trip_id: int, **kwargs) -> bool:
        """Aktualisiert eine Fahrt"""
        with get_session() as session:
            trip = session.query(MileageTrip).filter(
                MileageTrip.id == trip_id,
                MileageTrip.user_id == self.user_id
            ).first()

            if not trip:
                return False

            for key, value in kwargs.items():
                if hasattr(trip, key):
                    setattr(trip, key, value)

            trip.updated_at = datetime.now()
            session.commit()
            return True

    def delete_trip(self, trip_id: int) -> bool:
        """Löscht eine Fahrt"""
        with get_session() as session:
            trip = session.query(MileageTrip).filter(
                MileageTrip.id == trip_id,
                MileageTrip.user_id == self.user_id
            ).first()

            if not trip:
                return False

            session.delete(trip)
            session.commit()
            return True

    # ==================== BERECHNUNGEN ====================

    def calculate_reimbursement(self, trip: MileageTrip) -> float:
        """Berechnet Erstattungsbetrag für eine Fahrt"""
        rate = trip.reimbursement_rate or self.KM_RATE_BUSINESS

        if trip.purpose == TripPurpose.COMMUTE:
            # Pendlerpauschale: nur einfache Strecke
            return round(trip.distance_km * rate / 2, 2)
        else:
            return round(trip.distance_km * rate, 2)

    def get_year_summary(self, year: int) -> Dict[str, Any]:
        """Jahres-Zusammenfassung"""
        trips = self.get_trips(year=year)

        summary = {
            "year": year,
            "total_trips": len(trips),
            "total_km": sum(t.distance_km for t in trips),
            "by_purpose": {},
            "by_month": {},
            "total_costs": {
                "fuel": sum(t.fuel_cost or 0 for t in trips),
                "toll": sum(t.toll_cost or 0 for t in trips),
                "parking": sum(t.parking_cost or 0 for t in trips),
                "other": sum(t.other_costs or 0 for t in trips)
            },
            "tax_deductible": 0
        }

        # Nach Zweck
        for purpose in TripPurpose:
            purpose_trips = [t for t in trips if t.purpose == purpose]
            km = sum(t.distance_km for t in purpose_trips)
            reimbursement = sum(self.calculate_reimbursement(t) for t in purpose_trips)

            summary["by_purpose"][purpose.value] = {
                "trips": len(purpose_trips),
                "km": km,
                "reimbursement": round(reimbursement, 2)
            }

            if purpose in [TripPurpose.BUSINESS, TripPurpose.COMMUTE]:
                summary["tax_deductible"] += reimbursement

        # Nach Monat
        for month in range(1, 13):
            month_trips = [t for t in trips if t.trip_date.month == month]
            summary["by_month"][month] = {
                "trips": len(month_trips),
                "km": sum(t.distance_km for t in month_trips)
            }

        summary["tax_deductible"] = round(summary["tax_deductible"], 2)
        summary["total_costs"]["total"] = sum(summary["total_costs"].values())

        return summary

    def get_statistics(self, vehicle_id: int = None) -> Dict[str, Any]:
        """Holt Statistiken"""
        with get_session() as session:
            query = session.query(MileageTrip).filter(
                MileageTrip.user_id == self.user_id
            )

            if vehicle_id:
                query = query.filter(MileageTrip.vehicle_id == vehicle_id)

            trips = query.all()

            if not trips:
                return {"total_trips": 0, "total_km": 0}

            return {
                "total_trips": len(trips),
                "total_km": sum(t.distance_km for t in trips),
                "avg_km_per_trip": round(sum(t.distance_km for t in trips) / len(trips), 2),
                "business_km": sum(t.distance_km for t in trips if t.purpose == TripPurpose.BUSINESS),
                "commute_km": sum(t.distance_km for t in trips if t.purpose == TripPurpose.COMMUTE),
                "private_km": sum(t.distance_km for t in trips if t.purpose == TripPurpose.PRIVATE),
                "total_fuel_cost": sum(t.fuel_cost or 0 for t in trips),
                "total_reimbursable": sum(self.calculate_reimbursement(t) for t in trips if t.is_tax_deductible)
            }

    def quick_add_commute(self, vehicle_id: int, distance_km: float,
                          work_days: int = 1) -> List[MileageTrip]:
        """Schnelles Hinzufügen von Pendlerfahrten"""
        trips = []

        for i in range(work_days):
            trip = self.create_trip(
                vehicle_id=vehicle_id,
                trip_date=datetime.now() - timedelta(days=i),
                distance_km=distance_km * 2,  # Hin und zurück
                purpose=TripPurpose.COMMUTE,
                description="Arbeitsweg",
                is_tax_deductible=True
            )
            trips.append(trip)

        return trips
