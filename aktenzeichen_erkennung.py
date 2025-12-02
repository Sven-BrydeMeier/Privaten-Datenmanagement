"""
Aktenzeichen-Erkennungsmodul für RHM Posteingang
Implementiert alle Regeln aus dem Masterprompt
"""

import re
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime


class AktenzeichenErkenner:
    # Kanzlei-Kürzel (MQ vor M, da MQ spezifischer)
    KUERZEL = ['MQ', 'SQ', 'TS', 'CV', 'FÜ', 'FU', 'M']
    KUERZEL_NORMALISIERT = {
        'MQ': 'M',  # MQ = M (RAin Marquardsen)
        'FU': 'FÜ',  # FU = FÜ
        'FÜ': 'FÜ',
        'SQ': 'SQ',
        'TS': 'TS',
        'CV': 'CV',
        'M': 'M'
    }

    # Sachbearbeiter-Namen zu Kürzel Mapping (alle Variationen)
    SACHBEARBEITER_NAMEN = {
        # SQ = Sven-Bryde Meier (Rechtsanwalt und Notar)
        'meier': 'SQ',
        'sven-bryde': 'SQ',
        'sven': 'SQ',
        'sven-bryde meier': 'SQ',
        'sven meier': 'SQ',

        # TS = Tamara Meyer (Rechtsanwältin)
        'meyer': 'TS',
        'tamara': 'TS',
        'tamara meyer': 'TS',

        # M/MQ = Ann-Kathrin Marquardsen (Rechtsanwältin)
        'marquardsen': 'M',
        'ann-kathrin': 'M',
        'ann-kathrin marquardsen': 'M',

        # FÜ = Dr. Ernst Joachim Fürsen (Rechtsanwalt, Notar a.D.)
        'fürsen': 'FÜ',
        'fuersen': 'FÜ',
        'ernst joachim': 'FÜ',
        'ernst-joachim': 'FÜ',
        'ernst joachim fürsen': 'FÜ',
        'ernst-joachim fürsen': 'FÜ',
        'ernst joachim fuersen': 'FÜ',
        'ernst-joachim fuersen': 'FÜ',

        # CV = Christian Ostertun (Rechtsanwalt)
        'ostertun': 'CV',
        'christian': 'CV',
        'christian ostertun': 'CV',
        'vollbrecht': 'CV'  # Alternative Name
    }

    # Titel-Variationen (für erweiterte Suche)
    TITEL_VARIATIONEN = [
        'rechtsanwalt', 'rechtsanwältin', 'ra', 'rae', 'r.a.',
        'notar', 'notar a.d.', 'notar a. d.',
        'fachanwalt', 'fachanwältin', 'fa', 'fain',
        'dr.', 'dr', 'doktor'
    ]

    # Schlagwörter für "Ihr Zeichen" etc.
    ZEICHEN_KEYWORDS = [
        'ihr zeichen', 'unser zeichen', 'ihr az', 'ihr az.',
        'ihr aktenzeichen', 'dortiges aktenzeichen', 'verwendungszweck'
    ]

    # Externe Aktenzeichen-Schlagwörter
    EXTERNE_KEYWORDS = [
        'aktenzeichen beim', 'az.', 'schadennummer', 'schaden-nr',
        'versicherungsnummer', 'kundennummer'
    ]

    def __init__(self, excel_path: Path):
        """Lädt das Aktenregister"""
        self.akten_register = self._lade_aktenregister(excel_path)

    def _lade_aktenregister(self, excel_path: Path) -> pd.DataFrame:
        """Lädt aktenregister.xlsx, Blatt 'akten'"""
        df = pd.read_excel(excel_path, sheet_name='akten', header=1)

        # Prüfe ob erforderliche Spalten vorhanden sind
        if 'Akte' not in df.columns or 'SB' not in df.columns:
            # Zeige verfügbare Spalten für Debugging
            print(f"⚠️ Warnung: Erforderliche Spalten nicht gefunden!")
            print(f"Verfügbare Spalten: {list(df.columns)}")

            # Versuche alternative Spaltennamen
            column_mapping = {}
            for col in df.columns:
                col_lower = str(col).lower().strip()
                if 'akt' in col_lower and 'Akte' not in df.columns:
                    column_mapping[col] = 'Akte'
                elif col_lower in ['sb', 'sachbearbeiter', 'bearbeiter'] and 'SB' not in df.columns:
                    column_mapping[col] = 'SB'

            if column_mapping:
                df = df.rename(columns=column_mapping)
                print(f"✓ Spalten umbenannt: {column_mapping}")

        # Spalten bereinigen (nur wenn vorhanden)
        if 'Akte' in df.columns:
            df['Akte'] = df['Akte'].astype(str).str.strip()

        if 'SB' in df.columns:
            df['SB'] = df['SB'].astype(str).str.strip().str.upper()
            # FU zu FÜ normalisieren
            df['SB'] = df['SB'].replace('FU', 'FÜ')

        return df

    def erkenne_sachbearbeiter_aus_text(self, text: str) -> Optional[str]:
        """
        Extrahiert den Sachbearbeiter aus Anreden und Anschriften im Text.

        Regeln:
        1. Suche in Anreden wie "Sehr geehrter Herr Kollege Meier"
        2. Suche mit Titeln wie "Rechtsanwalt Meier", "Notar Meier", "Fachanwältin Meyer"
        3. Suche in Anschriften, ABER NICHT wenn der Name nur in Kanzleinamen erscheint
        4. Erkennt alle Namens-Variationen (Vorname + Nachname, nur Vorname, nur Nachname)

        Returns:
            Kürzel des Sachbearbeiters (SQ, TS, M, FÜ, CV) oder None
        """
        text_lower = text.lower()
        lines = text.split('\n')

        # Sortiere Namen nach Länge (längste zuerst) für spezifischere Matches
        sorted_names = sorted(self.SACHBEARBEITER_NAMEN.items(), key=lambda x: len(x[0]), reverse=True)

        # PRIORITÄT 1: Anrede-Suche (höchste Priorität)
        # Erweiterte Patterns für Anreden mit Namen
        for name, kuerzel in sorted_names:
            # Escape Sonderzeichen für regex
            name_escaped = re.escape(name)

            # Pattern: "Sehr geehrter Herr/Frau [Titel] [Name]"
            anrede_patterns = [
                rf'sehr\s+geehrte?[rn]?\s+(herr|frau|herrn)\s+(kollege?|kollegin)\s+({name_escaped})',
                rf'sehr\s+geehrte?[rn]?\s+(herr|frau|herrn)\s+({name_escaped})',
                rf'liebe?[rn]?\s+(herr|frau|kollege?|kollegin)\s+({name_escaped})',
                rf'guten\s+tag\s+(herr|frau)\s+({name_escaped})',
                rf'hallo\s+(herr|frau)\s+({name_escaped})'
            ]

            for pattern in anrede_patterns:
                if re.search(pattern, text_lower, re.IGNORECASE):
                    return kuerzel

        # PRIORITÄT 2: Titel + Name Kombinationen (z.B. "Rechtsanwalt Meier", "Notar Meier")
        for name, kuerzel in sorted_names:
            name_escaped = re.escape(name)

            # Suche nach Titel + Name Kombinationen
            for titel in self.TITEL_VARIATIONEN:
                titel_escaped = re.escape(titel)
                # Pattern: "[Titel] [und] [Titel] [Name]" oder einfach "[Titel] [Name]"
                patterns = [
                    rf'{titel_escaped}\s+und\s+\w+\s+{name_escaped}',  # "Rechtsanwalt und Notar Meier"
                    rf'{titel_escaped}\s+{name_escaped}',               # "Rechtsanwalt Meier"
                ]

                for pattern in patterns:
                    if re.search(pattern, text_lower, re.IGNORECASE):
                        return kuerzel

        # PRIORITÄT 3: Anschrift-Suche (mit Ausschluss von Kanzleinamen)
        # Suche in den ersten 30 Zeilen (typischer Anschriftenbereich)
        for i, line in enumerate(lines[:30]):
            line_lower = line.lower().strip()

            # Überspringe Zeilen mit Kanzleinamen
            # z.B. "Radtke, Heigener und Meier" (enthält Komma oder mehrere Namen)
            if ',' in line:
                # Prüfe ob es wie ein Kanzleiname aussieht (mehrere Namen getrennt durch Komma)
                continue

            # Überspringe Zeilen mit mehreren großgeschriebenen Namen (außer wenn Titel dabei)
            if ' und ' in line_lower or ' & ' in line:
                words = re.findall(r'\b[A-ZÄÖÜ][a-zäöüß]+\b', line)
                if len(words) >= 3:  # Mehrere Namen = wahrscheinlich Kanzleiname
                    continue

            # Suche nach Sachbearbeiter-Namen (längste Namen zuerst)
            for name, kuerzel in sorted_names:
                name_escaped = re.escape(name)

                # Suche nach dem Namen als ganzes Wort/Phrase
                if re.search(rf'\b{name_escaped}\b', line_lower):
                    # Hat die Zeile Rechtsanwalts-Kontext?
                    has_title = any(titel in line_lower for titel in self.TITEL_VARIATIONEN)

                    # Akzeptiere wenn:
                    # 1. Titel vorhanden (z.B. "Rechtsanwalt Meier")
                    # 2. In Zeilen 5-15 (typischer Empfängerbereich)
                    if has_title or (5 <= i <= 15):
                        return kuerzel

        return None

    def erkenne_aktenzeichen(self, text: str) -> Dict:
        """
        Hauptfunktion: Erkennt internes und externe Aktenzeichen im Text

        Returns:
            Dict mit:
            - internes_az: Internes Kanzlei-Aktenzeichen (z.B. "151/25M")
            - stamm: Nur der Stamm (z.B. "151/25")
            - kuerzel: Sachbearbeiter-Kürzel (z.B. "M")
            - externe_az: Liste externer Aktenzeichen
            - quelle: Woher das interne AZ stammt (zeichen_feld, vollmuster, register, etc.)
        """
        result = {
            'internes_az': None,
            'stamm': None,
            'kuerzel': None,
            'externe_az': [],
            'quelle': None
        }

        # Priorität 1: "Ihr Zeichen / Unser Zeichen" etc.
        zeichen_az = self._suche_in_zeichen_feldern(text)
        if zeichen_az:
            result.update(zeichen_az)
            result['quelle'] = 'zeichen_feld'
            return result

        # Priorität 2: Vollmuster im Text
        vollmuster = self._suche_vollmuster(text)
        if vollmuster:
            result.update(vollmuster)
            result['quelle'] = 'vollmuster'
            return result

        # Priorität 3: Stämme mit Registertreffer
        register_az = self._suche_stamm_mit_register(text)
        if register_az:
            result.update(register_az)
            result['quelle'] = 'register'
            return result

        # Externe Aktenzeichen sammeln (immer)
        result['externe_az'] = self._suche_externe_aktenzeichen(text)

        return result

    def _suche_in_zeichen_feldern(self, text: str) -> Optional[Dict]:
        """
        Sucht nach Aktenzeichen in "Ihr Zeichen / Unser Zeichen" etc. Zeilen
        Höchste Priorität!
        """
        lines = text.split('\n')

        for i, line in enumerate(lines):
            line_lower = line.lower()

            # Prüfe, ob Zeile ein Zeichen-Keyword enthält
            if any(kw in line_lower for kw in self.ZEICHEN_KEYWORDS):
                # Suche in dieser und der nächsten Zeile (wegen Umbruch)
                such_text = line
                if i + 1 < len(lines):
                    such_text += " " + lines[i + 1]

                # Suche nach Stamm
                stamm_match = re.search(r'\b(\d{1,5}/\d{2})', such_text)
                if stamm_match:
                    stamm = stamm_match.group(1)

                    # Hole Text nach dem Stamm (Suffix)
                    start_pos = stamm_match.end()
                    suffix = such_text[start_pos:start_pos + 20]  # max 20 Zeichen

                    # Suche Kürzel im Suffix (direkt nach Stamm, ohne Leerzeichen)
                    kuerzel = self._finde_kuerzel_im_text(suffix, position_sensitive=True)

                    if kuerzel:
                        # Kürzel gefunden!
                        kuerzel_norm = self.KUERZEL_NORMALISIERT.get(kuerzel, kuerzel)
                        return {
                            'internes_az': f"{stamm}{kuerzel_norm}",
                            'stamm': stamm,
                            'kuerzel': kuerzel_norm
                        }
                    else:
                        # Kein Kürzel im Suffix → Register prüfen
                        register_info = self._pruefe_register(stamm)
                        if register_info:
                            return register_info

        return None

    def _suche_vollmuster(self, text: str) -> Optional[Dict]:
        """
        Sucht nach Vollmustern: \d{1,5}/\d{2}(SQ|M|MQ|TS|FÜ|CV)...
        """
        # Pattern: Stamm + Kürzel
        pattern = r'\b(\d{1,5}/\d{2})(MQ|SQ|TS|CV|FÜ|FU|M)\b'

        matches = re.findall(pattern, text, re.IGNORECASE)

        if matches:
            # Nehme ersten Match
            stamm, kuerzel = matches[0]
            kuerzel = kuerzel.upper()
            kuerzel_norm = self.KUERZEL_NORMALISIERT.get(kuerzel, kuerzel)

            return {
                'internes_az': f"{stamm}{kuerzel_norm}",
                'stamm': stamm,
                'kuerzel': kuerzel_norm
            }

        return None

    def _suche_stamm_mit_register(self, text: str) -> Optional[Dict]:
        """
        Sucht nach Stämmen und prüft gegen Aktenregister
        """
        stamm_matches = re.findall(r'\b(\d{1,5}/\d{2})\b', text)

        for stamm in stamm_matches:
            register_info = self._pruefe_register(stamm)
            if register_info:
                return register_info

        return None

    def _pruefe_register(self, stamm: str) -> Optional[Dict]:
        """
        Prüft, ob ein Stamm im Aktenregister existiert
        Returns internes AZ = Akte + SB aus Register
        """
        # Prüfe ob erforderliche Spalten vorhanden sind
        if 'Akte' not in self.akten_register.columns:
            return None

        treffer = self.akten_register[self.akten_register['Akte'] == stamm]

        if not treffer.empty:
            row = treffer.iloc[0]
            sb = row.get('SB', 'nicht-zugeordnet')
            sb_norm = self.KUERZEL_NORMALISIERT.get(sb, sb)

            return {
                'internes_az': f"{stamm}{sb_norm}",
                'stamm': stamm,
                'kuerzel': sb_norm,
                'register_data': row.to_dict()
            }

        return None

    def _finde_kuerzel_im_text(self, text: str, position_sensitive: bool = False) -> Optional[str]:
        """
        Findet Kürzel im Text
        position_sensitive: Wenn True, muss Kürzel am Anfang sein (für Suffix)
        """
        text_upper = text.upper()

        if position_sensitive:
            # Kürzel muss am Anfang sein (mit max 1-2 Zeichen Abstand)
            for kuerzel in self.KUERZEL:
                if text_upper[:5].find(kuerzel) in [0, 1, 2]:
                    return kuerzel
        else:
            # Irgendwo im Text
            for kuerzel in self.KUERZEL:
                if kuerzel in text_upper:
                    return kuerzel

        return None

    def _suche_externe_aktenzeichen(self, text: str) -> List[str]:
        """
        Sucht nach externen Aktenzeichen (Gerichte, Versicherungen, etc.)
        """
        externe = []
        lines = text.split('\n')

        for line in lines:
            line_lower = line.lower()

            # Prüfe auf externe Keywords
            if any(kw in line_lower for kw in self.EXTERNE_KEYWORDS):
                # Extrahiere alles, was wie ein AZ aussieht
                # Typische Muster: 123 C 456/78, 12 O 345/24, Schaden-Nr. 123456789
                patterns = [
                    r'\b\d+\s+[A-Z]+\s+\d+/\d+\b',  # Gerichts-AZ
                    r'\b[A-Z]{2,}\d{6,}\b',  # Versicherungsnummern
                    r'\b\d{6,}\b'  # Schadensnummern
                ]

                for pattern in patterns:
                    matches = re.findall(pattern, line)
                    externe.extend(matches)

        return list(set(externe))  # Duplikate entfernen

    def ermittle_sachbearbeiter(self, akt_info: Dict, analyse: Dict, sachbearbeiter_aus_text: Optional[str] = None) -> str:
        """
        Ermittelt den Sachbearbeiter basierend auf verschiedenen Quellen

        Priorität:
        0. Sachbearbeiter aus Anrede/Anschrift (HÖCHSTE PRIORITÄT!)
        1. Kürzel aus internem AZ
        2. Register-Daten
        3. "nicht-zugeordnet"
        """
        # 0. Sachbearbeiter aus Text (Anrede/Anschrift) - HÖCHSTE PRIORITÄT
        if sachbearbeiter_aus_text:
            return sachbearbeiter_aus_text

        # 1. Kürzel aus internem AZ
        if akt_info.get('kuerzel'):
            return akt_info['kuerzel']

        # 2. Register-Daten
        if 'register_data' in akt_info:
            sb = akt_info['register_data'].get('SB')
            if sb:
                return self.KUERZEL_NORMALISIERT.get(sb, sb)

        # 3. Fallback
        return 'nicht-zugeordnet'

    def generiere_dateiname(self, internes_az: Optional[str], mandant: Optional[str],
                           gegner: Optional[str], datum: Optional[str],
                           stichworte: List[str]) -> str:
        """
        Generiert Dateinamen nach Schema:
        [Aktenzeichen]_[Mandant]_[Gegner]_[Datum]_[Stichworte].pdf
        """
        teile = []

        # 1. Aktenzeichen
        if internes_az:
            teile.append(self._bereinige_text(internes_az))
        else:
            teile.append("ohne-az")

        # 2. Mandant
        if mandant:
            teile.append(self._bereinige_text(mandant)[:30])

        # 3. Gegner
        if gegner:
            teile.append(self._bereinige_text(gegner)[:30])

        # 4. Datum
        if datum:
            teile.append(self._bereinige_text(datum))

        # 5. Stichworte (max 3)
        if stichworte:
            stichworte_str = "_".join([self._bereinige_text(s) for s in stichworte[:3]])
            teile.append(stichworte_str[:40])

        dateiname = "_".join(teile) + ".pdf"
        return dateiname

    def _bereinige_text(self, text: str) -> str:
        """
        Bereinigt Text für Dateinamen:
        - Umlaute ersetzen
        - Sonderzeichen entfernen
        - Leerzeichen durch Unterstrich
        """
        if not text:
            return ""

        # Umlaute
        replacements = {
            'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss',
            'Ä': 'Ae', 'Ö': 'Oe', 'Ü': 'Ue'
        }
        for alt, neu in replacements.items():
            text = text.replace(alt, neu)

        # Nur alphanumerisch, Unterstrich, Bindestrich
        text = re.sub(r'[^a-zA-Z0-9_\-]', '_', text)

        # Mehrfache Unterstriche vermeiden
        text = re.sub(r'_+', '_', text)

        return text.strip('_')

    def hole_register_info(self, stamm: str) -> Optional[Dict]:
        """
        Holt zusätzliche Informationen aus dem Register
        (Mandant, Gegner, Kurzbez, etc.)
        """
        # Prüfe ob erforderliche Spalten vorhanden sind
        if 'Akte' not in self.akten_register.columns:
            return None

        treffer = self.akten_register[self.akten_register['Akte'] == stamm]

        if not treffer.empty:
            row = treffer.iloc[0]
            info = {
                'art': row.get('Art'),
                'kurzbez': row.get('Kurzbez.'),
                'gegner': row.get('Gegner'),
                'sb': row.get('SB')
            }

            # Parse Kurzbez nach "Mandant ./. Gegner"
            kurzbez = info.get('kurzbez', '')
            if isinstance(kurzbez, str) and './' in kurzbez:
                teile = kurzbez.split('./')
                if len(teile) >= 2:
                    info['mandant'] = teile[0].strip()
                    info['gegner_aus_kurzbez'] = teile[1].strip()

            return info

        return None
