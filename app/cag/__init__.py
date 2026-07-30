"""Cache-Augmented Generation (CAG) layer.

The cache is the PRIMARY retrieval mechanism. There is no vector search in the
request path. Documents are preprocessed once into a knowledge cache that is
held in memory and injected directly into the model context.

Modules:
    document_processor - extract / clean / structure uploaded documents
    knowledge_cache    - Layer 4: preprocessed, indexed document knowledge
    context_cache      - conversation working set (recent 50-100 messages)
    response_cache     - reuse prior answers to avoid LLM calls
    cag_engine         - orchestrates cache lookup before any LLM call
"""
