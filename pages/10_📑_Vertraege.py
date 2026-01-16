"""
Vertrags-Dashboard
Übersicht über Verträge, Kosten und Kündigungsfristen
"""
import streamlit as st
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

from utils.components import render_sidebar_cart, apply_custom_css
from services.contract_service import get_contract_service
from database.db import get_current_user_id

# Seitenkonfiguration
st.set_page_config(
    page_title="Verträge",
    page_icon="📑",
    layout="wide"
)

apply_custom_css()
render_sidebar_cart()

st.title("📑 Vertrags-Dashboard")

user_id = get_current_user_id()
contract_service = get_contract_service()

# Tabs
tab_overview, tab_deadlines, tab_costs, tab_projection = st.tabs([
    "📋 Übersicht",
    "⏰ Fristen",
    "💶 Kostenanalyse",
    "📊 Jahresprojektion"
])

with tab_overview:
    st.subheader("📋 Vertragsübersicht")

    # Filter
    col1, col2 = st.columns([1, 3])
    with col1:
        show_expired = st.checkbox("Abgelaufene anzeigen", value=False)

    contracts = contract_service.get_all_contracts(user_id, include_expired=show_expired)
    cost_overview = contract_service.get_cost_overview(user_id)

    # KPIs
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Aktive Verträge", cost_overview["active_contracts"])

    with col2:
        st.metric("Monatliche Kosten", f"{cost_overview['total_monthly']:,.2f} €")

    with col3:
        st.metric("Jährliche Kosten", f"{cost_overview['total_yearly']:,.2f} €")

    with col4:
        urgent = len([c for c in contracts if c.get("is_notice_urgent")])
        st.metric("Dringende Fristen", urgent, delta_color="inverse" if urgent > 0 else "off")

    st.divider()

    # Vertragsliste
    if contracts:
        for contract in contracts:
            status = contract["status"]
            status_icons = {
                "active": "🟢",
                "notice_soon": "🟡",
                "notice_urgent": "🟠",
                "notice_expired": "🔴",
                "expired": "⚫",
                "pending": "⚪"
            }
            icon = status_icons.get(status, "⚪")

            title = f"{icon} {contract['title'][:50]}..."
            if contract["monthly_cost"]:
                title += f" - {contract['monthly_cost']:,.2f} €/Monat"

            with st.expander(title, expanded=contract.get("is_notice_urgent", False)):
                col1, col2, col3 = st.columns(3)

                with col1:
                    st.write(f"**Anbieter:** {contract['sender'] or 'Unbekannt'}")
                    if contract["contract_number"]:
                        st.write(f"**Vertragsnr.:** {contract['contract_number']}")
                    st.write(f"**Status:** {status.replace('_', ' ').title()}")

                with col2:
                    if contract["contract_start"]:
                        st.write(f"**Beginn:** {contract['contract_start'][:10]}")
                    if contract["contract_end"]:
                        st.write(f"**Ende:** {contract['contract_end'][:10]}")
                    if contract["notice_period_days"]:
                        st.write(f"**Kündigungsfrist:** {contract['notice_period_days']} Tage")

                with col3:
                    if contract["notice_deadline"]:
                        deadline = contract["notice_deadline"][:10]
                        days = contract["days_until_notice"]
                        if days is not None:
                            if days < 0:
                                st.error(f"⚠️ Frist verpasst! ({deadline})")
                            elif days <= 7:
                                st.warning(f"⏰ Nur noch {days} Tage! ({deadline})")
                            elif days <= 30:
                                st.info(f"📅 Frist: {deadline} ({days} Tage)")
                            else:
                                st.write(f"**Kündigungsfrist:** {deadline}")

                    if contract["invoice_amount"]:
                        st.write(f"**Letzte Zahlung:** {contract['invoice_amount']:,.2f} €")

                # Aktionen
                col_a, col_b, col_c = st.columns(3)
                with col_a:
                    if st.button("📄 Dokument öffnen", key=f"open_{contract['id']}"):
                        st.session_state["view_document_id"] = contract["id"]
                        st.switch_page("pages/3_📁_Dokumente.py")

                with col_b:
                    if st.button("✏️ Daten bearbeiten", key=f"edit_{contract['id']}"):
                        st.session_state[f"edit_contract_{contract['id']}"] = True
                        st.rerun()

                # Bearbeitungsmodus
                if st.session_state.get(f"edit_contract_{contract['id']}"):
                    st.write("---")
                    st.write("**Vertragsdaten bearbeiten:**")

                    col_e1, col_e2, col_e3 = st.columns(3)

                    with col_e1:
                        new_start = st.date_input(
                            "Vertragsbeginn",
                            value=datetime.fromisoformat(contract["contract_start"]).date() if contract["contract_start"] else datetime.now().date(),
                            key=f"start_{contract['id']}"
                        )

                    with col_e2:
                        new_end = st.date_input(
                            "Vertragsende",
                            value=datetime.fromisoformat(contract["contract_end"]).date() if contract["contract_end"] else None,
                            key=f"end_{contract['id']}"
                        )

                    with col_e3:
                        new_notice = st.number_input(
                            "Kündigungsfrist (Tage)",
                            value=contract["notice_period_days"] or 30,
                            min_value=0,
                            max_value=365,
                            key=f"notice_{contract['id']}"
                        )

                    col_s1, col_s2 = st.columns(2)
                    with col_s1:
                        if st.button("💾 Speichern", key=f"save_{contract['id']}"):
                            result = contract_service.update_contract_dates(
                                contract["id"],
                                user_id,
                                contract_start=datetime.combine(new_start, datetime.min.time()) if new_start else None,
                                contract_end=datetime.combine(new_end, datetime.min.time()) if new_end else None,
                                notice_period_days=new_notice
                            )
                            if result.get("success"):
                                st.success("Gespeichert!")
                                del st.session_state[f"edit_contract_{contract['id']}"]
                                st.rerun()
                            else:
                                st.error(result.get("error"))

                    with col_s2:
                        if st.button("❌ Abbrechen", key=f"cancel_{contract['id']}"):
                            del st.session_state[f"edit_contract_{contract['id']}"]
                            st.rerun()
    else:
        st.info("📭 Keine Verträge gefunden. Laden Sie Vertragsdokumente hoch und kategorisieren Sie diese als 'Vertrag'.")

with tab_deadlines:
    st.subheader("⏰ Anstehende Kündigungsfristen")

    col1, col2 = st.columns([1, 3])
    with col1:
        days_ahead = st.selectbox(
            "Zeitraum",
            options=[30, 60, 90, 180, 365],
            format_func=lambda x: f"Nächste {x} Tage",
            index=2
        )

    deadlines = contract_service.get_upcoming_deadlines(user_id, days_ahead)

    if deadlines:
        # Timeline-Visualisierung
        df_deadlines = pd.DataFrame([
            {
                "Vertrag": d["title"][:30],
                "Frist": d["notice_deadline"][:10],
                "Tage": d["days_until_notice"],
                "Anbieter": d["sender"] or "Unbekannt"
            }
            for d in deadlines
        ])

        fig = px.timeline(
            df_deadlines,
            x_start="Frist",
            x_end="Frist",
            y="Vertrag",
            color="Tage",
            title="Kündigungsfristen-Übersicht",
            color_continuous_scale="RdYlGn_r"
        )
        fig.update_layout(height=400)
        st.plotly_chart(fig, width="stretch")

        # Detailliste
        st.write("**Fristen im Detail:**")

        for deadline in deadlines:
            days = deadline["days_until_notice"]
            if days <= 7:
                icon = "🔴"
                urgency = "DRINGEND"
            elif days <= 30:
                icon = "🟠"
                urgency = "Bald"
            else:
                icon = "🟡"
                urgency = ""

            col1, col2, col3, col4 = st.columns([0.5, 2, 2, 1])

            with col1:
                st.write(icon)
            with col2:
                st.write(f"**{deadline['title'][:40]}**")
                st.caption(deadline["sender"] or "")
            with col3:
                st.write(f"Frist: {deadline['notice_deadline'][:10]}")
                st.caption(f"Noch {days} Tage {urgency}")
            with col4:
                if deadline["monthly_cost"]:
                    st.write(f"{deadline['monthly_cost']:,.2f} €/M")
    else:
        st.success("✅ Keine anstehenden Kündigungsfristen in diesem Zeitraum!")

with tab_costs:
    st.subheader("💶 Kostenanalyse")

    # Kosten nach Anbieter
    st.write("**Top Kosten nach Anbieter:**")

    if cost_overview["costs_by_sender"]:
        df_costs = pd.DataFrame(cost_overview["costs_by_sender"])

        fig = px.bar(
            df_costs,
            x="monthly_cost",
            y="sender",
            orientation='h',
            title="Monatliche Vertragskosten nach Anbieter",
            labels={"monthly_cost": "Monatlich (€)", "sender": ""},
            text="monthly_cost"
        )
        fig.update_traces(texttemplate='%{text:.2f} €', textposition='auto')
        fig.update_layout(height=400, yaxis={'categoryorder': 'total ascending'})

        st.plotly_chart(fig, width="stretch")

    # Kategorien-Aufschlüsselung
    st.divider()
    st.write("**Kosten nach Kategorie:**")

    categories = contract_service.get_category_breakdown(user_id)

    if categories["categories"]:
        df_cat = pd.DataFrame([
            {"Kategorie": c["category"], "Monatlich": c["monthly_total"], "Jährlich": c["yearly_total"]}
            for c in categories["categories"]
        ])

        col1, col2 = st.columns(2)

        with col1:
            fig = px.pie(
                df_cat,
                values="Monatlich",
                names="Kategorie",
                title="Verteilung der Kosten",
                hole=0.4
            )
            st.plotly_chart(fig, width="stretch")

        with col2:
            st.metric("Gesamt monatlich", f"{categories['total_monthly']:,.2f} €")
            st.metric("Gesamt jährlich", f"{categories['total_yearly']:,.2f} €")

            st.write("**Aufschlüsselung:**")
            for cat in categories["categories"]:
                st.caption(f"• {cat['category']}: {cat['monthly_total']:,.2f} €/M ({cat['count']} Posten)")

with tab_projection:
    st.subheader("📊 Jahresprojektion")

    projection = contract_service.get_yearly_projection(user_id)

    st.write(f"**Kostenprognose für {projection['year']}:**")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Jahresgesamt", f"{projection['yearly_total']:,.2f} €")
    with col2:
        st.metric("Ø Monatlich", f"{projection['monthly_average']:,.2f} €")
    with col3:
        st.metric("Aktive Verträge", cost_overview["active_contracts"])

    # Monatliches Diagramm
    if projection["months"]:
        df = pd.DataFrame(projection["months"])

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=df['name'],
            y=df['total'],
            name='Vertragskosten',
            marker_color='#3498db'
        ))

        fig.add_hline(
            y=projection['monthly_average'],
            line_dash="dash",
            line_color="red",
            annotation_text=f"Ø {projection['monthly_average']:.2f} €"
        )

        fig.update_layout(
            title="Projizierte monatliche Vertragskosten",
            height=400,
            xaxis_title="Monat",
            yaxis_title="Kosten (€)"
        )

        st.plotly_chart(fig, width="stretch")

        # Detailtabelle
        st.write("**Monatliche Details:**")

        for month in projection["months"]:
            if month["total"] > 0:
                with st.expander(f"{month['name']}: {month['total']:,.2f} €"):
                    for c in month["contracts"]:
                        st.caption(f"• {c['title'][:40]}: {c['cost']:,.2f} €")
