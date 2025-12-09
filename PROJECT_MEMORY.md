# 🧠 PROJECT MEMORY: RHM Automatisierter Posteingang

**Version**: 2.25.12.09.17.00
**Zweck**: Dokumentation für Wiederverwendung und Integration in andere Projekte
**Erstellt**: 09. Dezember 2025

---

## 📋 PROJEKT-ÜBERSICHT

### Beschreibung
Streamlit-basierte Webanwendung zur automatischen Verarbeitung, KI-gestützten Analyse, intelligenten Sortierung und Verteilung des täglichen Posteingangs für die Rechtsanwaltskanzlei Radtke, Heigener & Meier (RHM).

### Hauptfunktionen
1. **PDF-Verarbeitung**: OCR-PDF mit "Trennseite"-Markern wird in Einzeldokumente zerlegt
2. **KI-Analyse**: Extraktion von Aktenzeichen, Fristen, Mandanten, Gegner, Absendertyp
3. **Intelligente Zuordnung**: Automatische Sachbearbeiter-Erkennung aus Anrede/Anschrift
4. **Excel-Export**: Professional formatierte Fristenlisten mit deutscher Datumsformatierung
5. **Verteilung**: ZIP-Download oder Email-Versand an zugeordnete RENOs

### Technologie-Stack
- **Framework**: Streamlit 1.28+
- **PDF**: PyMuPDF (fitz)
- **KI-APIs**: OpenAI GPT-4o-mini, Anthropic Claude-3.5-Haiku, Google Gemini-1.5-Flash
- **Excel**: pandas + openpyxl
- **Sicherheit**: cryptography (Fernet-Verschlüsselung)
- **Email**: smtplib + email.mime
- **UI**: Custom CSS (Mobile-First, Responsive)

---

## 🏗️ ARCHITEKTUR & MODULE

### Dateistruktur (2637 Zeilen Python)

```
blank-app/
├── streamlit_app.py              # Hauptanwendung (934 Zeilen)
├── pdf_processor.py              # PDF-Trennung & OCR-Extraktion
├── document_analyzer.py          # KI-API-Integration & Analyse
├── aktenzeichen_erkennung.py     # Aktenzeichen & Sachbearbeiter-Logik
├── excel_generator.py            # Excel-Formatierung & Farbregeln
├── storage.py                    # Persistente Speicherung (Keys, Register)
├── email_sender.py               # SMTP Email-Versand
├── requirements.txt              # Dependencies
├── README.md                     # User-Dokumentation
├── PROJECT_MEMORY.md             # Diese Datei
├── .streamlit/
│   ├── config.toml              # Streamlit-Konfiguration
│   └── secrets.toml.example     # Secrets-Template
└── .gitignore                    # Git-Ignore (Secrets!)
```

---

## 🔧 MODUL-DETAILS

### 1. streamlit_app.py (Hauptanwendung)

**Verantwortlichkeit**: UI-Orchestrierung, Workflow-Steuerung, Session-Management

**Wichtige Features**:
- **Versionsnummer**: Format `Zähler.JJ.MM.TT.HH.MM` (z.B. "2.25.12.09.17.00")
- **API-Key-Management**: 3-stufige Priorität (Streamlit Secrets → Persistent Storage → Manual)
- **Visuelle Key-Status-Anzeige**:
  - 🟢 Grünes Lämpchen = Streamlit Secrets aktiv
  - 🟡 Gelbes Lämpchen = Lokal gespeichert
  - 🔴 Rotes Lämpchen = Kein Key
- **Responsive Design**: Mobile (<640px), Tablet (641-1023px), Desktop (≥1024px)
- **iPhone-optimiert**: Sidebar verschwindet komplett off-screen (translateX(-100%))
- **Download-Button-Persistenz**: Deep-Copy-Strategie verhindert Verschwinden nach Rerun

**Session State Variablen**:
```python
st.session_state.storage              # PersistentStorage-Instanz
st.session_state.api_keys             # Dict: {'openai', 'claude', 'gemini'}
st.session_state.api_provider         # Aktueller KI-Anbieter
st.session_state.verarbeitung_ergebnisse  # ZIP-Dateien, Excel, Stats (DEEP COPY!)
st.session_state.verarbeitung_abgeschlossen  # Flag für persistente Downloads
```

**CSS-Highlights**:
- Mobile-First mit Touch-Optimierung (44px Buttons)
- Auto-Zoom-Prevention (16px font-size auf inputs)
- Gradient-Hintergründe für Status-Lämpchen
- Box-Shadows für visuelle Tiefe

---

### 2. pdf_processor.py (PDF-Verarbeitung)

**Klasse**: `PDFProcessor`

**Hauptmethode**: `split_by_separator_pages(pdf_bytes: bytes) -> List[Tuple[bytes, str, Optional[str]]]`

**Funktionsweise**:
1. Sucht nach "Trennseite"-Marker (OCR-robust: verschiedene Schreibweisen)
2. Extrahiert Sachbearbeiter-Kürzel aus Trennseite
3. Trennt PDF in Einzeldokumente
4. Gibt zurück: `[(pdf_bytes, sachbearbeiter, original_name), ...]`

**OCR-Robustheit**:
- Ignoriert Groß-/Kleinschreibung
- Toleriert Leerzeichen/Zeilenumbrüche
- Erkennt Variationen: "Trennseite", "TRENNSEITE", "Trenn seite"

---

### 3. document_analyzer.py (KI-Analyse)

**Klasse**: `DocumentAnalyzer`

**Unterstützte APIs**:
- **OpenAI**: gpt-4o-mini ($0.15/1M input, $0.60/1M output)
- **Claude**: claude-3-5-haiku-20241022 ($0.80/1M input, $4.00/1M output)
- **Gemini**: gemini-1.5-flash ($0.075/1M input, $0.30/1M output)

**Hauptmethode**: `analyze_document(pdf_bytes, api_provider, api_key, aktenregister_df) -> dict`

**Extrahierte Daten**:
```python
{
    "aktenzeichen_intern": "12345/01",
    "aktenzeichen_extern": "1 O 234/24",
    "mandant": "Max Mustermann",
    "gegner": "Maria Musterfrau",
    "absender_typ": "Gericht",
    "frist_datum": "31.12.2024",
    "frist_beschreibung": "Klageerwiderung"
}
```

**Prompt-Engineering**:
- Kontext: Aktenregister mit bestehenden Aktenzeichen
- Output: Strukturiertes JSON
- Fehlerbehandlung: Fallback auf leere Werte bei Parse-Errors

---

### 4. aktenzeichen_erkennung.py (Intelligente Zuordnung)

**Kernlogik**: Sachbearbeiter-Erkennung aus Dokumententext

**SACHBEARBEITER_NAMEN Dictionary** (57 Variationen!):
```python
SACHBEARBEITER_NAMEN = {
    # SQ = Sven-Bryde Meier (Rechtsanwalt und Notar)
    'meier': 'SQ',
    'sven-bryde': 'SQ',
    'sven_bryde': 'SQ',           # OCR: Unterstrich statt Bindestrich
    'sven bryde': 'SQ',            # OCR: Leerzeichen
    'sven-bryde meier': 'SQ',
    'sven-bryde_meier': 'SQ',      # OCR: Gemischt
    'sven_bryde_meier': 'SQ',      # OCR: Nur Unterstriche
    'sven bryde-meier': 'SQ',
    'sven bryde meier': 'SQ',
    'sven meier': 'SQ',

    # TS = Tamara Meyer (Rechtsanwältin)
    'tamara': 'TS',
    'meyer': 'TS',
    'tamara_meyer': 'TS',
    'tamara meyer': 'TS',
    # ... (analog für M, CV, FÜ)
}
```

**Wichtig**: Namen sind nach Länge sortiert (längste zuerst), um spezifische Matches vor allgemeinen zu finden!

**Funktionen**:
- `erkenne_sachbearbeiter(text: str) -> str`: Sucht Namen in Text (Anrede, Anschrift)
- `erkenne_aktenzeichen(text: str) -> Tuple[str, str]`: Regex für intern/extern
- `format_aktenzeichen(az: str) -> str`: Normalisiert Format (12345/01)

---

### 5. excel_generator.py (Excel-Formatierung)

**Klasse**: `ExcelGenerator`

**Hauptmethode**: `create_formatted_excel(documents_data: List[dict]) -> bytes`

**Features**:
1. **Deutsche Datumsformate**: `DD.MM.YYYY` (nicht `YYYY-MM-DD`!)
2. **Farbliche Frist-Hervorhebung**:
   - 🔴 Rot: ≤ 3 Tage (kritisch)
   - 🟠 Orange: ≤ 7 Tage (wichtig)
   - 🟡 Gelb: ≤ 14 Tage (bald)
   - ⚪ Weiß: > 14 Tage (normal)
3. **Professional Styling**:
   - Header: Fettdruck, graue Hintergrundfarbe
   - Auto-Width für Spalten
   - Rahmen um Zellen
   - Zentrierte Ausrichtung

**Spalten**:
- Aktenzeichen (intern)
- Aktenzeichen (extern)
- Mandant
- Gegner
- Absender-Typ
- Frist-Datum
- Frist-Beschreibung

---

### 6. storage.py (Datenpersistenz)

**Klasse**: `PersistentStorage`

**Speicherorte**:
```python
~/.rhm_app_data/
├── api_keys.encrypted          # Fernet-verschlüsselte API-Keys
├── aktenregister.xlsx          # Persistentes Aktenregister
└── encryption.key              # Fernet-Key (chmod 0o600)
```

**Sicherheitsfeatures**:
- Fernet-Verschlüsselung (symmetrisch, kryptographisch sicher)
- Sichere Dateiberechtigungen (0o600 = nur Owner lesen/schreiben)
- Automatische Key-Generierung beim ersten Start

**Wichtige Methoden**:
```python
save_api_key(provider: str, key: str) -> bool
load_api_keys() -> dict
has_api_key(provider: str) -> bool
get_api_key_timestamp(provider: str) -> str

save_aktenregister(df: pd.DataFrame) -> bool
load_aktenregister() -> pd.DataFrame
merge_aktenregister(new_df: pd.DataFrame) -> pd.DataFrame  # Intelligent Merge!
```

**Aktenregister-Merge-Logik**:
- Bestehende Einträge bleiben
- Neue Einträge werden hinzugefügt
- Keine Duplikate (basierend auf Aktenzeichen)

---

### 7. email_sender.py (Email-Versand)

**Klasse**: `EmailSender`

**RENO-Zuordnungen** (Hart-codiert):
```python
RENO_ZUORDNUNG = {
    'SQ': ['Timo Litzenroth', 'Korinna Rückborn', 'Marlena Tönnjes',
           'Ulrike Göser', 'Nadine Pleißner'],
    'TS': ['Mandy Herberg', 'Korinna Rückborn'],
    'M':  ['Timo Litzenroth', 'Korinna Rückborn'],
    'CV': ['Bettina Akkoc', 'Korinna Rückborn'],
    'FÜ': ['Korinna Rückborn'],
    'nicht-zugeordnet': ['Alle RENOs']  # Auswahl
}

RENO_EMAILS = {
    'Timo Litzenroth': 'timo.litzenroth@rhm-recht.de',
    'Korinna Rückborn': 'korinna.rueckborn@rhm-recht.de',
    # ... weitere
}
```

**Hauptmethode**: `send_email(smtp_config, recipient, subject, body, attachments)`

**Features**:
- TLS-verschlüsselte Verbindung (STARTTLS)
- Multipart-Emails (Text + Anhänge)
- ZIP-Attachment-Support
- Error-Handling mit detaillierten Meldungen

---

## 🔑 API-KEY-MANAGEMENT (Kritisch!)

### 3-Stufen-Priorität

**1. PRIORITÄT: Streamlit Secrets (Höchste)**
```toml
# .streamlit/secrets.toml (NIEMALS in Git!)
[openai]
api_key = "sk-proj-..."

[claude]
api_key = "sk-ant-..."

[gemini]
api_key = "AIza..."
```

**Code-Logik** (streamlit_app.py:207-231):
```python
# PRIORITÄT 1: Streamlit Secrets
try:
    if 'openai' in st.secrets:
        st.session_state.api_keys['openai'] = st.secrets['openai'].get('api_key', '')
    # ... oder flache Struktur: st.secrets['OPENAI_API_KEY']
except:
    pass

# PRIORITÄT 2: Persistente Speicherung (nur Fallback)
saved_keys = storage.load_api_keys()
for provider in ['openai', 'claude', 'gemini']:
    if not st.session_state.api_keys[provider] and saved_keys.get(provider):
        st.session_state.api_keys[provider] = saved_keys[provider]
```

**2. PRIORITÄT: Persistente Speicherung**
- Verschlüsselte Datei: `~/.rhm_app_data/api_keys.encrypted`
- Wird NUR geladen, wenn kein Secret vorhanden
- Überlebt App-Neustarts

**3. PRIORITÄT: Manuelle Eingabe**
- Session-basiert (verloren nach Browser-Refresh)
- Nur wenn keine andere Quelle verfügbar

---

## 🎨 VISUELLE STATUS-ANZEIGE (Grünes Lämpchen)

### Implementierung (streamlit_app.py:287-352)

**🟢 GRÜNES LÄMPCHEN** (Key aus Streamlit Secrets):
```html
<div style="
    background: linear-gradient(135deg, #00c853 0%, #00e676 100%);
    padding: 20px;
    border-radius: 15px;
    text-align: center;
    box-shadow: 0 4px 15px rgba(0,200,83,0.4);
">
    <div style="font-size: 48px;">🟢</div>
    <div style="color: white; font-weight: bold; font-size: 18px;">
        API KEY AKTIV
    </div>
    <div style="color: #e8f5e9; font-size: 14px;">
        🔐 Streamlit Cloud Secrets
    </div>
    <div style="font-family: monospace;">
        sk-proj...X7yZ  <!-- Maskierter Key -->
    </div>
</div>
```

**🟡 GELBES LÄMPCHEN** (Lokal gespeichert):
- Oranger Gradient (#ffa726 → #ffb74d)
- "API KEY GESPEICHERT" / "💾 Lokal gespeichert"

**🔴 ROTES LÄMPCHEN** (Kein Key):
- Roter Gradient (#ef5350 → #e57373)
- "KEIN API KEY" / "⚠️ Bitte Key eingeben"

**Positionierung**: Direkt nach KI-Anbieter-Auswahl, VOR Eingabefeld (sehr prominent!)

---

## 📱 RESPONSIVE DESIGN

### Mobile-First CSS (streamlit_app.py:20-180)

**Breakpoints**:
```css
/* Mobile */
@media (max-width: 640px) {
    .row-widget.stHorizontalBlock {
        flex-direction: column !important;
    }
    [data-testid="column"] {
        width: 100% !important;
    }
}

/* Tablet */
@media (min-width: 641px) and (max-width: 1023px) {
    [data-testid="column"] {
        min-width: 45% !important;
    }
}

/* Desktop */
@media (min-width: 1024px) {
    .main .block-container {
        max-width: 1400px;
    }
}
```

**Touch-Optimierung**:
```css
@media (pointer: coarse) {
    button {
        min-height: 44px;  /* Apple HIG Guidelines */
        padding: 0.75rem 1rem;
    }
    input, select, textarea {
        min-height: 44px;
        font-size: 16px;  /* Verhindert Auto-Zoom auf iOS */
    }
}
```

**iPhone Sidebar-Fix**:
```css
@media (max-width: 768px) {
    [data-testid="stSidebar"][aria-expanded="false"] {
        margin-left: -100%;
        transform: translateX(-100%);  /* Komplett off-screen */
        transition: transform 0.3s ease-in-out;
    }

    /* Dark Overlay wenn offen */
    [data-testid="stSidebar"][aria-expanded="true"]::before {
        content: "";
        position: fixed;
        background: rgba(0, 0, 0, 0.5);
        z-index: -1;
    }
}
```

---

## 🐛 KRITISCHE BUGFIXES (Dokumentiert für Wiederverwendung)

### 1. Download-Button-Verschwinden (GELÖST)

**Problem**: Nach Download eines ZIP verschwindet alle andere Buttons

**Root Cause**: Session State speicherte nur Referenzen, nicht Deep Copies

**Lösung**:
```python
# FALSCH (nur Referenz):
st.session_state.data = zip_dateien

# RICHTIG (Deep Copy):
st.session_state.verarbeitung_ergebnisse = {
    'zip_dateien': dict(zip_dateien),        # Explizite Kopie
    'gesamt_excel': bytes(gesamt_excel),     # Explizite Kopie
    'sachbearbeiter_stats': dict(stats)      # Explizite Kopie
}
st.session_state.verarbeitung_abgeschlossen = True  # Flag setzen
```

**Wichtig**: Streamlit's Rerun nach Download führt zu Garbage Collection. IMMER Deep Copies verwenden!

---

### 2. OCR-Namens-Erkennung (GELÖST)

**Problem**: "Sven-Bryde Meier" wird nicht erkannt (OCR gibt "Sven-Bryde_Meier" aus)

**Lösung**: 57 Namensvariationen mit allen Kombinationen von `-`, `_`, ` ` (Leerzeichen)

**Implementierung**: Nach Länge sortiert für spezifische Matches zuerst!
```python
# Längste Namen zuerst (verhindert False Positives)
SACHBEARBEITER_NAMEN = {
    'sven-bryde meier': 'SQ',    # 17 chars
    'sven-bryde_meier': 'SQ',    # 17 chars
    'sven_bryde_meier': 'SQ',    # 17 chars
    'sven-bryde': 'SQ',          # 11 chars
    'meier': 'SQ'                # 5 chars (zuletzt!)
}
```

---

### 3. iPhone Sidebar (GELÖST)

**Problem**: Sidebar bleibt teilweise sichtbar auf iPhone

**Lösung**: `transform: translateX(-100%)` zusätzlich zu `margin-left: -100%`

**Wichtig**: Nur `margin` reicht nicht, da Streamlit interne Styles überschreiben!

---

## 🚀 DEPLOYMENT CHECKLIST

### Streamlit Cloud Setup

1. **Repository vorbereiten**:
   - [ ] `requirements.txt` vorhanden
   - [ ] `.streamlit/config.toml` vorhanden
   - [ ] `.gitignore` enthält `.streamlit/secrets.toml`
   - [ ] Keine Secrets im Code!

2. **Streamlit Cloud**:
   - [ ] GitHub Repository verbinden
   - [ ] Branch auswählen (z.B. `main` oder `claude/...`)
   - [ ] Main file: `streamlit_app.py`
   - [ ] Python Version: 3.9+

3. **Secrets konfigurieren** (Settings → Secrets):
   ```toml
   [openai]
   api_key = "sk-proj-..."

   [claude]
   api_key = "sk-ant-..."

   [gemini]
   api_key = "AIza..."
   ```

4. **Deploy & Test**:
   - [ ] App startet ohne Errors
   - [ ] 🟢 Grünes Lämpchen wird angezeigt
   - [ ] API-Calls funktionieren
   - [ ] PDF-Upload klappt
   - [ ] Excel-Download funktioniert

---

## 🔄 INTEGRATION IN ANDERE PROJEKTE

### Als Modul verwenden

**Szenario**: Sie wollen die PDF-Verarbeitungs- und KI-Analyse-Funktionalität in einem anderen Projekt nutzen.

**Schritte**:

1. **Kopieren Sie diese Module**:
   ```
   pdf_processor.py              # PDF-Trennung
   document_analyzer.py          # KI-Analyse
   aktenzeichen_erkennung.py     # Intelligente Zuordnung
   excel_generator.py            # Excel-Formatierung
   storage.py                    # Persistenz (optional)
   ```

2. **Dependencies installieren**:
   ```bash
   pip install PyMuPDF pandas openpyxl openai anthropic google-generativeai cryptography
   ```

3. **Minimales Beispiel**:
   ```python
   from pdf_processor import PDFProcessor
   from document_analyzer import DocumentAnalyzer
   from excel_generator import ExcelGenerator

   # 1. PDF trennen
   processor = PDFProcessor()
   documents = processor.split_by_separator_pages(pdf_bytes)

   # 2. KI-Analyse
   analyzer = DocumentAnalyzer()
   results = []
   for pdf_bytes, sachbearbeiter, _ in documents:
       data = analyzer.analyze_document(
           pdf_bytes,
           api_provider='openai',
           api_key='sk-...',
           aktenregister_df=None
       )
       data['sachbearbeiter'] = sachbearbeiter
       results.append(data)

   # 3. Excel generieren
   excel_gen = ExcelGenerator()
   excel_bytes = excel_gen.create_formatted_excel(results)

   # 4. Speichern
   with open('output.xlsx', 'wb') as f:
       f.write(excel_bytes)
   ```

4. **Anpassungen für Ihr Projekt**:
   - **Sachbearbeiter-Namen**: Passen Sie `SACHBEARBEITER_NAMEN` in `aktenzeichen_erkennung.py` an
   - **Excel-Spalten**: Modifizieren Sie `ExcelGenerator.create_formatted_excel()`
   - **KI-Prompt**: Ändern Sie `DocumentAnalyzer._build_analysis_prompt()` für Ihre Domain
   - **PDF-Trennung**: Ersetzen Sie "Trennseite"-Logik mit Ihrem Marker

---

## 📊 DATENFLUSS (Sequenzdiagramm)

```
User
  │
  ├─> [1] Upload OCR-PDF (mit "Trennseite"-Markern)
  │
  v
PDFProcessor.split_by_separator_pages()
  │
  ├─> Sucht "Trennseite"-Marker
  ├─> Extrahiert Sachbearbeiter-Kürzel
  ├─> Trennt in Einzeldokumente
  │
  v
[(pdf_bytes, 'SQ', 'doc1.pdf'), (pdf_bytes, 'TS', 'doc2.pdf'), ...]
  │
  v
FOR EACH Dokument:
  │
  ├─> DocumentAnalyzer.analyze_document()
  │     │
  │     ├─> Konvertiert PDF zu Base64
  │     ├─> Sendet an KI-API (OpenAI/Claude/Gemini)
  │     ├─> Parst JSON-Response
  │     │
  │     v
  │   {
  │     "aktenzeichen_intern": "12345/01",
  │     "frist_datum": "31.12.2024",
  │     ...
  │   }
  │
  ├─> aktenzeichen_erkennung.erkenne_sachbearbeiter(text)
  │     │
  │     ├─> Sucht Namen in Text (57 Variationen)
  │     ├─> Fallback: Sachbearbeiter von Trennseite
  │     │
  │     v
  │   "SQ"
  │
  v
Gruppierung nach Sachbearbeiter:
  SQ: [doc1, doc3, doc5]
  TS: [doc2, doc4]
  M:  [doc6]
  ...
  │
  v
FOR EACH Sachbearbeiter:
  │
  ├─> Erstelle ZIP mit PDFs
  ├─> ExcelGenerator.create_formatted_excel()
  │     │
  │     ├─> Erstelle DataFrame
  │     ├─> Formatiere Datum (DD.MM.YYYY)
  │     ├─> Farbliche Frist-Hervorhebung
  │     ├─> Professional Styling
  │     │
  │     v
  │   excel_bytes
  │
  ├─> Füge Excel zu ZIP hinzu
  │
  v
{
  'SQ': zip_bytes,
  'TS': zip_bytes,
  ...
}
  │
  v
Ausgabe-Optionen:
  │
  ├─> [A] Download ZIP-Dateien (persistente Buttons!)
  │
  └─> [B] Email-Versand an RENOs
        │
        ├─> Zuordnung: RENO_ZUORDNUNG[sachbearbeiter]
        ├─> SMTP-Verbindung (TLS)
        ├─> Sende Email mit ZIP-Attachment
        │
        v
      ✅ Versandt
```

---

## 🔐 SICHERHEITS-CHECKLISTE

### Implementierte Maßnahmen

- [x] **API-Keys verschlüsselt**: Fernet-Verschlüsselung (symmetrisch, 128-bit)
- [x] **Sichere Dateiberechtigungen**: `chmod 0o600` für Key-Dateien
- [x] **Secrets außerhalb Git**: `.gitignore` enthält `.streamlit/secrets.toml`
- [x] **TLS für Email**: SMTP mit STARTTLS
- [x] **Input-Validierung**: PDF-Format-Checks, Excel-Spalten-Validierung
- [x] **Error-Handling**: Try-Catch-Blöcke mit User-Friendly Messages
- [x] **Session-Isolation**: Streamlit Session State isoliert pro User

### Für andere Projekte beachten

1. **NIEMALS Secrets in Git committen!**
   ```gitignore
   .streamlit/secrets.toml
   *.encrypted
   encryption.key
   ```

2. **API-Keys rotieren** bei Verdacht auf Kompromittierung

3. **HTTPS verwenden** für Streamlit Cloud Deployment (automatisch)

4. **Rate-Limiting** für API-Calls (aktuell nicht implementiert, TODO für Production)

---

## 💰 KOSTEN-KALKULATION (KI-APIs)

### OpenAI GPT-4o-mini (Standard)
- Input: $0.15 / 1M Tokens
- Output: $0.60 / 1M Tokens
- **Durchschnitt pro Dokument**: ~$0.002 (2000 Input + 500 Output Tokens)

### Claude 3.5 Haiku
- Input: $0.80 / 1M Tokens
- Output: $4.00 / 1M Tokens
- **Durchschnitt pro Dokument**: ~$0.004

### Gemini 1.5 Flash (Günstigste)
- Input: $0.075 / 1M Tokens
- Output: $0.30 / 1M Tokens
- **Durchschnitt pro Dokument**: ~$0.001

**Tagespost-Beispiel** (100 Dokumente):
- OpenAI: $0.20/Tag = $6/Monat
- Claude: $0.40/Tag = $12/Monat
- Gemini: $0.10/Tag = $3/Monat

---

## 🧪 TESTSZENARIEN (Für QA)

### 1. PDF-Verarbeitung
- [ ] Upload PDF ohne "Trennseite" → Fehler-Handling
- [ ] Upload PDF mit 1 Trennseite → 1 Dokument
- [ ] Upload PDF mit 10 Trennseiten → 10 Dokumente
- [ ] Trennseite mit Schreibfehlern (OCR) → Korrekt erkannt
- [ ] Sachbearbeiter-Kürzel fehlt → Fallback auf "nicht-zugeordnet"

### 2. Sachbearbeiter-Erkennung
- [ ] "Sven-Bryde Meier" im Text → 'SQ'
- [ ] "Sven_Bryde_Meier" (OCR) → 'SQ'
- [ ] "Sven Bryde Meier" (OCR) → 'SQ'
- [ ] "Tamara Meyer" → 'TS'
- [ ] Kein Name gefunden → Trennseiten-Kürzel

### 3. KI-Analyse
- [ ] Aktenzeichen erkannt (intern & extern)
- [ ] Frist korrekt extrahiert (DD.MM.YYYY)
- [ ] Mandant/Gegner extrahiert
- [ ] Absender-Typ klassifiziert
- [ ] Ungültiges PDF → Fehler-Handling

### 4. Excel-Export
- [ ] Datum in deutschem Format (DD.MM.YYYY)
- [ ] Fristen korrekt farblich markiert (Rot/Orange/Gelb)
- [ ] Header fettgedruckt
- [ ] Spaltenbreite automatisch angepasst

### 5. Download-Persistenz
- [ ] Download ZIP "SQ" → Andere Buttons bleiben sichtbar ✅
- [ ] Nach Rerun → Buttons noch da ✅
- [ ] Session beenden & neu starten → Buttons weg (erwartet)

### 6. API-Key-Management
- [ ] Streamlit Secret konfiguriert → 🟢 Grünes Lämpchen
- [ ] Kein Secret, aber gespeichert → 🟡 Gelbes Lämpchen
- [ ] Kein Key → 🔴 Rotes Lämpchen
- [ ] Key eingeben & speichern → Persistent nach Rerun
- [ ] API-Anbieter wechseln → Status aktualisiert

### 7. Responsive Design
- [ ] iPhone (375px): Sidebar off-screen, Spalten gestapelt
- [ ] iPad (768px): 2-Spalten-Layout
- [ ] Desktop (1920px): Max-Width 1400px, volle Features

### 8. Email-Versand
- [ ] SMTP-Config korrekt → Email versandt
- [ ] Falsche Credentials → Fehler-Meldung
- [ ] RENO-Zuordnung korrekt (SQ → 5 RENOs zur Auswahl)

---

## 📝 LESSONS LEARNED (Für zukünftige Projekte)

### 1. Streamlit Session State ist tricky
**Problem**: Nach `st.download_button()` führt Streamlit einen Rerun aus → Daten können verloren gehen
**Lösung**: IMMER Deep Copies verwenden (`dict()`, `bytes()`), nicht nur Referenzen!

### 2. OCR ist unzuverlässig
**Problem**: OCR ersetzt `-` durch `_`, fügt Leerzeichen ein, etc.
**Lösung**: Erstelle ALLE möglichen Variationen (Permutationen von `-`, `_`, ` `)

### 3. Mobile-First ist Pflicht
**Problem**: Streamlit-Apps sind oft Desktop-only
**Lösung**: CSS von Anfang an mit Mobile-Breakpoints planen (640px, 768px, 1024px)

### 4. Visuelle Feedback ist King
**Problem**: User wissen nicht, ob API-Key aus Secrets oder Storage kommt
**Lösung**: Große, farbige Lämpchen mit Gradienten und Schatten → sofort sichtbar!

### 5. API-Key-Priorität ist wichtig
**Problem**: Lokal gespeicherte Keys überschreiben Streamlit Secrets
**Lösung**: Klare Priorität: Secrets → Storage → Manual (in dieser Reihenfolge laden!)

### 6. Versionsnummering frühzeitig planen
**Problem**: Keine Versionsnummern → Schwer zu tracken welche Version deployed ist
**Lösung**: Format `Zähler.JJ.MM.TT.HH.MM` von Anfang an implementieren

---

## 🔮 ZUKÜNFTIGE ERWEITERUNGEN (Ideas)

### Kurzfristig (Low-Hanging Fruit)
- [ ] **Rate-Limiting**: Max. X API-Calls pro Minute (verhindert Kostenlawine)
- [ ] **Batch-Processing**: Mehrere PDFs gleichzeitig hochladen
- [ ] **Export-Formate**: CSV, Word-Tabelle zusätzlich zu Excel
- [ ] **Statistik-Dashboard**: Anzahl Dokumente pro Monat, durchschnittliche Fristen, etc.

### Mittelfristig (More Complex)
- [ ] **Aktenregister-Editor**: In-App-Bearbeitung statt nur Upload
- [ ] **OCR selbst durchführen**: pytesseract statt externes OCR-PDF erwarten
- [ ] **PDF-Vorschau**: Inline-PDF-Viewer in Streamlit
- [ ] **Undo-Funktion**: Letzte Verarbeitung rückgängig machen

### Langfristig (Big Features)
- [ ] **Multi-User-Auth**: Login-System mit Rollen (Admin, RA, RENO)
- [ ] **Datenbank**: PostgreSQL statt File-Storage für Aktenregister
- [ ] **API-Endpunkte**: REST API für externe Integrationen
- [ ] **Frist-Reminder**: Automatische Email-Benachrichtigungen X Tage vor Frist
- [ ] **KI-Training**: Fine-Tuning auf kanzleispezifische Dokumente

---

## 🆘 TROUBLESHOOTING GUIDE

### Problem: Grünes Lämpchen wird nicht angezeigt (trotz Secrets)

**Checkliste**:
1. Secrets korrekt in Streamlit Cloud konfiguriert? (Settings → Secrets)
2. Format korrekt? (Verschachtelt `[openai]` oder flach `OPENAI_API_KEY`)
3. Key enthält Tippfehler? (Leerzeichen am Anfang/Ende?)
4. Cache löschen: Streamlit Cloud → Reboot App
5. Logs prüfen: Streamlit Cloud → Logs (Exceptions bei Secret-Zugriff?)

**Debug-Code einfügen**:
```python
st.write("Debug: st.secrets keys:", list(st.secrets.keys()))
st.write("Debug: stored_key length:", len(stored_key))
st.write("Debug: key_from_secrets:", key_from_secrets)
```

---

### Problem: Download-Buttons verschwinden

**Checkliste**:
1. Verwendest du `dict()` und `bytes()` für Deep Copies? ✅
2. Ist `st.session_state.verarbeitung_abgeschlossen` gesetzt? ✅
3. Sind Buttons außerhalb des `if st.button("Verarbeitung starten"):` Blocks?

**Lösung**: Siehe Abschnitt "Download-Button-Verschwinden" oben

---

### Problem: OCR-Namen werden nicht erkannt

**Checkliste**:
1. Sind alle Variationen in `SACHBEARBEITER_NAMEN`? (mit `_`, `-`, ` `)
2. Groß-/Kleinschreibung beachtet? (`.lower()` verwenden!)
3. Text wird extrahiert? (`st.write(text)` zum Debuggen)

**Debug-Code**:
```python
text_lower = text.lower()
for name in SACHBEARBEITER_NAMEN.keys():
    if name in text_lower:
        st.write(f"✅ Match: {name} → {SACHBEARBEITER_NAMEN[name]}")
```

---

### Problem: KI-API gibt Fehler zurück

**Häufige Ursachen**:
- **401 Unauthorized**: API-Key falsch oder abgelaufen
- **429 Rate Limit**: Zu viele Requests → Pause einlegen oder Tier upgraden
- **500 Server Error**: API-Anbieter hat Problem → Später erneut versuchen
- **Timeout**: PDF zu groß → Komprimieren oder kleinere Seiten

**Lösung**: Error-Message genau lesen und in Streamlit anzeigen (nicht nur in Logs)

---

## 📚 EXTERNE RESSOURCEN

### Dokumentation
- **Streamlit**: https://docs.streamlit.io
- **PyMuPDF**: https://pymupdf.readthedocs.io
- **OpenAI API**: https://platform.openai.com/docs
- **Anthropic Claude**: https://docs.anthropic.com
- **Google Gemini**: https://ai.google.dev/docs

### Tutorials (Referenziert)
- Streamlit Secrets Management: https://docs.streamlit.io/streamlit-community-cloud/deploy-your-app/secrets-management
- Responsive CSS in Streamlit: https://discuss.streamlit.io/t/responsive-design
- Fernet Encryption: https://cryptography.io/en/latest/fernet/

---

## 🎯 ZUSAMMENFASSUNG FÜR NEUE PROJEKTE

### Was du aus diesem Projekt übernehmen solltest:

1. **API-Key-Management mit 3-Stufen-Priorität** (Secrets → Storage → Manual)
2. **Visuelle Status-Anzeigen** (Farbige Lämpchen mit Gradienten)
3. **Responsive Design von Anfang an** (Mobile-First CSS)
4. **Download-Button-Persistenz** (Deep Copies in Session State)
5. **OCR-robuste Namenserkennung** (Alle Variationen mit `-`, `_`, ` `)
6. **Professional Excel-Formatierung** (Deutsche Datumsformate, Farben, Styling)
7. **Modulare Architektur** (Jede Klasse hat eine klare Verantwortlichkeit)
8. **Versionsnummering** (Format `Zähler.JJ.MM.TT.HH.MM`)

### Dateien die du kopieren kannst:

- `storage.py` → Universal verwendbar für verschlüsselte Persistenz
- `excel_generator.py` → Anpassbar für beliebige Excel-Exports
- CSS-Abschnitt aus `streamlit_app.py` → Responsive Design Template
- API-Key-Management-Code → 3-Stufen-Priorität für andere Apps

---

**Ende der Dokumentation**
Version: 2.25.12.09.17.00
Erstellt: 09. Dezember 2025
Autor: Claude Code (Anthropic)
