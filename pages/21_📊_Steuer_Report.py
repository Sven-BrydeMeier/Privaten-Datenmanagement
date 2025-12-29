"""
Steuer-Report Seite
Jahresübersicht für die Steuererklärung
"""
import streamlit as st
from datetime import datetime
import plotly.express as px
import json

# Imports
try:
    from services.tax_service import TaxReportService
    TAX_AVAILABLE = True
except ImportError:
    TAX_AVAILABLE = False


def render_tax_page():
    """Rendert die Steuer-Report Seite"""
    st.title("Steuer-Report")
    st.markdown("Übersicht aller steuerrelevanten Belege und Ausgaben")

    if not TAX_AVAILABLE:
        st.error("Steuer-Module nicht verfügbar.")
        return

    if "user" not in st.session_state or not st.session_state.user:
        st.warning("Bitte melden Sie sich an.")
        return

    user_id = st.session_state.user.get("id", 1)
    service = TaxReportService(user_id)

    # Jahr auswählen
    col1, col2 = st.columns([1, 3])

    with col1:
        year = st.selectbox(
            "Steuerjahr",
            options=list(range(datetime.now().year, 2019, -1)),
            index=0
        )

    # Report generieren
    report = service.generate_yearly_report(year)

    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs([
        "Übersicht", "Nach Kategorie", "Monatlich", "Export"
    ])

    with tab1:
        render_overview(report, service, year)

    with tab2:
        render_by_category(report)

    with tab3:
        render_monthly(service, year)

    with tab4:
        render_export(service, year, report)


def render_overview(report: dict, service: TaxReportService, year: int):
    """Tab: Übersicht"""
    st.subheader(f"Steuerübersicht {year}")

    totals = report["totals"]

    # Hauptmetriken
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Belege/Rechnungen", f"{totals['documents']:.2f}€")

    with col2:
        st.metric("Fahrtkosten", f"{totals['mileage']:.2f}€")

    with col3:
        st.metric("Versicherungen", f"{totals['insurances']:.2f}€")

    with col4:
        st.metric(
            "Gesamt absetzbar",
            f"{totals['grand_total']:.2f}€",
            help="Summe aller steuerlich relevanten Ausgaben"
        )

    st.divider()

    # Aufschlüsselung
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Werbungskosten")

        wk_total = report["categories"].get("werbungskosten", {}).get("total", 0)
        st.metric("Summe", f"{wk_total:.2f}€")

        items = report["categories"].get("werbungskosten", {}).get("items", [])
        for item in items[:5]:
            st.markdown(f"- {item['title']}: **{item['amount']:.2f}€**")

    with col2:
        st.subheader("Sonderausgaben")

        sa_total = report["categories"].get("sonderausgaben", {}).get("total", 0)
        st.metric("Summe", f"{sa_total:.2f}€")

        items = report["categories"].get("sonderausgaben", {}).get("items", [])
        for item in items[:5]:
            st.markdown(f"- {item['title']}: **{item['amount']:.2f}€**")

    st.divider()

    # Fahrtkosten
    st.subheader("Fahrtkosten (Kilometerpauschale)")

    mileage = report["mileage"]

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Geschäftliche Fahrten", f"{mileage.get('business_km', 0):.0f} km")
        st.caption(f"= {mileage.get('business_deductible', 0):.2f}€")

    with col2:
        st.metric("Arbeitsweg", f"{mileage.get('commute_km', 0):.0f} km")
        st.caption(f"= {mileage.get('commute_deductible', 0):.2f}€")

    with col3:
        st.metric("Absetzbar gesamt", f"{mileage.get('total_deductible', 0):.2f}€")

    # Hinweise
    st.divider()
    st.subheader("Hinweise")

    missing = service.get_missing_receipts(year)
    if missing:
        st.warning(f"**{len(missing)} Belege fehlen!**")
        st.markdown("Folgende Buchungen haben keinen Beleg:")
        for item in missing[:5]:
            st.markdown(f"- {item['title']} ({item['amount']:.2f}€)")


def render_by_category(report: dict):
    """Tab: Nach Kategorie"""
    st.subheader("Ausgaben nach Kategorie")

    categories = report["categories"]

    if not categories:
        st.info("Keine kategorisierten Ausgaben gefunden.")
        return

    # Diagramm
    cat_names = [get_category_name(k) for k in categories.keys()]
    cat_totals = [c["total"] for c in categories.values()]

    if any(t > 0 for t in cat_totals):
        fig = px.pie(
            values=cat_totals,
            names=cat_names,
            hole=0.4
        )
        fig.update_layout(margin=dict(t=20, b=20, l=20, r=20), height=350)
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # Details pro Kategorie
    for cat_key, cat_data in categories.items():
        if cat_data["total"] > 0:
            with st.expander(f"{get_category_name(cat_key)} - {cat_data['total']:.2f}€"):
                for item in cat_data["items"]:
                    col1, col2, col3 = st.columns([3, 1, 1])

                    with col1:
                        st.markdown(f"**{item['title']}**")
                        if item.get('sender'):
                            st.caption(item['sender'])

                    with col2:
                        if item.get('date'):
                            st.markdown(item['date'][:10])

                    with col3:
                        st.markdown(f"**{item['amount']:.2f}€**")

                    st.divider()


def render_monthly(service: TaxReportService, year: int):
    """Tab: Monatliche Aufschlüsselung"""
    st.subheader(f"Monatliche Ausgaben {year}")

    breakdown = service.get_monthly_breakdown(year)

    # Diagramm
    months = list(breakdown.keys())
    totals = [breakdown[m]["total"] for m in months]

    fig = px.bar(
        x=months,
        y=totals,
        labels={"x": "Monat", "y": "Ausgaben (€)"}
    )
    fig.update_layout(margin=dict(t=20, b=20, l=20, r=20), height=350)
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # Details pro Monat
    for month, data in breakdown.items():
        if data["count"] > 0:
            with st.expander(f"{month}: {data['count']} Belege - {data['total']:.2f}€"):
                for doc in data["documents"]:
                    col1, col2 = st.columns([3, 1])

                    with col1:
                        st.markdown(f"**{doc['title']}**")
                        if doc.get('sender'):
                            st.caption(doc['sender'])

                    with col2:
                        st.markdown(f"**{doc['amount']:.2f}€**")


def render_export(service: TaxReportService, year: int, report: dict):
    """Tab: Export"""
    st.subheader("Daten exportieren")

    st.markdown("""
    Exportieren Sie Ihre Steuerdaten für:
    - Ihre eigene Steuererklärung (ELSTER)
    - Ihren Steuerberater
    - Ihre Unterlagen
    """)

    st.divider()

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("### Übersicht (JSON)")
        json_data = json.dumps(report, indent=2, ensure_ascii=False, default=str)

        st.download_button(
            "JSON herunterladen",
            data=json_data,
            file_name=f"steuer_report_{year}.json",
            mime="application/json"
        )

    with col2:
        st.markdown("### Für Steuerberater")

        export_data = service.export_for_steuerberater(year)
        export_json = json.dumps(export_data, indent=2, ensure_ascii=False, default=str)

        st.download_button(
            "Export herunterladen",
            data=export_json,
            file_name=f"steuerberater_export_{year}.json",
            mime="application/json"
        )

    with col3:
        st.markdown("### Belegliste (CSV)")

        # CSV erstellen
        csv_lines = ["Datum;Beschreibung;Absender;Betrag;Kategorie;Belegnummer"]

        for doc in report["documents"]:
            csv_lines.append(
                f"{doc.get('date', '')[:10] if doc.get('date') else ''};{doc.get('title', '')};{doc.get('sender', '')};{doc.get('amount', 0):.2f};{get_category_name(doc.get('tax_category', ''))};{doc.get('invoice_number', '')}"
            )

        csv_data = "\n".join(csv_lines)

        st.download_button(
            "CSV herunterladen",
            data=csv_data,
            file_name=f"belege_{year}.csv",
            mime="text/csv"
        )

    st.divider()

    # Zusammenfassung für Steuererklärung
    st.subheader("Zusammenfassung für Steuererklärung")

    totals = report["totals"]

    st.markdown(f"""
    ### Steuerjahr {year}

    **Werbungskosten (Anlage N):**
    - Arbeitsmittel, Fachliteratur, etc.: {report['categories'].get('werbungskosten', {}).get('total', 0):.2f}€
    - Fahrtkosten (Pendlerpauschale): {report['mileage'].get('commute_deductible', 0):.2f}€
    - Reisekosten: {report['mileage'].get('business_deductible', 0):.2f}€

    **Sonderausgaben:**
    - Versicherungen: {report['insurances'].get('total_deductible', 0):.2f}€
    - Weitere Sonderausgaben: {report['categories'].get('sonderausgaben', {}).get('total', 0):.2f}€

    **Haushaltsnahe Dienstleistungen:**
    - Handwerkerleistungen: {report['categories'].get('haushaltsnahe', {}).get('total', 0):.2f}€

    ---

    **Gesamt potenziell absetzbar: {totals['grand_total']:.2f}€**

    *Hinweis: Dies ist eine Übersicht und keine Steuerberatung.
    Bitte konsultieren Sie einen Steuerberater für Ihre individuelle Situation.*
    """)


def get_category_name(category: str) -> str:
    """Gibt deutschen Namen für Steuerkategorie zurück"""
    names = {
        "werbungskosten": "Werbungskosten",
        "sonderausgaben": "Sonderausgaben",
        "haushaltsnahe": "Haushaltsnahe Dienstleistungen",
        "krankheit": "Krankheitskosten",
        "sonstige": "Sonstige"
    }
    return names.get(category, category or "Sonstige")


# ==================== HAUPTFUNKTION ====================

if __name__ == "__main__":
    st.set_page_config(page_title="Steuer-Report", page_icon="📊", layout="wide")
    render_tax_page()
else:
    render_tax_page()
