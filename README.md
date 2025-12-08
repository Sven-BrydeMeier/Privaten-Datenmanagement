# 📄 RHM | Automatisierter Posteingang

Eine Streamlit-Anwendung zur automatischen Verarbeitung, Sortierung und Verteilung des täglichen Posteingangs für die Kanzlei Radtke, Heigener & Meier.

## ✨ Features

### 🤖 KI-gestützte Dokumentenanalyse
- **Multi-API-Support**: OpenAI (GPT-4o-mini), Claude (claude-3-5-haiku), Gemini (gemini-1.5-flash)
- Automatische Aktenzeichen-Erkennung (intern & extern)
- Intelligente Fristenerkennung
- Mandanten- und Gegner-Extraktion
- Absendertyp-Klassifizierung (Gericht, Versicherung, etc.)

### 📑 Dokumententrennung
- Automatische Trennung durch "Trennseite"-Marker
- OCR-robuste Namens-Erkennung mit Variationen
- Intelligente Sachbearbeiter-Zuordnung aus Anrede/Anschrift

### 👥 Sachbearbeiter-Management
- **SQ** - RA und Notar Sven-Bryde Meier
- **TS** - RAin Tamara Meyer
- **M** - RAin Ann-Kathrin Marquardsen
- **CV** - RA Christian Ostertun
- **FÜ** - RA Dr. Ernst Joachim Fürsen

### 📊 Excel-Export
- Professional formatierte Fristenlisten pro Sachbearbeiter
- Deutsche Datumsformate (DD.MM.YYYY)
- Farbliche Frist-Hervorhebung (Rot ≤3 Tage, Orange ≤7 Tage, Gelb ≤14 Tage)
- Gesamt-Excel mit allen Dokumenten

### 📦 Ausgabe-Optionen
- **ZIP-Download**: Einzelne ZIP-Dateien pro Sachbearbeiter
- **Email-Versand**: Direkte Verteilung an RENOs per SMTP
- Persistente Download-Buttons (bleiben nach Rerun sichtbar)

### 💾 Datenpersistenz
- Verschlüsselte Speicherung von API-Keys (Fernet)
- Aktenregister mit intelligenter Merge-Funktion
- Automatische Timestamps für Updates
- Sicheres Session-State-Management

## 🚀 Deployment auf Streamlit Cloud

### Voraussetzungen
- GitHub Account
- Streamlit Cloud Account (kostenlos bei [share.streamlit.io](https://share.streamlit.io))

### Schritte

1. **Repository auf GitHub**
   - Stellen Sie sicher, dass dieser Code in einem GitHub Repository liegt

2. **Streamlit Cloud verbinden**
   - Gehen Sie zu [share.streamlit.io](https://share.streamlit.io)
   - Klicken Sie auf "New app"
   - Wählen Sie Ihr Repository aus
   - Branch: `claude/streamlit-pdf-processor-01QbAfkkBgaJveWzVsNzM7jh` (oder Ihr Main-Branch)
   - Main file: `streamlit_app.py`

3. **Deploy!**
   - Klicken Sie auf "Deploy"
   - Die App wird automatisch gebaut und deployed

### Konfiguration

#### **API-Keys** (3 Optionen):

1. **Streamlit Secrets** (empfohlen für Streamlit Cloud):
   - In Streamlit Cloud: Settings → Secrets → Add Secret
   - Unterstützte Formate:
     ```toml
     # Option 1: Verschachtelt
     [openai]
     api_key = "sk-..."

     [claude]
     api_key = "sk-ant-..."

     [gemini]
     api_key = "AIza..."

     # Option 2: Flach
     OPENAI_API_KEY = "sk-..."
     ANTHROPIC_API_KEY = "sk-ant-..."
     GOOGLE_API_KEY = "AIza..."
     ```

2. **Persistente Speicherung** (automatisch):
   - Keys werden verschlüsselt im User-Verzeichnis gespeichert
   - Überleben App-Neustarts

3. **Manuelle Eingabe** (Session-basiert):
   - Keys nur für aktuelle Session gültig

**Priorität**: Streamlit Secrets → Persistente Speicherung → Manuelle Eingabe

**Aktenregister**: Beim ersten Start hochladen, danach persistent gespeichert und automatisch gemergt.

## 📝 Verwendung

### 1. API-Key konfigurieren
- Wählen Sie KI-Anbieter (OpenAI/Claude/Gemini)
- Geben Sie API-Key ein
- Key wird verschlüsselt gespeichert

### 2. Aktenregister hochladen
- Excel-Datei mit Spalten: `Akte`, `SB`, `Kurzbez.`, `Gegner`
- Header in Zeile 2 (Zeile 1 = Titel)
- Wird automatisch gemergt bei erneutem Upload

### 3. Tagespost verarbeiten
- OCR-PDF hochladen (mit "Trennseite"-Markern)
- "Verarbeitung starten" klicken
- Automatische Sortierung nach Sachbearbeiter

### 4. Ausgabe nutzen
- **Option A**: ZIP-Dateien downloaden
- **Option B**: Per Email an RENOs versenden (SMTP konfigurieren)

## 🔧 Technischer Stack

- **Frontend**: Streamlit
- **PDF-Verarbeitung**: PyMuPDF (fitz)
- **KI-APIs**: OpenAI, Anthropic Claude, Google Gemini
- **Excel**: pandas + openpyxl
- **Verschlüsselung**: cryptography (Fernet)
- **Email**: smtplib + email.mime

## 📧 RENO-Zuordnungen

| Sachbearbeiter | Verfügbare RENOs |
|---------------|------------------|
| SQ (Meier) | Timo Litzenroth, Korinna Rückborn, Marlena Tönnjes, Ulrike Göser, Nadine Pleißner |
| TS (Meyer) | Mandy Herberg, Korinna Rückborn |
| M (Marquardsen) | Timo Litzenroth, Korinna Rückborn |
| CV (Ostertun) | Bettina Akkoc, Korinna Rückborn |
| FÜ (Fürsen) | Korinna Rückborn |
| nicht-zugeordnet | Alle RENOs |

## 🔒 Sicherheit

- ✅ TLS-verschlüsselte Email-Übertragung
- ✅ Fernet-Verschlüsselung für API-Keys
- ✅ Sichere Dateiberechtigungen (chmod 0o600)
- ✅ Session-basierte Zustandsverwaltung
- ✅ Input-Validierung und Error-Handling

## 📄 Lizenz

Proprietäre Software für Radtke, Heigener & Meier Rechtsanwälte

---

**Entwickelt mit Claude Code** | © 2024 RHM Rechtsanwälte
