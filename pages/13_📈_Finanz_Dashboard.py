"""
Finanz-Dashboard
Erweiterte Analysen, Trends und Rechnungs-Abgleich
"""
import streamlit as st
from datetime import datetime
import pandas as pd

from utils.components import render_sidebar_cart, apply_custom_css
from database.db import get_current_user_id, init_db

# Seitenkonfiguration
st.set_page_config(
    page_title="Finanz-Dashboard",
    page_icon="📈",
    layout="wide"
)

init_db()
apply_custom_css()
render_sidebar_cart()

st.title("📈 Finanz-Dashboard")
st.caption("Erweiterte Analysen, Trends und Rechnungs-Abgleich")

user_id = get_current_user_id()

# Services importieren mit Fallback
try:
    from services.finance_service import get_finance_service
    from services.invoice_matching_service import get_invoice_matching_service
    finance_service = get_finance_service()
    matching_service = get_invoice_matching_service()
    services_available = True
except ImportError as e:
    services_available = False
    st.error(f"Service nicht verfügbar: {e}")

if services_available:
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
                f"{overview['total_income']:,.2f} €"
            )

        with col2:
            st.metric(
                "💸 Ausgaben",
                f"{overview['total_expenses']:,.2f} €"
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
            try:
                import plotly.graph_objects as go

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
                    legend=dict(orientation="h", yanchor="bottom", y=1.02)
                )

                st.plotly_chart(fig, use_container_width=True)
            except ImportError:
                st.warning("Plotly nicht installiert - Diagramme nicht verfügbar")

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
                f"⚠️ {matching_stats['overdue_invoices']} überfällige Rechnung(en)"
            )

    with tab_trends:
        st.subheader("📈 Ausgabentrends")

        trends = finance_service.get_spending_trends(user_id, 6)

        if trends["months"]:
            # Trend-Anzeige
            col1, col2, col3 = st.columns(3)

            with col1:
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
            try:
                import plotly.express as px
                df = pd.DataFrame(trends["months"])

                fig = px.line(
                    df,
                    x='month_name',
                    y='total',
                    markers=True,
                    title="Monatliche Ausgaben"
                )
                fig.add_hline(
                    y=trends['average_monthly'],
                    line_dash="dash",
                    line_color="gray",
                    annotation_text=f"Ø {trends['average_monthly']:.2f} €"
                )
                fig.update_layout(height=400)
                st.plotly_chart(fig, use_container_width=True)
            except ImportError:
                st.info("Plotly für Diagramme benötigt")

        # Top Händler
        st.subheader("🏪 Top Händler")

        top_merchants = finance_service.get_top_merchants(user_id, 3, 10)

        if top_merchants:
            for m in top_merchants[:5]:
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.write(f"**{m['name']}**")
                with col2:
                    st.write(f"{m['total']:,.2f} €")
        else:
            st.info("Keine Händler-Daten verfügbar")

    with tab_categories:
        st.subheader("🏷️ Ausgaben nach Kategorien")

        categories = finance_service.get_expense_categories(user_id, 3)

        if categories["categories"]:
            st.metric("Gesamtausgaben", f"{categories['total_expenses']:,.2f} €")

            for cat in categories["categories"]:
                pct = (cat["total"] / categories["total_expenses"] * 100) if categories["total_expenses"] > 0 else 0
                st.write(f"**{cat['category']}**: {cat['total']:,.2f} € ({pct:.1f}%)")
        else:
            st.info("Keine Kategorien-Daten verfügbar")

    with tab_recurring:
        st.subheader("🔄 Wiederkehrende Ausgaben")

        recurring = finance_service.get_recurring_expenses(user_id)

        if recurring:
            total_monthly = sum(r["monthly_equivalent"] for r in recurring)

            col1, col2 = st.columns(2)
            with col1:
                st.metric("Monatliche Fixkosten", f"{total_monthly:,.2f} €")
            with col2:
                st.metric("Jährliche Fixkosten", f"{total_monthly * 12:,.2f} €")

            st.divider()

            for r in recurring:
                with st.expander(f"{r['merchant']} - {r['average_amount']:,.2f} € ({r['frequency']})"):
                    st.write(f"**Monatl. Äquivalent:** {r['monthly_equivalent']:,.2f} €")
                    st.write(f"**Anzahl Zahlungen:** {r['occurrence_count']}")
        else:
            st.info("Noch keine wiederkehrenden Ausgaben erkannt.")

    with tab_matching:
        st.subheader("🔗 Rechnungs-Bank-Abgleich")

        # Statistiken
        stats = matching_service.get_matching_statistics(user_id)

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Offene Rechnungen", stats["open_invoices"])
        with col2:
            st.metric("Überfällig", stats["overdue_invoices"])
        with col3:
            st.metric("Bezahlt (90 Tage)", stats["paid_invoices_90d"])
        with col4:
            st.metric("Nicht zugeordnet", stats["unmatched_transactions_90d"])

        st.divider()

        # Auto-Match Button
        if st.button("🤖 Auto-Abgleich starten", type="primary"):
            with st.spinner("Führe automatischen Abgleich durch..."):
                result = matching_service.auto_match_all(user_id)

                if result.get("success"):
                    st.success(f"✅ {result['auto_matched']} Rechnungen automatisch zugeordnet!")
                else:
                    st.error(f"❌ {result.get('error', 'Fehler beim Abgleich')}")

        # Unbezahlte Rechnungen
        st.subheader("📋 Offene Rechnungen")

        unmatched_invoices = matching_service.find_unmatched_invoices(user_id)

        if unmatched_invoices:
            for inv in unmatched_invoices[:10]:
                status_icon = "🔴" if inv["is_overdue"] else "🟡"
                st.write(f"{status_icon} **{inv['title'][:40]}** - {inv['amount']:,.2f} €")
        else:
            st.success("✅ Alle Rechnungen sind bezahlt!")

# Hinweis für Erinnerung
st.divider()
st.info("""
💡 **Hinweis:** Einige erweiterte Funktionen (OCR, Barcode-Scan, Audio-Aufnahme)
erfordern eine lokale Installation mit System-Bibliotheken.
Siehe Dokumentation für Details zur lokalen Einrichtung.
""")
