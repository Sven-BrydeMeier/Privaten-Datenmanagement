"""
Entitäten-Verwaltung: Personen, Fahrzeuge, Lieferanten etc.
"""
import streamlit as st
from datetime import datetime
import json

from database import get_db
from database.db import get_current_user_id
from database.models import Entity, EntityType, Folder, Document

st.set_page_config(page_title="Entitäten", page_icon="👥", layout="wide")

# Benutzer-ID abrufen
user_id = get_current_user_id()


def get_entities(entity_type: EntityType = None):
    """Lädt alle Entities des Benutzers als Dictionaries"""
    with get_db() as session:
        query = session.query(Entity).filter(
            Entity.user_id == user_id,
            Entity.is_active == True
        )
        if entity_type:
            query = query.filter(Entity.entity_type == entity_type)
        entities = query.order_by(Entity.name).all()

        # Daten extrahieren während Session noch offen ist
        return [{
            'id': e.id,
            'name': e.name,
            'display_name': e.display_name,
            'entity_type': e.entity_type,
            'aliases': e.aliases or [],
            'meta': e.meta or {},
            'document_count': e.document_count or 0,
            'folder_id': e.folder_id
        } for e in entities]


def get_folders():
    """Lädt alle Ordner des Benutzers als Dictionaries"""
    with get_db() as session:
        folders = session.query(Folder).filter(
            Folder.user_id == user_id
        ).order_by(Folder.name).all()

        # Daten extrahieren während Session noch offen ist
        return [{'id': f.id, 'name': f.name} for f in folders]


def create_entity(entity_type: EntityType, name: str, display_name: str = None,
                  aliases: list = None, meta: dict = None, folder_id: int = None):
    """Erstellt eine neue Entity"""
    with get_db() as session:
        entity = Entity(
            user_id=user_id,
            entity_type=entity_type,
            name=name,
            display_name=display_name,
            aliases=aliases or [],
            meta=meta or {},
            folder_id=folder_id
        )
        session.add(entity)
        session.commit()
        return entity.id


def update_entity(entity_id: int, **kwargs):
    """Aktualisiert eine Entity"""
    with get_db() as session:
        entity = session.get(Entity, entity_id)
        if entity and entity.user_id == user_id:
            for key, value in kwargs.items():
                if hasattr(entity, key):
                    setattr(entity, key, value)
            entity.updated_at = datetime.now()
            session.commit()


def delete_entity(entity_id: int):
    """Löscht eine Entity (soft delete)"""
    with get_db() as session:
        entity = session.get(Entity, entity_id)
        if entity and entity.user_id == user_id:
            entity.is_active = False
            session.commit()


def get_entity_documents(entity_id: int):
    """Gibt alle Dokumente zurück, die mit einer Entity verknüpft sind"""
    with get_db() as session:
        entity = session.get(Entity, entity_id)
        if entity:
            return list(entity.documents)
    return []


# Header
st.title("👥 Entitäten verwalten")
st.markdown("""
Verwalten Sie Ihre Entitäten für intelligente Dokumentenzuordnung.
Entitäten können Personen (z.B. Familienmitglieder), Fahrzeuge, Lieferanten oder Projekte sein.
""")

# Tabs für verschiedene Entity-Typen
tab_overview, tab_person, tab_vehicle, tab_supplier, tab_other = st.tabs([
    "📊 Übersicht", "👤 Personen", "🚗 Fahrzeuge", "🏢 Lieferanten", "📁 Sonstige"
])

with tab_overview:
    st.subheader("Alle Entitäten")

    entities = get_entities()

    if not entities:
        st.info("Noch keine Entitäten vorhanden. Erstellen Sie Ihre erste Entität in einem der Tabs.")
    else:
        # Statistik
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            person_count = len([e for e in entities if e['entity_type'] == EntityType.PERSON])
            st.metric("Personen", person_count)
        with col2:
            vehicle_count = len([e for e in entities if e['entity_type'] == EntityType.VEHICLE])
            st.metric("Fahrzeuge", vehicle_count)
        with col3:
            supplier_count = len([e for e in entities if e['entity_type'] == EntityType.SUPPLIER])
            st.metric("Lieferanten", supplier_count)
        with col4:
            total_docs = sum(e['document_count'] for e in entities)
            st.metric("Verknüpfte Dokumente", total_docs)

        st.divider()

        # Liste aller Entities
        for entity in entities:
            type_emoji = {
                EntityType.PERSON: "👤",
                EntityType.VEHICLE: "🚗",
                EntityType.SUPPLIER: "🏢",
                EntityType.ORGANIZATION: "🏛️",
                EntityType.PROJECT: "📁",
                EntityType.CONTRACT: "📑"
            }.get(entity['entity_type'], "📌")

            with st.expander(f"{type_emoji} {entity['display_name'] or entity['name']} ({entity['document_count']} Dokumente)"):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.write(f"**Typ:** {entity['entity_type'].value if entity['entity_type'] else 'Unbekannt'}")
                    if entity['aliases']:
                        st.write(f"**Aliase:** {', '.join(entity['aliases'])}")
                    if entity['meta']:
                        st.write("**Metadaten:**")
                        st.json(entity['meta'])
                with col2:
                    if st.button("🗑️ Löschen", key=f"del_{entity['id']}"):
                        delete_entity(entity['id'])
                        st.rerun()


with tab_person:
    st.subheader("👤 Personen verwalten")

    # Neue Person erstellen
    with st.expander("➕ Neue Person hinzufügen", expanded=False):
        with st.form("new_person"):
            name = st.text_input("Name*", placeholder="z.B. Max Mustermann")
            display_name = st.text_input("Anzeigename", placeholder="z.B. Max")
            aliases = st.text_input("Aliase (kommagetrennt)", placeholder="z.B. M. Mustermann, Maxi")

            col1, col2 = st.columns(2)
            with col1:
                birthday = st.date_input("Geburtstag", value=None)
            with col2:
                relation = st.selectbox("Beziehung",
                    ["", "Partner/in", "Kind", "Elternteil", "Geschwister", "Verwandte/r", "Freund/in", "Sonstige"])

            is_minor = st.checkbox("Minderjährig")

            # Ordner zuweisen
            folders = get_folders()
            folder_options = {f['name']: f['id'] for f in folders}
            folder_name = st.selectbox("Zugeordneter Ordner", ["(Kein Ordner)"] + list(folder_options.keys()))
            folder_id = folder_options.get(folder_name)

            if st.form_submit_button("Person erstellen"):
                if name:
                    alias_list = [a.strip() for a in aliases.split(",") if a.strip()] if aliases else []
                    meta = {
                        "birthday": birthday.isoformat() if birthday else None,
                        "relation": relation if relation else None,
                        "minor": is_minor
                    }
                    create_entity(EntityType.PERSON, name, display_name or None, alias_list, meta, folder_id)
                    st.success(f"Person '{name}' wurde erstellt!")
                    st.rerun()
                else:
                    st.error("Bitte geben Sie einen Namen ein.")

    # Bestehende Personen
    persons = get_entities(EntityType.PERSON)
    if persons:
        for person in persons:
            meta = person['meta']
            with st.container(border=True):
                col1, col2, col3 = st.columns([3, 2, 1])
                with col1:
                    st.write(f"**{person['display_name'] or person['name']}**")
                    if person['aliases']:
                        st.caption(f"Aliase: {', '.join(person['aliases'])}")
                with col2:
                    if meta.get('relation'):
                        st.write(f"🔗 {meta['relation']}")
                    if meta.get('birthday'):
                        st.write(f"🎂 {meta['birthday']}")
                with col3:
                    st.write(f"📄 {person['document_count']}")
    else:
        st.info("Noch keine Personen angelegt.")


with tab_vehicle:
    st.subheader("🚗 Fahrzeuge verwalten")

    # Neues Fahrzeug erstellen
    with st.expander("➕ Neues Fahrzeug hinzufügen", expanded=False):
        with st.form("new_vehicle"):
            name = st.text_input("Bezeichnung*", placeholder="z.B. Golf von Papa")

            col1, col2 = st.columns(2)
            with col1:
                brand = st.text_input("Marke", placeholder="z.B. Volkswagen")
                model = st.text_input("Modell", placeholder="z.B. Golf 8")
            with col2:
                plate = st.text_input("Kennzeichen", placeholder="z.B. B-AB 1234")
                vin = st.text_input("Fahrgestellnummer (VIN)", placeholder="Optional")

            col3, col4 = st.columns(2)
            with col3:
                year = st.number_input("Baujahr", min_value=1900, max_value=2030, value=2020)
            with col4:
                vehicle_type = st.selectbox("Fahrzeugtyp",
                    ["PKW", "Motorrad", "Transporter", "LKW", "Anhänger", "Sonstige"])

            # Person zuordnen (optional)
            persons = get_entities(EntityType.PERSON)
            person_options = {"(Keine Zuordnung)": None}
            person_options.update({p['name']: p['id'] for p in persons})
            owner_name = st.selectbox("Eigentümer/Halter", list(person_options.keys()))
            owner_id = person_options.get(owner_name)

            # Ordner zuweisen
            folders = get_folders()
            folder_options = {f['name']: f['id'] for f in folders}
            folder_name = st.selectbox("Zugeordneter Ordner", ["(Kein Ordner)"] + list(folder_options.keys()))
            folder_id = folder_options.get(folder_name)

            if st.form_submit_button("Fahrzeug erstellen"):
                if name:
                    meta = {
                        "brand": brand,
                        "model": model,
                        "plate": plate,
                        "vin": vin,
                        "year": year,
                        "vehicle_type": vehicle_type
                    }
                    # Kennzeichen als Alias für Erkennung
                    aliases = [plate] if plate else []
                    if brand and model:
                        aliases.append(f"{brand} {model}")

                    entity_id = create_entity(EntityType.VEHICLE, name, None, aliases, meta, folder_id)

                    # Parent-Entity setzen wenn Eigentümer gewählt
                    if owner_id:
                        update_entity(entity_id, parent_entity_id=owner_id)

                    st.success(f"Fahrzeug '{name}' wurde erstellt!")
                    st.rerun()
                else:
                    st.error("Bitte geben Sie eine Bezeichnung ein.")

    # Bestehende Fahrzeuge
    vehicles = get_entities(EntityType.VEHICLE)
    if vehicles:
        for vehicle in vehicles:
            meta = vehicle['meta']
            with st.container(border=True):
                col1, col2, col3 = st.columns([3, 2, 1])
                with col1:
                    st.write(f"**{vehicle['name']}**")
                    if meta.get('brand') and meta.get('model'):
                        st.caption(f"{meta['brand']} {meta['model']}")
                with col2:
                    if meta.get('plate'):
                        st.write(f"🚗 {meta['plate']}")
                    if meta.get('year'):
                        st.write(f"📅 {meta['year']}")
                with col3:
                    st.write(f"📄 {vehicle['document_count']}")
    else:
        st.info("Noch keine Fahrzeuge angelegt.")


with tab_supplier:
    st.subheader("🏢 Lieferanten & Dienstleister")

    # Neuen Lieferanten erstellen
    with st.expander("➕ Neuen Lieferanten hinzufügen", expanded=False):
        with st.form("new_supplier"):
            name = st.text_input("Firmenname*", placeholder="z.B. Elektro Müller GmbH")

            col1, col2 = st.columns(2)
            with col1:
                category = st.selectbox("Kategorie", [
                    "Handwerker", "Versicherung", "Bank", "Energieversorger",
                    "Telekommunikation", "Behörde", "Arzt/Gesundheit",
                    "Handel", "Online-Shop", "Sonstige"
                ])
            with col2:
                industry = st.text_input("Branche/Gewerk", placeholder="z.B. Elektrik")

            aliases = st.text_input("Alternative Namen/Schreibweisen",
                                   placeholder="z.B. E. Müller, Mueller Elektro")

            contact_email = st.text_input("E-Mail", placeholder="Optional")
            contact_phone = st.text_input("Telefon", placeholder="Optional")

            # Ordner zuweisen
            folders = get_folders()
            folder_options = {f['name']: f['id'] for f in folders}
            folder_name = st.selectbox("Zugeordneter Ordner", ["(Kein Ordner)"] + list(folder_options.keys()))
            folder_id = folder_options.get(folder_name)

            if st.form_submit_button("Lieferant erstellen"):
                if name:
                    meta = {
                        "category": category,
                        "industry": industry,
                        "email": contact_email,
                        "phone": contact_phone
                    }
                    alias_list = [a.strip() for a in aliases.split(",") if a.strip()] if aliases else []
                    create_entity(EntityType.SUPPLIER, name, None, alias_list, meta, folder_id)
                    st.success(f"Lieferant '{name}' wurde erstellt!")
                    st.rerun()
                else:
                    st.error("Bitte geben Sie einen Firmennamen ein.")

    # Bestehende Lieferanten
    suppliers = get_entities(EntityType.SUPPLIER)
    if suppliers:
        for supplier in suppliers:
            meta = supplier['meta']
            with st.container(border=True):
                col1, col2, col3 = st.columns([3, 2, 1])
                with col1:
                    st.write(f"**{supplier['name']}**")
                    if supplier['aliases']:
                        st.caption(f"Auch bekannt als: {', '.join(supplier['aliases'])}")
                with col2:
                    if meta.get('category'):
                        st.write(f"📁 {meta['category']}")
                    if meta.get('industry'):
                        st.write(f"🔧 {meta['industry']}")
                with col3:
                    st.write(f"📄 {supplier['document_count']}")
    else:
        st.info("Noch keine Lieferanten angelegt.")


with tab_other:
    st.subheader("📁 Sonstige Entitäten")

    st.markdown("""
    Hier können Sie weitere Entitäten wie Organisationen, Projekte oder Verträge anlegen.
    """)

    # Neue sonstige Entity erstellen
    with st.expander("➕ Neue Entität hinzufügen", expanded=False):
        with st.form("new_other"):
            entity_type_str = st.selectbox("Typ", [
                "Organisation/Verein", "Projekt", "Vertrag"
            ])
            entity_type_map = {
                "Organisation/Verein": EntityType.ORGANIZATION,
                "Projekt": EntityType.PROJECT,
                "Vertrag": EntityType.CONTRACT
            }

            name = st.text_input("Name*", placeholder="z.B. Sportverein XY")
            display_name = st.text_input("Anzeigename", placeholder="Optional")
            aliases = st.text_input("Aliase (kommagetrennt)", placeholder="Optional")
            notes = st.text_area("Notizen", placeholder="Optional")

            # Ordner zuweisen
            folders = get_folders()
            folder_options = {f['name']: f['id'] for f in folders}
            folder_name = st.selectbox("Zugeordneter Ordner", ["(Kein Ordner)"] + list(folder_options.keys()))
            folder_id = folder_options.get(folder_name)

            if st.form_submit_button("Entität erstellen"):
                if name:
                    meta = {"notes": notes} if notes else {}
                    alias_list = [a.strip() for a in aliases.split(",") if a.strip()] if aliases else []
                    create_entity(entity_type_map[entity_type_str], name, display_name or None, alias_list, meta, folder_id)
                    st.success(f"Entität '{name}' wurde erstellt!")
                    st.rerun()
                else:
                    st.error("Bitte geben Sie einen Namen ein.")

    # Bestehende sonstige Entities
    other_types = [EntityType.ORGANIZATION, EntityType.PROJECT, EntityType.CONTRACT]
    others = [e for e in get_entities() if e['entity_type'] in other_types]

    if others:
        for entity in others:
            type_emoji = {
                EntityType.ORGANIZATION: "🏛️",
                EntityType.PROJECT: "📁",
                EntityType.CONTRACT: "📑"
            }.get(entity['entity_type'], "📌")

            with st.container(border=True):
                col1, col2, col3 = st.columns([3, 2, 1])
                with col1:
                    st.write(f"**{type_emoji} {entity['display_name'] or entity['name']}**")
                    if entity['aliases']:
                        st.caption(f"Aliase: {', '.join(entity['aliases'])}")
                with col2:
                    st.write(f"Typ: {entity['entity_type'].value if entity['entity_type'] else 'Unbekannt'}")
                with col3:
                    st.write(f"📄 {entity['document_count']}")
    else:
        st.info("Noch keine sonstigen Entitäten angelegt.")


# Footer mit Hilfe
st.divider()
with st.expander("ℹ️ Wie funktioniert die Entity-Erkennung?"):
    st.markdown("""
    **Automatische Zuordnung:**
    - Beim Upload neuer Dokumente wird der Text nach Entitäten durchsucht
    - Namen, Aliase und spezifische Merkmale (z.B. Kennzeichen) werden erkannt
    - Erkannte Dokumente werden automatisch mit der Entität verknüpft

    **Aliase nutzen:**
    - Geben Sie verschiedene Schreibweisen an (z.B. "Max Mustermann", "M. Mustermann", "Max")
    - Bei Fahrzeugen wird das Kennzeichen automatisch als Alias verwendet

    **Ordner-Zuordnung:**
    - Weisen Sie einer Entität einen Ordner zu
    - Neue Dokumente zu dieser Entität werden automatisch dort abgelegt

    **Warum wurde dieses Dokument so eingeordnet?**
    - In der Dokumentenansicht können Sie die Klassifikationserklärung einsehen
    - Dort sehen Sie welche Keywords, Absender und Entitäten erkannt wurden
    """)
