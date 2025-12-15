"""
Volltext-Suchservice mit Whoosh
"""
import os
import warnings
from typing import List, Dict, Optional
from datetime import datetime
import streamlit as st

from config.settings import INDEX_DIR

# Whoosh-Warnungen unterdrücken (Kompatibilitätsprobleme mit Python 3.13)
warnings.filterwarnings('ignore', category=SyntaxWarning, module='whoosh')


class SearchService:
    """Volltext-Suchservice für Dokumente"""

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.index_dir = INDEX_DIR / str(user_id)
        self._index = None
        self._index_available = True
        try:
            self._ensure_index()
        except Exception as e:
            self._index_available = False
            # Stille Warnung - Suche ist optional
            pass

    def _ensure_index(self):
        """Stellt sicher dass der Index existiert"""
        try:
            os.makedirs(self.index_dir, exist_ok=True)

            from whoosh.fields import Schema, TEXT, ID, NUMERIC, DATETIME, KEYWORD
            from whoosh.index import create_in, open_dir, exists_in

            # Schema definieren
            schema = Schema(
                id=ID(stored=True, unique=True),
                title=TEXT(stored=True),
                content=TEXT(stored=True),
                sender=TEXT(stored=True),
                category=KEYWORD(stored=True),
                folder_id=ID(stored=True),
                document_date=DATETIME(stored=True),
                amounts=TEXT(stored=True),  # Komma-getrennte Beträge
                ibans=TEXT(stored=True),    # Komma-getrennte IBANs
                contract_numbers=TEXT(stored=True),
                created_at=DATETIME(stored=True)
            )

            if exists_in(self.index_dir):
                self._index = open_dir(self.index_dir)
            else:
                self._index = create_in(self.index_dir, schema)
            self._index_available = True
        except Exception as e:
            self._index_available = False
            self._index = None

    @property
    def index(self):
        """Lazy-Loading des Index"""
        if self._index is None and self._index_available:
            self._ensure_index()
        return self._index

    def index_document(self, document_id: int, data: Dict):
        """
        Fügt ein Dokument zum Index hinzu.

        Args:
            document_id: Dokument-ID
            data: Dokumentdaten zum Indexieren
        """
        if not self._index_available or self._index is None:
            return  # Stille Rückkehr wenn Index nicht verfügbar

        try:
            from whoosh.writing import AsyncWriter

            writer = AsyncWriter(self.index)

            # Beträge und IBANs als durchsuchbare Strings
            amounts_str = ','.join(str(a) for a in data.get('amounts', []))
            ibans_str = ','.join(data.get('ibans', []))
            contracts_str = ','.join(data.get('contract_numbers', []))

            writer.update_document(
                id=str(document_id),
                title=data.get('title', ''),
                content=data.get('content', ''),
                sender=data.get('sender', ''),
                category=data.get('category', ''),
                folder_id=str(data.get('folder_id', '')),
                document_date=data.get('document_date'),
                amounts=amounts_str,
                ibans=ibans_str,
                contract_numbers=contracts_str,
                created_at=data.get('created_at', datetime.now())
            )

            writer.commit()
        except Exception:
            # Indexierungsfehler ignorieren - Dokument wurde trotzdem gespeichert
            pass

    def remove_document(self, document_id: int):
        """Entfernt ein Dokument aus dem Index"""
        if not self._index_available or self._index is None:
            return

        try:
            from whoosh.writing import AsyncWriter

            writer = AsyncWriter(self.index)
            writer.delete_by_term('id', str(document_id))
            writer.commit()
        except Exception:
            pass

    def search(
        self,
        query: str,
        filters: Optional[Dict] = None,
        limit: int = 50,
        page: int = 1
    ) -> Dict:
        """
        Durchsucht den Index.

        Args:
            query: Suchanfrage
            filters: Optionale Filter (category, folder_id, date_from, date_to)
            limit: Maximale Ergebnisse pro Seite
            page: Seitennummer

        Returns:
            Dictionary mit Ergebnissen und Metadaten
        """
        results = {
            'items': [],
            'total': 0,
            'page': page,
            'pages': 0
        }

        if not self._index_available or self._index is None:
            return results

        try:
            from whoosh.qparser import MultifieldParser, OrGroup
            from whoosh.query import And, Term, DateRange

            with self.index.searcher() as searcher:
                # Multi-Feld-Parser für Freitextsuche
                parser = MultifieldParser(
                    ['title', 'content', 'sender', 'amounts', 'ibans', 'contract_numbers'],
                    self.index.schema,
                    group=OrGroup
                )

                try:
                    q = parser.parse(query)
                except Exception:
                    # Bei Parse-Fehlern als exakte Phrase suchen
                    q = parser.parse(f'"{query}"')

                # Filter anwenden
                filter_queries = []

                if filters:
                    if filters.get('category'):
                        filter_queries.append(Term('category', filters['category']))

                    if filters.get('folder_id'):
                        filter_queries.append(Term('folder_id', str(filters['folder_id'])))

                    if filters.get('date_from') or filters.get('date_to'):
                        filter_queries.append(DateRange(
                            'document_date',
                            start=filters.get('date_from'),
                            end=filters.get('date_to')
                        ))

                # Kombiniere Query mit Filtern
                if filter_queries:
                    q = And([q] + filter_queries)

                # Suche ausführen
                offset = (page - 1) * limit
                search_results = searcher.search(q, limit=None)

                results['total'] = len(search_results)
                results['pages'] = (results['total'] + limit - 1) // limit

                # Paginierte Ergebnisse
                for hit in search_results[offset:offset + limit]:
                    results['items'].append({
                        'id': int(hit['id']),
                        'title': hit.get('title', ''),
                        'sender': hit.get('sender', ''),
                        'category': hit.get('category', ''),
                        'folder_id': hit.get('folder_id'),
                        'document_date': hit.get('document_date'),
                        'score': hit.score,
                        'highlights': hit.highlights('content', top=3)
                    })
        except Exception:
            # Suchfehler ignorieren - leere Ergebnisse zurückgeben
            pass

        return results

    def search_by_amount(self, amount: float, tolerance: float = 0.01) -> List[int]:
        """
        Sucht Dokumente mit einem bestimmten Betrag.

        Args:
            amount: Gesuchter Betrag
            tolerance: Toleranz für Betragsvergleich

        Returns:
            Liste von Dokument-IDs
        """
        # Formatiere Betrag für Textsuche
        amount_str = f"{amount:.2f}"
        results = self.search(amount_str, limit=100)
        return [item['id'] for item in results['items']]

    def search_by_iban(self, iban: str) -> List[int]:
        """
        Sucht Dokumente mit einer bestimmten IBAN.

        Args:
            iban: Die IBAN

        Returns:
            Liste von Dokument-IDs
        """
        # IBAN normalisieren (Leerzeichen entfernen)
        iban_clean = iban.replace(' ', '').upper()
        results = self.search(iban_clean, limit=100)
        return [item['id'] for item in results['items']]

    def rebuild_index(self):
        """Baut den gesamten Index neu auf"""
        from database import get_db, Document

        # Alten Index löschen
        import shutil
        if self.index_dir.exists():
            shutil.rmtree(self.index_dir)

        # Neu erstellen
        self._index = None
        self._ensure_index()

        # Alle Dokumente des Benutzers indexieren
        with get_db() as session:
            documents = session.query(Document).filter(
                Document.user_id == self.user_id
            ).all()

            for doc in documents:
                self.index_document(doc.id, {
                    'title': doc.title or doc.filename,
                    'content': doc.ocr_text or '',
                    'sender': doc.sender or '',
                    'category': doc.category or '',
                    'folder_id': doc.folder_id,
                    'document_date': doc.document_date,
                    'amounts': [doc.invoice_amount] if doc.invoice_amount else [],
                    'ibans': [doc.iban] if doc.iban else [],
                    'contract_numbers': [doc.contract_number] if doc.contract_number else [],
                    'created_at': doc.created_at
                })


def get_search_service(user_id: int) -> SearchService:
    """Factory für SearchService"""
    key = f'search_service_{user_id}'
    if key not in st.session_state:
        st.session_state[key] = SearchService(user_id)
    return st.session_state[key]
