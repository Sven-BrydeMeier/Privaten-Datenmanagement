"""
Finanz-Dashboard
Übersicht über Einnahmen, Ausgaben und Trends
"""
import streamlit as st
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

from utils.components import render_sidebar_cart, apply_custom_css
from services.finance_service import get_finance_service
from services.invoice_matching_service import get_invoice_matching_service
from database.db import get_current_user_id

# Seitenkonfiguration
st.set_page_config(
    page_title="Finanzen",
    page_icon="💰",
    layout="wide"
)

apply_custom_css()
render_sidebar_cart()

st.title("💰 Finanz-Dashboard")

user_id = get_current_user_id()
finance_service = get_finance_service()
matching_service = get_invoice_matching_service()

# Tabs für verschiedene Ansichten
tab_overview, tab_trends, tab_categories, tab_recurring, tab_matching = st.tabs([
    "📊 Übersicht",
    "📈 Trends",
    "🏷️ Kategorien",
    "🔄 Wiederkehrend",
    "🔗 Rechnungs-Abgleich"
])

with tab_overview:
    st.subheader("📊 Finanzübersicht")

    # Zeitraum auswählen
    col_filter, col_empty = st.columns([1, 3])
    with col_filter:
        months = st.selectbox(
            "Zeitraum",
            options=[3, 6, 12, 24],
            format_func=lambda x: f"Letzte {x} Monate",
            index=2
        )

    # Übersichtsdaten laden
    overview = finance_service.get_financial_overview(user_id, months)
    matching_stats = matching_service.get_matching_statistics(user_id)

    # KPI-Karten
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "💵 Einnahmen",
            f"{overview['total_income']:,.2f} €",
            help="Summe aller Einnahmen"
        )

    with col2:
        st.metric(
            "💸 Ausgaben",
            f"{overview['total_expenses']:,.2f} €",
            help="Summe aller Ausgaben"
        )

    with col3:
        delta_color = "normal" if overview['balance'] >= 0 else "inverse"
        st.metric(
            "💰 Bilanz",
            f"{overview['balance']:,.2f} €",
            delta=f"{overview['savings_rate']:.1f}% Sparquote",
            delta_color=delta_color
        )

    with col4:
        st.metric(
            "📋 Offene Rechnungen",
            f"{matching_stats['open_invoices']}",
            delta=f"{matching_stats['total_open_amount']:,.2f} €",
            delta_color="off"
        )

    st.divider()

    # Monatlicher Verlauf
    st.subheader("📅 Monatlicher Verlauf")

    monthly = finance_service.get_monthly_breakdown(user_id, datetime.now().year)

    if monthly["months"]:
        df = pd.DataFrame(monthly["months"])

        fig = go.Figure()
        fig.add_trace(go.Bar(
            name='Einnahmen',
            x=df['name'],
            y=df['income'],
            marker_color='#2ecc71'
        ))
        fig.add_trace(go.Bar(
            name='Ausgaben',
            x=df['name'],
            y=df['expenses'],
            marker_color='#e74c3c'
        ))
        fig.add_trace(go.Scatter(
            name='Bilanz',
            x=df['name'],
            y=df['balance'],
            mode='lines+markers',
            line=dict(color='#3498db', width=3)
        ))

        fig.update_layout(
            barmode='group',
            height=400,
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(l=20, r=20, t=40, b=20)
        )

        st.plotly_chart(fig, use_container_width=True)

        # Zusammenfassung
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Jahreseinnahmen", f"{monthly['total_income']:,.2f} €")
        with col2:
            st.metric("Jahresausgaben", f"{monthly['total_expenses']:,.2f} €")
        with col3:
            st.metric("Jahresbilanz", f"{monthly['total_balance']:,.2f} €")

    # Warnungen
    if matching_stats['overdue_invoices'] > 0:
        st.warning(
            f"⚠️ {matching_stats['overdue_invoices']} überfällige Rechnung(en) "
            f"im Wert von {matching_stats['total_open_amount']:,.2f} €"
        )

with tab_trends:
    st.subheader("📈 Ausgabentrends")

    trends = finance_service.get_spending_trends(user_id, 6)

    if trends["months"]:
        # Trend-Anzeige
        col1, col2, col3 = st.columns(3)

        with col1:
            trend_icon = "📈" if trends["trend_direction"] == "steigend" else "📉" if trends["trend_direction"] == "fallend" else "➡️"
            st.metric(
                "Trend",
                trends["trend_direction"].title(),
                delta=f"{trends['trend_percent']:+.1f}%",
                delta_color="inverse" if trends["trend_percent"] > 0 else "normal"
            )

        with col2:
            st.metric("Ø Monatlich", f"{trends['average_monthly']:,.2f} €")

        with col3:
            st.metric("Höchste Ausgaben", f"{trends['highest_month']:,.2f} €")

        # Trend-Diagramm
        df = pd.DataFrame(trends["months"])

        fig = px.line(
            df,
            x='month_name',
            y='total',
            markers=True,
            title="Monatliche Ausgaben",
            labels={'total': 'Ausgaben (€)', 'month_name': 'Monat'}
        )

        # Durchschnittslinie hinzufügen
        fig.add_hline(
            y=trends['average_monthly'],
            line_dash="dash",
            line_color="gray",
            annotation_text=f"Ø {trends['average_monthly']:.2f} €"
        )

        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)

    # Top Händler
    st.subheader("🏪 Top Händler")

    top_merchants = finance_service.get_top_merchants(user_id, 3, 10)

    if top_merchants:
        df_merchants = pd.DataFrame(top_merchants)

        fig = px.bar(
            df_merchants,
            x='total',
            y='name',
            orientation='h',
            title="Ausgaben nach Händler (letzte 3 Monate)",
            labels={'total': 'Summe (€)', 'name': ''},
            text='total'
        )
        fig.update_traces(texttemplate='%{text:.2f} €', textposition='auto')
        fig.update_layout(height=400, yaxis={'categoryorder': 'total ascending'})

        st.plotly_chart(fig, use_container_width=True)

with tab_categories:
    st.subheader("🏷️ Ausgaben nach Kategorien")

    col1, col2 = st.columns([1, 4])
    with col1:
        cat_months = st.selectbox(
            "Zeitraum",
            options=[1, 3, 6, 12],
            format_func=lambda x: f"{x} Monat(e)",
            index=1,
            key="cat_months"
        )

    categories = finance_service.get_expense_categories(user_id, cat_months)

    if categories["categories"]:
        # Kreisdiagramm
        df_cat = pd.DataFrame(categories["categories"])

        col1, col2 = st.columns([2, 1])

        with col1:
            fig = px.pie(
                df_cat,
                values='total',
                names='category',
                title=f"Ausgabenverteilung ({cat_months} Monat(e))",
                hole=0.4
            )
            fig.update_traces(textposition='inside', textinfo='percent+label')
            fig.update_layout(height=450)
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            st.metric("Gesamtausgaben", f"{categories['total_expenses']:,.2f} €")

            st.write("**Top Kategorien:**")
            for cat in categories["categories"][:5]:
                pct = (cat["total"] / categories["total_expenses"] * 100) if categories["total_expenses"] > 0 else 0
                st.caption(f"• {cat['category']}: {cat['total']:,.2f} € ({pct:.1f}%)")

        # Detail-Tabelle
        st.divider()
        st.write("**Kategorien-Details:**")

        for cat in categories["categories"]:
            with st.expander(f"{cat['category']} - {cat['total']:,.2f} € ({cat['count']} Transaktionen)"):
                if cat["transactions"]:
                    for t in cat["transactions"]:
                        st.caption(f"• {t['date'][:10] if t['date'] else 'N/A'}: {t['description'][:40]}... - {t['amount']:,.2f} €")

with tab_recurring:
    st.subheader("🔄 Wiederkehrende Ausgaben")

    recurring = finance_service.get_recurring_expenses(user_id)

    if recurring:
        # Übersicht
        total_monthly = sum(r["monthly_equivalent"] for r in recurring)

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Monatliche Fixkosten", f"{total_monthly:,.2f} €")
        with col2:
            st.metric("Jährliche Fixkosten", f"{total_monthly * 12:,.2f} €")
        with col3:
            st.metric("Erkannte Zahlungen", len(recurring))

        st.divider()

        # Cashflow-Prognose
        forecast = finance_service.get_cash_flow_forecast(user_id, 3)

        st.write("**📊 3-Monats-Prognose:**")

        for month in forecast["forecast"]:
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.write(f"**{month['month']}**")
            with col2:
                st.caption(f"Einnahmen: {month['expected_income']:,.2f} €")
            with col3:
                st.caption(f"Ausgaben: {month['expected_expenses']:,.2f} €")
            with col4:
                color = "green" if month['expected_balance'] >= 0 else "red"
                st.markdown(f"<span style='color:{color}'>Bilanz: {month['expected_balance']:,.2f} €</span>", unsafe_allow_html=True)

        st.divider()

        # Liste der wiederkehrenden Ausgaben
        st.write("**Erkannte wiederkehrende Zahlungen:**")

        for r in recurring:
            with st.expander(f"{r['merchant']} - {r['average_amount']:,.2f} € ({r['frequency']})"):
                col1, col2 = st.columns(2)
                with col1:
                    st.write(f"**Häufigkeit:** {r['frequency']}")
                    st.write(f"**Durchschnitt:** {r['average_amount']:,.2f} €")
                    st.write(f"**Anzahl Zahlungen:** {r['occurrence_count']}")
                with col2:
                    st.write(f"**Letzte Zahlung:** {r['last_payment'][:10] if r['last_payment'] else 'N/A'}")
                    st.write(f"**Nächste erwartet:** {r['next_expected'][:10] if r['next_expected'] else 'N/A'}")
                    st.write(f"**Monatl. Äquivalent:** {r['monthly_equivalent']:,.2f} €")
    else:
        st.info("📭 Noch keine wiederkehrenden Ausgaben erkannt. Verbinden Sie ein Bankkonto, um Transaktionen zu analysieren.")

with tab_matching:
    st.subheader("🔗 Rechnungs-Bank-Abgleich")

    # Statistiken
    stats = matching_service.get_matching_statistics(user_id)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Offene Rechnungen", stats["open_invoices"])
    with col2:
        st.metric("Überfällig", stats["overdue_invoices"], delta_color="inverse" if stats["overdue_invoices"] > 0 else "off")
    with col3:
        st.metric("Bezahlt (90 Tage)", stats["paid_invoices_90d"])
    with col4:
        st.metric("Nicht zugeordnet", stats["unmatched_transactions_90d"])

    st.divider()

    # Auto-Match Button
    col1, col2 = st.columns([1, 3])
    with col1:
        if st.button("🤖 Auto-Abgleich starten", type="primary"):
            with st.spinner("Führe automatischen Abgleich durch..."):
                result = matching_service.auto_match_all(user_id)

                if result.get("success"):
                    st.success(f"✅ {result['auto_matched']} Rechnungen automatisch zugeordnet!")

                    if result.get("suggested_matches"):
                        st.info(f"💡 {len(result['suggested_matches'])} Vorschläge zur manuellen Prüfung")
                else:
                    st.error(f"❌ {result.get('error', 'Fehler beim Abgleich')}")

    # Unbezahlte Rechnungen
    st.subheader("📋 Offene Rechnungen")

    unmatched_invoices = matching_service.find_unmatched_invoices(user_id)

    if unmatched_invoices:
        for inv in unmatched_invoices[:10]:
            status_icon = "🔴" if inv["is_overdue"] else "🟡"
            days_text = f" (überfällig seit {abs(inv['days_until_due'])} Tagen)" if inv["is_overdue"] else f" (noch {inv['days_until_due']} Tage)" if inv["days_until_due"] else ""

            with st.expander(f"{status_icon} {inv['title'][:40]}... - {inv['amount']:,.2f} {inv['currency']}{days_text}"):
                col1, col2 = st.columns(2)
                with col1:
                    st.write(f"**Absender:** {inv['sender'] or 'Unbekannt'}")
                    st.write(f"**Rechnungsnr.:** {inv['invoice_number'] or '-'}")
                with col2:
                    st.write(f"**Datum:** {inv['document_date'][:10] if inv['document_date'] else '-'}")
                    st.write(f"**Fällig:** {inv['due_date'][:10] if inv['due_date'] else '-'}")

                # Passende Transaktionen suchen
                if st.button("🔍 Passende Transaktionen suchen", key=f"find_{inv['id']}"):
                    matches = matching_service.find_matches_for_invoice(inv['id'], user_id)

                    if matches.get("matches"):
                        st.write("**Mögliche Zuordnungen:**")
                        for match in matches["matches"][:5]:
                            t = match["transaction"]
                            score_color = "green" if match["score"] >= 70 else "orange" if match["score"] >= 50 else "red"

                            col_t1, col_t2, col_t3 = st.columns([3, 1, 1])
                            with col_t1:
                                st.caption(f"{t['date'][:10] if t['date'] else '-'}: {t['creditor'] or t['reference'][:30] if t['reference'] else 'N/A'}...")
                            with col_t2:
                                st.caption(f"{abs(t['amount']):,.2f} €")
                            with col_t3:
                                st.markdown(f"<span style='color:{score_color}'>{match['score']}%</span>", unsafe_allow_html=True)
                                if st.button("✓", key=f"link_{inv['id']}_{t['id']}"):
                                    result = matching_service.link_transaction_to_document(
                                        t['id'], inv['id'], user_id
                                    )
                                    if result.get("success"):
                                        st.success("Zugeordnet!")
                                        st.rerun()
                    else:
                        st.info("Keine passenden Transaktionen gefunden.")
    else:
        st.success("✅ Alle Rechnungen sind bezahlt!")
