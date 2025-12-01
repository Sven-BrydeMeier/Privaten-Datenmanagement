"""
Dokumentenanalyse-Modul mit OpenAI
Extrahiert Mandant, Gegner, Datum, Stichworte, etc.
"""

from openai import OpenAI
from typing import Dict, Optional
import json
import re
from datetime import datetime


class DocumentAnalyzer:
    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)

    def analysiere_dokument(self, text: str, akt_info: Dict) -> Dict:
        """
        Analysiert ein Dokument mit OpenAI und extrahiert:
        - Mandant
        - Gegner / Absender
        - Frühestes Datum
        - 3-5 Stichworte
        - Absendertyp (Gericht, Behörde, Versicherung, Sonstige)
        - Fristen (falls vorhanden)
        """
        # Begrenze Text auf erste 4000 Zeichen (API-Kosten sparen)
        text_gekuerzt = text[:4000]

        # Prompt für OpenAI
        prompt = self._erstelle_analyse_prompt(text_gekuerzt, akt_info)

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",  # Günstiges, schnelles Modell
                messages=[
                    {"role": "system", "content": "Du bist ein Assistent für eine Anwaltskanzlei und analysierst eingehende Dokumente."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                response_format={"type": "json_object"}
            )

            result = json.loads(response.choices[0].message.content)

            # Fallback-Werte
            return {
                'mandant': result.get('mandant'),
                'gegner': result.get('gegner'),
                'datum': result.get('datum'),
                'stichworte': result.get('stichworte', []),
                'absendertyp': result.get('absendertyp', 'Sonstige'),
                'fristen': result.get('fristen', []),
                'textauszug': self._erstelle_textauszug(text)
            }

        except Exception as e:
            # Fallback bei Fehler: Versuche manuelle Extraktion
            return self._fallback_analyse(text)

    def _erstelle_analyse_prompt(self, text: str, akt_info: Dict) -> str:
        """Erstellt den Prompt für OpenAI"""

        internes_az = akt_info.get('internes_az', 'unbekannt')
        externe_az = ', '.join(akt_info.get('externe_az', []))

        prompt = f"""Analysiere das folgende Anwaltsschreiben/Dokument und extrahiere die wichtigsten Informationen.

DOKUMENT:
---
{text}
---

BEKANNTE AKTENZEICHEN:
- Internes Kanzlei-AZ: {internes_az}
- Externe AZ: {externe_az}

AUFGABE:
Extrahiere folgende Informationen und antworte im JSON-Format:

1. **mandant**: Name des Mandanten (der Kanzlei RHM). Falls nicht erkennbar: null
2. **gegner**: Name der Gegenseite/des Absenders
3. **datum**: Frühestes relevantes Datum im Dokument (Format: YYYY-MM-DD)
4. **stichworte**: 3-5 prägnante Stichworte zum Inhalt (z.B. "Mahnung", "Klageerwiderung", "Fristverlaengerung")
5. **absendertyp**: Einer von: "Gericht", "Behoerde", "Versicherung", "Sonstige"
6. **fristen**: Liste von Fristen mit:
   - datum (YYYY-MM-DD)
   - typ (z.B. "Klagerwiderung", "Stellungnahme", "Zahlung")
   - quelle (Textauszug, wo die Frist steht)

ANTWORT-FORMAT (JSON):
{{
  "mandant": "Max Mustermann",
  "gegner": "Amtsgericht Hamburg",
  "datum": "2025-11-15",
  "stichworte": ["Mahnung", "Zahlungsaufforderung", "Mietrueckstand"],
  "absendertyp": "Gericht",
  "fristen": [
    {{
      "datum": "2025-12-10",
      "typ": "Stellungnahme",
      "quelle": "Frist zur Stellungnahme bis 10.12.2025"
    }}
  ]
}}

Wenn eine Information nicht verfügbar ist, verwende null bzw. leere Liste.
"""
        return prompt

    def _fallback_analyse(self, text: str) -> Dict:
        """
        Fallback-Analyse ohne OpenAI
        Einfache Regex-basierte Extraktion
        """
        result = {
            'mandant': None,
            'gegner': None,
            'datum': None,
            'stichworte': [],
            'absendertyp': 'Sonstige',
            'fristen': [],
            'textauszug': self._erstelle_textauszug(text)
        }

        # Datum suchen (einfaches Pattern)
        datum_pattern = r'\b(\d{1,2}\.\d{1,2}\.\d{4})\b'
        datum_matches = re.findall(datum_pattern, text)
        if datum_matches:
            # Versuche zu parsen
            try:
                datum_str = datum_matches[0]
                datum_obj = datetime.strptime(datum_str, '%d.%m.%Y')
                result['datum'] = datum_obj.strftime('%Y-%m-%d')
            except:
                pass

        # Absendertyp erkennen
        text_lower = text.lower()
        if 'gericht' in text_lower or 'amtsgericht' in text_lower or 'landgericht' in text_lower:
            result['absendertyp'] = 'Gericht'
        elif 'versicherung' in text_lower:
            result['absendertyp'] = 'Versicherung'
        elif 'behörde' in text_lower or 'amt' in text_lower:
            result['absendertyp'] = 'Behoerde'

        # Stichworte (einfach)
        stichworte_kandidaten = ['Mahnung', 'Klage', 'Beschluss', 'Urteil', 'Frist', 'Zahlung']
        for stichwort in stichworte_kandidaten:
            if stichwort.lower() in text_lower:
                result['stichworte'].append(stichwort)

        return result

    def _erstelle_textauszug(self, text: str) -> str:
        """
        Erstellt einen kurzen Textauszug (erste 200 Zeichen)
        """
        text_clean = re.sub(r'\s+', ' ', text).strip()
        return text_clean[:200] + "..." if len(text_clean) > 200 else text_clean
