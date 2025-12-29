"""
Immobilien-Verwaltung - Verwaltung von Immobilien für automatische Dokumentenzuordnung
"""
import streamlit as st
from pathlib import Path
import sys
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.db import init_db, get_db, get_current_user_id
from database.models import Property, Document, Folder
from utils.components import render_sidebar_cart
from utils.helpers import format_date

st.set_page_config(page_title="Immobilien", page_icon="🏘️", layout="wide")
init_db()

# Sidebar mit Aktentasche
render_sidebar_cart()

st.title("🏘️ Immobilien-Verwaltung")
st.markdown("Verwalten Sie Ihre Immobilien für automatische Dokumentenzuordnung")

user_id = get_current_user_id()


def render_property_card(prop: Property, doc_count: int):
    """Rendert eine Immobilien-Karte"""
    with st.container():
        col_icon, col_info, col_stats, col_actions = st.columns([1, 4, 2, 2])

        with col_icon:
            # Icon basierend auf Typ
            icon = "🏠"
            if prop.property_type == "Gewerbe":
                icon = "🏢"
            elif prop.property_type == "Miete":
                icon = "🏘️"
            elif prop.usage == "Vermietet":
                icon = "🏡"
            st.markdown(f"### {icon}")

        with col_info:
            st.markdown(f"**{prop.name or 'Unbenannt'}**")
            st.caption(prop.full_address or "Keine Adresse")
            if prop.property_type:
                st.caption(f"Typ: {prop.property_type} | {prop.usage or '—'}")

        with col_stats:
            st.metric("Dokumente", doc_count)

        with col_actions:
            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("✏️", key=f"edit_prop_{prop.id}", help="Bearbeiten"):
                    st.session_state.edit_property_id = prop.id
                    st.rerun()
            with col_b:
                if st.button("🗑️", key=f"delete_prop_{prop.id}", help="Löschen"):
                    st.session_state.delete_property_id = prop.id
                    st.rerun()

        st.divider()


# Tabs für verschiedene Ansichten
tab_list, tab_add, tab_docs = st.tabs(["📋 Übersicht", "➕ Hinzufügen", "📄 Dokumente nach Immobilie"])

with tab_list:
    st.subheader("Ihre Immobilien")

    with get_db() as session:
        properties = session.query(Property).filter(
            Property.user_id == user_id
        ).order_by(Property.name).all()

        if properties:
            for prop in properties:
                # Anzahl der zugeordneten Dokumente
                doc_count = session.query(Document).filter(
                    Document.user_id == user_id,
                    Document.property_id == prop.id
                ).count()

                render_property_card(prop, doc_count)
        else:
            st.info("Sie haben noch keine Immobilien angelegt.")
            st.markdown("""
            ### Warum Immobilien anlegen?

            Wenn Sie Immobilien in der App hinterlegen, werden Dokumente automatisch zugeordnet:

            - **Rechnungen** mit Ihrer Immobilienadresse werden erkannt
            - **Nebenkostenabrechnungen** werden dem Objekt zugeordnet
            - **Verträge** (Strom, Gas, Wasser) werden verknüpft
            - **Versicherungen** für die Immobilie werden gruppiert

            👉 Gehen Sie zum Tab **"Hinzufügen"** um Ihre erste Immobilie anzulegen.
            """)


with tab_add:
    st.subheader("Neue Immobilie hinzufügen")

    # Prüfen ob Bearbeitung aktiv
    edit_mode = False
    edit_prop = None
    if st.session_state.get('edit_property_id'):
        with get_db() as session:
            edit_prop = session.get(Property, st.session_state.edit_property_id)
            if edit_prop:
                edit_mode = True
                st.info(f"✏️ Bearbeite: {edit_prop.name or edit_prop.full_address}")

                if st.button("❌ Bearbeitung abbrechen"):
                    del st.session_state.edit_property_id
                    st.rerun()

    with st.form("property_form"):
        col1, col2 = st.columns(2)

        with col1:
            name = st.text_input(
                "Kurzname *",
                value=edit_prop.name if edit_prop else "",
                placeholder="z.B. Mietwohnung Berlin, Ferienhaus Ostsee",
                help="Ein eindeutiger Name für die Immobilie"
            )

            property_type = st.selectbox(
                "Art der Immobilie",
                options=["Eigentum", "Miete", "Gewerbe", "Ferienimmobilie", "Sonstige"],
                index=["Eigentum", "Miete", "Gewerbe", "Ferienimmobilie", "Sonstige"].index(edit_prop.property_type) if edit_prop and edit_prop.property_type else 0
            )

            usage = st.selectbox(
                "Nutzung",
                options=["Selbstgenutzt", "Vermietet", "Teilvermietet", "Leerstand"],
                index=["Selbstgenutzt", "Vermietet", "Teilvermietet", "Leerstand"].index(edit_prop.usage) if edit_prop and edit_prop.usage else 0
            )

        with col2:
            street = st.text_input(
                "Straße *",
                value=edit_prop.street if edit_prop else "",
                placeholder="Musterstraße"
            )

            house_number = st.text_input(
                "Hausnummer",
                value=edit_prop.house_number if edit_prop else "",
                placeholder="123a"
            )

        col3, col4 = st.columns(2)

        with col3:
            postal_code = st.text_input(
                "PLZ *",
                value=edit_prop.postal_code if edit_prop else "",
                placeholder="12345",
                max_chars=5
            )

        with col4:
            city = st.text_input(
                "Stadt *",
                value=edit_prop.city if edit_prop else "",
                placeholder="Berlin"
            )

        st.markdown("---")
        st.markdown("**Zusätzliche Informationen (optional)**")

        col5, col6 = st.columns(2)

        with col5:
            owner = st.text_input(
                "Eigentümer / Vermieter",
                value=edit_prop.owner if edit_prop else "",
                placeholder="Name des Eigentümers oder Vermieters"
            )

            management = st.text_input(
                "Hausverwaltung",
                value=edit_prop.management if edit_prop else "",
                placeholder="Name der Hausverwaltung"
            )

        with col6:
            acquired_date = st.date_input(
                "Einzugs-/Kaufdatum",
                value=edit_prop.acquired_date.date() if edit_prop and edit_prop.acquired_date else None
            )

            sold_date = st.date_input(
                "Auszugs-/Verkaufsdatum",
                value=edit_prop.sold_date.date() if edit_prop and edit_prop.sold_date else None
            )

        notes = st.text_area(
            "Notizen",
            value=edit_prop.notes if edit_prop else "",
            placeholder="Zusätzliche Informationen zur Immobilie...",
            height=100
        )

        submit_label = "💾 Änderungen speichern" if edit_mode else "➕ Immobilie hinzufügen"
        submitted = st.form_submit_button(submit_label, type="primary", use_container_width=True)

        if submitted:
            if not name or not street or not postal_code or not city:
                st.error("Bitte füllen Sie alle Pflichtfelder (*) aus.")
            else:
                with get_db() as session:
                    if edit_mode:
                        # Bestehende Immobilie aktualisieren
                        prop = session.get(Property, st.session_state.edit_property_id)
                        if prop:
                            prop.name = name
                            prop.street = street
                            prop.house_number = house_number
                            prop.postal_code = postal_code
                            prop.city = city
                            prop.property_type = property_type
                            prop.usage = usage
                            prop.owner = owner
                            prop.management = management
                            prop.acquired_date = datetime.combine(acquired_date, datetime.min.time()) if acquired_date else None
                            prop.sold_date = datetime.combine(sold_date, datetime.min.time()) if sold_date else None
                            prop.notes = notes
                            session.commit()
                            st.success(f"✅ Immobilie '{name}' wurde aktualisiert!")
                            del st.session_state.edit_property_id
                            st.rerun()
                    else:
                        # Neue Immobilie erstellen
                        new_prop = Property(
                            user_id=user_id,
                            name=name,
                            street=street,
                            house_number=house_number,
                            postal_code=postal_code,
                            city=city,
                            property_type=property_type,
                            usage=usage,
                            owner=owner,
                            management=management,
                            acquired_date=datetime.combine(acquired_date, datetime.min.time()) if acquired_date else None,
                            sold_date=datetime.combine(sold_date, datetime.min.time()) if sold_date else None,
                            notes=notes
                        )
                        session.add(new_prop)
                        session.commit()
                        st.success(f"✅ Immobilie '{name}' wurde hinzugefügt!")

                        # Ordner für Immobilie erstellen
                        immobilien_folder = session.query(Folder).filter(
                            Folder.user_id == user_id,
                            Folder.name == "Immobilien"
                        ).first()

                        if not immobilien_folder:
                            immobilien_folder = Folder(
                                user_id=user_id,
                                name="Immobilien",
                                color="#795548",
                                icon="🏘️"
                            )
                            session.add(immobilien_folder)
                            session.flush()

                        # Unterordner für diese Immobilie
                        prop_folder = Folder(
                            user_id=user_id,
                            name=name,
                            parent_id=immobilien_folder.id,
                            color="#A1887F"
                        )
                        session.add(prop_folder)
                        session.commit()
                        st.info(f"📁 Ordner 'Immobilien/{name}' wurde erstellt.")

                        st.rerun()


with tab_docs:
    st.subheader("Dokumente nach Immobilie")

    with get_db() as session:
        properties = session.query(Property).filter(
            Property.user_id == user_id
        ).order_by(Property.name).all()

        if properties:
            # Immobilie auswählen
            prop_options = {0: "-- Alle Immobilien --"}
            prop_options.update({p.id: f"🏠 {p.name or p.full_address}" for p in properties})

            selected_prop_id = st.selectbox(
                "Immobilie auswählen",
                options=list(prop_options.keys()),
                format_func=lambda x: prop_options.get(x, "")
            )

            # Dokumente laden
            query = session.query(Document).filter(
                Document.user_id == user_id,
                Document.property_id.isnot(None)
            )

            if selected_prop_id:
                query = query.filter(Document.property_id == selected_prop_id)

            documents = query.order_by(Document.document_date.desc()).limit(100).all()

            if documents:
                st.write(f"**{len(documents)} Dokumente** gefunden")

                for doc in documents:
                    col_doc, col_prop, col_date, col_cat = st.columns([3, 2, 1, 1])

                    with col_doc:
                        st.write(f"📄 {doc.title or doc.filename}")
                        if doc.sender:
                            st.caption(f"Von: {doc.sender}")

                    with col_prop:
                        if doc.property:
                            st.caption(f"🏠 {doc.property.name or doc.property.city}")
                        if doc.property_address:
                            st.caption(f"📍 {doc.property_address[:50]}...")

                    with col_date:
                        st.caption(format_date(doc.document_date))

                    with col_cat:
                        st.caption(doc.category or "—")

                    st.divider()
            else:
                st.info("Keine Dokumente mit Immobilien-Zuordnung gefunden.")
        else:
            st.info("Legen Sie zuerst Immobilien an, um Dokumente zuordnen zu können.")


# Lösch-Dialog
if st.session_state.get('delete_property_id'):
    with get_db() as session:
        prop = session.get(Property, st.session_state.delete_property_id)
        if prop:
            st.warning(f"⚠️ Möchten Sie die Immobilie **'{prop.name}'** wirklich löschen?")
            st.caption("Die zugeordneten Dokumente bleiben erhalten, verlieren aber ihre Immobilien-Zuordnung.")

            col_confirm, col_cancel = st.columns(2)

            with col_confirm:
                if st.button("🗑️ Ja, löschen", type="primary", use_container_width=True):
                    # Dokumente von Immobilie trennen
                    session.query(Document).filter(
                        Document.property_id == prop.id
                    ).update({Document.property_id: None})

                    # Immobilie löschen
                    session.delete(prop)
                    session.commit()
                    st.success("Immobilie wurde gelöscht.")
                    del st.session_state.delete_property_id
                    st.rerun()

            with col_cancel:
                if st.button("❌ Abbrechen", use_container_width=True):
                    del st.session_state.delete_property_id
                    st.rerun()
