import streamlit as st
import os
import tempfile
from pathlib import Path
import zipfile
from io import BytesIO
from datetime import datetime

# Import der Verarbeitungsmodule
from pdf_processor import PDFProcessor
from aktenzeichen_erkennung import AktenzeichenErkenner
from document_analyzer import DocumentAnalyzer
from excel_generator import ExcelGenerator
from storage import PersistentStorage

st.set_page_config(
    page_title="RHM Posteingangsverarbeitung",
    page_icon="📄",
    layout="wide"
)

st.title("📄 RHM | Automatisierter Posteingang")
st.markdown("---")

# Initialisiere Persistent Storage
if 'storage' not in st.session_state:
    st.session_state.storage = PersistentStorage()

storage = st.session_state.storage

# Lade gespeicherte API Keys beim ersten Laden
if 'api_keys' not in st.session_state:
    saved_keys = storage.load_api_keys()
    st.session_state.api_keys = {
        'openai': saved_keys.get('openai', ''),
        'claude': saved_keys.get('claude', ''),
        'gemini': saved_keys.get('gemini', '')
    }
if 'api_provider' not in st.session_state:
    st.session_state.api_provider = 'OpenAI (ChatGPT)'

# Sidebar für API-Konfiguration
st.sidebar.header("⚙️ Einstellungen")

# API-Anbieter-Auswahl
st.sidebar.subheader("🤖 KI-Anbieter")
api_provider = st.sidebar.selectbox(
    "Wählen Sie den KI-Dienst:",
    options=["OpenAI (ChatGPT)", "Claude (Anthropic)", "Gemini (Google)"],
    index=0,  # OpenAI als Standard
    help="Wählen Sie den KI-Dienst für die Dokumentenanalyse"
)
st.session_state.api_provider = api_provider

# API-Key Eingabe (mit persistenter Speicherung)
provider_key_map = {
    "OpenAI (ChatGPT)": "openai",
    "Claude (Anthropic)": "claude",
    "Gemini (Google)": "gemini"
}
current_provider_key = provider_key_map[api_provider]

# Zeige Status: Gespeicherter Key vorhanden?
has_saved_key = storage.has_api_key(current_provider_key)
if has_saved_key:
    timestamp = storage.get_api_key_timestamp(current_provider_key)
    if timestamp:
        # Convert ISO to German format
        from datetime import datetime
        dt = datetime.fromisoformat(timestamp)
        formatted = dt.strftime('%d.%m.%Y %H:%M')
        st.sidebar.success(f"💾 Gespeicherter {api_provider} Key gefunden\n\n*Zuletzt aktualisiert: {formatted}*")
    else:
        st.sidebar.success(f"💾 Gespeicherter {api_provider} Key gefunden")

# Zeige gespeicherten Key als Placeholder
stored_key = st.session_state.api_keys.get(current_provider_key, '')
api_key_input = st.sidebar.text_input(
    f"{api_provider} API Key" + (" (neu eingeben zum Ändern)" if has_saved_key else ""),
    value=stored_key,
    type="password",
    help=f"Neuer Key überschreibt gespeicherten Key",
    key=f"api_key_input_{current_provider_key}"
)

# Speichere Key in Session State und persistentem Storage
if api_key_input and api_key_input != stored_key:
    st.session_state.api_keys[current_provider_key] = api_key_input
    # Speichere persistent (verschlüsselt)
    storage.save_api_key(current_provider_key, api_key_input)
    st.sidebar.success("✅ API-Key gespeichert!")

# Lösch-Button für gespeicherten Key
if has_saved_key:
    if st.sidebar.button(f"🗑️ {api_provider} Key löschen", key=f"delete_{current_provider_key}"):
        storage.delete_api_key(current_provider_key)
        st.session_state.api_keys[current_provider_key] = ''
        st.rerun()

# Hole aktuellen Key
current_api_key = st.session_state.api_keys.get(current_provider_key, '')

# API-Key Verbindungstest
if current_api_key:
    try:
        if api_provider == "OpenAI (ChatGPT)":
            from openai import OpenAI
            test_client = OpenAI(api_key=current_api_key)
            test_client.models.list()
            st.sidebar.markdown("🟢 **Verbindung erfolgreich**")

        elif api_provider == "Claude (Anthropic)":
            import anthropic
            test_client = anthropic.Anthropic(api_key=current_api_key)
            # Test mit einfachem API-Aufruf
            test_client.models.list()
            st.sidebar.markdown("🟢 **Verbindung erfolgreich**")

        elif api_provider == "Gemini (Google)":
            import google.generativeai as genai
            genai.configure(api_key=current_api_key)
            # Test: Liste verfügbare Modelle
            list(genai.list_models())
            st.sidebar.markdown("🟢 **Verbindung erfolgreich**")

    except Exception as e:
        error_msg = str(e)
        if "authentication" in error_msg.lower() or "api key" in error_msg.lower() or "api_key" in error_msg.lower():
            st.sidebar.markdown("🔴 **Ungültiger API-Key**")
        else:
            st.sidebar.markdown(f"🟡 **Verbindungsfehler**: {error_msg[:100]}")
else:
    st.sidebar.markdown("⚪ **Kein API-Key eingegeben**")

st.sidebar.markdown("---")

# Dokumententrennung (fest: nur "Trennseite"-Text)
st.sidebar.subheader("📑 Dokumententrennung")
st.sidebar.info("Dokumente werden durch Seiten mit dem Text **'Trennseite'** getrennt.")

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

    # Zeige Status: Gespeichertes Register vorhanden?
    if storage.has_aktenregister():
        stats = storage.get_aktenregister_stats()
        # Format timestamp
        from datetime import datetime
        dt = datetime.fromtimestamp(stats['last_modified'])
        formatted = dt.strftime('%d.%m.%Y %H:%M')
        st.success(f"💾 Gespeichertes Register: {stats['count']} Akten\n\n*Zuletzt aktualisiert: {formatted}*")

        # Lösch-Button
        if st.button("🗑️ Gespeichertes Register löschen"):
            storage.delete_aktenregister()
            st.rerun()

    uploaded_excel = st.file_uploader(
        "Neues Aktenregister (wird mit vorhandenem gemergt)" if storage.has_aktenregister() else "aktenregister.xlsx",
        type=["xlsx"],
        help="Neue Daten werden mit gespeicherten Daten zusammengeführt",
        key="excel_uploader"
    )

st.markdown("---")

# Verarbeitungsbutton (Excel ist optional wenn gespeichert)
can_process = uploaded_pdf and current_api_key and (uploaded_excel or storage.has_aktenregister())
if st.button("🚀 Verarbeitung starten", type="primary", disabled=not can_process):
    if not current_api_key:
        st.error(f"❌ Bitte geben Sie Ihren {api_provider} API-Key ein!")
    elif not uploaded_pdf:
        st.error("❌ Bitte laden Sie eine PDF-Datei hoch!")
    else:
        # Temporäres Verzeichnis für die Verarbeitung
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Dateien speichern
            pdf_path = temp_path / "tagespost.pdf"
            excel_path = temp_path / "aktenregister.xlsx"

            with open(pdf_path, "wb") as f:
                f.write(uploaded_pdf.read())

            # Progress-Container
            progress_container = st.container()
            with progress_container:
                st.info("⏳ Verarbeitung läuft...")
                progress_bar = st.progress(0)
                status_text = st.empty()

                try:
                    # 1. Aktenregister vorbereiten
                    status_text.text("📊 Lade Aktenregister...")
                    progress_bar.progress(10)

                    if uploaded_excel:
                        # Neues Excel hochgeladen: Merge mit gespeichertem
                        import pandas as pd
                        new_df = pd.read_excel(BytesIO(uploaded_excel.read()), sheet_name='akten', header=1)

                        # Speichere und merge mit vorhandenem
                        merged_df = storage.save_aktenregister(new_df, merge=storage.has_aktenregister())
                        st.success(f"✅ Aktenregister aktualisiert: {len(merged_df)} Akten")

                        # Verwende gespeicherte Version
                        excel_path = storage.aktenregister_file
                    else:
                        # Verwende nur gespeichertes Register
                        excel_path = storage.aktenregister_file
                        df = storage.load_aktenregister()
                        st.info(f"📂 Verwende gespeichertes Register: {len(df)} Akten")

                    erkenner = AktenzeichenErkenner(excel_path)

                    # 2. PDF verarbeiten
                    status_text.text("📄 Analysiere PDF und trenne Dokumente...")
                    progress_bar.progress(20)

                    # Live-Logging-Container
                    log_container = st.empty()

                    processor = PDFProcessor(pdf_path, debug=True, trennmodus="Text 'Trennseite'", excel_path=excel_path)
                    dokumente, debug_info = processor.verarbeite_pdf()

                    st.success(f"✅ {len(dokumente)} Einzeldokumente erkannt")

                    # Zeige wichtige Statistiken
                    st.info(f"""
                    **Verarbeitungs-Statistik:**
                    - Erkannte Dokumente: {len(dokumente)}
                    - Trennblätter gefunden: {debug_info.count('TRENNBLATT')}
                    - Leerseiten übersprungen: {debug_info.count('LEERSEITE')}
                    """)

                    # Debug-Informationen anzeigen
                    with st.expander("🔍 Debug-Informationen zur PDF-Verarbeitung", expanded=True):
                        for info in debug_info:
                            st.text(info)

                    # 3. Dokumente analysieren mit KI
                    status_text.text(f"🤖 Analysiere Dokumente mit {api_provider}...")
                    progress_bar.progress(40)
                    analyzer = DocumentAnalyzer(current_api_key, api_provider=api_provider)

                    alle_daten = []
                    sachbearbeiter_stats = {"SQ": 0, "TS": 0, "M": 0, "FÜ": 0, "CV": 0, "nicht-zugeordnet": 0}

                    for i, doc in enumerate(dokumente):
                        status_text.text(f"🔍 Verarbeite Dokument {i+1}/{len(dokumente)}...")
                        progress_bar.progress(40 + int(40 * (i+1) / len(dokumente)))

                        # Aktenzeichen erkennen
                        akt_info = erkenner.erkenne_aktenzeichen(doc['text'])

                        # Sachbearbeiter aus Text erkennen (Anrede/Anschrift)
                        sb_aus_text = erkenner.erkenne_sachbearbeiter_aus_text(doc['text'])

                        # Dokumenteninhalt analysieren
                        analyse = analyzer.analysiere_dokument(doc['text'], akt_info)

                        # Sachbearbeiter zuordnen (mit Priorität für Text-Erkennung)
                        sb = erkenner.ermittle_sachbearbeiter(akt_info, analyse, sachbearbeiter_aus_text=sb_aus_text)
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
                            'sachbearbeiter_aus_text': sb_aus_text,  # Debug-Info speichern
                            'dateiname': dateiname
                        })

                        # Zeige Zuordnung mit Debug-Info
                        debug_text = f"  → {dateiname} → SB: {sb}"
                        if sb_aus_text:
                            debug_text += f" (aus Text erkannt: {sb_aus_text})"
                        elif akt_info.get('kuerzel'):
                            debug_text += f" (aus AZ: {akt_info.get('kuerzel')})"
                        elif 'register_data' in akt_info:
                            debug_text += " (aus Register)"
                        else:
                            debug_text += " (nicht zugeordnet)"
                        st.text(debug_text)

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

                    # Speichere Ergebnisse in Session State für persistente Download-Buttons
                    st.session_state.verarbeitung_ergebnisse = {
                        'zip_dateien': zip_dateien,
                        'gesamt_excel': gesamt_excel,
                        'sachbearbeiter_stats': sachbearbeiter_stats
                    }

                except Exception as e:
                    st.error(f"❌ Fehler bei der Verarbeitung: {str(e)}")
                    st.exception(e)

# Zeige Download-Buttons außerhalb des Processing-Blocks (persistent)
if 'verarbeitung_ergebnisse' in st.session_state:
    ergebnisse = st.session_state.verarbeitung_ergebnisse

    # Ergebnisse anzeigen
    st.markdown("---")
    st.success("🎉 Verarbeitung erfolgreich abgeschlossen!")

    # Statistik
    st.subheader("📊 Verteilung")
    cols = st.columns(6)
    for i, (sb, count) in enumerate(ergebnisse['sachbearbeiter_stats'].items()):
        if count > 0:
            cols[i].metric(sb, count)

    # Downloads
    st.subheader("📥 Downloads")

    # ZIP-Dateien
    col_downloads = st.columns(3)
    col_idx = 0
    for sb, zip_bytes in ergebnisse['zip_dateien'].items():
        with col_downloads[col_idx % 3]:
            st.download_button(
                label=f"📦 {sb}.zip ({ergebnisse['sachbearbeiter_stats'][sb]} Dokumente)",
                data=zip_bytes,
                file_name=f"{sb}.zip",
                mime="application/zip",
                key=f"download_zip_{sb}"  # Eindeutiger Key
            )
            col_idx += 1

    # Gesamt-Excel
    st.download_button(
        label="📊 Gesamt-Excel: Fristen & Akten",
        data=ergebnisse['gesamt_excel'],
        file_name="Fristen_und_Akten_Gesamt.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="download_gesamt_excel"  # Eindeutiger Key
    )

    # Button zum Löschen der Ergebnisse
    if st.button("🗑️ Ergebnisse löschen und neu verarbeiten"):
        del st.session_state.verarbeitung_ergebnisse
        st.rerun()

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
