"""
Banking Service für Nordigen/GoCardless Bank Account Data API
Ermöglicht den Abruf von Kontodaten und Transaktionen von deutschen Banken.

Dokumentation: https://developer.gocardless.com/bank-account-data/overview
"""
import requests
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import logging

from database.db import get_db
from database.models import BankConnection, BankTransaction, BankAccount
from config.settings import get_settings

logger = logging.getLogger(__name__)


class NordigenService:
    """
    Service für die Integration mit Nordigen/GoCardless Bank Account Data API.

    Um diesen Service zu nutzen:
    1. Registrieren Sie sich kostenlos bei https://bankaccountdata.gocardless.com/
    2. Erstellen Sie API-Credentials (Secret ID und Secret Key)
    3. Tragen Sie diese in den Einstellungen ein
    """

    BASE_URL = "https://bankaccountdata.gocardless.com/api/v2"

    # Cache für Access Token
    _access_token = None
    _token_expires = None

    def __init__(self, secret_id: str = None, secret_key: str = None):
        """
        Initialisiert den Nordigen-Service.

        Args:
            secret_id: Nordigen Secret ID (aus den Einstellungen)
            secret_key: Nordigen Secret Key (aus den Einstellungen)
        """
        settings = get_settings()
        self.secret_id = secret_id or getattr(settings, 'nordigen_secret_id', None)
        self.secret_key = secret_key or getattr(settings, 'nordigen_secret_key', None)

    def is_configured(self) -> bool:
        """Prüft ob die API-Credentials konfiguriert sind"""
        return bool(self.secret_id and self.secret_key)

    def _get_access_token(self) -> Optional[str]:
        """
        Holt einen Access Token von der Nordigen API.
        Tokens werden gecached bis sie ablaufen.
        """
        # Prüfen ob gecachter Token noch gültig
        if self._access_token and self._token_expires:
            if datetime.now() < self._token_expires:
                return self._access_token

        if not self.is_configured():
            logger.error("Nordigen API nicht konfiguriert")
            return None

        try:
            response = requests.post(
                f"{self.BASE_URL}/token/new/",
                json={
                    "secret_id": self.secret_id,
                    "secret_key": self.secret_key
                },
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                self._access_token = data.get("access")
                # Token ist 24 Stunden gültig, wir erneuern nach 23 Stunden
                self._token_expires = datetime.now() + timedelta(hours=23)
                return self._access_token
            else:
                logger.error(f"Token-Anfrage fehlgeschlagen: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.error(f"Fehler beim Token-Abruf: {e}")
            return None

    def _request(self, method: str, endpoint: str, data: dict = None) -> Optional[Dict]:
        """Führt eine authentifizierte API-Anfrage aus"""
        token = self._get_access_token()
        if not token:
            return None

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        url = f"{self.BASE_URL}/{endpoint}"

        try:
            if method == "GET":
                response = requests.get(url, headers=headers, timeout=30)
            elif method == "POST":
                response = requests.post(url, headers=headers, json=data, timeout=30)
            elif method == "DELETE":
                response = requests.delete(url, headers=headers, timeout=30)
            else:
                return None

            if response.status_code in [200, 201]:
                return response.json()
            else:
                logger.error(f"API-Fehler: {response.status_code} - {response.text}")
                return {"error": response.text, "status_code": response.status_code}

        except Exception as e:
            logger.error(f"API-Anfrage fehlgeschlagen: {e}")
            return {"error": str(e)}

    # ==========================================
    # INSTITUTIONEN (Banken)
    # ==========================================

    def get_institutions(self, country: str = "DE") -> List[Dict]:
        """
        Holt die Liste aller verfügbaren Banken für ein Land.

        Args:
            country: ISO 3166-1 alpha-2 Ländercode (default: DE)

        Returns:
            Liste von Banken mit ID, Name, Logo
        """
        result = self._request("GET", f"institutions/?country={country}")

        if result and not result.get("error"):
            return result
        return []

    def search_institutions(self, query: str, country: str = "DE") -> List[Dict]:
        """Sucht nach Banken anhand des Namens"""
        institutions = self.get_institutions(country)
        query_lower = query.lower()

        return [
            inst for inst in institutions
            if query_lower in inst.get("name", "").lower()
        ]

    def get_institution(self, institution_id: str) -> Optional[Dict]:
        """Holt Details zu einer bestimmten Bank"""
        return self._request("GET", f"institutions/{institution_id}/")

    # ==========================================
    # VERBINDUNGEN (Requisitions)
    # ==========================================

    def create_requisition(
        self,
        institution_id: str,
        redirect_url: str,
        reference: str = None,
        user_language: str = "DE",
        agreement_id: str = None
    ) -> Optional[Dict]:
        """
        Erstellt eine neue Verbindungsanfrage (Requisition).

        Der Benutzer wird zur Bank weitergeleitet, um sich zu authentifizieren.

        Args:
            institution_id: ID der Bank
            redirect_url: URL für Redirect nach Auth
            reference: Eigene Referenz (optional)
            user_language: Sprache für Bank-Login
            agreement_id: ID einer bestehenden Vereinbarung

        Returns:
            Dict mit 'id' (requisition_id) und 'link' (Bank-Login URL)
        """
        data = {
            "institution_id": institution_id,
            "redirect": redirect_url,
            "user_language": user_language
        }

        if reference:
            data["reference"] = reference
        if agreement_id:
            data["agreement"] = agreement_id

        return self._request("POST", "requisitions/", data)

    def get_requisition(self, requisition_id: str) -> Optional[Dict]:
        """
        Holt den Status einer Verbindungsanfrage.

        Returns:
            Dict mit Status und ggf. Account-IDs
        """
        return self._request("GET", f"requisitions/{requisition_id}/")

    def delete_requisition(self, requisition_id: str) -> bool:
        """Löscht eine Verbindungsanfrage"""
        result = self._request("DELETE", f"requisitions/{requisition_id}/")
        return result is not None and not result.get("error")

    # ==========================================
    # KONTEN
    # ==========================================

    def get_account_details(self, account_id: str) -> Optional[Dict]:
        """Holt Kontodetails (IBAN, Name, etc.)"""
        return self._request("GET", f"accounts/{account_id}/details/")

    def get_account_balances(self, account_id: str) -> Optional[Dict]:
        """Holt aktuelle Kontostände"""
        return self._request("GET", f"accounts/{account_id}/balances/")

    def get_account_transactions(
        self,
        account_id: str,
        date_from: str = None,
        date_to: str = None
    ) -> Optional[Dict]:
        """
        Holt Transaktionen für ein Konto.

        Args:
            account_id: Nordigen Account ID
            date_from: Startdatum (YYYY-MM-DD)
            date_to: Enddatum (YYYY-MM-DD)

        Returns:
            Dict mit 'booked' und 'pending' Transaktionen
        """
        params = []
        if date_from:
            params.append(f"date_from={date_from}")
        if date_to:
            params.append(f"date_to={date_to}")

        query = f"?{'&'.join(params)}" if params else ""

        return self._request("GET", f"accounts/{account_id}/transactions/{query}")

    # ==========================================
    # VEREINBARUNGEN (Agreements)
    # ==========================================

    def create_agreement(
        self,
        institution_id: str,
        max_historical_days: int = 90,
        access_valid_for_days: int = 90,
        access_scope: List[str] = None
    ) -> Optional[Dict]:
        """
        Erstellt eine Endbenutzer-Vereinbarung.

        Args:
            institution_id: Bank-ID
            max_historical_days: Wie viele Tage Historie
            access_valid_for_days: Wie lange gültig
            access_scope: ["balances", "details", "transactions"]
        """
        data = {
            "institution_id": institution_id,
            "max_historical_days": max_historical_days,
            "access_valid_for_days": access_valid_for_days,
            "access_scope": access_scope or ["balances", "details", "transactions"]
        }

        return self._request("POST", "agreements/enduser/", data)

    # ==========================================
    # DATENBANK-INTEGRATION
    # ==========================================

    def sync_connection(self, connection_id: int) -> Dict:
        """
        Synchronisiert eine Bankverbindung (holt neue Transaktionen).

        Args:
            connection_id: ID der BankConnection in der DB

        Returns:
            Dict mit Sync-Ergebnis
        """
        with get_db() as session:
            connection = session.query(BankConnection).get(connection_id)

            if not connection:
                return {"error": "Verbindung nicht gefunden"}

            if connection.status != "active":
                return {"error": f"Verbindung nicht aktiv (Status: {connection.status})"}

            try:
                # Kontostände abrufen
                balances = self.get_account_balances(connection.account_id)
                if balances and not balances.get("error"):
                    balance_list = balances.get("balances", [])
                    for bal in balance_list:
                        if bal.get("balanceType") == "interimAvailable":
                            connection.balance_available = float(bal.get("balanceAmount", {}).get("amount", 0))
                        elif bal.get("balanceType") == "interimBooked":
                            connection.balance_booked = float(bal.get("balanceAmount", {}).get("amount", 0))

                # Transaktionen abrufen (letzte 30 Tage)
                date_from = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
                transactions = self.get_account_transactions(
                    connection.account_id,
                    date_from=date_from
                )

                new_count = 0
                if transactions and not transactions.get("error"):
                    # Gebuchte Transaktionen
                    for tx in transactions.get("transactions", {}).get("booked", []):
                        new_count += self._save_transaction(session, connection, tx, is_booked=True)

                    # Vorgemerkte Transaktionen
                    for tx in transactions.get("transactions", {}).get("pending", []):
                        new_count += self._save_transaction(session, connection, tx, is_booked=False)

                connection.last_sync = datetime.now()
                connection.sync_error = None
                session.commit()

                return {
                    "success": True,
                    "new_transactions": new_count,
                    "balance_available": connection.balance_available,
                    "balance_booked": connection.balance_booked
                }

            except Exception as e:
                connection.sync_error = str(e)
                session.commit()
                logger.error(f"Sync-Fehler: {e}")
                return {"error": str(e)}

    def _save_transaction(
        self,
        session,
        connection: BankConnection,
        tx_data: Dict,
        is_booked: bool
    ) -> int:
        """Speichert eine Transaktion in der Datenbank"""
        tx_id = tx_data.get("transactionId") or tx_data.get("internalTransactionId")

        # Prüfen ob bereits vorhanden
        existing = session.query(BankTransaction).filter(
            BankTransaction.transaction_id == tx_id
        ).first()

        if existing:
            return 0

        # Betrag ermitteln
        amount_data = tx_data.get("transactionAmount", {})
        amount = float(amount_data.get("amount", 0))
        currency = amount_data.get("currency", "EUR")

        # Datum parsen
        booking_date = None
        value_date = None

        if tx_data.get("bookingDate"):
            try:
                booking_date = datetime.strptime(tx_data["bookingDate"], "%Y-%m-%d")
            except:
                pass

        if tx_data.get("valueDate"):
            try:
                value_date = datetime.strptime(tx_data["valueDate"], "%Y-%m-%d")
            except:
                pass

        # Verwendungszweck zusammensetzen
        remittance_parts = []
        if tx_data.get("remittanceInformationUnstructured"):
            remittance_parts.append(tx_data["remittanceInformationUnstructured"])
        if tx_data.get("remittanceInformationStructured"):
            remittance_parts.append(tx_data["remittanceInformationStructured"])
        if tx_data.get("additionalInformation"):
            remittance_parts.append(tx_data["additionalInformation"])

        remittance = " | ".join(remittance_parts) if remittance_parts else None

        transaction = BankTransaction(
            connection_id=connection.id,
            user_id=connection.user_id,
            transaction_id=tx_id,
            booking_date=booking_date,
            value_date=value_date,
            amount=amount,
            currency=currency,
            creditor_name=tx_data.get("creditorName"),
            creditor_iban=tx_data.get("creditorAccount", {}).get("iban"),
            debtor_name=tx_data.get("debtorName"),
            debtor_iban=tx_data.get("debtorAccount", {}).get("iban"),
            remittance_info=remittance,
            reference=tx_data.get("endToEndId"),
            is_booked=is_booked
        )

        session.add(transaction)
        return 1

    def get_user_connections(self, user_id: int) -> List[Dict]:
        """Holt alle Bankverbindungen eines Benutzers"""
        with get_db() as session:
            connections = session.query(BankConnection).filter(
                BankConnection.user_id == user_id
            ).all()

            return [{
                'id': conn.id,
                'institution_name': conn.institution_name,
                'institution_logo': conn.institution_logo,
                'iban': conn.iban,
                'account_name': conn.account_name,
                'status': conn.status,
                'balance_available': conn.balance_available,
                'balance_booked': conn.balance_booked,
                'last_sync': conn.last_sync,
                'valid_until': conn.valid_until
            } for conn in connections]

    def get_transactions(
        self,
        user_id: int,
        connection_id: int = None,
        days: int = 30,
        limit: int = 100
    ) -> List[Dict]:
        """Holt Transaktionen aus der Datenbank"""
        with get_db() as session:
            query = session.query(BankTransaction).filter(
                BankTransaction.user_id == user_id
            )

            if connection_id:
                query = query.filter(BankTransaction.connection_id == connection_id)

            date_from = datetime.now() - timedelta(days=days)
            query = query.filter(BankTransaction.booking_date >= date_from)

            transactions = query.order_by(
                BankTransaction.booking_date.desc()
            ).limit(limit).all()

            return [{
                'id': tx.id,
                'date': tx.booking_date,
                'amount': tx.amount,
                'currency': tx.currency,
                'creditor': tx.creditor_name,
                'debtor': tx.debtor_name,
                'remittance': tx.remittance_info,
                'category': tx.category,
                'is_booked': tx.is_booked,
                'document_id': tx.document_id,
                'receipt_id': tx.receipt_id
            } for tx in transactions]


# Singleton-Instanz
_nordigen_service = None


def get_nordigen_service() -> NordigenService:
    """Gibt die Singleton-Instanz des Nordigen-Service zurück"""
    global _nordigen_service
    if _nordigen_service is None:
        _nordigen_service = NordigenService()
    return _nordigen_service
