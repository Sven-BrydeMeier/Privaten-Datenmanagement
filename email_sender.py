"""
Email-Versand-Modul für RHM Posteingang
Sendet ZIP-Dateien an RENOs (Rechtanwaltsfachangestellte)
"""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from typing import Dict, List, Optional
from datetime import datetime


class EmailSender:
    """Sendet ZIP-Dateien an RENOs per Email"""

    # RENO-Zuordnungen: Welche RENOs können für welchen Sachbearbeiter ausgewählt werden
    RENO_ZUORDNUNGEN = {
        'SQ': [  # Meier
            {'name': 'Timo Litzenroth', 'email': 'timo.litzenroth@ra-rhm.de'},
            {'name': 'Korinna Rückborn', 'email': 'korinna.rueckborn@ra-rhm.de'},
            {'name': 'Marlena Tönnjes', 'email': 'marlena.toenjes@ra-rhm.de'},
            {'name': 'Ulrike Göser', 'email': 'ulrike.goeser@ra-rhm.de'},
            {'name': 'Nadine Pleißner', 'email': 'nadine.pleissner@ra-rhm.de'},
        ],
        'TS': [  # Meyer
            {'name': 'Mandy Herberg', 'email': 'mandy.herberg@ra-rhm.de'},
            {'name': 'Korinna Rückborn', 'email': 'korinna.rueckborn@ra-rhm.de'},
        ],
        'M': [  # Marquardsen
            {'name': 'Timo Litzenroth', 'email': 'timo.litzenroth@ra-rhm.de'},
            {'name': 'Korinna Rückborn', 'email': 'korinna.rueckborn@ra-rhm.de'},
        ],
        'CV': [  # Ostertun
            {'name': 'Bettina Akkoc', 'email': 'bettina.akkoc@ra-rhm.de'},
            {'name': 'Korinna Rückborn', 'email': 'korinna.rueckborn@ra-rhm.de'},
        ],
        'FÜ': [  # Fürsen
            {'name': 'Korinna Rückborn', 'email': 'korinna.rueckborn@ra-rhm.de'},
        ],
        'nicht-zugeordnet': [  # Alle RENOs
            {'name': 'Mandy Herberg', 'email': 'mandy.herberg@ra-rhm.de'},
            {'name': 'Timo Litzenroth', 'email': 'timo.litzenroth@ra-rhm.de'},
            {'name': 'Korinna Rückborn', 'email': 'korinna.rueckborn@ra-rhm.de'},
            {'name': 'Marlena Tönnjes', 'email': 'marlena.toenjes@ra-rhm.de'},
            {'name': 'Ulrike Göser', 'email': 'ulrike.goeser@ra-rhm.de'},
            {'name': 'Nadine Pleißner', 'email': 'nadine.pleissner@ra-rhm.de'},
            {'name': 'Bettina Akkoc', 'email': 'bettina.akkoc@ra-rhm.de'},
        ]
    }

    # Sachbearbeiter-Namen (für Email-Text)
    SACHBEARBEITER_NAMEN = {
        'SQ': 'RA und Notar Sven-Bryde Meier',
        'TS': 'RAin Tamara Meyer',
        'M': 'RAin Ann-Kathrin Marquardsen',
        'CV': 'RA Christian Ostertun',
        'FÜ': 'RA Dr. Ernst Joachim Fürsen',
        'nicht-zugeordnet': 'Nicht zugeordnet'
    }

    def __init__(self, smtp_server: str, smtp_port: int, smtp_user: str, smtp_password: str):
        """
        Initialisiert Email-Sender

        Args:
            smtp_server: SMTP Server (z.B. "smtp.gmail.com", "smtp.office365.com")
            smtp_port: SMTP Port (z.B. 587 für TLS)
            smtp_user: SMTP Benutzername (Email-Adresse)
            smtp_password: SMTP Passwort
        """
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password

    def sende_zip_an_reno(
        self,
        reno_email: str,
        reno_name: str,
        sachbearbeiter: str,
        zip_data: bytes,
        anzahl_dokumente: int,
        datum: Optional[str] = None
    ) -> bool:
        """
        Sendet ZIP-Datei per Email an RENO

        Args:
            reno_email: Email-Adresse des RENOs
            reno_name: Name des RENOs
            sachbearbeiter: Kürzel des Sachbearbeiters (SQ, TS, M, CV, FÜ)
            zip_data: ZIP-Datei als Bytes
            anzahl_dokumente: Anzahl der Dokumente in der ZIP
            datum: Datum der Verarbeitung (optional)

        Returns:
            True bei Erfolg, False bei Fehler
        """
        try:
            # Email erstellen
            msg = MIMEMultipart()
            msg['From'] = self.smtp_user
            msg['To'] = reno_email

            # Betreff
            sachbearbeiter_name = self.SACHBEARBEITER_NAMEN.get(sachbearbeiter, sachbearbeiter)
            datum_str = datum or datetime.now().strftime('%d.%m.%Y')
            msg['Subject'] = f"Posteingang {sachbearbeiter} - {datum_str} ({anzahl_dokumente} Dokumente)"

            # Email-Text
            body = f"""Hallo {reno_name},

anbei erhalten Sie den verarbeiteten Posteingang für {sachbearbeiter_name}.

📊 Details:
- Sachbearbeiter: {sachbearbeiter_name}
- Anzahl Dokumente: {anzahl_dokumente}
- Datum: {datum_str}

Die ZIP-Datei enthält alle sortierten PDF-Dokumente sowie die Excel-Übersicht mit Fristen und Metadaten.

Mit freundlichen Grüßen
RHM Posteingangs-System
"""

            msg.attach(MIMEText(body, 'plain', 'utf-8'))

            # ZIP-Datei anhängen
            zip_attachment = MIMEBase('application', 'zip')
            zip_attachment.set_payload(zip_data)
            encoders.encode_base64(zip_attachment)
            zip_attachment.add_header(
                'Content-Disposition',
                f'attachment; filename="{sachbearbeiter}.zip"'
            )
            msg.attach(zip_attachment)

            # Email senden
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()  # TLS-Verschlüsselung
                server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)

            return True

        except Exception as e:
            print(f"❌ Fehler beim Email-Versand an {reno_email}: {str(e)}")
            return False

    def sende_mehrere_zips(
        self,
        reno_auswahl: Dict[str, List[str]],
        zip_dateien: Dict[str, bytes],
        sachbearbeiter_stats: Dict[str, int],
        datum: Optional[str] = None
    ) -> Dict[str, bool]:
        """
        Sendet mehrere ZIP-Dateien an ausgewählte RENOs

        Args:
            reno_auswahl: Dict {sachbearbeiter: [reno_emails]}
            zip_dateien: Dict {sachbearbeiter: zip_bytes}
            sachbearbeiter_stats: Dict {sachbearbeiter: anzahl_dokumente}
            datum: Datum der Verarbeitung (optional)

        Returns:
            Dict mit Versand-Status pro Email {email: success}
        """
        results = {}

        for sachbearbeiter, reno_emails in reno_auswahl.items():
            if sachbearbeiter not in zip_dateien:
                continue

            zip_data = zip_dateien[sachbearbeiter]
            anzahl_dokumente = sachbearbeiter_stats.get(sachbearbeiter, 0)

            for reno_email in reno_emails:
                # Finde RENO-Namen
                reno_name = "RENO"
                for reno in self.RENO_ZUORDNUNGEN.get(sachbearbeiter, []):
                    if reno['email'] == reno_email:
                        reno_name = reno['name']
                        break

                # Sende Email
                success = self.sende_zip_an_reno(
                    reno_email=reno_email,
                    reno_name=reno_name,
                    sachbearbeiter=sachbearbeiter,
                    zip_data=zip_data,
                    anzahl_dokumente=anzahl_dokumente,
                    datum=datum
                )

                results[f"{sachbearbeiter} → {reno_email}"] = success

        return results

    @staticmethod
    def get_renos_fuer_sachbearbeiter(sachbearbeiter: str) -> List[Dict[str, str]]:
        """
        Gibt verfügbare RENOs für einen Sachbearbeiter zurück

        Args:
            sachbearbeiter: Kürzel (SQ, TS, M, CV, FÜ, nicht-zugeordnet)

        Returns:
            Liste von Dicts mit 'name' und 'email'
        """
        return EmailSender.RENO_ZUORDNUNGEN.get(sachbearbeiter, [])
