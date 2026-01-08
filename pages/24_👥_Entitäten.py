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


def scan_documents_for_entity(entity_id: int) -> dict:
    """
    Durchsucht alle vorhandenen Dokumente nach Übereinstimmungen mit einer Entität.

    Returns:
        dict mit 'found': Anzahl gefundener Dokumente, 'linked': Anzahl neu verknüpfter
    """
    from sqlalchemy import and_
    from database.models import document_entities

    result = {'found': 0, 'linked': 0, 'documents': []}

    with get_db() as session:
        entity = session.get(Entity, entity_id)
        if not entity:
            return result

        # Suchbegriffe zusammenstellen: Name + Aliase + spezifische Meta-Werte
        search_terms = [entity.name.lower()]
        if entity.aliases:
            search_terms.extend([a.lower() for a in entity.aliases])

        # Meta-spezifische Suchbegriffe
        if entity.meta:
            # Kennzeichen bei Fahrzeugen
            if entity.meta.get('plate'):
                search_terms.append(entity.meta['plate'].lower())
            # Dokumentennummer bei Ausweisen
            if entity.meta.get('doc_number'):
                search_terms.append(entity.meta['doc_number'].lower())

        # Alle Dokumente des Benutzers laden
        documents = session.query(Document).filter(
            Document.user_id == user_id,
            Document.is_deleted == False
        ).all()

        for doc in documents:
            # Prüfe ob bereits verknüpft
            existing_link = session.execute(
                document_entities.select().where(
                    and_(
                        document_entities.c.document_id == doc.id,
                        document_entities.c.entity_id == entity_id
                    )
                )
            ).first()

            if existing_link:
                continue

            # Text zum Durchsuchen zusammenstellen
            searchable_text = ""
            if doc.ocr_text:
                searchable_text += doc.ocr_text.lower()
            if doc.ai_summary:
                searchable_text += " " + doc.ai_summary.lower()
            if doc.sender:
                searchable_text += " " + doc.sender.lower()
            if doc.original_filename:
                searchable_text += " " + doc.original_filename.lower()

            # Suche nach Übereinstimmungen
            matched = False
            for term in search_terms:
                if term and len(term) >= 3 and term in searchable_text:
                    matched = True
                    break

            if matched:
                result['found'] += 1
                result['documents'].append({
                    'id': doc.id,
                    'title': doc.title or doc.original_filename,
                    'date': doc.document_date
                })

                # Verknüpfung erstellen
                session.execute(
                    document_entities.insert().values(
                        document_id=doc.id,
                        entity_id=entity_id,
                        relation_type='auto_detected',
                        confidence=0.8
                    )
                )
                result['linked'] += 1

        # Entity-Statistik aktualisieren
        if result['linked'] > 0:
            entity.document_count = (entity.document_count or 0) + result['linked']
            session.commit()

    return result


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
Entitäten können Personen (z.B. Familienmitglieder), Fahrzeuge, Lieferanten, Ausweisdokumente oder Projekte sein.
""")

# Tabs für verschiedene Entity-Typen
tab_overview, tab_person, tab_vehicle, tab_id_doc, tab_supplier, tab_other = st.tabs([
    "📊 Übersicht", "👤 Personen", "🚗 Fahrzeuge", "🪪 Ausweise", "🏢 Lieferanten", "📁 Sonstige"
])

with tab_overview:
    st.subheader("Alle Entitäten")

    entities = get_entities()

    if not entities:
        st.info("Noch keine Entitäten vorhanden. Erstellen Sie Ihre erste Entität in einem der Tabs.")
    else:
        # Statistik
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            person_count = len([e for e in entities if e['entity_type'] == EntityType.PERSON])
            st.metric("Personen", person_count)
        with col2:
            vehicle_count = len([e for e in entities if e['entity_type'] == EntityType.VEHICLE])
            st.metric("Fahrzeuge", vehicle_count)
        with col3:
            id_doc_count = len([e for e in entities if e['entity_type'] == EntityType.ID_DOCUMENT])
            st.metric("Ausweise", id_doc_count)
        with col4:
            supplier_count = len([e for e in entities if e['entity_type'] == EntityType.SUPPLIER])
            st.metric("Lieferanten", supplier_count)
        with col5:
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
                EntityType.CONTRACT: "📑",
                EntityType.ID_DOCUMENT: "🪪"
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

            scan_after_create = st.checkbox("🔍 Nach Erstellung vorhandene Dokumente durchsuchen", value=True,
                help="Durchsucht alle vorhandenen Dokumente nach Übereinstimmungen mit dieser Person")

            if st.form_submit_button("Person erstellen"):
                if name:
                    alias_list = [a.strip() for a in aliases.split(",") if a.strip()] if aliases else []
                    meta = {
                        "birthday": birthday.isoformat() if birthday else None,
                        "relation": relation if relation else None,
                        "minor": is_minor
                    }
                    entity_id = create_entity(EntityType.PERSON, name, display_name or None, alias_list, meta, folder_id)
                    st.success(f"Person '{name}' wurde erstellt!")

                    if scan_after_create:
                        with st.spinner("Durchsuche vorhandene Dokumente..."):
                            scan_result = scan_documents_for_entity(entity_id)
                        if scan_result['linked'] > 0:
                            st.success(f"✅ {scan_result['linked']} passende Dokumente gefunden und verknüpft!")
                        else:
                            st.info("Keine passenden Dokumente in Ihrem Bestand gefunden.")
                    st.rerun()
                else:
                    st.error("Bitte geben Sie einen Namen ein.")

    # Bestehende Personen
    persons = get_entities(EntityType.PERSON)
    if persons:
        for person in persons:
            meta = person['meta']
            with st.container(border=True):
                col1, col2, col3, col4 = st.columns([3, 2, 1, 1])
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
                with col4:
                    col_edit, col_scan, col_del = st.columns(3)
                    with col_edit:
                        if st.button("✏️", key=f"edit_person_{person['id']}", help="Bearbeiten"):
                            st.session_state[f"editing_person_{person['id']}"] = True
                    with col_scan:
                        if st.button("🔍", key=f"scan_person_{person['id']}", help="Dokumente suchen"):
                            with st.spinner("Durchsuche Dokumente..."):
                                scan_result = scan_documents_for_entity(person['id'])
                            if scan_result['linked'] > 0:
                                st.success(f"✅ {scan_result['linked']} Dokumente verknüpft!")
                                st.rerun()
                            else:
                                st.info("Keine neuen passenden Dokumente gefunden.")
                    with col_del:
                        if st.button("🗑️", key=f"del_person_{person['id']}", help="Löschen"):
                            delete_entity(person['id'])
                            st.rerun()

                # Bearbeitungsformular
                if st.session_state.get(f"editing_person_{person['id']}"):
                    st.divider()
                    with st.form(f"edit_person_form_{person['id']}"):
                        edit_name = st.text_input("Name", value=person['name'])
                        edit_display_name = st.text_input("Anzeigename", value=person['display_name'] or "")
                        edit_aliases = st.text_input("Aliase (kommagetrennt)",
                            value=", ".join(person['aliases']) if person['aliases'] else "")

                        col_a, col_b = st.columns(2)
                        with col_a:
                            current_birthday = None
                            if meta.get('birthday'):
                                try:
                                    from datetime import date
                                    current_birthday = date.fromisoformat(meta['birthday'])
                                except:
                                    pass
                            edit_birthday = st.date_input("Geburtstag", value=current_birthday)
                        with col_b:
                            relation_options = ["", "Partner/in", "Kind", "Elternteil", "Geschwister", "Verwandte/r", "Freund/in", "Sonstige"]
                            current_relation = meta.get('relation', "")
                            rel_index = relation_options.index(current_relation) if current_relation in relation_options else 0
                            edit_relation = st.selectbox("Beziehung", relation_options, index=rel_index)

                        edit_minor = st.checkbox("Minderjährig", value=meta.get('minor', False))

                        folders = get_folders()
                        folder_options = {"(Kein Ordner)": None}
                        folder_options.update({f['name']: f['id'] for f in folders})
                        current_folder = next((f['name'] for f in folders if f['id'] == person['folder_id']), "(Kein Ordner)")
                        edit_folder = st.selectbox("Zugeordneter Ordner", list(folder_options.keys()),
                            index=list(folder_options.keys()).index(current_folder) if current_folder in folder_options else 0)

                        col_save, col_cancel = st.columns(2)
                        with col_save:
                            if st.form_submit_button("💾 Speichern", type="primary"):
                                new_aliases = [a.strip() for a in edit_aliases.split(",") if a.strip()]
                                new_meta = {
                                    "birthday": edit_birthday.isoformat() if edit_birthday else None,
                                    "relation": edit_relation if edit_relation else None,
                                    "minor": edit_minor
                                }
                                update_entity(
                                    person['id'],
                                    name=edit_name,
                                    display_name=edit_display_name or None,
                                    aliases=new_aliases,
                                    meta=new_meta,
                                    folder_id=folder_options.get(edit_folder)
                                )
                                del st.session_state[f"editing_person_{person['id']}"]
                                st.success("Person aktualisiert!")
                                st.rerun()
                        with col_cancel:
                            if st.form_submit_button("❌ Abbrechen"):
                                del st.session_state[f"editing_person_{person['id']}"]
                                st.rerun()
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

            scan_after_create = st.checkbox("🔍 Nach Erstellung vorhandene Dokumente durchsuchen", value=True,
                help="Durchsucht alle vorhandenen Dokumente nach Übereinstimmungen mit diesem Fahrzeug")

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

                    if scan_after_create:
                        with st.spinner("Durchsuche vorhandene Dokumente..."):
                            scan_result = scan_documents_for_entity(entity_id)
                        if scan_result['linked'] > 0:
                            st.success(f"✅ {scan_result['linked']} passende Dokumente gefunden und verknüpft!")
                        else:
                            st.info("Keine passenden Dokumente in Ihrem Bestand gefunden.")
                    st.rerun()
                else:
                    st.error("Bitte geben Sie eine Bezeichnung ein.")

    # Bestehende Fahrzeuge
    vehicles = get_entities(EntityType.VEHICLE)
    if vehicles:
        for vehicle in vehicles:
            meta = vehicle['meta']
            with st.container(border=True):
                col1, col2, col3, col4 = st.columns([3, 2, 1, 1])
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
                with col4:
                    col_edit, col_scan, col_del = st.columns(3)
                    with col_edit:
                        if st.button("✏️", key=f"edit_vehicle_{vehicle['id']}", help="Bearbeiten"):
                            st.session_state[f"editing_vehicle_{vehicle['id']}"] = True
                    with col_scan:
                        if st.button("🔍", key=f"scan_vehicle_{vehicle['id']}", help="Dokumente suchen"):
                            with st.spinner("Durchsuche Dokumente..."):
                                scan_result = scan_documents_for_entity(vehicle['id'])
                            if scan_result['linked'] > 0:
                                st.success(f"✅ {scan_result['linked']} Dokumente verknüpft!")
                                st.rerun()
                            else:
                                st.info("Keine neuen passenden Dokumente gefunden.")
                    with col_del:
                        if st.button("🗑️", key=f"del_vehicle_{vehicle['id']}", help="Löschen"):
                            delete_entity(vehicle['id'])
                            st.rerun()

                # Bearbeitungsformular
                if st.session_state.get(f"editing_vehicle_{vehicle['id']}"):
                    st.divider()
                    with st.form(f"edit_vehicle_form_{vehicle['id']}"):
                        edit_name = st.text_input("Bezeichnung", value=vehicle['name'])

                        col_a, col_b = st.columns(2)
                        with col_a:
                            edit_brand = st.text_input("Marke", value=meta.get('brand', ''))
                            edit_model = st.text_input("Modell", value=meta.get('model', ''))
                        with col_b:
                            edit_plate = st.text_input("Kennzeichen", value=meta.get('plate', ''))
                            edit_vin = st.text_input("Fahrgestellnummer", value=meta.get('vin', ''))

                        col_c, col_d = st.columns(2)
                        with col_c:
                            edit_year = st.number_input("Baujahr", min_value=1900, max_value=2030,
                                value=meta.get('year', 2020))
                        with col_d:
                            vehicle_types = ["PKW", "Motorrad", "Transporter", "LKW", "Anhänger", "Sonstige"]
                            current_type = meta.get('vehicle_type', 'PKW')
                            type_index = vehicle_types.index(current_type) if current_type in vehicle_types else 0
                            edit_type = st.selectbox("Fahrzeugtyp", vehicle_types, index=type_index)

                        folders = get_folders()
                        folder_options = {"(Kein Ordner)": None}
                        folder_options.update({f['name']: f['id'] for f in folders})
                        current_folder = next((f['name'] for f in folders if f['id'] == vehicle['folder_id']), "(Kein Ordner)")
                        edit_folder = st.selectbox("Zugeordneter Ordner", list(folder_options.keys()),
                            index=list(folder_options.keys()).index(current_folder) if current_folder in folder_options else 0)

                        col_save, col_cancel = st.columns(2)
                        with col_save:
                            if st.form_submit_button("💾 Speichern", type="primary"):
                                new_meta = {
                                    "brand": edit_brand,
                                    "model": edit_model,
                                    "plate": edit_plate,
                                    "vin": edit_vin,
                                    "year": edit_year,
                                    "vehicle_type": edit_type
                                }
                                # Aliase aktualisieren
                                new_aliases = [edit_plate] if edit_plate else []
                                if edit_brand and edit_model:
                                    new_aliases.append(f"{edit_brand} {edit_model}")

                                update_entity(
                                    vehicle['id'],
                                    name=edit_name,
                                    aliases=new_aliases,
                                    meta=new_meta,
                                    folder_id=folder_options.get(edit_folder)
                                )
                                del st.session_state[f"editing_vehicle_{vehicle['id']}"]
                                st.success("Fahrzeug aktualisiert!")
                                st.rerun()
                        with col_cancel:
                            if st.form_submit_button("❌ Abbrechen"):
                                del st.session_state[f"editing_vehicle_{vehicle['id']}"]
                                st.rerun()
    else:
        st.info("Noch keine Fahrzeuge angelegt.")


with tab_id_doc:
    st.subheader("🪪 Ausweisdokumente verwalten")

    st.markdown("""
    Erfassen Sie Personalausweise, Reisepässe, Führerscheine und andere Ausweisdokumente.
    Das System erkennt automatisch Ablaufdaten und erinnert Sie rechtzeitig.
    """)

    # Neues Ausweisdokument erstellen
    with st.expander("➕ Neues Ausweisdokument hinzufügen", expanded=False):
        with st.form("new_id_doc"):
            doc_type = st.selectbox("Dokumenttyp*", [
                "Personalausweis", "Reisepass", "Führerschein",
                "Aufenthaltstitel", "Kinderreisepass", "Sonstiges"
            ])

            col1, col2 = st.columns(2)
            with col1:
                doc_number = st.text_input("Dokumentennummer*", placeholder="z.B. T220001293")
                issue_date = st.date_input("Ausstellungsdatum", value=None)
            with col2:
                expiry_date = st.date_input("Gültig bis*", value=None)
                issuing_authority = st.text_input("Ausstellende Behörde", placeholder="z.B. Stadt Musterstadt")

            # Person zuordnen
            persons = get_entities(EntityType.PERSON)
            person_options = {"(Keine Zuordnung)": None}
            person_options.update({p['name']: p['id'] for p in persons})
            holder_name = st.selectbox("Inhaber (Person)*", list(person_options.keys()))
            holder_id = person_options.get(holder_name)

            # Ordner zuweisen
            folders = get_folders()
            folder_options = {f['name']: f['id'] for f in folders}
            folder_name = st.selectbox("Zugeordneter Ordner", ["(Kein Ordner)"] + list(folder_options.keys()))
            folder_id = folder_options.get(folder_name)

            # Erinnerung aktivieren
            remind_before_expiry = st.checkbox("Vor Ablauf erinnern", value=True)
            if remind_before_expiry:
                remind_days = st.number_input("Tage vor Ablauf", min_value=7, max_value=180, value=90)
            else:
                remind_days = 0

            notes = st.text_area("Notizen", placeholder="Optional")

            if st.form_submit_button("Ausweisdokument erstellen"):
                if doc_number and expiry_date:
                    # Anzeigename erstellen
                    display_name = f"{doc_type}"
                    if holder_name and holder_name != "(Keine Zuordnung)":
                        display_name = f"{doc_type} - {holder_name}"

                    meta = {
                        "doc_type": doc_type,
                        "doc_number": doc_number,
                        "issue_date": issue_date.isoformat() if issue_date else None,
                        "expiry_date": expiry_date.isoformat() if expiry_date else None,
                        "issuing_authority": issuing_authority,
                        "holder_id": holder_id,
                        "remind_before_expiry": remind_before_expiry,
                        "remind_days": remind_days,
                        "notes": notes
                    }

                    # Aliase für Dokumentenerkennung
                    aliases = [doc_number]
                    if doc_type == "Personalausweis":
                        aliases.append("PERSONALAUSWEIS")
                        aliases.append("Ausweis")
                    elif doc_type == "Reisepass":
                        aliases.append("REISEPASS")
                        aliases.append("Pass")
                    elif doc_type == "Führerschein":
                        aliases.append("FÜHRERSCHEIN")
                        aliases.append("Fahrerlaubnis")

                    entity_id = create_entity(
                        EntityType.ID_DOCUMENT,
                        f"{doc_type} {doc_number}",
                        display_name,
                        aliases,
                        meta,
                        folder_id
                    )

                    # Parent-Entity setzen wenn Inhaber gewählt
                    if holder_id:
                        update_entity(entity_id, parent_entity_id=holder_id)

                    # Kalendererinnerung erstellen wenn gewünscht
                    if remind_before_expiry and expiry_date:
                        from datetime import timedelta
                        from database.models import CalendarEvent, EventType
                        reminder_date = expiry_date - timedelta(days=remind_days)
                        with get_db() as session:
                            event = CalendarEvent(
                                user_id=user_id,
                                title=f"🪪 {doc_type} läuft ab",
                                description=f"Ihr {doc_type} (Nr. {doc_number}) läuft am {expiry_date.strftime('%d.%m.%Y')} ab. Bitte rechtzeitig verlängern!",
                                event_type=EventType.DEADLINE,
                                start_date=reminder_date,
                                all_day=True
                            )
                            session.add(event)
                            session.commit()
                        st.success(f"Ausweisdokument '{display_name}' wurde erstellt! Erinnerung am {reminder_date.strftime('%d.%m.%Y')} erstellt.")
                    else:
                        st.success(f"Ausweisdokument '{display_name}' wurde erstellt!")
                    st.rerun()
                else:
                    st.error("Bitte geben Sie mindestens Dokumentennummer und Ablaufdatum ein.")

    # Bestehende Ausweisdokumente
    id_docs = get_entities(EntityType.ID_DOCUMENT)
    if id_docs:
        # Warnung für bald ablaufende Dokumente
        from datetime import date, timedelta
        today = date.today()
        warning_threshold = today + timedelta(days=90)

        expiring_soon = []
        for doc in id_docs:
            meta = doc['meta']
            if meta.get('expiry_date'):
                try:
                    exp_date = date.fromisoformat(meta['expiry_date'])
                    if exp_date <= warning_threshold:
                        expiring_soon.append((doc, exp_date))
                except (ValueError, TypeError):
                    pass

        if expiring_soon:
            st.warning(f"⚠️ {len(expiring_soon)} Dokument(e) laufen in den nächsten 90 Tagen ab!")
            for doc, exp_date in sorted(expiring_soon, key=lambda x: x[1]):
                days_left = (exp_date - today).days
                if days_left < 0:
                    st.error(f"❌ **{doc['display_name'] or doc['name']}** - ABGELAUFEN seit {abs(days_left)} Tagen!")
                elif days_left == 0:
                    st.error(f"⏰ **{doc['display_name'] or doc['name']}** - Läuft HEUTE ab!")
                else:
                    st.warning(f"⏳ **{doc['display_name'] or doc['name']}** - Läuft in {days_left} Tagen ab ({exp_date.strftime('%d.%m.%Y')})")

        st.divider()

        for doc in id_docs:
            meta = doc['meta']
            with st.container(border=True):
                col1, col2, col3 = st.columns([3, 2, 1])
                with col1:
                    st.write(f"**🪪 {doc['display_name'] or doc['name']}**")
                    if meta.get('doc_number'):
                        st.caption(f"Nr.: {meta['doc_number']}")
                with col2:
                    if meta.get('expiry_date'):
                        try:
                            exp_date = date.fromisoformat(meta['expiry_date'])
                            days_left = (exp_date - today).days
                            if days_left < 0:
                                st.write(f"❌ Abgelaufen: {exp_date.strftime('%d.%m.%Y')}")
                            elif days_left <= 90:
                                st.write(f"⚠️ Gültig bis: {exp_date.strftime('%d.%m.%Y')}")
                            else:
                                st.write(f"✅ Gültig bis: {exp_date.strftime('%d.%m.%Y')}")
                        except (ValueError, TypeError):
                            pass
                    if meta.get('issuing_authority'):
                        st.caption(f"📍 {meta['issuing_authority']}")
                with col3:
                    st.write(f"📄 {doc['document_count']}")
                    if st.button("🗑️", key=f"del_id_{doc['id']}"):
                        delete_entity(doc['id'])
                        st.rerun()
    else:
        st.info("Noch keine Ausweisdokumente angelegt.")


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

            scan_after_create = st.checkbox("🔍 Nach Erstellung vorhandene Dokumente durchsuchen", value=True,
                help="Durchsucht alle vorhandenen Dokumente nach Übereinstimmungen mit diesem Lieferanten")

            if st.form_submit_button("Lieferant erstellen"):
                if name:
                    meta = {
                        "category": category,
                        "industry": industry,
                        "email": contact_email,
                        "phone": contact_phone
                    }
                    alias_list = [a.strip() for a in aliases.split(",") if a.strip()] if aliases else []
                    entity_id = create_entity(EntityType.SUPPLIER, name, None, alias_list, meta, folder_id)
                    st.success(f"Lieferant '{name}' wurde erstellt!")

                    if scan_after_create:
                        with st.spinner("Durchsuche vorhandene Dokumente..."):
                            scan_result = scan_documents_for_entity(entity_id)
                        if scan_result['linked'] > 0:
                            st.success(f"✅ {scan_result['linked']} passende Dokumente gefunden und verknüpft!")
                        else:
                            st.info("Keine passenden Dokumente in Ihrem Bestand gefunden.")
                    st.rerun()
                else:
                    st.error("Bitte geben Sie einen Firmennamen ein.")

    # Bestehende Lieferanten
    suppliers = get_entities(EntityType.SUPPLIER)
    if suppliers:
        for supplier in suppliers:
            meta = supplier['meta']
            with st.container(border=True):
                col1, col2, col3, col4 = st.columns([3, 2, 1, 1])
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
                with col4:
                    col_edit, col_scan, col_del = st.columns(3)
                    with col_edit:
                        if st.button("✏️", key=f"edit_supplier_{supplier['id']}", help="Bearbeiten"):
                            st.session_state[f"editing_supplier_{supplier['id']}"] = True
                    with col_scan:
                        if st.button("🔍", key=f"scan_supplier_{supplier['id']}", help="Dokumente suchen"):
                            with st.spinner("Durchsuche Dokumente..."):
                                scan_result = scan_documents_for_entity(supplier['id'])
                            if scan_result['linked'] > 0:
                                st.success(f"✅ {scan_result['linked']} Dokumente verknüpft!")
                                st.rerun()
                            else:
                                st.info("Keine neuen passenden Dokumente gefunden.")
                    with col_del:
                        if st.button("🗑️", key=f"del_supplier_{supplier['id']}", help="Löschen"):
                            delete_entity(supplier['id'])
                            st.rerun()

                # Bearbeitungsformular
                if st.session_state.get(f"editing_supplier_{supplier['id']}"):
                    st.divider()
                    with st.form(f"edit_supplier_form_{supplier['id']}"):
                        edit_name = st.text_input("Firmenname", value=supplier['name'])

                        col_a, col_b = st.columns(2)
                        with col_a:
                            categories = ["Handwerker", "Versicherung", "Bank", "Energieversorger",
                                "Telekommunikation", "Behörde", "Arzt/Gesundheit", "Handel", "Online-Shop", "Sonstige"]
                            current_cat = meta.get('category', 'Sonstige')
                            cat_index = categories.index(current_cat) if current_cat in categories else len(categories)-1
                            edit_category = st.selectbox("Kategorie", categories, index=cat_index)
                        with col_b:
                            edit_industry = st.text_input("Branche/Gewerk", value=meta.get('industry', ''))

                        edit_aliases = st.text_input("Alternative Namen",
                            value=", ".join(supplier['aliases']) if supplier['aliases'] else "")

                        col_c, col_d = st.columns(2)
                        with col_c:
                            edit_email = st.text_input("E-Mail", value=meta.get('email', ''))
                        with col_d:
                            edit_phone = st.text_input("Telefon", value=meta.get('phone', ''))

                        folders = get_folders()
                        folder_options = {"(Kein Ordner)": None}
                        folder_options.update({f['name']: f['id'] for f in folders})
                        current_folder = next((f['name'] for f in folders if f['id'] == supplier['folder_id']), "(Kein Ordner)")
                        edit_folder = st.selectbox("Zugeordneter Ordner", list(folder_options.keys()),
                            index=list(folder_options.keys()).index(current_folder) if current_folder in folder_options else 0)

                        col_save, col_cancel = st.columns(2)
                        with col_save:
                            if st.form_submit_button("💾 Speichern", type="primary"):
                                new_meta = {
                                    "category": edit_category,
                                    "industry": edit_industry,
                                    "email": edit_email,
                                    "phone": edit_phone
                                }
                                new_aliases = [a.strip() for a in edit_aliases.split(",") if a.strip()]
                                update_entity(
                                    supplier['id'],
                                    name=edit_name,
                                    aliases=new_aliases,
                                    meta=new_meta,
                                    folder_id=folder_options.get(edit_folder)
                                )
                                del st.session_state[f"editing_supplier_{supplier['id']}"]
                                st.success("Lieferant aktualisiert!")
                                st.rerun()
                        with col_cancel:
                            if st.form_submit_button("❌ Abbrechen"):
                                del st.session_state[f"editing_supplier_{supplier['id']}"]
                                st.rerun()
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

            scan_after_create = st.checkbox("🔍 Nach Erstellung vorhandene Dokumente durchsuchen", value=True,
                help="Durchsucht alle vorhandenen Dokumente nach Übereinstimmungen mit dieser Entität")

            if st.form_submit_button("Entität erstellen"):
                if name:
                    meta = {"notes": notes} if notes else {}
                    alias_list = [a.strip() for a in aliases.split(",") if a.strip()] if aliases else []
                    entity_id = create_entity(entity_type_map[entity_type_str], name, display_name or None, alias_list, meta, folder_id)
                    st.success(f"Entität '{name}' wurde erstellt!")

                    if scan_after_create:
                        with st.spinner("Durchsuche vorhandene Dokumente..."):
                            scan_result = scan_documents_for_entity(entity_id)
                        if scan_result['linked'] > 0:
                            st.success(f"✅ {scan_result['linked']} passende Dokumente gefunden und verknüpft!")
                        else:
                            st.info("Keine passenden Dokumente in Ihrem Bestand gefunden.")
                    st.rerun()
                else:
                    st.error("Bitte geben Sie einen Namen ein.")

    # Bestehende sonstige Entities
    other_types = [EntityType.ORGANIZATION, EntityType.PROJECT, EntityType.CONTRACT]
    others = [e for e in get_entities() if e['entity_type'] in other_types]

    if others:
        for entity in others:
            meta = entity['meta']
            type_emoji = {
                EntityType.ORGANIZATION: "🏛️",
                EntityType.PROJECT: "📁",
                EntityType.CONTRACT: "📑"
            }.get(entity['entity_type'], "📌")

            with st.container(border=True):
                col1, col2, col3, col4 = st.columns([3, 2, 1, 1])
                with col1:
                    st.write(f"**{type_emoji} {entity['display_name'] or entity['name']}**")
                    if entity['aliases']:
                        st.caption(f"Aliase: {', '.join(entity['aliases'])}")
                with col2:
                    st.write(f"Typ: {entity['entity_type'].value if entity['entity_type'] else 'Unbekannt'}")
                with col3:
                    st.write(f"📄 {entity['document_count']}")
                with col4:
                    col_edit, col_scan, col_del = st.columns(3)
                    with col_edit:
                        if st.button("✏️", key=f"edit_other_{entity['id']}", help="Bearbeiten"):
                            st.session_state[f"editing_other_{entity['id']}"] = True
                    with col_scan:
                        if st.button("🔍", key=f"scan_other_{entity['id']}", help="Dokumente suchen"):
                            with st.spinner("Durchsuche Dokumente..."):
                                scan_result = scan_documents_for_entity(entity['id'])
                            if scan_result['linked'] > 0:
                                st.success(f"✅ {scan_result['linked']} Dokumente verknüpft!")
                                st.rerun()
                            else:
                                st.info("Keine neuen passenden Dokumente gefunden.")
                    with col_del:
                        if st.button("🗑️", key=f"del_other_{entity['id']}", help="Löschen"):
                            delete_entity(entity['id'])
                            st.rerun()

                # Bearbeitungsformular
                if st.session_state.get(f"editing_other_{entity['id']}"):
                    st.divider()
                    with st.form(f"edit_other_form_{entity['id']}"):
                        type_options = ["Organisation/Verein", "Projekt", "Vertrag"]
                        type_map = {
                            EntityType.ORGANIZATION: "Organisation/Verein",
                            EntityType.PROJECT: "Projekt",
                            EntityType.CONTRACT: "Vertrag"
                        }
                        current_type_str = type_map.get(entity['entity_type'], "Organisation/Verein")
                        type_index = type_options.index(current_type_str) if current_type_str in type_options else 0
                        edit_type_str = st.selectbox("Typ", type_options, index=type_index)

                        edit_name = st.text_input("Name", value=entity['name'])
                        edit_display_name = st.text_input("Anzeigename", value=entity['display_name'] or "")
                        edit_aliases = st.text_input("Aliase (kommagetrennt)",
                            value=", ".join(entity['aliases']) if entity['aliases'] else "")
                        edit_notes = st.text_area("Notizen", value=meta.get('notes', ''))

                        folders = get_folders()
                        folder_options = {"(Kein Ordner)": None}
                        folder_options.update({f['name']: f['id'] for f in folders})
                        current_folder = next((f['name'] for f in folders if f['id'] == entity['folder_id']), "(Kein Ordner)")
                        edit_folder = st.selectbox("Zugeordneter Ordner", list(folder_options.keys()),
                            index=list(folder_options.keys()).index(current_folder) if current_folder in folder_options else 0)

                        col_save, col_cancel = st.columns(2)
                        with col_save:
                            if st.form_submit_button("💾 Speichern", type="primary"):
                                type_map_reverse = {
                                    "Organisation/Verein": EntityType.ORGANIZATION,
                                    "Projekt": EntityType.PROJECT,
                                    "Vertrag": EntityType.CONTRACT
                                }
                                new_meta = {"notes": edit_notes} if edit_notes else {}
                                new_aliases = [a.strip() for a in edit_aliases.split(",") if a.strip()]
                                update_entity(
                                    entity['id'],
                                    name=edit_name,
                                    display_name=edit_display_name or None,
                                    entity_type=type_map_reverse.get(edit_type_str),
                                    aliases=new_aliases,
                                    meta=new_meta,
                                    folder_id=folder_options.get(edit_folder)
                                )
                                del st.session_state[f"editing_other_{entity['id']}"]
                                st.success("Entität aktualisiert!")
                                st.rerun()
                        with col_cancel:
                            if st.form_submit_button("❌ Abbrechen"):
                                del st.session_state[f"editing_other_{entity['id']}"]
                                st.rerun()
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

    **Dokumente durchsuchen (🔍):**
    - Bei Erstellung einer neuen Entität werden automatisch alle vorhandenen Dokumente durchsucht
    - Mit dem 🔍 Button können Sie jederzeit nach passenden Dokumenten suchen
    - Gefundene Dokumente werden automatisch mit der Entität verknüpft

    **Entitäten bearbeiten (✏️):**
    - Klicken Sie auf ✏️ um eine Entität zu bearbeiten
    - Ändern Sie Name, Aliase, Metadaten und Ordnerzuordnung
    - Nach dem Speichern können Sie erneut nach Dokumenten suchen

    **Aliase nutzen:**
    - Geben Sie verschiedene Schreibweisen an (z.B. "Max Mustermann", "M. Mustermann", "Max")
    - Bei Fahrzeugen wird das Kennzeichen automatisch als Alias verwendet
    - Je mehr Aliase, desto besser die Dokumentenerkennung

    **Ordner-Zuordnung:**
    - Weisen Sie einer Entität einen Ordner zu
    - Neue Dokumente zu dieser Entität werden automatisch dort abgelegt

    **Warum wurde dieses Dokument so eingeordnet?**
    - In der Dokumentenansicht können Sie die Klassifikationserklärung einsehen
    - Dort sehen Sie welche Keywords, Absender und Entitäten erkannt wurden
    """)
