"""
Feldmarkierung - Interaktive Markierung von Feldern auf Dokumenten
Ermöglicht dem System zu lernen, wo Absender, Fristen und Beträge zu finden sind.
"""
import streamlit as st
from pathlib import Path
import sys
import io
from datetime import datetime
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.db import init_db, get_db, get_current_user_id
from database.models import Document, FieldAnnotation, LayoutTemplate, FieldType
from services.encryption import get_encryption_service
from services.ocr import get_ocr_service
from utils.helpers import format_date

st.set_page_config(page_title="Feldmarkierung", page_icon="🎯", layout="wide")
init_db()

user_id = get_current_user_id()

st.title("🎯 Feldmarkierung & Lernen")
st.markdown("""
Markieren Sie Felder auf Dokumenten, damit das System lernt, wo wichtige Informationen zu finden sind.
Das System merkt sich die Positionen und wendet sie auf ähnliche Dokumente an.
""")

# Feldtyp-Optionen mit Beschreibung
FIELD_TYPE_OPTIONS = {
    FieldType.SENDER: ("📤 Absender", "Name des Absenders/Unternehmens"),
    FieldType.SENDER_ADDRESS: ("📍 Absender-Adresse", "Vollständige Adresse des Absenders"),
    FieldType.DATE: ("📅 Datum", "Dokumentendatum"),
    FieldType.DUE_DATE: ("⏰ Frist/Fälligkeit", "Zahlungsfrist oder Fälligkeitsdatum"),
    FieldType.AMOUNT: ("💰 Betrag", "Rechnungsbetrag oder Summe"),
    FieldType.INVOICE_NUMBER: ("🔢 Rechnungsnummer", "Rechnungs- oder Belegnummer"),
    FieldType.CUSTOMER_NUMBER: ("👤 Kundennummer", "Ihre Kundennummer"),
    FieldType.REFERENCE: ("📋 Aktenzeichen", "Referenz- oder Aktenzeichen"),
    FieldType.IBAN: ("🏦 IBAN", "Bankverbindung IBAN"),
    FieldType.SUBJECT: ("📝 Betreff", "Betreffzeile"),
    FieldType.CONTRACT_NUMBER: ("📄 Vertragsnummer", "Vertrags- oder Policennummer"),
}


def load_document_image(document) -> Image.Image:
    """Lädt ein Dokument als Bild für die Annotation"""
    try:
        from utils.helpers import get_document_file_content, document_file_exists
        if not document.file_path or not document_file_exists(document.file_path):
            return None

        encryption = get_encryption_service()

        success, result = get_document_file_content(document.file_path, document.user_id)
        if not success:
            return None

        decrypted_data = encryption.decrypt_file(
            result,
            document.encryption_iv,
            document.filename
        )

        if document.filename.lower().endswith('.pdf'):
            # PDF zu Bild konvertieren
            try:
                from pdf2image import convert_from_bytes
                images = convert_from_bytes(decrypted_data, first_page=1, last_page=1, dpi=150)
                if images:
                    return images[0]
            except Exception as e:
                st.error(f"PDF-Konvertierung fehlgeschlagen: {e}")
                return None
        else:
            # Bild direkt laden
            return Image.open(io.BytesIO(decrypted_data))

    except Exception as e:
        st.error(f"Fehler beim Laden des Dokuments: {e}")
        return None


def extract_text_from_region(image: Image.Image, x_pct: float, y_pct: float,
                              w_pct: float, h_pct: float) -> str:
    """Extrahiert Text aus einem markierten Bereich per OCR"""
    try:
        # Pixelkoordinaten berechnen
        img_width, img_height = image.size
        x = int(x_pct * img_width)
        y = int(y_pct * img_height)
        w = int(w_pct * img_width)
        h = int(h_pct * img_height)

        # Bereich ausschneiden
        cropped = image.crop((x, y, x + w, y + h))

        # OCR durchführen
        ocr = get_ocr_service()
        text, confidence = ocr.extract_text_from_image(cropped)

        return text.strip()
    except Exception as e:
        st.warning(f"OCR-Fehler: {e}")
        return ""


def save_annotation(document_id: int, field_type: FieldType,
                   x_pct: float, y_pct: float, w_pct: float, h_pct: float,
                   extracted_text: str, confirmed_value: str = None):
    """Speichert eine Feldmarkierung"""
    with get_db() as session:
        annotation = FieldAnnotation(
            document_id=document_id,
            user_id=user_id,
            field_type=field_type,
            page_number=1,
            x_percent=x_pct,
            y_percent=y_pct,
            width_percent=w_pct,
            height_percent=h_pct,
            extracted_text=extracted_text,
            confirmed_value=confirmed_value or extracted_text,
            is_confirmed=True
        )
        session.add(annotation)
        session.commit()
        return annotation.id


def get_existing_annotations(document_id: int):
    """Lädt vorhandene Annotationen für ein Dokument"""
    with get_db() as session:
        annotations = session.query(FieldAnnotation).filter(
            FieldAnnotation.document_id == document_id,
            FieldAnnotation.user_id == user_id
        ).all()

        return [{
            'id': a.id,
            'field_type': a.field_type,
            'x': a.x_percent,
            'y': a.y_percent,
            'w': a.width_percent,
            'h': a.height_percent,
            'text': a.extracted_text,
            'value': a.confirmed_value
        } for a in annotations]


def create_layout_template(document_id: int, template_name: str, sender_pattern: str = None):
    """Erstellt ein Layout-Template aus den Annotationen eines Dokuments"""
    with get_db() as session:
        annotations = session.query(FieldAnnotation).filter(
            FieldAnnotation.document_id == document_id,
            FieldAnnotation.user_id == user_id,
            FieldAnnotation.is_confirmed == True
        ).all()

        if not annotations:
            return None

        # Feldpositionen sammeln
        field_positions = {}
        for ann in annotations:
            field_name = ann.field_type.value
            field_positions[field_name] = {
                'page': ann.page_number,
                'x': ann.x_percent,
                'y': ann.y_percent,
                'w': ann.width_percent,
                'h': ann.height_percent
            }

        template = LayoutTemplate(
            user_id=user_id,
            name=template_name,
            sender_pattern=sender_pattern,
            field_positions=field_positions,
            source_document_ids=[document_id],
            confidence=0.8
        )
        session.add(template)
        session.commit()
        return template.id


# Tabs
tab_annotate, tab_templates, tab_help = st.tabs([
    "✏️ Dokument markieren",
    "📚 Gelernte Templates",
    "❓ Hilfe"
])

with tab_annotate:
    # Dokument auswählen
    col_select, col_filter = st.columns([3, 1])

    with col_filter:
        show_only_missing = st.checkbox("Nur ohne Absender", value=True)

    with col_select:
        with get_db() as session:
            query = session.query(Document).filter(
                Document.user_id == user_id,
                Document.is_deleted == False
            )

            if show_only_missing:
                query = query.filter(
                    (Document.sender == None) | (Document.sender == "")
                )

            documents = query.order_by(Document.created_at.desc()).limit(50).all()

            doc_options = {
                d.id: f"{d.title or d.filename} ({format_date(d.document_date or d.created_at)})"
                for d in documents
            }

    if not doc_options:
        st.info("Keine Dokumente zum Markieren gefunden.")
    else:
        selected_doc_id = st.selectbox(
            "Dokument auswählen",
            options=list(doc_options.keys()),
            format_func=lambda x: doc_options.get(x, "Unbekannt")
        )

        if selected_doc_id:
            with get_db() as session:
                doc = session.get(Document, selected_doc_id)

                if doc:
                    st.markdown(f"**Datei:** {doc.filename}")
                    if doc.sender:
                        st.markdown(f"**Aktueller Absender:** {doc.sender}")

                    # Bild laden
                    image = load_document_image(doc)

                    if image:
                        st.markdown("---")
                        st.markdown("### Dokument-Vorschau")

                        col_image, col_tools = st.columns([2, 1])

                        with col_image:
                            # Canvas für Zeichnung
                            try:
                                from streamlit_drawable_canvas import st_canvas

                                # Bild skalieren für Canvas
                                max_width = 700
                                img_width, img_height = image.size
                                if img_width > max_width:
                                    scale = max_width / img_width
                                    new_height = int(img_height * scale)
                                    display_image = image.resize((max_width, new_height))
                                else:
                                    display_image = image
                                    scale = 1.0

                                canvas_result = st_canvas(
                                    fill_color="rgba(255, 165, 0, 0.3)",
                                    stroke_width=2,
                                    stroke_color="#FF6600",
                                    background_image=display_image,
                                    update_streamlit=True,
                                    height=display_image.size[1],
                                    width=display_image.size[0],
                                    drawing_mode="rect",
                                    key=f"canvas_{selected_doc_id}",
                                )

                            except ImportError:
                                st.warning("streamlit-drawable-canvas nicht installiert. Bitte installieren mit: pip install streamlit-drawable-canvas")
                                st.image(image, width="stretch")
                                canvas_result = None

                        with col_tools:
                            st.markdown("### Feldtyp wählen")

                            selected_field_type = st.selectbox(
                                "Zu markierendes Feld",
                                options=list(FIELD_TYPE_OPTIONS.keys()),
                                format_func=lambda x: FIELD_TYPE_OPTIONS[x][0]
                            )

                            st.caption(FIELD_TYPE_OPTIONS[selected_field_type][1])

                            st.markdown("---")

                            # Vorhandene Annotationen anzeigen
                            existing = get_existing_annotations(selected_doc_id)
                            if existing:
                                st.markdown("### Vorhandene Markierungen")
                                for ann in existing:
                                    field_name = FIELD_TYPE_OPTIONS.get(
                                        ann['field_type'],
                                        (ann['field_type'].value, "")
                                    )[0]
                                    st.markdown(f"**{field_name}:** {ann['value'][:30]}...")

                            st.markdown("---")

                            # Canvas-Ergebnis verarbeiten
                            if canvas_result is not None and canvas_result.json_data is not None:
                                objects = canvas_result.json_data.get("objects", [])

                                if objects:
                                    # Letztes Rechteck nehmen
                                    last_rect = objects[-1]

                                    if last_rect.get("type") == "rect":
                                        # Koordinaten extrahieren
                                        left = last_rect.get("left", 0)
                                        top = last_rect.get("top", 0)
                                        width = last_rect.get("width", 0)
                                        height = last_rect.get("height", 0)

                                        # Skalierung berücksichtigen
                                        canvas_w, canvas_h = display_image.size
                                        orig_w, orig_h = image.size

                                        # Prozentuale Koordinaten berechnen
                                        x_pct = left / canvas_w
                                        y_pct = top / canvas_h
                                        w_pct = width / canvas_w
                                        h_pct = height / canvas_h

                                        st.markdown("### Markierter Bereich")
                                        st.caption(f"Position: {x_pct:.1%} x {y_pct:.1%}, Größe: {w_pct:.1%} x {h_pct:.1%}")

                                        # OCR für markierten Bereich
                                        if st.button("🔍 Text extrahieren"):
                                            extracted = extract_text_from_region(
                                                image, x_pct, y_pct, w_pct, h_pct
                                            )
                                            st.session_state.extracted_text = extracted

                                        if 'extracted_text' in st.session_state:
                                            st.text_area(
                                                "Extrahierter Text",
                                                value=st.session_state.extracted_text,
                                                height=100,
                                                key="extracted_display"
                                            )

                                            confirmed = st.text_input(
                                                "Korrigierter Wert (optional)",
                                                value=st.session_state.extracted_text,
                                                key="confirmed_value"
                                            )

                                            if st.button("💾 Markierung speichern", type="primary"):
                                                ann_id = save_annotation(
                                                    selected_doc_id,
                                                    selected_field_type,
                                                    x_pct, y_pct, w_pct, h_pct,
                                                    st.session_state.extracted_text,
                                                    confirmed
                                                )

                                                # Auch das Dokument aktualisieren
                                                with get_db() as session:
                                                    doc = session.get(Document, selected_doc_id)
                                                    if doc:
                                                        if selected_field_type == FieldType.SENDER:
                                                            doc.sender = confirmed
                                                        elif selected_field_type == FieldType.DATE:
                                                            # Datum parsen (vereinfacht)
                                                            pass
                                                        elif selected_field_type == FieldType.AMOUNT:
                                                            try:
                                                                # Betrag parsen
                                                                amount_str = confirmed.replace("€", "").replace(",", ".").strip()
                                                                doc.invoice_amount = float(amount_str)
                                                            except:
                                                                pass
                                                        elif selected_field_type == FieldType.DUE_DATE:
                                                            # Frist parsen
                                                            pass
                                                        elif selected_field_type == FieldType.IBAN:
                                                            doc.iban = confirmed.replace(" ", "")
                                                        elif selected_field_type == FieldType.CUSTOMER_NUMBER:
                                                            doc.customer_number = confirmed
                                                        elif selected_field_type == FieldType.INVOICE_NUMBER:
                                                            doc.invoice_number = confirmed
                                                        elif selected_field_type == FieldType.REFERENCE:
                                                            doc.reference_number = confirmed

                                                        session.commit()

                                                st.success(f"Markierung gespeichert! (ID: {ann_id})")
                                                del st.session_state.extracted_text
                                                st.rerun()

                        # Template erstellen
                        st.markdown("---")
                        st.markdown("### Layout-Template erstellen")
                        st.caption("Erstellen Sie ein Template, damit ähnliche Dokumente automatisch erkannt werden.")

                        col_t1, col_t2 = st.columns(2)
                        with col_t1:
                            template_name = st.text_input(
                                "Template-Name",
                                value=doc.sender or doc.filename[:30],
                                key="template_name"
                            )
                        with col_t2:
                            sender_pattern = st.text_input(
                                "Absender-Muster (für Erkennung)",
                                value=doc.sender or "",
                                key="sender_pattern"
                            )

                        if st.button("📚 Template erstellen"):
                            existing_ann = get_existing_annotations(selected_doc_id)
                            if existing_ann:
                                template_id = create_layout_template(
                                    selected_doc_id,
                                    template_name,
                                    sender_pattern
                                )
                                if template_id:
                                    st.success(f"Template '{template_name}' erstellt!")
                                else:
                                    st.error("Fehler beim Erstellen des Templates")
                            else:
                                st.warning("Keine Markierungen vorhanden. Markieren Sie zuerst Felder.")

                    else:
                        st.error("Dokument konnte nicht als Bild geladen werden.")


with tab_templates:
    st.markdown("### Gelernte Layout-Templates")

    with get_db() as session:
        templates = session.query(LayoutTemplate).filter(
            LayoutTemplate.user_id == user_id,
            LayoutTemplate.is_active == True
        ).order_by(LayoutTemplate.times_used.desc()).all()

        if templates:
            for template in templates:
                with st.expander(f"📄 {template.name} (Vertrauen: {template.confidence:.0%})"):
                    col1, col2 = st.columns([2, 1])

                    with col1:
                        st.markdown(f"**Absender-Muster:** {template.sender_pattern or 'Nicht definiert'}")
                        st.markdown(f"**Verwendungen:** {template.times_used}")
                        st.markdown(f"**Korrekturen:** {template.times_corrected}")

                        st.markdown("**Gelernte Felder:**")
                        for field_name, pos in (template.field_positions or {}).items():
                            field_label = FIELD_TYPE_OPTIONS.get(
                                FieldType(field_name),
                                (field_name, "")
                            )[0]
                            st.caption(f"  • {field_label}: Seite {pos.get('page', 1)}, Position ({pos.get('x', 0):.1%}, {pos.get('y', 0):.1%})")

                    with col2:
                        if st.button("🗑️ Löschen", key=f"del_template_{template.id}"):
                            template.is_active = False
                            session.commit()
                            st.rerun()
        else:
            st.info("Noch keine Templates erstellt. Markieren Sie Felder auf Dokumenten, um Templates zu erstellen.")


with tab_help:
    st.markdown("""
    ### So funktioniert die Feldmarkierung

    1. **Dokument auswählen**: Wählen Sie ein Dokument aus, bei dem der Absender oder andere Felder nicht erkannt wurden.

    2. **Bereich markieren**: Zeichnen Sie mit der Maus ein Rechteck um den Bereich, der das gewünschte Feld enthält.

    3. **Feldtyp wählen**: Wählen Sie aus, welche Art von Information sich in diesem Bereich befindet (z.B. Absender, Betrag, Frist).

    4. **Text extrahieren**: Klicken Sie auf "Text extrahieren", um den Text per OCR zu lesen.

    5. **Korrigieren & Speichern**: Korrigieren Sie ggf. den erkannten Text und speichern Sie die Markierung.

    6. **Template erstellen**: Wenn Sie mehrere Felder markiert haben, erstellen Sie ein Template, damit ähnliche Dokumente automatisch erkannt werden.

    ---

    ### Tipps

    - **Präzise markieren**: Je genauer Sie den Bereich markieren, desto besser lernt das System.

    - **Absender-Muster**: Geben Sie ein eindeutiges Wort oder den Firmennamen als Absender-Muster ein, damit das Template für alle Dokumente dieses Absenders gilt.

    - **Mehrere Dokumente**: Markieren Sie Felder auf mehreren Dokumenten desselben Absenders, um die Erkennung zu verbessern.

    ---

    ### Unterstützte Feldtypen

    """)

    for field_type, (label, desc) in FIELD_TYPE_OPTIONS.items():
        st.markdown(f"- **{label}**: {desc}")
