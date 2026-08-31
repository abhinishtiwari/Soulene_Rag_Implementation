"""Shared MongoDB Atlas connection — single MongoClient, reused everywhere.

Returns None if MONGO_URI is not set (falls back to JSON locally).
On Render (Linux + Python 3.12), this connects fine.
"""

from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)

_client = None
_db = None
_initialized = False


def get_mongo_db(uri: str = "", db_name: str = ""):
    """Return the configured authoritative Mongo database or raise."""
    global _client, _db, _initialized

    if _initialized:
        if _db is None:
            raise RuntimeError("MongoDB was not initialized")
        return _db
    if not uri or not db_name:
        raise RuntimeError("MongoDB requires both MONGO_URI and DB_NAME")

    from pymongo import MongoClient
    import certifi

    options = dict(
        maxPoolSize=20,
        minPoolSize=1,
        maxIdleTimeMS=45000,
        connectTimeoutMS=10000,
        serverSelectionTimeoutMS=10000,
        retryWrites=True,
        retryReads=True,
    )
    if uri.startswith("mongodb+srv://"):
        options["tlsCAFile"] = certifi.where()
    _client = MongoClient(uri, **options)
    _client.admin.command("ping")
    _db = _client[db_name]
    _initialized = True
    log.info("MongoDB connected: db=%s", db_name)
    return _db


def reset_mongo():
    """Reset connection (for testing)."""
    global _client, _db, _initialized
    if _client:
        try:
            _client.close()
        except Exception:
            pass
    _client = None
    _db = None
    _initialized = False
