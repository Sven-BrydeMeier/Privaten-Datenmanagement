"""
Garantie-Tracker Seite
Übersicht und Verwaltung von Garantien
"""
import streamlit as st
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go

# Imports
try:
    from services.warranty_service import WarrantyService
    from database.extended_models import WarrantyStatus
    from database.models import Document, get_session
    WARRANTY_AVAILABLE = True
except ImportError:
    WARRANTY_AVAILABLE = False


def render_warranty_page():
    """Rendert die Garantie-Seite"""
    st.title("Garantie-Tracker")
    st.markdown("Behalten Sie den Überblick über Ihre Garantien und Gewährleistungen")

    if not WARRANTY_AVAILABLE:
        st.error("Garantie-Module nicht verfügbar.")
        return

    # Benutzer-Check
    if "user" not in st.session_state or not st.session_state.user:
        st.warning("Bitte melden Sie sich an.")
        return

    user_id = st.session_state.user.get("id", 1)
    service = WarrantyService(user_id)

    # Status aktualisieren
    service.update_all_statuses()

    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs([
        "Übersicht", "Neue Garantie", "Alle Garantien", "Erinnerungen"
    ])

    with tab1:
        render_overview(service)

    with tab2:
        render_new_warranty(service, user_id)

    with tab3:
        render_all_warranties(service)

    with tab4:
        render_reminders(service)


def render_overview(service: WarrantyService):
    """Tab: Übersicht"""
    stats = service.get_statistics()

    # Metriken
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Aktive Garantien", stats["active"], help="Garantien die noch gültig sind")

    with col2:
        st.metric(
            "Bald ablaufend",
            stats["expiring_soon"],
            delta=f"In 30 Tagen" if stats["expiring_soon"] > 0 else None,
            delta_color="inverse"
        )

    with col3:
        st.metric("Abgelaufen", stats["expired"])

    with col4:
        st.metric(
            "Geschützter Wert",
            f"{stats['total_protected_value']:,.2f}€",
            help="Gesamtwert der Produkte mit aktiver Garantie"
        )

    st.divider()

    # Bald ablaufende Garantien
    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("Bald ablaufende Garantien")
        expiring = service.get_expiring_soon(days=60)

        if not expiring:
            st.success("Keine Garantien laufen in den nächsten 60 Tagen ab.")
        else:
            for warranty in expiring:
                days_left = (warranty.warranty_end - datetime.now()).days

                with st.container():
                    wcol1, wcol2, wcol3 = st.columns([3, 1, 1])

                    with wcol1:
                        st.markdown(f"**{warranty.product_name}**")
                        st.caption(f"{warranty.manufacturer or ''} {warranty.model_number or ''}")

                    with wcol2:
                        if days_left <= 7:
                            st.error(f"{days_left} Tage")
                        elif days_left <= 30:
                            st.warning(f"{days_left} Tage")
                        else:
                            st.info(f"{days_left} Tage")

                    with wcol3:
                        if warranty.purchase_price:
                            st.markdown(f"**{warranty.purchase_price:.2f}€**")

                    st.divider()

    with col2:
        # Status-Verteilung
        st.subheader("Status")

        if stats["total"] > 0:
            fig = go.Figure(data=[go.Pie(
                labels=["Aktiv", "Bald ablaufend", "Abgelaufen", "Beansprucht"],
                values=[stats["active"], stats["expiring_soon"], stats["expired"], stats["claimed"]],
                hole=0.4,
                marker_colors=["#4CAF50", "#FF9800", "#F44336", "#9E9E9E"]
            )])
            fig.update_layout(
                showlegend=True,
                margin=dict(t=20, b=20, l=20, r=20),
                height=250
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Noch keine Garantien eingetragen")

    # Nächste ablaufende
    if stats["next_expiring"]:
        st.divider()
        st.subheader("Nächster Ablauf")
        w = stats["next_expiring"]
        days_left = (w.warranty_end - datetime.now()).days

        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown(f"**{w.product_name}**")
        with col2:
            st.markdown(f"Läuft ab: **{w.warranty_end.strftime('%d.%m.%Y')}**")
        with col3:
            st.markdown(f"Noch **{days_left} Tage**")


def render_new_warranty(service: WarrantyService, user_id: int):
    """Tab: Neue Garantie hinzufügen"""
    st.subheader("Neue Garantie erfassen")

    with st.form("new_warranty_form"):
        col1, col2 = st.columns(2)

        with col1:
            product_name = st.text_input("Produktname *", placeholder="z.B. Samsung Galaxy S24")
            manufacturer = st.text_input("Hersteller", placeholder="z.B. Samsung")
            model_number = st.text_input("Modellnummer")
            serial_number = st.text_input("Seriennummer")

        with col2:
            purchase_date = st.date_input("Kaufdatum *", value=datetime.now())
            warranty_years = st.selectbox(
                "Garantiedauer",
                options=[1, 2, 3, 5, 10],
                index=1,
                format_func=lambda x: f"{x} Jahr(e)"
            )
            warranty_end = st.date_input(
                "Garantie endet am",
                value=datetime.now() + timedelta(days=warranty_years * 365)
            )
            purchase_price = st.number_input("Kaufpreis (€)", min_value=0.0, step=0.01)

        st.divider()

        col1, col2 = st.columns(2)

        with col1:
            retailer = st.text_input("Händler", placeholder="z.B. Amazon, MediaMarkt")
            warranty_contact = st.text_input("Garantie-Kontakt", placeholder="Hotline oder E-Mail")

        with col2:
            warranty_url = st.text_input("Garantie-Website", placeholder="https://...")

            # Dokument verknüpfen
            with get_session() as session:
                docs = session.query(Document).filter(
                    Document.user_id == user_id,
                    Document.is_deleted == False
                ).order_by(Document.created_at.desc()).limit(50).all()

            doc_options = {"Kein Dokument": None}
            for doc in docs:
                doc_options[f"{doc.title or doc.filename} ({doc.created_at.strftime('%d.%m.%Y')})"] = doc.id

            selected_doc = st.selectbox("Kaufbeleg verknüpfen", options=list(doc_options.keys()))
            document_id = doc_options[selected_doc]

        notes = st.text_area("Notizen", placeholder="Zusätzliche Informationen...")

        # Erweiterte Garantie
        has_extended = st.checkbox("Erweiterte Garantie gekauft")
        if has_extended:
            extended_end = st.date_input(
                "Erweiterte Garantie endet am",
                value=datetime.now() + timedelta(days=warranty_years * 365 + 365)
            )
        else:
            extended_end = None

        submitted = st.form_submit_button("Garantie speichern", type="primary")

        if submitted:
            if not product_name:
                st.error("Bitte geben Sie einen Produktnamen ein.")
            else:
                warranty = service.create_warranty(
                    product_name=product_name,
                    purchase_date=datetime.combine(purchase_date, datetime.min.time()),
                    warranty_end=datetime.combine(warranty_end, datetime.min.time()),
                    manufacturer=manufacturer,
                    model_number=model_number,
                    serial_number=serial_number,
                    purchase_price=purchase_price if purchase_price > 0 else None,
                    retailer=retailer,
                    warranty_contact=warranty_contact,
                    warranty_url=warranty_url,
                    document_id=document_id,
                    receipt_document_id=document_id,
                    notes=notes,
                    extended_warranty_end=datetime.combine(extended_end, datetime.min.time()) if extended_end else None
                )

                st.success(f"Garantie für '{product_name}' erfolgreich gespeichert!")
                st.balloons()


def render_all_warranties(service: WarrantyService):
    """Tab: Alle Garantien"""
    st.subheader("Alle Garantien")

    # Filter
    col1, col2, col3 = st.columns(3)

    with col1:
        show_expired = st.checkbox("Abgelaufene anzeigen", value=False)

    with col2:
        search_query = st.text_input("Suchen", placeholder="Produkt, Hersteller...")

    with col3:
        sort_by = st.selectbox(
            "Sortieren nach",
            options=["Ablaufdatum", "Produktname", "Kaufpreis"],
            index=0
        )

    # Garantien abrufen
    if search_query:
        warranties = service.search_warranties(search_query)
    else:
        warranties = service.get_all_warranties(include_expired=show_expired)

    # Sortieren
    if sort_by == "Ablaufdatum":
        warranties = sorted(warranties, key=lambda w: w.warranty_end)
    elif sort_by == "Produktname":
        warranties = sorted(warranties, key=lambda w: w.product_name.lower())
    elif sort_by == "Kaufpreis":
        warranties = sorted(warranties, key=lambda w: w.purchase_price or 0, reverse=True)

    if not warranties:
        st.info("Keine Garantien gefunden.")
        return

    st.markdown(f"**{len(warranties)} Garantien gefunden**")

    # Liste anzeigen
    for warranty in warranties:
        status_icon = get_status_icon(warranty.status)
        days_left = (warranty.warranty_end - datetime.now()).days

        with st.expander(f"{status_icon} {warranty.product_name}", expanded=False):
            col1, col2, col3 = st.columns([2, 1, 1])

            with col1:
                st.markdown(f"**Hersteller:** {warranty.manufacturer or '-'}")
                st.markdown(f"**Modell:** {warranty.model_number or '-'}")
                st.markdown(f"**Seriennummer:** {warranty.serial_number or '-'}")
                st.markdown(f"**Händler:** {warranty.retailer or '-'}")

            with col2:
                st.markdown(f"**Kaufdatum:** {warranty.purchase_date.strftime('%d.%m.%Y')}")
                st.markdown(f"**Garantie bis:** {warranty.warranty_end.strftime('%d.%m.%Y')}")
                if warranty.extended_warranty_end:
                    st.markdown(f"**Erweitert bis:** {warranty.extended_warranty_end.strftime('%d.%m.%Y')}")
                st.markdown(f"**Status:** {get_status_text(warranty.status)}")

            with col3:
                if warranty.purchase_price:
                    st.metric("Kaufpreis", f"{warranty.purchase_price:.2f}€")

                if days_left > 0:
                    st.metric("Verbleibend", f"{days_left} Tage")
                else:
                    st.metric("Abgelaufen", f"vor {abs(days_left)} Tagen")

            # Aktionen
            st.divider()
            action_col1, action_col2, action_col3, action_col4 = st.columns(4)

            with action_col1:
                if warranty.warranty_url:
                    st.link_button("Garantie-Website", warranty.warranty_url)

            with action_col2:
                if warranty.status != WarrantyStatus.CLAIMED and days_left > 0:
                    if st.button("Garantiefall melden", key=f"claim_{warranty.id}"):
                        st.session_state[f"claiming_{warranty.id}"] = True
                        st.rerun()

            with action_col3:
                if st.button("Bearbeiten", key=f"edit_{warranty.id}"):
                    st.session_state[f"editing_{warranty.id}"] = True
                    st.rerun()

            with action_col4:
                if st.button("Löschen", key=f"delete_{warranty.id}"):
                    if st.session_state.get(f"confirm_delete_{warranty.id}"):
                        service.delete_warranty(warranty.id)
                        st.success("Gelöscht!")
                        st.rerun()
                    else:
                        st.session_state[f"confirm_delete_{warranty.id}"] = True
                        st.warning("Erneut klicken zum Bestätigen")
                        st.rerun()

            # Garantiefall-Dialog
            if st.session_state.get(f"claiming_{warranty.id}"):
                claim_notes = st.text_area("Beschreibung des Garantiefalls", key=f"claim_notes_{warranty.id}")
                if st.button("Garantiefall speichern", key=f"save_claim_{warranty.id}"):
                    service.mark_as_claimed(warranty.id, claim_notes)
                    st.success("Garantiefall erfasst!")
                    del st.session_state[f"claiming_{warranty.id}"]
                    st.rerun()

            if warranty.notes:
                st.markdown(f"**Notizen:** {warranty.notes}")


def render_reminders(service: WarrantyService):
    """Tab: Erinnerungen"""
    st.subheader("Erinnerungen")

    # Ausstehende Erinnerungen
    due_reminders = service.get_due_reminders()

    if due_reminders:
        st.warning(f"{len(due_reminders)} Garantien brauchen Aufmerksamkeit!")

        for warranty in due_reminders:
            days_left = (warranty.warranty_end - datetime.now()).days

            col1, col2, col3 = st.columns([3, 1, 1])

            with col1:
                st.markdown(f"**{warranty.product_name}**")
                st.caption(f"Läuft ab am {warranty.warranty_end.strftime('%d.%m.%Y')}")

            with col2:
                if days_left <= 7:
                    st.error(f"{days_left} Tage")
                elif days_left <= 30:
                    st.warning(f"{days_left} Tage")
                else:
                    st.info(f"{days_left} Tage")

            with col3:
                if st.button("Als gelesen markieren", key=f"read_{warranty.id}"):
                    service.mark_reminder_sent(warranty.id)
                    st.success("Markiert!")
                    st.rerun()

            st.divider()
    else:
        st.success("Keine ausstehenden Erinnerungen!")

    # Erinnerungseinstellungen
    st.divider()
    st.subheader("Einstellungen")

    st.markdown("""
    **Erinnerungen werden gesendet:**
    - 30 Tage vor Ablauf (Standard)
    - Bei Produkten mit hohem Wert auch 60 Tage vorher

    **Tipp:** Überprüfen Sie regelmäßig, ob Sie Garantieansprüche geltend machen können,
    bevor die Garantie abläuft!
    """)


def get_status_icon(status: WarrantyStatus) -> str:
    """Gibt Icon für Status zurück"""
    icons = {
        WarrantyStatus.ACTIVE: "🟢",
        WarrantyStatus.EXPIRING_SOON: "🟡",
        WarrantyStatus.EXPIRED: "🔴",
        WarrantyStatus.CLAIMED: "🔵"
    }
    return icons.get(status, "⚪")


def get_status_text(status: WarrantyStatus) -> str:
    """Gibt Text für Status zurück"""
    texts = {
        WarrantyStatus.ACTIVE: "Aktiv",
        WarrantyStatus.EXPIRING_SOON: "Läuft bald ab",
        WarrantyStatus.EXPIRED: "Abgelaufen",
        WarrantyStatus.CLAIMED: "Beansprucht"
    }
    return texts.get(status, str(status))


# ==================== HAUPTFUNKTION ====================

if __name__ == "__main__":
    st.set_page_config(page_title="Garantien", page_icon="🛡️", layout="wide")
    render_warranty_page()
else:
    render_warranty_page()
