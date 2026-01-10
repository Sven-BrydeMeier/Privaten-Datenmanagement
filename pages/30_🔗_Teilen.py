"""
Öffentliche Seite für geteilte Dokumente
"""
import streamlit as st
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.db import init_db, get_db
from database.models import Document
from utils.helpers import verify_share_link, get_document_file_content
from services.encryption import get_encryption_service

st.set_page_config(page_title="Geteiltes Dokument", page_icon="🔗", layout="centered")
init_db()

st.title("🔗 Geteiltes Dokument")

# Token aus URL-Parameter lesen
token = st.query_params.get("token")

if not token:
    st.info("Kein Freigabe-Link angegeben.")
    st.markdown("""
    ### So funktioniert's:
    1. Öffnen Sie ein Dokument in Ihrem Archiv
    2. Klicken Sie auf **⋮ → Teilen**
    3. Kopieren Sie den generierten Link
    4. Teilen Sie den Link mit anderen

    Der Link ist 7 Tage gültig.
    """)
else:
    # Token verifizieren
    document_id = verify_share_link(token)

    if not document_id:
        st.error("❌ Dieser Link ist ungültig oder abgelaufen.")
        st.markdown("""
        **Mögliche Gründe:**
        - Der Link ist älter als 7 Tage
        - Der Link wurde bereits widerrufen
        - Der Link wurde falsch kopiert

        Bitte fordern Sie einen neuen Link an.
        """)
    else:
        # Dokument laden
        with get_db() as session:
            doc = session.get(Document, document_id)

            if not doc:
                st.error("❌ Dokument nicht gefunden.")
            else:
                # Dokument-Info anzeigen
                st.success("✅ Link gültig")

                st.markdown(f"### 📄 {doc.title or doc.filename}")

                col1, col2 = st.columns(2)
                with col1:
                    if doc.sender:
                        st.markdown(f"**Absender:** {doc.sender}")
                    if doc.category:
                        st.markdown(f"**Kategorie:** {doc.category}")
                with col2:
                    if doc.document_date:
                        st.markdown(f"**Datum:** {doc.document_date.strftime('%d.%m.%Y')}")
                    if doc.invoice_amount:
                        st.markdown(f"**Betrag:** {doc.invoice_amount:.2f} €")

                st.markdown("---")

                # Datei laden und Download anbieten
                if doc.file_path:
                    success, file_result = get_document_file_content(doc.file_path, doc.user_id)

                    if success:
                        # Entschlüsseln wenn nötig
                        if doc.is_encrypted and doc.encryption_iv:
                            encryption = get_encryption_service()
                            try:
                                file_data = encryption.decrypt_file(file_result, doc.encryption_iv, doc.filename)
                            except:
                                file_data = file_result
                        else:
                            file_data = file_result

                        # Download-Button
                        st.download_button(
                            "⬇️ Dokument herunterladen",
                            data=file_data,
                            file_name=doc.filename,
                            mime=doc.mime_type or "application/octet-stream",
                            type="primary",
                            use_container_width=True
                        )

                        # Vorschau für PDFs und Bilder
                        st.markdown("### 👁️ Vorschau")

                        mime_type = doc.mime_type or ""
                        if mime_type == "application/pdf":
                            import base64
                            b64_pdf = base64.b64encode(file_data).decode('utf-8')
                            pdf_display = f'''
                            <iframe src="data:application/pdf;base64,{b64_pdf}"
                                    width="100%" height="600px" type="application/pdf">
                            </iframe>
                            '''
                            st.markdown(pdf_display, unsafe_allow_html=True)
                        elif mime_type.startswith("image/"):
                            from PIL import Image
                            import io
                            img = Image.open(io.BytesIO(file_data))
                            st.image(img, use_container_width=True)
                        else:
                            st.info(f"Vorschau für {mime_type or 'dieses Format'} nicht verfügbar. Bitte herunterladen.")
                    else:
                        st.error(f"Fehler beim Laden: {file_result}")
                else:
                    st.warning("Keine Datei verfügbar.")

# Footer
st.markdown("---")
st.caption("🔒 Dieser Link gewährt temporären Lesezugriff auf das Dokument.")
