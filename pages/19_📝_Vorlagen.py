"""
Vorlagen-System Seite
Erstellen und Verwenden von Dokumentenvorlagen
"""
import streamlit as st
from datetime import datetime

# Imports
try:
    from services.template_service import TemplateService
    TEMPLATE_AVAILABLE = True
except ImportError:
    TEMPLATE_AVAILABLE = False


def render_template_page():
    """Rendert die Vorlagen-Seite"""
    st.title("Dokumenten-Vorlagen")
    st.markdown("Erstellen Sie Briefe, Kündigungen und mehr mit Vorlagen")

    if not TEMPLATE_AVAILABLE:
        st.error("Vorlagen-Module nicht verfügbar.")
        return

    if "user" not in st.session_state or not st.session_state.user:
        st.warning("Bitte melden Sie sich an.")
        return

    user_id = st.session_state.user.get("id", 1)
    service = TemplateService(user_id)

    # Standard-Vorlagen initialisieren
    service.initialize_default_templates()

    # Tabs
    tab1, tab2, tab3 = st.tabs(["Vorlage verwenden", "Neue Vorlage", "Meine Vorlagen"])

    with tab1:
        render_use_template(service)

    with tab2:
        render_new_template(service)

    with tab3:
        render_my_templates(service)


def render_use_template(service: TemplateService):
    """Tab: Vorlage verwenden"""
    st.subheader("Dokument aus Vorlage erstellen")

    # Vorlagen abrufen
    templates = service.get_all_templates()

    if not templates:
        st.info("Keine Vorlagen verfügbar.")
        return

    # Kategorie-Filter
    categories = service.get_categories()
    selected_category = st.selectbox(
        "Kategorie",
        options=["Alle"] + categories,
        format_func=lambda x: get_category_name(x) if x != "Alle" else "Alle Kategorien"
    )

    if selected_category != "Alle":
        templates = [t for t in templates if t.category == selected_category]

    # Vorlage auswählen
    template_options = {f"{t.name} {'(System)' if t.is_system else ''}": t for t in templates}

    selected_name = st.selectbox("Vorlage auswählen", options=list(template_options.keys()))
    selected_template = template_options[selected_name]

    if selected_template:
        st.divider()

        if selected_template.description:
            st.info(selected_template.description)

        # Platzhalter-Formular
        st.subheader("Daten eingeben")

        values = {}
        placeholders = selected_template.placeholders or []

        col1, col2 = st.columns(2)

        for i, placeholder in enumerate(placeholders):
            with col1 if i % 2 == 0 else col2:
                key = placeholder["key"]
                label = placeholder["label"]
                input_type = placeholder.get("type", "text")

                if input_type == "text":
                    values[key] = st.text_input(label, key=f"ph_{key}")
                elif input_type == "textarea":
                    values[key] = st.text_area(label, key=f"ph_{key}")
                elif input_type == "date":
                    date_val = st.date_input(label, key=f"ph_{key}")
                    values[key] = date_val.strftime("%d.%m.%Y") if date_val else ""
                elif input_type == "number":
                    values[key] = st.number_input(label, key=f"ph_{key}", min_value=0.0, step=0.01)

        st.divider()

        # Vorschau und Download
        if st.button("Vorschau generieren", type="primary"):
            rendered = service.render_template(selected_template.id, values)

            st.subheader("Vorschau")
            st.text_area("Generiertes Dokument", value=rendered, height=400)

            # Download
            st.download_button(
                "Als Text herunterladen",
                data=rendered,
                file_name=f"{selected_template.name}_{datetime.now().strftime('%Y%m%d')}.txt",
                mime="text/plain"
            )


def render_new_template(service: TemplateService):
    """Tab: Neue Vorlage erstellen"""
    st.subheader("Neue Vorlage erstellen")

    st.markdown("""
    **Platzhalter verwenden:** Verwenden Sie `{{name}}` für Platzhalter, z.B. `{{absender_name}}`
    """)

    with st.form("new_template_form"):
        name = st.text_input("Name der Vorlage *", placeholder="z.B. Meine Kündigung")

        category = st.selectbox(
            "Kategorie",
            options=["letter", "contract", "invoice", "application", "other"],
            format_func=get_category_name
        )

        description = st.text_input("Beschreibung", placeholder="Wofür ist diese Vorlage?")

        content = st.text_area(
            "Vorlagen-Inhalt *",
            height=400,
            placeholder="""{{absender_name}}
{{absender_adresse}}

{{empfaenger_name}}
{{empfaenger_adresse}}

{{datum}}

Betreff: ...

Sehr geehrte Damen und Herren,

[Ihr Text hier]

Mit freundlichen Grüßen

{{absender_name}}"""
        )

        submitted = st.form_submit_button("Vorlage speichern", type="primary")

        if submitted:
            if not name or not content:
                st.error("Bitte füllen Sie alle Pflichtfelder aus.")
            else:
                template = service.create_template(
                    name=name,
                    content=content,
                    category=category,
                    description=description
                )

                st.success(f"Vorlage '{name}' erfolgreich gespeichert!")

                if template.placeholders:
                    st.info(f"Erkannte Platzhalter: {', '.join(p['key'] for p in template.placeholders)}")


def render_my_templates(service: TemplateService):
    """Tab: Eigene Vorlagen verwalten"""
    st.subheader("Meine Vorlagen")

    templates = service.get_all_templates()
    user_templates = [t for t in templates if not t.is_system]
    system_templates = [t for t in templates if t.is_system]

    # Eigene Vorlagen
    if user_templates:
        st.markdown("### Eigene Vorlagen")

        for template in user_templates:
            with st.expander(f"📝 {template.name}"):
                col1, col2 = st.columns([3, 1])

                with col1:
                    st.markdown(f"**Kategorie:** {get_category_name(template.category)}")
                    if template.description:
                        st.markdown(f"**Beschreibung:** {template.description}")
                    st.markdown(f"**Verwendet:** {template.times_used or 0}x")

                    if template.placeholders:
                        st.markdown("**Platzhalter:**")
                        for p in template.placeholders:
                            st.markdown(f"- `{{{{{p['key']}}}}}` ({p['label']})")

                with col2:
                    if st.button("Duplizieren", key=f"dup_{template.id}"):
                        service.duplicate_template(template.id)
                        st.success("Vorlage dupliziert!")
                        st.rerun()

                    if st.button("Löschen", key=f"del_{template.id}"):
                        if st.session_state.get(f"confirm_del_{template.id}"):
                            service.delete_template(template.id)
                            st.success("Gelöscht!")
                            st.rerun()
                        else:
                            st.session_state[f"confirm_del_{template.id}"] = True
                            st.warning("Erneut klicken zum Bestätigen")
                            st.rerun()

                # Inhalt anzeigen
                st.text_area("Inhalt", value=template.content, height=200, disabled=True)
    else:
        st.info("Sie haben noch keine eigenen Vorlagen erstellt.")

    # System-Vorlagen
    st.divider()
    st.markdown("### System-Vorlagen")
    st.caption("Diese Vorlagen können nicht bearbeitet werden, aber Sie können eine Kopie erstellen.")

    for template in system_templates:
        with st.expander(f"📄 {template.name}"):
            st.markdown(f"**Kategorie:** {get_category_name(template.category)}")

            if st.button("Als Kopie speichern", key=f"copy_{template.id}"):
                service.duplicate_template(template.id, f"{template.name} (Kopie)")
                st.success("Vorlage kopiert! Sie können sie nun unter 'Eigene Vorlagen' bearbeiten.")
                st.rerun()


def get_category_name(category: str) -> str:
    """Gibt deutschen Namen für Kategorie zurück"""
    names = {
        "letter": "Brief",
        "contract": "Vertrag",
        "invoice": "Rechnung",
        "application": "Antrag",
        "other": "Sonstige"
    }
    return names.get(category, category or "Sonstige")


# ==================== HAUPTFUNKTION ====================

if __name__ == "__main__":
    st.set_page_config(page_title="Vorlagen", page_icon="📝", layout="wide")
    render_template_page()
else:
    render_template_page()
