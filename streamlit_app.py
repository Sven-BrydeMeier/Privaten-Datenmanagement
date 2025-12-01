import streamlit as st
import os
import tempfile
from pathlib import Path
import zipfile
from io import BytesIO

# Import der Verarbeitungsmodule
from pdf_processor import PDFProcessor
from aktenzeichen_erkennung import AktenzeichenErkenner
from document_analyzer import DocumentAnalyzer
from excel_generator import ExcelGenerator

st.set_page_config(
    page_title="RHM Posteingangsverarbeitung",
    page_icon="📄",
    layout="wide"
)

st.title("📄 RHM | Automatisierter Posteingang")
st.markdown("---")

# Sidebar für API-Key
st.sidebar.header("⚙️ Einstellungen")
openai_api_key = st.sidebar.text_input(
    "OpenAI API Key",
    type="password",
    help="Ihr OpenAI API-Schlüssel für die Dokumentenanalyse"
)

st.sidebar.markdown("---")
st.sidebar.info("""
**Sachbearbeiter:**
- SQ: Rechtsanwalt und Notar Sven-Bryde Meier
- TS: Rechtsanwältin Tamara Meyer
- M/MQ: Rechtsanwältin Ann-Kathrin Marquardsen
- FÜ: Rechtsanwalt Dr. Fürsen
- CV: Rechtsanwalt Christian Ostertun
""")

# Haupt-Upload-Bereich
col1, col2 = st.columns(2)

with col1:
    st.subheader("📄 Tagespost-PDF hochladen")
    uploaded_pdf = st.file_uploader(
        "PDF-Datei mit Tagespost (OCR)",
        type=["pdf"],
        help="Laden Sie die OCR-PDF-Datei mit der Tagespost hoch"
    )

with col2:
    st.subheader("📊 Aktenregister hochladen")
    uploaded_excel = st.file_uploader(
        "aktenregister.xlsx",
        type=["xlsx"],
        help="Laden Sie die Aktenregister-Datei hoch"
    )

st.markdown("---")

# Verarbeitungsbutton
if st.button("🚀 Verarbeitung starten", type="primary", disabled=not (uploaded_pdf and uploaded_excel and openai_api_key)):
    if not openai_api_key:
        st.error("❌ Bitte geben Sie Ihren OpenAI API-Key ein!")
    elif not uploaded_pdf:
        st.error("❌ Bitte laden Sie eine PDF-Datei hoch!")
    elif not uploaded_excel:
        st.error("❌ Bitte laden Sie die Aktenregister-Datei hoch!")
    else:
        # Temporäres Verzeichnis für die Verarbeitung
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Dateien speichern
            pdf_path = temp_path / "tagespost.pdf"
            excel_path = temp_path / "aktenregister.xlsx"

            with open(pdf_path, "wb") as f:
                f.write(uploaded_pdf.read())
            with open(excel_path, "wb") as f:
                f.write(uploaded_excel.read())

            # Progress-Container
            progress_container = st.container()
            with progress_container:
                st.info("⏳ Verarbeitung läuft...")
                progress_bar = st.progress(0)
                status_text = st.empty()

                try:
                    # 1. Aktenregister laden
                    status_text.text("📊 Lade Aktenregister...")
                    progress_bar.progress(10)
                    erkenner = AktenzeichenErkenner(excel_path)
                    st.success(f"✅ Aktenregister geladen ({len(erkenner.akten_register)} Akten)")

                    # 2. PDF verarbeiten
                    status_text.text("📄 Analysiere PDF und trenne Dokumente...")
                    progress_bar.progress(20)
                    processor = PDFProcessor(pdf_path, debug=True)
                    dokumente, debug_info = processor.verarbeite_pdf()
                    st.success(f"✅ {len(dokumente)} Einzeldokumente erkannt")

                    # Debug-Informationen anzeigen
                    with st.expander("🔍 Debug-Informationen zur PDF-Verarbeitung"):
                        for info in debug_info:
                            st.text(info)

                    # 3. Dokumente analysieren mit OpenAI
                    status_text.text("🤖 Analysiere Dokumente mit OpenAI...")
                    progress_bar.progress(40)
                    analyzer = DocumentAnalyzer(openai_api_key)

                    alle_daten = []
                    sachbearbeiter_stats = {"SQ": 0, "TS": 0, "M": 0, "FÜ": 0, "CV": 0, "nicht-zugeordnet": 0}

                    for i, doc in enumerate(dokumente):
                        status_text.text(f"🔍 Verarbeite Dokument {i+1}/{len(dokumente)}...")
                        progress_bar.progress(40 + int(40 * (i+1) / len(dokumente)))

                        # Aktenzeichen erkennen
                        akt_info = erkenner.erkenne_aktenzeichen(doc['text'])

                        # Dokumenteninhalt analysieren
                        analyse = analyzer.analysiere_dokument(doc['text'], akt_info)

                        # Sachbearbeiter zuordnen
                        sb = erkenner.ermittle_sachbearbeiter(akt_info, analyse)
                        sachbearbeiter_stats[sb] = sachbearbeiter_stats.get(sb, 0) + 1

                        # Dateiname generieren
                        dateiname = erkenner.generiere_dateiname(
                            akt_info.get('internes_az'),
                            analyse.get('mandant'),
                            analyse.get('gegner'),
                            analyse.get('datum'),
                            analyse.get('stichworte', [])
                        )

                        alle_daten.append({
                            'dokument': doc,
                            'aktenzeichen_info': akt_info,
                            'analyse': analyse,
                            'sachbearbeiter': sb,
                            'dateiname': dateiname
                        })

                        st.text(f"  → {dateiname} → SB: {sb}")

                    # 4. Excel-Dateien generieren
                    status_text.text("📊 Generiere Excel-Dateien...")
                    progress_bar.progress(85)
                    excel_gen = ExcelGenerator()
                    excel_dateien = excel_gen.erstelle_excel_dateien(alle_daten, temp_path)

                    # 5. ZIP-Dateien erstellen
                    status_text.text("📦 Erstelle ZIP-Dateien...")
                    progress_bar.progress(90)
                    zip_dateien = {}

                    for sb in ["SQ", "TS", "M", "FÜ", "CV", "nicht-zugeordnet"]:
                        if sachbearbeiter_stats.get(sb, 0) > 0:
                            zip_buffer = BytesIO()
                            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
                                # PDFs hinzufügen
                                for daten in alle_daten:
                                    if daten['sachbearbeiter'] == sb:
                                        pdf_content = daten['dokument']['pdf_bytes']
                                        zipf.writestr(daten['dateiname'], pdf_content)

                                # Excel hinzufügen
                                if sb in excel_dateien:
                                    excel_bytes = excel_dateien[sb]
                                    zipf.writestr(f"{sb}_Fristen.xlsx", excel_bytes)

                            zip_dateien[sb] = zip_buffer.getvalue()

                    # Gesamt-Excel
                    gesamt_excel = excel_gen.erstelle_gesamt_excel(alle_daten)

                    progress_bar.progress(100)
                    status_text.text("✅ Verarbeitung abgeschlossen!")

                    # Ergebnisse anzeigen
                    st.markdown("---")
                    st.success("🎉 Verarbeitung erfolgreich abgeschlossen!")

                    # Statistik
                    st.subheader("📊 Verteilung")
                    cols = st.columns(6)
                    for i, (sb, count) in enumerate(sachbearbeiter_stats.items()):
                        if count > 0:
                            cols[i].metric(sb, count)

                    # Downloads
                    st.subheader("📥 Downloads")

                    # ZIP-Dateien
                    col_downloads = st.columns(3)
                    col_idx = 0
                    for sb, zip_bytes in zip_dateien.items():
                        with col_downloads[col_idx % 3]:
                            st.download_button(
                                label=f"📦 {sb}.zip ({sachbearbeiter_stats[sb]} Dokumente)",
                                data=zip_bytes,
                                file_name=f"{sb}.zip",
                                mime="application/zip"
                            )
                            col_idx += 1

                    # Gesamt-Excel
                    st.download_button(
                        label="📊 Gesamt-Excel: Fristen & Akten",
                        data=gesamt_excel,
                        file_name="Fristen_und_Akten_Gesamt.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )

                except Exception as e:
                    st.error(f"❌ Fehler bei der Verarbeitung: {str(e)}")
                    st.exception(e)

# Info-Box
st.markdown("---")
with st.expander("ℹ️ Anleitung"):
    st.markdown("""
    ### So funktioniert die App:

    1. **OpenAI API Key eingeben** (links in der Sidebar)
    2. **Tagespost-PDF hochladen** (OCR-Version)
    3. **Aktenregister-Excel hochladen** (aktenregister.xlsx)
    4. **"Verarbeitung starten" klicken**
    5. **ZIP-Dateien herunterladen** (eine pro Sachbearbeiter)

    ### Die App erstellt:
    - ZIP-Dateien pro Sachbearbeiter (SQ, TS, M, FÜ, CV, nicht-zugeordnet)
    - Einzelne PDFs mit erkannten Aktenzeichen im Dateinamen
    - Excel-Dateien mit Fristen und Metadaten
    - Gesamt-Excel mit allen Dokumenten

    ### Aktenzeichen-Erkennung:
    - Interne Kanzlei-Aktenzeichen (z.B. 151/25M, 1179/24TS)
    - "Ihr Zeichen" / "Unser Zeichen" - Felder haben höchste Priorität
    - Externe Aktenzeichen (Gerichte, Versicherungen)
    - Automatische Zuordnung über Aktenregister
    """)
