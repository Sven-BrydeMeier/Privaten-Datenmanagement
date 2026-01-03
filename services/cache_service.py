"""
Cache-Service für schnellen Datenzugriff

Unterstützt:
- Redis (Upstash) für Cloud-Deployment
- In-Memory Cache als Fallback

Verwendung:
1. Erstelle kostenloses Konto bei https://upstash.com
2. Erstelle Redis-Datenbank
3. Füge in Streamlit Secrets hinzu:
   UPSTASH_REDIS_URL = "rediss://default:xxx@xxx.upstash.io:6379"
"""
import os
import json
import hashlib
import logging
from typing import Optional, Any, Union
from datetime import datetime, timedelta
from functools import wraps

logger = logging.getLogger(__name__)

# Versuche Redis zu importieren
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.info("Redis nicht verfügbar, verwende In-Memory Cache")


class CacheService:
    """
    Hybrid Cache Service mit Redis (primär) und In-Memory (Fallback).
    """

    def __init__(self):
        self._redis_client = None
        self._memory_cache = {}
        self._memory_expiry = {}
        self._initialized = False

    def _init_redis(self):
        """Initialisiert Redis-Verbindung wenn verfügbar."""
        if self._initialized:
            return

        self._initialized = True

        if not REDIS_AVAILABLE:
            logger.info("Redis-Bibliothek nicht installiert, verwende Memory-Cache")
            return

        # Versuche Redis-URL aus verschiedenen Quellen
        redis_url = None

        # 1. Streamlit Secrets
        try:
            import streamlit as st
            if hasattr(st, 'secrets'):
                if 'UPSTASH_REDIS_URL' in st.secrets:
                    redis_url = st.secrets['UPSTASH_REDIS_URL']
                elif 'REDIS_URL' in st.secrets:
                    redis_url = st.secrets['REDIS_URL']
        except Exception:
            pass

        # 2. Umgebungsvariablen
        if not redis_url:
            redis_url = os.environ.get('UPSTASH_REDIS_URL') or os.environ.get('REDIS_URL')

        if redis_url:
            try:
                self._redis_client = redis.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_timeout=5,
                    socket_connect_timeout=5
                )
                # Test connection
                self._redis_client.ping()
                logger.info("Redis-Verbindung erfolgreich hergestellt")
            except Exception as e:
                logger.warning(f"Redis-Verbindung fehlgeschlagen: {e}, verwende Memory-Cache")
                self._redis_client = None
        else:
            logger.info("Keine Redis-URL konfiguriert, verwende Memory-Cache")

    @property
    def is_redis_connected(self) -> bool:
        """Prüft ob Redis verbunden ist."""
        self._init_redis()
        return self._redis_client is not None

    def _generate_key(self, namespace: str, identifier: str) -> str:
        """Generiert einen Cache-Key."""
        return f"docmgmt:{namespace}:{identifier}"

    def _hash_content(self, content: Union[str, bytes]) -> str:
        """Erstellt einen Hash für Content-basierte Keys."""
        if isinstance(content, str):
            content = content.encode('utf-8')
        return hashlib.sha256(content).hexdigest()[:16]

    def get(self, namespace: str, key: str) -> Optional[Any]:
        """
        Holt einen Wert aus dem Cache.

        Args:
            namespace: Kategorie (z.B. 'ocr', 'ai', 'session')
            key: Eindeutiger Schlüssel

        Returns:
            Cached value oder None
        """
        self._init_redis()
        cache_key = self._generate_key(namespace, key)

        # Versuche Redis
        if self._redis_client:
            try:
                value = self._redis_client.get(cache_key)
                if value:
                    return json.loads(value)
            except Exception as e:
                logger.warning(f"Redis GET Fehler: {e}")

        # Fallback: Memory Cache
        if cache_key in self._memory_cache:
            # Prüfe Expiry
            expiry = self._memory_expiry.get(cache_key)
            if expiry and datetime.now() > expiry:
                del self._memory_cache[cache_key]
                del self._memory_expiry[cache_key]
                return None
            return self._memory_cache[cache_key]

        return None

    def set(self, namespace: str, key: str, value: Any, ttl_seconds: int = 3600) -> bool:
        """
        Speichert einen Wert im Cache.

        Args:
            namespace: Kategorie
            key: Eindeutiger Schlüssel
            value: Zu speichernder Wert (muss JSON-serialisierbar sein)
            ttl_seconds: Time-to-live in Sekunden (Standard: 1 Stunde)

        Returns:
            True wenn erfolgreich
        """
        self._init_redis()
        cache_key = self._generate_key(namespace, key)

        # Versuche Redis
        if self._redis_client:
            try:
                self._redis_client.setex(
                    cache_key,
                    ttl_seconds,
                    json.dumps(value, default=str)
                )
                return True
            except Exception as e:
                logger.warning(f"Redis SET Fehler: {e}")

        # Fallback: Memory Cache
        try:
            self._memory_cache[cache_key] = value
            self._memory_expiry[cache_key] = datetime.now() + timedelta(seconds=ttl_seconds)
            return True
        except Exception as e:
            logger.error(f"Memory Cache SET Fehler: {e}")
            return False

    def delete(self, namespace: str, key: str) -> bool:
        """Löscht einen Wert aus dem Cache."""
        self._init_redis()
        cache_key = self._generate_key(namespace, key)

        success = False

        if self._redis_client:
            try:
                self._redis_client.delete(cache_key)
                success = True
            except Exception:
                pass

        if cache_key in self._memory_cache:
            del self._memory_cache[cache_key]
            if cache_key in self._memory_expiry:
                del self._memory_expiry[cache_key]
            success = True

        return success

    def clear_namespace(self, namespace: str) -> int:
        """Löscht alle Keys in einem Namespace."""
        self._init_redis()
        pattern = self._generate_key(namespace, "*")
        deleted = 0

        if self._redis_client:
            try:
                keys = self._redis_client.keys(pattern)
                if keys:
                    deleted = self._redis_client.delete(*keys)
            except Exception as e:
                logger.warning(f"Redis clear Fehler: {e}")

        # Memory Cache
        prefix = self._generate_key(namespace, "")
        to_delete = [k for k in self._memory_cache.keys() if k.startswith(prefix)]
        for k in to_delete:
            del self._memory_cache[k]
            if k in self._memory_expiry:
                del self._memory_expiry[k]
            deleted += 1

        return deleted

    # ==================== SPEZIALISIERTE CACHE-METHODEN ====================

    def get_ocr_result(self, file_hash: str) -> Optional[str]:
        """Holt gecachtes OCR-Ergebnis für eine Datei."""
        return self.get('ocr', file_hash)

    def set_ocr_result(self, file_hash: str, text: str, ttl_days: int = 30) -> bool:
        """Cached OCR-Ergebnis für eine Datei."""
        return self.set('ocr', file_hash, text, ttl_seconds=ttl_days * 86400)

    def get_ai_response(self, prompt_hash: str) -> Optional[dict]:
        """Holt gecachte KI-Antwort."""
        return self.get('ai', prompt_hash)

    def set_ai_response(self, prompt_hash: str, response: dict, ttl_hours: int = 24) -> bool:
        """Cached KI-Antwort."""
        return self.set('ai', prompt_hash, response, ttl_seconds=ttl_hours * 3600)

    def get_document_metadata(self, doc_id: int) -> Optional[dict]:
        """Holt gecachte Dokument-Metadaten."""
        return self.get('doc', str(doc_id))

    def set_document_metadata(self, doc_id: int, metadata: dict, ttl_minutes: int = 60) -> bool:
        """Cached Dokument-Metadaten."""
        return self.set('doc', str(doc_id), metadata, ttl_seconds=ttl_minutes * 60)

    def invalidate_document(self, doc_id: int) -> bool:
        """Invalidiert Cache für ein Dokument."""
        return self.delete('doc', str(doc_id))

    def get_status(self) -> dict:
        """Gibt Cache-Status zurück."""
        self._init_redis()

        status = {
            'type': 'redis' if self._redis_client else 'memory',
            'connected': self._redis_client is not None,
            'memory_entries': len(self._memory_cache),
            'redis_info': None
        }

        if self._redis_client:
            try:
                info = self._redis_client.info('memory')
                status['redis_info'] = {
                    'used_memory_human': info.get('used_memory_human', 'unknown'),
                    'connected_clients': info.get('connected_clients', 0)
                }
            except Exception:
                pass

        return status


# Singleton-Instanz
_cache_service = None


def get_cache_service() -> CacheService:
    """Gibt die Cache-Service Singleton-Instanz zurück."""
    global _cache_service
    if _cache_service is None:
        _cache_service = CacheService()
    return _cache_service


def cached(namespace: str, ttl_seconds: int = 3600, key_func=None):
    """
    Decorator für automatisches Caching von Funktionsergebnissen.

    Args:
        namespace: Cache-Namespace
        ttl_seconds: Time-to-live
        key_func: Optionale Funktion zur Key-Generierung (erhält *args, **kwargs)

    Beispiel:
        @cached('ocr', ttl_seconds=86400)
        def process_document(file_path: str) -> str:
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache = get_cache_service()

            # Generiere Cache-Key
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                # Standard: Hash aus Funktionsname + Args
                key_data = f"{func.__name__}:{str(args)}:{str(sorted(kwargs.items()))}"
                cache_key = hashlib.md5(key_data.encode()).hexdigest()

            # Versuche aus Cache zu laden
            cached_result = cache.get(namespace, cache_key)
            if cached_result is not None:
                logger.debug(f"Cache HIT: {namespace}:{cache_key[:8]}...")
                return cached_result

            # Führe Funktion aus
            result = func(*args, **kwargs)

            # Speichere im Cache
            if result is not None:
                cache.set(namespace, cache_key, result, ttl_seconds)
                logger.debug(f"Cache SET: {namespace}:{cache_key[:8]}...")

            return result
        return wrapper
    return decorator
