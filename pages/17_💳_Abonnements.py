"""
Abo-Verwaltung Seite
Übersicht und Verwaltung von Abonnements
"""
import streamlit as st
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go

# Imports
try:
    from services.subscription_service import SubscriptionService
    from database.extended_models import Subscription, SubscriptionInterval
    SUBSCRIPTION_AVAILABLE = True
except ImportError:
    SUBSCRIPTION_AVAILABLE = False


def render_subscription_page():
    """Rendert die Abo-Seite"""
    st.title("Abo-Verwaltung")
    st.markdown("Behalten Sie den Überblick über Ihre Abonnements")

    if not SUBSCRIPTION_AVAILABLE:
        st.error("Abo-Module nicht verfügbar.")
        return

    if "user" not in st.session_state or not st.session_state.user:
        st.warning("Bitte melden Sie sich an.")
        return

    user_id = st.session_state.user.get("id", 1)
    service = SubscriptionService(user_id)

    # Abrechnungsdaten aktualisieren
    service.update_next_billing_dates()

    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs([
        "Übersicht", "Neues Abo", "Alle Abos", "Sparpotenzial"
    ])

    with tab1:
        render_overview(service)

    with tab2:
        render_new_subscription(service)

    with tab3:
        render_all_subscriptions(service)

    with tab4:
        render_savings(service)


def render_overview(service: SubscriptionService):
    """Tab: Übersicht"""
    stats = service.get_statistics()

    # Metriken
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Aktive Abos", stats["active"])

    with col2:
        st.metric("Monatliche Kosten", f"{stats['monthly_cost']:.2f}€")

    with col3:
        st.metric("Jährliche Kosten", f"{stats['yearly_cost']:.2f}€")

    with col4:
        st.metric("Kategorien", stats["categories"])

    st.divider()

    # Kosten nach Kategorie
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Kosten nach Kategorie")
        cost_by_cat = stats["cost_by_category"]

        if cost_by_cat:
            fig = px.pie(
                values=list(cost_by_cat.values()),
                names=[service.CATEGORIES.get(k, k) for k in cost_by_cat.keys()],
                hole=0.4
            )
            fig.update_layout(margin=dict(t=20, b=20, l=20, r=20), height=300)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Keine Daten vorhanden")

    with col2:
        st.subheader("Teuerste Abos")

        if stats["most_expensive"]:
            for sub in stats["most_expensive"]:
                monthly = service._to_monthly(sub.amount, sub.billing_interval)
                col_a, col_b = st.columns([3, 1])

                with col_a:
                    st.markdown(f"**{sub.name}**")
                    st.caption(sub.provider or "")

                with col_b:
                    st.markdown(f"**{monthly:.2f}€**/Monat")

                st.divider()
        else:
            st.info("Keine Abos vorhanden")

    # Anstehende Zahlungen
    st.divider()
    st.subheader("Anstehende Zahlungen (nächste 30 Tage)")

    upcoming = service.get_upcoming_payments(days=30)

    if upcoming:
        total_upcoming = sum(p["amount"] for p in upcoming)
        st.metric("Summe", f"{total_upcoming:.2f}€")

        for payment in upcoming:
            sub = payment["subscription"]
            col1, col2, col3 = st.columns([3, 1, 1])

            with col1:
                st.markdown(f"**{sub.name}**")

            with col2:
                st.markdown(f"{payment['date'].strftime('%d.%m.%Y')}")

            with col3:
                if payment["days_until"] <= 3:
                    st.error(f"{payment['amount']:.2f}€")
                elif payment["days_until"] <= 7:
                    st.warning(f"{payment['amount']:.2f}€")
                else:
                    st.info(f"{payment['amount']:.2f}€")
    else:
        st.success("Keine Zahlungen in den nächsten 30 Tagen")

    # Probezeiten
    trial_ending = service.get_trial_ending_soon(days=7)

    if trial_ending:
        st.divider()
        st.warning("**Probezeiten enden bald:**")

        for sub in trial_ending:
            days_left = (sub.trial_end_date - datetime.now()).days
            st.markdown(f"- **{sub.name}**: noch {days_left} Tage (wird dann {sub.amount:.2f}€)")


def render_new_subscription(service: SubscriptionService):
    """Tab: Neues Abo"""
    st.subheader("Neues Abonnement erfassen")

    with st.form("new_subscription_form"):
        col1, col2 = st.columns(2)

        with col1:
            name = st.text_input("Name *", placeholder="z.B. Netflix, Spotify")
            provider = st.text_input("Anbieter", placeholder="z.B. Netflix Inc.")

            category = st.selectbox(
                "Kategorie",
                options=list(service.CATEGORIES.keys()),
                format_func=lambda x: service.CATEGORIES.get(x, x)
            )

            website_url = st.text_input("Website", placeholder="https://...")

        with col2:
            amount = st.number_input("Betrag (€) *", min_value=0.0, step=0.01)

            billing_interval = st.selectbox(
                "Abrechnungsintervall",
                options=[i.value for i in SubscriptionInterval],
                format_func=get_interval_name,
                index=0
            )

            start_date = st.date_input("Startdatum", value=datetime.now())
            payment_method = st.selectbox(
                "Zahlungsmethode",
                options=["credit_card", "direct_debit", "paypal", "other"],
                format_func=lambda x: {
                    "credit_card": "Kreditkarte",
                    "direct_debit": "Lastschrift",
                    "paypal": "PayPal",
                    "other": "Sonstige"
                }.get(x, x)
            )

        st.divider()

        col1, col2 = st.columns(2)

        with col1:
            has_trial = st.checkbox("Hat Probezeit")
            if has_trial:
                trial_end = st.date_input("Probezeit endet am")
            else:
                trial_end = None

            cancellation_url = st.text_input("Kündigungs-Link", placeholder="https://...")
            notice_period = st.number_input("Kündigungsfrist (Tage)", min_value=0, value=0)

        with col2:
            login_email = st.text_input("Login E-Mail")
            shared_count = st.number_input("Geteilt mit (Personen)", min_value=0, value=0)

        notes = st.text_area("Notizen")

        submitted = st.form_submit_button("Abonnement speichern", type="primary")

        if submitted:
            if not name or amount <= 0:
                st.error("Bitte füllen Sie alle Pflichtfelder aus.")
            else:
                subscription = service.create_subscription(
                    name=name,
                    amount=amount,
                    billing_interval=SubscriptionInterval(billing_interval),
                    start_date=datetime.combine(start_date, datetime.min.time()),
                    provider=provider,
                    category=category,
                    website_url=website_url,
                    payment_method=payment_method,
                    cancellation_url=cancellation_url,
                    notice_period_days=notice_period if notice_period > 0 else None,
                    login_email=login_email,
                    trial_end_date=datetime.combine(trial_end, datetime.min.time()) if trial_end else None,
                    shared_with=[f"Person {i+1}" for i in range(shared_count)] if shared_count > 0 else None,
                    notes=notes
                )

                st.success(f"Abonnement '{name}' erfolgreich gespeichert!")


def render_all_subscriptions(service: SubscriptionService):
    """Tab: Alle Abos"""
    st.subheader("Alle Abonnements")

    # Filter
    col1, col2, col3 = st.columns(3)

    with col1:
        show_cancelled = st.checkbox("Gekündigte anzeigen", value=False)

    with col2:
        filter_category = st.selectbox(
            "Nach Kategorie filtern",
            options=["all"] + list(service.CATEGORIES.keys()),
            format_func=lambda x: "Alle" if x == "all" else service.CATEGORIES.get(x, x)
        )

    with col3:
        sort_by = st.selectbox(
            "Sortieren nach",
            options=["next_billing", "amount", "name"],
            format_func=lambda x: {
                "next_billing": "Nächste Zahlung",
                "amount": "Betrag",
                "name": "Name"
            }.get(x, x)
        )

    # Abos abrufen
    subscriptions = service.get_all_subscriptions(active_only=not show_cancelled)

    if filter_category != "all":
        subscriptions = [s for s in subscriptions if s.category == filter_category]

    # Sortieren
    if sort_by == "next_billing":
        subscriptions = sorted(subscriptions, key=lambda s: s.next_billing_date or datetime.max)
    elif sort_by == "amount":
        subscriptions = sorted(subscriptions, key=lambda s: service._to_monthly(s.amount, s.billing_interval), reverse=True)
    elif sort_by == "name":
        subscriptions = sorted(subscriptions, key=lambda s: s.name.lower())

    if not subscriptions:
        st.info("Keine Abonnements gefunden.")
        return

    # Liste anzeigen
    for sub in subscriptions:
        icon = get_category_icon(sub.category)
        monthly = service._to_monthly(sub.amount, sub.billing_interval)

        status = "🟢" if sub.is_active and not sub.cancellation_date else "🔴"
        if sub.is_paused:
            status = "⏸️"

        with st.expander(f"{status} {icon} {sub.name} - {monthly:.2f}€/Monat"):
            col1, col2, col3 = st.columns([2, 1, 1])

            with col1:
                st.markdown(f"**Anbieter:** {sub.provider or '-'}")
                st.markdown(f"**Kategorie:** {service.CATEGORIES.get(sub.category, sub.category or '-')}")
                st.markdown(f"**Zahlungsweise:** {get_interval_name(sub.billing_interval.value)}")
                st.markdown(f"**Betrag:** {sub.amount:.2f}€")
                if sub.website_url:
                    st.markdown(f"[Website öffnen]({sub.website_url})")

            with col2:
                if sub.next_billing_date:
                    days_until = (sub.next_billing_date - datetime.now()).days
                    st.metric("Nächste Zahlung", sub.next_billing_date.strftime("%d.%m.%Y"))
                    st.caption(f"in {days_until} Tagen")

                if sub.trial_end_date and sub.trial_end_date > datetime.now():
                    st.warning(f"Probezeit bis {sub.trial_end_date.strftime('%d.%m.%Y')}")

            with col3:
                if sub.login_email:
                    st.markdown(f"**Login:** {sub.login_email}")
                if sub.shared_with:
                    st.markdown(f"**Geteilt mit:** {len(sub.shared_with)} Personen")

            # Aktionen
            st.divider()
            col1, col2, col3, col4 = st.columns(4)

            with col1:
                if sub.cancellation_url:
                    st.link_button("Kündigen", sub.cancellation_url)

            with col2:
                if sub.is_active and not sub.cancellation_date:
                    if sub.is_paused:
                        if st.button("Fortsetzen", key=f"resume_{sub.id}"):
                            service.resume_subscription(sub.id)
                            st.success("Fortgesetzt!")
                            st.rerun()
                    else:
                        if st.button("Pausieren", key=f"pause_{sub.id}"):
                            service.pause_subscription(sub.id)
                            st.success("Pausiert!")
                            st.rerun()

            with col3:
                if not sub.cancellation_date:
                    if st.button("Als gekündigt markieren", key=f"cancel_{sub.id}"):
                        service.cancel_subscription(sub.id)
                        st.success("Als gekündigt markiert!")
                        st.rerun()

            with col4:
                if st.button("Löschen", key=f"delete_{sub.id}"):
                    if st.session_state.get(f"confirm_del_{sub.id}"):
                        service.delete_subscription(sub.id)
                        st.success("Gelöscht!")
                        st.rerun()
                    else:
                        st.session_state[f"confirm_del_{sub.id}"] = True
                        st.warning("Erneut klicken zum Bestätigen")
                        st.rerun()

            if sub.notes:
                st.markdown(f"**Notizen:** {sub.notes}")


def render_savings(service: SubscriptionService):
    """Tab: Sparpotenzial"""
    st.subheader("Sparpotenzial erkennen")

    suggestions = service.get_potential_savings()

    if not suggestions:
        st.success("Keine offensichtlichen Einsparmöglichkeiten gefunden!")
        st.markdown("""
        **Tipps zum Sparen:**
        - Prüfen Sie regelmäßig, ob Sie alle Abos nutzen
        - Vergleichen Sie Preise bei jährlicher vs. monatlicher Zahlung
        - Nutzen Sie Familien- oder Gruppen-Tarife
        """)
        return

    total_potential = 0

    for suggestion in suggestions:
        if suggestion["type"] == "duplicate_category":
            st.warning(f"**Mehrere Abos in '{service.CATEGORIES.get(suggestion['category'], suggestion['category'])}'**")
            st.markdown(f"Monatliche Kosten: **{suggestion['monthly_cost']:.2f}€**")
            st.markdown(suggestion["suggestion"])

            for sub in suggestion["subscriptions"]:
                st.markdown(f"- {sub.name}: {sub.amount:.2f}€/{get_interval_name(sub.billing_interval.value)}")

            st.divider()

        elif suggestion["type"] == "expensive":
            sub = suggestion["subscription"]
            st.info(f"**{sub.name}** kostet **{suggestion['monthly_cost']:.2f}€/Monat**")
            st.markdown(suggestion["suggestion"])
            st.divider()

    # Gesamtübersicht
    st.divider()
    stats = service.get_statistics()

    st.markdown("### Jahresübersicht")

    col1, col2 = st.columns(2)

    with col1:
        st.metric("Jährliche Ausgaben", f"{stats['yearly_cost']:.2f}€")

    with col2:
        # Annahme: 10% Einsparpotenzial
        potential = stats['yearly_cost'] * 0.1
        st.metric("Geschätztes Einsparpotenzial", f"{potential:.2f}€", help="Basierend auf Branchendurchschnitt von 10%")

    st.markdown("""
    ### Tipps

    1. **Jährliche Zahlung**: Viele Anbieter gewähren Rabatt bei jährlicher Zahlung (oft 15-20%)
    2. **Familien-Tarife**: Teilen Sie Abos mit Familie oder Freunden
    3. **Studentenrabatte**: Nutzen Sie Rabatte für Studenten, Schüler oder Azubis
    4. **Bundle-Angebote**: Kombinieren Sie Dienste beim gleichen Anbieter
    5. **Regelmäßige Überprüfung**: Prüfen Sie vierteljährlich, ob Sie alle Abos nutzen
    """)


# ==================== HILFSFUNKTIONEN ====================

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


def get_category_icon(category: str) -> str:
    """Gibt Icon für Kategorie zurück"""
    icons = {
        "streaming": "📺",
        "software": "💻",
        "music": "🎵",
        "fitness": "💪",
        "news": "📰",
        "cloud": "☁️",
        "gaming": "🎮",
        "education": "📚",
        "productivity": "⚡",
        "other": "📦"
    }
    return icons.get(category, "📦")


# ==================== HAUPTFUNKTION ====================

if __name__ == "__main__":
    st.set_page_config(page_title="Abonnements", page_icon="💳", layout="wide")
    render_subscription_page()
else:
    render_subscription_page()
