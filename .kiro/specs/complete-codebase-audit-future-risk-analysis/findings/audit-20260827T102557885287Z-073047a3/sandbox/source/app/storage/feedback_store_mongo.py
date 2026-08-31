"""MongoDB-backed feedback store, isolated from chat storage."""

from __future__ import annotations

from typing import List, Optional

from pymongo import ASCENDING, DESCENDING

from app.storage.feedback_store import FeedbackItem, VALID_CATEGORIES


class FeedbackStoreMongo:
    """MongoDB-backed drop-in replacement for ``FeedbackStore``."""

    COLLECTION = "feedback"

    def __init__(self, db) -> None:
        self._db = db
        self._col = db[self.COLLECTION]
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        self._col.create_index(
            [("feedback_id", ASCENDING)], unique=True, name="uq_feedback_id"
        )
        self._col.create_index([("user_id", ASCENDING)], name="ix_feedback_owner")
        self._col.create_index([("category", ASCENDING)], name="ix_feedback_category")
        self._col.create_index([("created_at", DESCENDING)], name="ix_feedback_created")

    def submit(self, user_id: str, message: str, category: str = "other") -> FeedbackItem:
        category = (category or "other").lower().strip()
        if category not in VALID_CATEGORIES:
            category = "other"
        item = FeedbackItem(user_id=user_id, category=category, message=message.strip())
        self._col.insert_one({
            "feedback_id": item.feedback_id, "user_id": item.user_id,
            "category": item.category, "message": item.message,
            "created_at": item.created_at, "status": item.status,
        })
        return item

    def list_feedback(self, category: Optional[str] = None, limit: int = 100) -> List[FeedbackItem]:
        if limit == 0:
            return []
        query = {"category": category} if category else {}
        cursor = self._col.find(query).sort("created_at", DESCENDING).limit(limit)
        return [FeedbackItem(feedback_id=row["feedback_id"], user_id=row["user_id"],
                             category=row["category"], message=row["message"],
                             created_at=row["created_at"], status=row["status"])
                for row in cursor]

    def count(self, user_id: Optional[str] = None) -> int:
        query = {"user_id": user_id} if user_id else {}
        return int(self._col.count_documents(query))

    def delete_user(self, user_id: str) -> None:
        self._col.delete_many({"user_id": user_id})

    def close(self) -> None:
        """The shared MongoClient is owned by ``mongo_client``."""
