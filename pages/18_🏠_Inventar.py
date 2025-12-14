"""
Haushalts-Inventar Seite
Übersicht und Verwaltung des Haushalts-Inventars
"""
import streamlit as st
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go
import json

# Imports
try:
    from services.inventory_service import InventoryService
    from database.extended_models import InventoryItem
    from database.models import Document, get_session
    INVENTORY_AVAILABLE = True
except ImportError:
    INVENTORY_AVAILABLE = False


def render_inventory_page():
    """Rendert die Inventar-Seite"""
    st.title("Haushalts-Inventar")
    st.markdown("Verwalten Sie Ihr Inventar für Versicherungsnachweise")

    if not INVENTORY_AVAILABLE:
        st.error("Inventar-Module nicht verfügbar.")
        return

    if "user" not in st.session_state or not st.session_state.user:
        st.warning("Bitte melden Sie sich an.")
        return

    user_id = st.session_state.user.get("id", 1)
    service = InventoryService(user_id)

    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs([
        "Übersicht", "Neuer Gegenstand", "Alle Gegenstände", "Versicherungs-Report"
    ])

    with tab1:
        render_overview(service)

    with tab2:
        render_new_item(service, user_id)

    with tab3:
        render_all_items(service)

    with tab4:
        render_insurance_report(service)


def render_overview(service: InventoryService):
    """Tab: Übersicht"""
    # Werte aktualisieren
    service.update_all_values()

    stats = service.get_statistics()

    # Metriken
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Gegenstände", stats["active_items"])

    with col2:
        st.metric("Kaufwert", f"{stats['total_purchase_value']:,.2f}€")

    with col3:
        st.metric("Aktueller Wert", f"{stats['total_current_value']:,.2f}€")

    with col4:
        st.metric(
            "Wertverlust",
            f"-{stats['depreciation']:,.2f}€",
            delta=f"-{(stats['depreciation']/stats['total_purchase_value']*100):.1f}%" if stats['total_purchase_value'] > 0 else None,
            delta_color="inverse"
        )

    st.divider()

    # Wert nach Kategorie und Raum
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Wert nach Kategorie")
        value_by_cat = stats["value_by_category"]

        if value_by_cat:
            fig = px.pie(
                values=list(value_by_cat.values()),
                names=[service.CATEGORIES.get(k, k) for k in value_by_cat.keys()],
                hole=0.4
            )
            fig.update_layout(margin=dict(t=20, b=20, l=20, r=20), height=300)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Keine Daten vorhanden")

    with col2:
        st.subheader("Wert nach Raum")
        value_by_room = stats["value_by_room"]

        if value_by_room:
            fig = px.bar(
                x=list(value_by_room.values()),
                y=list(value_by_room.keys()),
                orientation='h',
                labels={"x": "Wert (€)", "y": "Raum"}
            )
            fig.update_layout(margin=dict(t=20, b=20, l=20, r=20), height=300)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Keine Daten vorhanden")

    # Warnungen
    st.divider()

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Fehlende Kaufbelege")
        items_without_receipt = service.get_items_without_receipt()

        if items_without_receipt:
            st.warning(f"{len(items_without_receipt)} Gegenstände ohne Kaufbeleg")
            for item in items_without_receipt[:5]:
                st.markdown(f"- {item.name}")
            if len(items_without_receipt) > 5:
                st.caption(f"... und {len(items_without_receipt) - 5} weitere")
        else:
            st.success("Alle Gegenstände haben Kaufbelege!")

    with col2:
        st.subheader("Garantie prüfen")
        items_needing_warranty = service.get_items_needing_warranty()

        if items_needing_warranty:
            st.info(f"{len(items_needing_warranty)} Gegenstände könnten Garantie haben")
            for item in items_needing_warranty[:5]:
                st.markdown(f"- {item.name}")
        else:
            st.success("Alle Garantien erfasst!")


def render_new_item(service: InventoryService, user_id: int):
    """Tab: Neuer Gegenstand"""
    st.subheader("Neuen Gegenstand erfassen")

    with st.form("new_item_form"):
        col1, col2 = st.columns(2)

        with col1:
            name = st.text_input("Name *", placeholder="z.B. Samsung TV 55 Zoll")
            description = st.text_area("Beschreibung", placeholder="Zusätzliche Details...")

            category = st.selectbox(
                "Kategorie",
                options=list(service.CATEGORIES.keys()),
                format_func=lambda x: service.CATEGORIES.get(x, x)
            )

            manufacturer = st.text_input("Hersteller", placeholder="z.B. Samsung")
            model = st.text_input("Modell", placeholder="z.B. QE55Q80C")
            serial_number = st.text_input("Seriennummer")

        with col2:
            purchase_date = st.date_input("Kaufdatum", value=None)
            purchase_price = st.number_input("Kaufpreis (€)", min_value=0.0, step=0.01)
            retailer = st.text_input("Händler", placeholder="z.B. MediaMarkt")

            room = st.selectbox("Raum", options=[""] + service.ROOMS)
            location = st.text_input("Genauer Standort", placeholder="z.B. Wohnzimmer links")

            condition = st.selectbox(
                "Zustand",
                options=["new", "good", "fair", "poor"],
                format_func=lambda x: {
                    "new": "Neu",
                    "good": "Gut",
                    "fair": "Gebraucht",
                    "poor": "Abgenutzt"
                }.get(x, x)
            )

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

        # Abschreibung
        st.markdown("**Abschreibung**")
        depreciation_rate = st.slider(
            "Jährliche Abschreibung (%)",
            min_value=0,
            max_value=50,
            value=10,
            help="Wie viel Wert verliert der Gegenstand pro Jahr?"
        ) / 100

        notes = st.text_area("Notizen")

        submitted = st.form_submit_button("Gegenstand speichern", type="primary")

        if submitted:
            if not name:
                st.error("Bitte geben Sie einen Namen ein.")
            else:
                item = service.create_item(
                    name=name,
                    description=description,
                    category=category,
                    manufacturer=manufacturer,
                    model=model,
                    serial_number=serial_number,
                    purchase_date=datetime.combine(purchase_date, datetime.min.time()) if purchase_date else None,
                    purchase_price=purchase_price if purchase_price > 0 else None,
                    retailer=retailer,
                    room=room if room else None,
                    location=location,
                    condition=condition,
                    document_id=document_id,
                    depreciation_rate=depreciation_rate,
                    notes=notes
                )

                st.success(f"'{name}' erfolgreich gespeichert!")
                st.info(f"QR-Code: **{item.qr_code}**")


def render_all_items(service: InventoryService):
    """Tab: Alle Gegenstände"""
    st.subheader("Alle Gegenstände")

    # Filter
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        show_disposed = st.checkbox("Entsorgte anzeigen", value=False)

    with col2:
        filter_category = st.selectbox(
            "Kategorie",
            options=["all"] + list(service.CATEGORIES.keys()),
            format_func=lambda x: "Alle" if x == "all" else service.CATEGORIES.get(x, x)
        )

    with col3:
        filter_room = st.selectbox(
            "Raum",
            options=["all"] + service.ROOMS,
            format_func=lambda x: "Alle" if x == "all" else x
        )

    with col4:
        search_query = st.text_input("Suchen", placeholder="Name, Hersteller...")

    # Gegenstände abrufen
    if search_query:
        items = service.search_items(search_query)
    else:
        items = service.get_all_items(include_disposed=show_disposed)

    # Filter anwenden
    if filter_category != "all":
        items = [i for i in items if i.category == filter_category]

    if filter_room != "all":
        items = [i for i in items if i.room == filter_room]

    if not items:
        st.info("Keine Gegenstände gefunden.")
        return

    # Sortierung
    items = sorted(items, key=lambda i: i.name.lower())

    st.markdown(f"**{len(items)} Gegenstände gefunden**")

    # Liste anzeigen
    for item in items:
        icon = get_category_icon(item.category)
        current_value = service.calculate_current_value(item)

        status = "🟢" if item.is_active else "🔴"

        with st.expander(f"{status} {icon} {item.name}"):
            col1, col2, col3 = st.columns([2, 1, 1])

            with col1:
                st.markdown(f"**Hersteller:** {item.manufacturer or '-'}")
                st.markdown(f"**Modell:** {item.model or '-'}")
                st.markdown(f"**Seriennummer:** {item.serial_number or '-'}")
                st.markdown(f"**Kategorie:** {service.CATEGORIES.get(item.category, item.category or '-')}")
                st.markdown(f"**Raum:** {item.room or '-'}")
                st.markdown(f"**Standort:** {item.location or '-'}")
                st.markdown(f"**Zustand:** {get_condition_name(item.condition)}")

            with col2:
                if item.purchase_price:
                    st.metric("Kaufpreis", f"{item.purchase_price:.2f}€")
                st.metric("Aktueller Wert", f"{current_value:.2f}€")
                if item.purchase_date:
                    st.markdown(f"**Gekauft:** {item.purchase_date.strftime('%d.%m.%Y')}")

            with col3:
                st.markdown(f"**QR-Code:** `{item.qr_code}`")
                if item.retailer:
                    st.markdown(f"**Händler:** {item.retailer}")

            if item.description:
                st.markdown(f"**Beschreibung:** {item.description}")

            if item.notes:
                st.markdown(f"**Notizen:** {item.notes}")

            # Aktionen
            st.divider()
            col1, col2, col3, col4 = st.columns(4)

            with col1:
                if st.button("Bearbeiten", key=f"edit_{item.id}"):
                    st.session_state[f"editing_{item.id}"] = True

            with col2:
                if item.is_active:
                    if st.button("Entsorgt/Verkauft", key=f"dispose_{item.id}"):
                        st.session_state[f"disposing_{item.id}"] = True

            with col3:
                if st.button("Löschen", key=f"delete_{item.id}"):
                    if st.session_state.get(f"confirm_del_{item.id}"):
                        service.delete_item(item.id)
                        st.success("Gelöscht!")
                        st.rerun()
                    else:
                        st.session_state[f"confirm_del_{item.id}"] = True
                        st.warning("Erneut klicken")

            # Entsorgungs-Dialog
            if st.session_state.get(f"disposing_{item.id}"):
                reason = st.selectbox(
                    "Grund",
                    options=["sold", "donated", "discarded", "broken"],
                    format_func=lambda x: {
                        "sold": "Verkauft",
                        "donated": "Gespendet",
                        "discarded": "Entsorgt",
                        "broken": "Defekt"
                    }.get(x, x),
                    key=f"dispose_reason_{item.id}"
                )
                if st.button("Bestätigen", key=f"confirm_dispose_{item.id}"):
                    service.dispose_item(item.id, reason)
                    st.success("Gegenstand als entsorgt markiert!")
                    del st.session_state[f"disposing_{item.id}"]
                    st.rerun()


def render_insurance_report(service: InventoryService):
    """Tab: Versicherungs-Report"""
    st.subheader("Versicherungs-Report")

    st.markdown("""
    Dieser Report enthält eine Übersicht aller Gegenstände für Ihre Hausratversicherung.
    """)

    report = service.get_insurance_report()

    # Zusammenfassung
    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Gesamtwert", f"{report['total_value']:,.2f}€")

    with col2:
        st.metric("Gegenstände", report["total_items"])

    with col3:
        st.metric("Hochwertige Gegenstände (>500€)", len(report["high_value_items"]))

    st.divider()

    # Hochwertige Gegenstände
    if report["high_value_items"]:
        st.subheader("Hochwertige Gegenstände")

        for item in report["high_value_items"]:
            col1, col2, col3 = st.columns([3, 1, 1])

            with col1:
                st.markdown(f"**{item['name']}**")
                if item["manufacturer"]:
                    st.caption(f"{item['manufacturer']} {item['model'] or ''}")

            with col2:
                if item["serial_number"]:
                    st.markdown(f"SN: `{item['serial_number']}`")

            with col3:
                st.markdown(f"**{item['current_value']:.2f}€**")

            st.divider()

    # Nach Kategorie
    st.subheader("Übersicht nach Kategorie")

    for cat, data in report["by_category"].items():
        col1, col2, col3 = st.columns([3, 1, 1])

        with col1:
            st.markdown(f"**{service.CATEGORIES.get(cat, cat)}**")

        with col2:
            st.markdown(f"{data['count']} Stück")

        with col3:
            st.markdown(f"**{data['value']:.2f}€**")

    # Export
    st.divider()
    st.subheader("Report exportieren")

    col1, col2 = st.columns(2)

    with col1:
        # JSON Export
        json_data = json.dumps(report, indent=2, default=str, ensure_ascii=False)
        st.download_button(
            "Als JSON herunterladen",
            data=json_data,
            file_name=f"inventar_report_{datetime.now().strftime('%Y%m%d')}.json",
            mime="application/json"
        )

    with col2:
        # CSV Export (vereinfacht)
        csv_lines = ["Name;Kategorie;Raum;Kaufpreis;Aktueller Wert;Seriennummer"]
        for item in report["items"]:
            csv_lines.append(
                f"{item['name']};{item['category']};{item['room'] or ''};{item['purchase_price'] or ''};{item['current_value']};{item['serial_number'] or ''}"
            )
        csv_data = "\n".join(csv_lines)

        st.download_button(
            "Als CSV herunterladen",
            data=csv_data,
            file_name=f"inventar_liste_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv"
        )


# ==================== HILFSFUNKTIONEN ====================

def get_category_icon(category: str) -> str:
    """Gibt Icon für Kategorie zurück"""
    icons = {
        "electronics": "📱",
        "furniture": "🛋️",
        "appliances": "🔌",
        "kitchen": "🍳",
        "clothing": "👔",
        "jewelry": "💍",
        "sports": "⚽",
        "tools": "🔧",
        "garden": "🌿",
        "art": "🖼️",
        "books": "📚",
        "toys": "🧸",
        "vehicles": "🚗",
        "other": "📦"
    }
    return icons.get(category, "📦")


def get_condition_name(condition: str) -> str:
    """Gibt deutschen Namen für Zustand zurück"""
    names = {
        "new": "Neu",
        "good": "Gut",
        "fair": "Gebraucht",
        "poor": "Abgenutzt"
    }
    return names.get(condition, condition)


# ==================== HAUPTFUNKTION ====================

if __name__ == "__main__":
    st.set_page_config(page_title="Inventar", page_icon="🏠", layout="wide")
    render_inventory_page()
else:
    render_inventory_page()
