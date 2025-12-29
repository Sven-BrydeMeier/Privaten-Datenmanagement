"""
Kilometerlogbuch Seite
Fahrten erfassen für Steuerzwecke
"""
import streamlit as st
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go

# Imports
try:
    from services.mileage_service import MileageService
    from database.extended_models import TripPurpose
    MILEAGE_AVAILABLE = True
except ImportError:
    MILEAGE_AVAILABLE = False


def render_mileage_page():
    """Rendert die Kilometerlogbuch-Seite"""
    st.title("Kilometerlogbuch")
    st.markdown("Fahrten erfassen für die Steuererklärung")

    if not MILEAGE_AVAILABLE:
        st.error("Kilometerlogbuch-Module nicht verfügbar.")
        return

    if "user" not in st.session_state or not st.session_state.user:
        st.warning("Bitte melden Sie sich an.")
        return

    user_id = st.session_state.user.get("id", 1)
    service = MileageService(user_id)

    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs([
        "Übersicht", "Neue Fahrt", "Fahrzeuge", "Jahresauswertung"
    ])

    with tab1:
        render_overview(service)

    with tab2:
        render_new_trip(service)

    with tab3:
        render_vehicles(service)

    with tab4:
        render_yearly_report(service)


def render_overview(service: MileageService):
    """Tab: Übersicht"""
    stats = service.get_statistics()

    # Metriken
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Gesamte Fahrten", stats.get("total_trips", 0))

    with col2:
        st.metric("Gesamte Kilometer", f"{stats.get('total_km', 0):,.0f} km")

    with col3:
        st.metric("Geschäftlich", f"{stats.get('business_km', 0):,.0f} km")

    with col4:
        st.metric(
            "Erstattungsfähig",
            f"{stats.get('total_reimbursable', 0):,.2f}€",
            help="Bei 0,30€/km Pauschale"
        )

    st.divider()

    # Letzte Fahrten
    st.subheader("Letzte Fahrten")

    trips = service.get_trips()[:10]

    if not trips:
        st.info("Noch keine Fahrten erfasst.")
        return

    for trip in trips:
        purpose_icon = get_purpose_icon(trip.purpose)
        reimbursement = service.calculate_reimbursement(trip)

        col1, col2, col3, col4 = st.columns([2, 1, 1, 1])

        with col1:
            st.markdown(f"{purpose_icon} **{trip.description or 'Fahrt'}**")
            if trip.start_location and trip.end_location:
                st.caption(f"{trip.start_location} → {trip.end_location}")

        with col2:
            st.markdown(trip.trip_date.strftime("%d.%m.%Y"))

        with col3:
            st.markdown(f"**{trip.distance_km:.1f} km**")

        with col4:
            if trip.is_tax_deductible:
                st.markdown(f"💰 {reimbursement:.2f}€")

        st.divider()


def render_new_trip(service: MileageService):
    """Tab: Neue Fahrt"""
    st.subheader("Neue Fahrt erfassen")

    vehicles = service.get_all_vehicles()

    if not vehicles:
        st.warning("Bitte legen Sie zuerst ein Fahrzeug an (Tab 'Fahrzeuge').")
        return

    with st.form("new_trip_form"):
        col1, col2 = st.columns(2)

        with col1:
            vehicle_options = {v.name: v.id for v in vehicles}
            selected_vehicle = st.selectbox("Fahrzeug", options=list(vehicle_options.keys()))
            vehicle_id = vehicle_options[selected_vehicle]

            trip_date = st.date_input("Datum", value=datetime.now())

            purpose = st.selectbox(
                "Fahrtzweck",
                options=[p.value for p in TripPurpose],
                format_func=get_purpose_name
            )

            description = st.text_input("Beschreibung", placeholder="z.B. Kundenbesuch")

        with col2:
            start_location = st.text_input("Startort", placeholder="z.B. Zuhause")
            end_location = st.text_input("Zielort", placeholder="z.B. Büro Kunde XY")
            distance_km = st.number_input("Entfernung (km)", min_value=0.0, step=0.1)

            if purpose == "business":
                client_name = st.text_input("Kunde/Auftraggeber")
                project_name = st.text_input("Projekt")
            else:
                client_name = None
                project_name = None

        # Kosten (optional)
        with st.expander("Zusätzliche Kosten"):
            cost_col1, cost_col2 = st.columns(2)

            with cost_col1:
                fuel_cost = st.number_input("Tankkosten (€)", min_value=0.0, step=0.01)
                toll_cost = st.number_input("Maut (€)", min_value=0.0, step=0.01)

            with cost_col2:
                parking_cost = st.number_input("Parkgebühren (€)", min_value=0.0, step=0.01)
                other_costs = st.number_input("Sonstige Kosten (€)", min_value=0.0, step=0.01)

        notes = st.text_area("Notizen")

        submitted = st.form_submit_button("Fahrt speichern", type="primary")

        if submitted:
            if distance_km <= 0:
                st.error("Bitte geben Sie eine gültige Entfernung ein.")
            else:
                trip = service.create_trip(
                    vehicle_id=vehicle_id,
                    trip_date=datetime.combine(trip_date, datetime.min.time()),
                    distance_km=distance_km,
                    purpose=TripPurpose(purpose),
                    description=description,
                    start_location=start_location,
                    end_location=end_location,
                    fuel_cost=fuel_cost if fuel_cost > 0 else None,
                    toll_cost=toll_cost if toll_cost > 0 else None,
                    parking_cost=parking_cost if parking_cost > 0 else None,
                    other_costs=other_costs if other_costs > 0 else None,
                    client_name=client_name,
                    project_name=project_name,
                    notes=notes
                )

                reimbursement = service.calculate_reimbursement(trip)
                st.success(f"Fahrt erfasst! Erstattungsfähig: {reimbursement:.2f}€")

    # Schnell-Erfassung Pendler
    st.divider()
    st.subheader("Schnell-Erfassung: Arbeitsweg")

    col1, col2, col3 = st.columns(3)

    with col1:
        quick_vehicle = st.selectbox(
            "Fahrzeug",
            options=list(vehicle_options.keys()),
            key="quick_vehicle"
        )

    with col2:
        quick_distance = st.number_input(
            "Einfache Strecke (km)",
            min_value=0.0,
            step=0.1,
            key="quick_distance",
            help="Wird automatisch verdoppelt (Hin+Rück)"
        )

    with col3:
        quick_days = st.number_input(
            "Anzahl Tage",
            min_value=1,
            max_value=31,
            value=5,
            key="quick_days"
        )

    if st.button("Arbeitsweg hinzufügen"):
        if quick_distance > 0:
            trips = service.quick_add_commute(
                vehicle_id=vehicle_options[quick_vehicle],
                distance_km=quick_distance,
                work_days=quick_days
            )
            st.success(f"{len(trips)} Fahrten hinzugefügt!")
            st.rerun()


def render_vehicles(service: MileageService):
    """Tab: Fahrzeuge"""
    st.subheader("Fahrzeuge verwalten")

    vehicles = service.get_all_vehicles(active_only=False)

    # Vorhandene Fahrzeuge
    if vehicles:
        for vehicle in vehicles:
            status = "🟢" if vehicle.is_active else "🔴"

            with st.expander(f"{status} {vehicle.name}"):
                col1, col2 = st.columns(2)

                with col1:
                    st.markdown(f"**Kennzeichen:** {vehicle.license_plate or '-'}")
                    st.markdown(f"**Marke:** {vehicle.make or '-'}")
                    st.markdown(f"**Modell:** {vehicle.model or '-'}")
                    st.markdown(f"**Baujahr:** {vehicle.year or '-'}")

                with col2:
                    if vehicle.current_odometer:
                        st.metric("Kilometerstand", f"{vehicle.current_odometer:,} km")
                    st.markdown(f"**Kraftstoff:** {vehicle.fuel_type or '-'}")
                    if vehicle.business_use_percentage:
                        st.markdown(f"**Geschäftliche Nutzung:** {vehicle.business_use_percentage}%")

                if vehicle.is_active:
                    if st.button("Deaktivieren", key=f"deactivate_{vehicle.id}"):
                        service.delete_vehicle(vehicle.id)
                        st.success("Fahrzeug deaktiviert")
                        st.rerun()

    # Neues Fahrzeug
    st.divider()
    st.subheader("Neues Fahrzeug hinzufügen")

    with st.form("new_vehicle_form"):
        col1, col2 = st.columns(2)

        with col1:
            name = st.text_input("Name *", placeholder="z.B. Mein Auto")
            license_plate = st.text_input("Kennzeichen", placeholder="z.B. B-AB 1234")
            make = st.text_input("Marke", placeholder="z.B. VW")
            model = st.text_input("Modell", placeholder="z.B. Golf")

        with col2:
            year = st.number_input("Baujahr", min_value=1990, max_value=2030, value=2020)
            initial_odometer = st.number_input("Anfangs-Kilometerstand", min_value=0, value=0)
            fuel_type = st.selectbox(
                "Kraftstoff",
                options=["petrol", "diesel", "electric", "hybrid", "other"],
                format_func=lambda x: {
                    "petrol": "Benzin",
                    "diesel": "Diesel",
                    "electric": "Elektro",
                    "hybrid": "Hybrid",
                    "other": "Sonstige"
                }.get(x, x)
            )
            business_use = st.slider("Geschäftliche Nutzung (%)", 0, 100, 50)

        submitted = st.form_submit_button("Fahrzeug speichern", type="primary")

        if submitted:
            if not name:
                st.error("Bitte geben Sie einen Namen ein.")
            else:
                service.create_vehicle(
                    name=name,
                    license_plate=license_plate,
                    make=make,
                    model=model,
                    year=year,
                    initial_odometer=initial_odometer,
                    fuel_type=fuel_type,
                    business_use_percentage=business_use
                )
                st.success(f"Fahrzeug '{name}' hinzugefügt!")
                st.rerun()


def render_yearly_report(service: MileageService):
    """Tab: Jahresauswertung"""
    st.subheader("Jahresauswertung")

    year = st.selectbox(
        "Jahr",
        options=list(range(datetime.now().year, 2019, -1)),
        index=0
    )

    summary = service.get_year_summary(year)

    # Übersicht
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Fahrten", summary["total_trips"])

    with col2:
        st.metric("Kilometer gesamt", f"{summary['total_km']:,.0f}")

    with col3:
        st.metric("Steuerlich absetzbar", f"{summary['tax_deductible']:,.2f}€")

    with col4:
        total_costs = summary["total_costs"]["total"]
        st.metric("Gesamtkosten", f"{total_costs:,.2f}€")

    st.divider()

    # Nach Zweck
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Nach Fahrtzweck")

        purpose_data = summary["by_purpose"]
        if any(p["trips"] > 0 for p in purpose_data.values()):
            fig = px.pie(
                values=[p["km"] for p in purpose_data.values()],
                names=[get_purpose_name(k) for k in purpose_data.keys()],
                hole=0.4
            )
            fig.update_layout(margin=dict(t=20, b=20, l=20, r=20), height=300)
            st.plotly_chart(fig, use_container_width=True)

            for purpose, data in purpose_data.items():
                if data["trips"] > 0:
                    st.markdown(f"**{get_purpose_name(purpose)}:** {data['km']:.0f} km ({data['trips']} Fahrten) = {data['reimbursement']:.2f}€")

    with col2:
        st.subheader("Nach Monat")

        month_data = summary["by_month"]
        months = list(month_data.keys())
        km_values = [month_data[m]["km"] for m in months]

        fig = px.bar(
            x=["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"],
            y=km_values,
            labels={"x": "Monat", "y": "Kilometer"}
        )
        fig.update_layout(margin=dict(t=20, b=20, l=20, r=20), height=300)
        st.plotly_chart(fig, use_container_width=True)

    # Export
    st.divider()
    st.subheader("Export für Steuererklärung")

    trips = service.get_trips(year=year)

    if trips:
        # CSV erstellen
        csv_lines = ["Datum;Zweck;Strecke;Kilometer;Erstattung"]
        for trip in trips:
            reimbursement = service.calculate_reimbursement(trip)
            start_end = f"{trip.start_location or ''} - {trip.end_location or ''}"
            csv_lines.append(
                f"{trip.trip_date.strftime('%d.%m.%Y')};{get_purpose_name(trip.purpose.value)};{start_end};{trip.distance_km};{reimbursement:.2f}"
            )

        csv_data = "\n".join(csv_lines)

        st.download_button(
            "Als CSV herunterladen",
            data=csv_data,
            file_name=f"kilometerlogbuch_{year}.csv",
            mime="text/csv"
        )

        st.info(f"""
        **Für die Steuererklärung {year}:**
        - Geschäftliche Fahrten: {summary['by_purpose'].get('business', {}).get('km', 0):.0f} km × 0,30€ = {summary['by_purpose'].get('business', {}).get('reimbursement', 0):.2f}€
        - Pendlerpauschale: {summary['by_purpose'].get('commute', {}).get('km', 0):.0f} km / 2 × 0,30€ = {summary['by_purpose'].get('commute', {}).get('reimbursement', 0):.2f}€
        """)


def get_purpose_icon(purpose: TripPurpose) -> str:
    """Gibt Icon für Fahrtzweck zurück"""
    icons = {
        TripPurpose.BUSINESS: "💼",
        TripPurpose.PRIVATE: "🏠",
        TripPurpose.COMMUTE: "🏢"
    }
    return icons.get(purpose, "🚗")


def get_purpose_name(purpose: str) -> str:
    """Gibt deutschen Namen für Fahrtzweck zurück"""
    names = {
        "business": "Geschäftlich",
        "private": "Privat",
        "commute": "Arbeitsweg"
    }
    return names.get(purpose, purpose)


# ==================== HAUPTFUNKTION ====================

if __name__ == "__main__":
    st.set_page_config(page_title="Kilometerlogbuch", page_icon="🚗", layout="wide")
    render_mileage_page()
else:
    render_mileage_page()
