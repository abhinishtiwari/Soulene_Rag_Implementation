"""Memory package.

Layer 2 (durable user profile memory) lives here. The conversation working set
is NOT here — it is the CAG context cache (`app/cag/context_cache.py`), and the
full transcript is the chat archive (`app/storage/chat_archive.py`).
"""

from app.memory.long_term_memory import LongTermMemory

# Canonical spec name for Layer 2.
ProfileMemory = LongTermMemory

__all__ = ["LongTermMemory", "ProfileMemory"]
