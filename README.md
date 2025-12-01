# 📄 RHM Posteingangsverarbeitung

Automatisierte Verarbeitung von Tagespost für Anwaltskanzleien mit intelligenter Dokumentenerkennung und -zuordnung.

## 🚀 Features

- **Automatische Dokumententrennung**: Erkennt Trennblätter (T-Seiten) und segmentiert PDFs
- **Intelligente Aktenzeichen-Erkennung**:
  - Interne Kanzlei-Aktenzeichen (z.B. 151/25M, 1179/24TS)
  - Priorisierung von "Ihr Zeichen" / "Unser Zeichen" Feldern
  - Externe Aktenzeichen (Gerichte, Versicherungen)
  - Automatischer Abgleich mit Aktenregister
- **KI-gestützte Dokumentenanalyse**: Extraktion von Mandant, Gegner, Fristen, Stichworte
- **Sachbearbeiter-Zuordnung**: Automatische Zuordnung zu SQ, TS, M, FÜ, CV
- **Excel-Reports**: Fristenverwaltung mit farblicher Markierung
- **ZIP-Archivierung**: Separate ZIP-Dateien pro Sachbearbeiter

## 📋 Voraussetzungen

- Python 3.8+
- OpenAI API Key
- Aktenregister-Datei (`aktenregister.xlsx`)
- OCR-fähige PDFs (Tagespost)

## 🛠️ Installation

1. **Repository klonen**
   ```bash
   git clone <repository-url>
   cd blank-app
   ```

2. **Abhängigkeiten installieren**
   ```bash
   pip install -r requirements.txt
   ```

3. **App starten**
   ```bash
   streamlit run streamlit_app.py
   ```

## 📖 Verwendung

### 1. Vorbereitung

**Aktenregister (aktenregister.xlsx):**
- Blatt "akten" mit folgenden Spalten:
  - `Akte`: Aktenzeichen-Stamm (z.B. "151/25")
  - `SB`: Sachbearbeiter-Kürzel (SQ, TS, M, FÜ, CV)
  - `Kurzbez.`: Kurzbezeichnung ("Mandant ./. Gegner")
  - `Gegner`: Gegenseite
  - `Art`: RA/Notar

**Tagespost-PDF:**
- OCR-verarbeitet
- Dokumente durch T-Seiten (Trennblätter) getrennt

### 2. App bedienen

1. **OpenAI API Key eingeben** (in der Sidebar)
2. **Tagespost-PDF hochladen**
3. **Aktenregister-Excel hochladen**
4. **"Verarbeitung starten" klicken**
5. **ZIP-Dateien herunterladen**

### 3. Ausgabe

Die App erstellt:

- **ZIP-Dateien pro Sachbearbeiter** (`SQ.zip`, `TS.zip`, `M.zip`, `FÜ.zip`, `CV.zip`, `nicht-zugeordnet.zip`)
  - Einzelne PDFs mit Dateinamen: `[AZ]_[Mandant]_[Gegner]_[Datum]_[Stichworte].pdf`
  - Excel-Datei mit Fristen und Metadaten

- **Gesamt-Excel**: `Fristen_und_Akten_Gesamt.xlsx`
  - Alle Dokumente in einer Übersicht
  - Farbmarkierung: Rot (≤ 3 Tage), Orange (≤ 7 Tage)

## 🎯 Aktenzeichen-Erkennung

### Muster

- **Stamm**: `\d{1,5}/\d{2}` (z.B. "151/25")
- **Vollform**: `\d{1,5}/\d{2}(SQ|M|MQ|TS|FÜ|CV)` (z.B. "151/25M")

### Prioritäten

1. **"Ihr Zeichen" / "Unser Zeichen" Felder** (höchste Priorität)
2. **Vollmuster im Text**
3. **Stämme mit Registertreffer**
4. **Fallback**: "nicht-zugeordnet"

### Kürzel-Normalisierung

- `MQ` → `M` (RAin Marquardsen)
- `FU` → `FÜ` (Dr. Fürsen)

## 👥 Sachbearbeiter

- **SQ**: Rechtsanwalt und Notar Sven-Bryde Meier
- **TS**: Rechtsanwältin Tamara Meyer
- **M**: Rechtsanwältin Ann-Kathrin Marquardsen
- **FÜ**: Rechtsanwalt Dr. Fürsen
- **CV**: Rechtsanwalt Christian Ostertun

## 📊 Excel-Struktur

| Spalte | Inhalt |
|--------|--------|
| A | Eingangsdatum |
| B | Internes Aktenzeichen |
| C | Externes Aktenzeichen |
| D | Mandant |
| E | Gegner / Absender |
| F | Absendertyp |
| G | Sachbearbeiter |
| H | Fristdatum |
| I | Fristtyp |
| J | Fristquelle |
| K | Textauszug |
| L | PDF-Datei |
| M | Status |

## 🔧 Technische Details

### Module

- `streamlit_app.py`: Haupt-UI
- `pdf_processor.py`: PDF-Segmentierung und Trennblatt-Erkennung
- `aktenzeichen_erkennung.py`: Aktenzeichen-Extraktion mit Regex
- `document_analyzer.py`: OpenAI-Integration für Dokumentenanalyse
- `excel_generator.py`: Excel-Erstellung mit Formatierung

### Dependencies

- `streamlit`: Web-Interface
- `PyMuPDF`: PDF-Verarbeitung
- `pandas`: Datenverarbeitung
- `openpyxl`: Excel-Erstellung
- `openai`: KI-Dokumentenanalyse

## 🐛 Troubleshooting

**Fehler beim PDF-Upload:**
- Stellen Sie sicher, dass das PDF OCR-verarbeitet ist
- Prüfen Sie, ob T-Seiten korrekt eingefügt wurden

**Keine Aktenzeichen erkannt:**
- Überprüfen Sie das Aktenregister-Format
- Prüfen Sie, ob Aktenzeichen im erwarteten Format vorliegen

**OpenAI-Fehler:**
- Validieren Sie Ihren API Key
- Prüfen Sie Ihr OpenAI-Guthaben

## 📄 Lizenz

MIT License - siehe [LICENSE](LICENSE)

## 🤝 Support

Bei Fragen oder Problemen öffnen Sie bitte ein Issue im Repository.
