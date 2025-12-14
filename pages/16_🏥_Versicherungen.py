"""
Versicherungs-Manager Seite
Übersicht und Verwaltung von Versicherungen
"""
import streamlit as st
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go

# Imports
try:
    from services.insurance_service import InsuranceService
    from database.extended_models import Insurance, InsuranceType, SubscriptionInterval
    from database.models import Document, get_session
    INSURANCE_AVAILABLE = True
except ImportError:
    INSURANCE_AVAILABLE = False


def render_insurance_page():
    """Rendert die Versicherungs-Seite"""
    st.title("Versicherungs-Manager")
    st.markdown("Alle Ihre Versicherungen im Überblick")

    if not INSURANCE_AVAILABLE:
        st.error("Versicherungs-Module nicht verfügbar.")
        return

    if "user" not in st.session_state or not st.session_state.user:
        st.warning("Bitte melden Sie sich an.")
        return

    user_id = st.session_state.user.get("id", 1)
    service = InsuranceService(user_id)

    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs([
        "Übersicht", "Neue Versicherung", "Alle Versicherungen", "Schäden"
    ])

    with tab1:
        render_overview(service)

    with tab2:
        render_new_insurance(service, user_id)

    with tab3:
        render_all_insurances(service)

    with tab4:
        render_claims(service)


def render_overview(service: InsuranceService):
    """Tab: Übersicht"""
    stats = service.get_statistics()

    # Metriken
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Aktive Versicherungen", stats["active_insurances"])

    with col2:
        st.metric("Monatliche Kosten", f"{stats['monthly_cost']:.2f}€")

    with col3:
        st.metric("Jährliche Kosten", f"{stats['yearly_cost']:.2f}€")

    with col4:
        st.metric("Deckungssumme", f"{stats['total_coverage']:,.0f}€")

    st.divider()

    # Kosten nach Typ
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Kosten nach Versicherungstyp")
        cost_by_type = service.get_cost_by_type()

        if cost_by_type:
            fig = px.pie(
                values=list(cost_by_type.values()),
                names=[get_insurance_type_name(k) for k in cost_by_type.keys()],
                hole=0.4
            )
            fig.update_layout(margin=dict(t=20, b=20, l=20, r=20), height=300)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Keine Daten vorhanden")

    with col2:
        st.subheader("Kosten nach Unternehmen")
        cost_by_company = service.get_cost_by_company()

        if cost_by_company:
            fig = px.bar(
                x=list(cost_by_company.values()),
                y=list(cost_by_company.keys()),
                orientation='h',
                labels={"x": "Monatliche Kosten (€)", "y": "Unternehmen"}
            )
            fig.update_layout(margin=dict(t=20, b=20, l=20, r=20), height=300)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Keine Daten vorhanden")

    # Deckungslücken
    st.divider()
    gaps = service.get_coverage_gaps()

    if gaps:
        st.warning("**Empfohlene Versicherungen fehlen:**")
        for gap in gaps:
            st.markdown(f"- {get_insurance_type_name(gap)}")
    else:
        st.success("Sie haben alle empfohlenen Grundversicherungen!")

    # Kündigungsfristen
    st.divider()
    st.subheader("Anstehende Kündigungsfristen")

    deadlines = service.get_cancellation_deadlines()

    if deadlines:
        for item in deadlines[:5]:
            ins = item["insurance"]
            col1, col2, col3 = st.columns([3, 1, 1])

            with col1:
                st.markdown(f"**{ins.company}** - {get_insurance_type_name(ins.insurance_type.value)}")

            with col2:
                st.markdown(f"Frist: {item['deadline'].strftime('%d.%m.%Y')}")

            with col3:
                if item["days_remaining"] <= 30:
                    st.error(f"{item['days_remaining']} Tage")
                else:
                    st.info(f"{item['days_remaining']} Tage")
    else:
        st.info("Keine anstehenden Kündigungsfristen")


def render_new_insurance(service: InsuranceService, user_id: int):
    """Tab: Neue Versicherung"""
    st.subheader("Neue Versicherung erfassen")

    with st.form("new_insurance_form"):
        col1, col2 = st.columns(2)

        with col1:
            insurance_type = st.selectbox(
                "Versicherungstyp *",
                options=[t.value for t in InsuranceType],
                format_func=get_insurance_type_name
            )

            company = st.text_input("Versicherungsunternehmen *", placeholder="z.B. Allianz")
            policy_name = st.text_input("Tarifname", placeholder="z.B. Privat-Haftpflicht Plus")
            policy_number = st.text_input("Policennummer")

        with col2:
            premium_amount = st.number_input("Beitrag (€) *", min_value=0.0, step=0.01)

            premium_interval = st.selectbox(
                "Zahlungsintervall",
                options=[i.value for i in SubscriptionInterval],
                format_func=get_interval_name,
                index=0
            )

            start_date = st.date_input("Versicherungsbeginn *", value=datetime.now())
            end_date = st.date_input("Vertragsende (optional)", value=None)

        st.divider()

        col1, col2 = st.columns(2)

        with col1:
            coverage_amount = st.number_input("Deckungssumme (€)", min_value=0.0, step=1000.0)
            deductible = st.number_input("Selbstbeteiligung (€)", min_value=0.0, step=10.0)
            notice_period = st.number_input("Kündigungsfrist (Tage)", min_value=0, value=90)

        with col2:
            agent_name = st.text_input("Ansprechpartner/Vermittler")
            agent_phone = st.text_input("Telefon")
            agent_email = st.text_input("E-Mail")
            claims_phone = st.text_input("Schadenhotline")

        coverage_description = st.text_area("Deckungsumfang", placeholder="Was ist versichert?")
        notes = st.text_area("Notizen")

        auto_renew = st.checkbox("Verlängert sich automatisch", value=True)

        submitted = st.form_submit_button("Versicherung speichern", type="primary")

        if submitted:
            if not company or premium_amount <= 0:
                st.error("Bitte füllen Sie alle Pflichtfelder aus.")
            else:
                insurance = service.create_insurance(
                    insurance_type=InsuranceType(insurance_type),
                    company=company,
                    premium_amount=premium_amount,
                    start_date=datetime.combine(start_date, datetime.min.time()),
                    premium_interval=SubscriptionInterval(premium_interval),
                    policy_name=policy_name,
                    policy_number=policy_number,
                    coverage_amount=coverage_amount if coverage_amount > 0 else None,
                    deductible=deductible if deductible > 0 else None,
                    notice_period_days=notice_period,
                    end_date=datetime.combine(end_date, datetime.min.time()) if end_date else None,
                    agent_name=agent_name,
                    agent_phone=agent_phone,
                    agent_email=agent_email,
                    claims_phone=claims_phone,
                    coverage_description=coverage_description,
                    notes=notes,
                    auto_renew=auto_renew
                )

                st.success(f"Versicherung '{company}' erfolgreich gespeichert!")


def render_all_insurances(service: InsuranceService):
    """Tab: Alle Versicherungen"""
    st.subheader("Alle Versicherungen")

    # Filter
    col1, col2 = st.columns(2)

    with col1:
        show_inactive = st.checkbox("Inaktive anzeigen", value=False)

    with col2:
        filter_type = st.selectbox(
            "Nach Typ filtern",
            options=["Alle"] + [t.value for t in InsuranceType],
            format_func=lambda x: "Alle Typen" if x == "Alle" else get_insurance_type_name(x)
        )

    # Versicherungen abrufen
    insurances = service.get_all_insurances(active_only=not show_inactive)

    if filter_type != "Alle":
        insurances = [i for i in insurances if i.insurance_type.value == filter_type]

    if not insurances:
        st.info("Keine Versicherungen gefunden.")
        return

    # Liste anzeigen
    for ins in insurances:
        icon = get_insurance_icon(ins.insurance_type)
        monthly = service._to_monthly(ins.premium_amount, ins.premium_interval)

        with st.expander(f"{icon} {ins.company} - {get_insurance_type_name(ins.insurance_type.value)}"):
            col1, col2, col3 = st.columns([2, 1, 1])

            with col1:
                st.markdown(f"**Tarif:** {ins.policy_name or '-'}")
                st.markdown(f"**Policennummer:** {ins.policy_number or '-'}")
                st.markdown(f"**Beginn:** {ins.start_date.strftime('%d.%m.%Y')}")
                if ins.end_date:
                    st.markdown(f"**Ende:** {ins.end_date.strftime('%d.%m.%Y')}")
                st.markdown(f"**Kündigungsfrist:** {ins.notice_period_days} Tage")

            with col2:
                st.metric("Monatlich", f"{monthly:.2f}€")
                if ins.coverage_amount:
                    st.metric("Deckung", f"{ins.coverage_amount:,.0f}€")
                if ins.deductible:
                    st.metric("Selbstbet.", f"{ins.deductible:.0f}€")

            with col3:
                if ins.agent_name:
                    st.markdown(f"**Kontakt:** {ins.agent_name}")
                if ins.agent_phone:
                    st.markdown(f"📞 {ins.agent_phone}")
                if ins.claims_phone:
                    st.markdown(f"🚨 Schaden: {ins.claims_phone}")

            if ins.coverage_description:
                st.markdown(f"**Deckungsumfang:** {ins.coverage_description}")

            # Aktionen
            st.divider()
            col1, col2, col3 = st.columns(3)

            with col1:
                if st.button("Schadenfall melden", key=f"claim_{ins.id}"):
                    st.session_state[f"new_claim_{ins.id}"] = True

            with col2:
                if ins.is_active:
                    if st.button("Deaktivieren", key=f"deactivate_{ins.id}"):
                        service.deactivate_insurance(ins.id)
                        st.success("Deaktiviert!")
                        st.rerun()

            with col3:
                if st.button("Löschen", key=f"delete_{ins.id}"):
                    if st.session_state.get(f"confirm_del_{ins.id}"):
                        service.delete_insurance(ins.id)
                        st.success("Gelöscht!")
                        st.rerun()
                    else:
                        st.session_state[f"confirm_del_{ins.id}"] = True
                        st.warning("Erneut klicken")

            # Schadensfall-Dialog
            if st.session_state.get(f"new_claim_{ins.id}"):
                with st.form(f"claim_form_{ins.id}"):
                    incident_date = st.date_input("Schadensdatum")
                    description = st.text_area("Beschreibung *")
                    claimed_amount = st.number_input("Schadenssumme (€)", min_value=0.0)

                    if st.form_submit_button("Schadenfall speichern"):
                        if description:
                            service.create_claim(
                                insurance_id=ins.id,
                                incident_date=datetime.combine(incident_date, datetime.min.time()),
                                description=description,
                                claimed_amount=claimed_amount if claimed_amount > 0 else None
                            )
                            st.success("Schadenfall erfasst!")
                            del st.session_state[f"new_claim_{ins.id}"]
                            st.rerun()


def render_claims(service: InsuranceService):
    """Tab: Schadensfälle"""
    st.subheader("Schadensfälle")

    claims = service.get_claims()

    if not claims:
        st.info("Keine Schadensfälle erfasst.")
        return

    for claim in claims:
        status_icon = "🟡" if claim.status == "submitted" else "🟢" if claim.status == "paid" else "🔴"

        with st.expander(f"{status_icon} Schaden vom {claim.incident_date.strftime('%d.%m.%Y')}"):
            col1, col2 = st.columns(2)

            with col1:
                st.markdown(f"**Schadennummer:** {claim.claim_number or '-'}")
                st.markdown(f"**Gemeldet am:** {claim.report_date.strftime('%d.%m.%Y')}")
                st.markdown(f"**Status:** {get_claim_status_name(claim.status)}")

            with col2:
                if claim.claimed_amount:
                    st.metric("Gefordert", f"{claim.claimed_amount:.2f}€")
                if claim.approved_amount:
                    st.metric("Genehmigt", f"{claim.approved_amount:.2f}€")
                if claim.paid_amount:
                    st.metric("Ausgezahlt", f"{claim.paid_amount:.2f}€")

            st.markdown(f"**Beschreibung:** {claim.description}")

            if claim.status_notes:
                st.markdown(f"**Status-Notizen:** {claim.status_notes}")

            # Status aktualisieren
            new_status = st.selectbox(
                "Status ändern",
                options=["submitted", "processing", "approved", "rejected", "paid"],
                format_func=get_claim_status_name,
                index=["submitted", "processing", "approved", "rejected", "paid"].index(claim.status),
                key=f"status_{claim.id}"
            )

            if new_status != claim.status:
                if st.button("Status speichern", key=f"save_status_{claim.id}"):
                    service.update_claim_status(claim.id, new_status)
                    st.success("Status aktualisiert!")
                    st.rerun()


# ==================== HILFSFUNKTIONEN ====================

def get_insurance_type_name(type_value: str) -> str:
    """Gibt deutschen Namen für Versicherungstyp zurück"""
    names = {
        "liability": "Haftpflicht",
        "household": "Hausrat",
        "legal": "Rechtsschutz",
        "health": "Krankenversicherung",
        "car": "KFZ-Versicherung",
        "life": "Lebensversicherung",
        "disability": "Berufsunfähigkeit",
        "travel": "Reiseversicherung",
        "pet": "Tierversicherung",
        "other": "Sonstige"
    }
    return names.get(type_value, type_value)


def get_insurance_icon(ins_type: InsuranceType) -> str:
    """Gibt Icon für Versicherungstyp zurück"""
    icons = {
        InsuranceType.LIABILITY: "🛡️",
        InsuranceType.HOUSEHOLD: "🏠",
        InsuranceType.LEGAL: "⚖️",
        InsuranceType.HEALTH: "🏥",
        InsuranceType.CAR: "🚗",
        InsuranceType.LIFE: "💚",
        InsuranceType.DISABILITY: "♿",
        InsuranceType.TRAVEL: "✈️",
        InsuranceType.PET: "🐕",
        InsuranceType.OTHER: "📋"
    }
    return icons.get(ins_type, "📋")


def get_interval_name(interval: str) -> str:
    """Gibt deutschen Namen für Intervall zurück"""
    names = {
        "weekly": "Wöchentlich",
        "monthly": "Monatlich",
        "quarterly": "Vierteljährlich",
        "semi_annually": "Halbjährlich",
        "annually": "Jährlich"
    }
    return names.get(interval, interval)


def get_claim_status_name(status: str) -> str:
    """Gibt deutschen Namen für Schadensstatus zurück"""
    names = {
        "submitted": "Eingereicht",
        "processing": "In Bearbeitung",
        "approved": "Genehmigt",
        "rejected": "Abgelehnt",
        "paid": "Ausgezahlt"
    }
    return names.get(status, status)


# ==================== HAUPTFUNKTION ====================

if __name__ == "__main__":
    st.set_page_config(page_title="Versicherungen", page_icon="🏥", layout="wide")
    render_insurance_page()
else:
    render_insurance_page()
