"""CLI: build / refresh the CAG knowledge cache from the knowledge/ folder.

    python build_cache.py            # incremental (skips unchanged documents)
    python build_cache.py --force    # rebuild everything
    python build_cache.py --stats    # show cache stats only
"""

from __future__ import annotations

import json
import sys

from app.cag.cag_engine import CAGEngine
from app.config.settings import Settings


def main() -> None:
    settings = Settings.from_env()
    engine = CAGEngine(
        knowledge_dir=settings.knowledge_path,
        cache_dir=settings.root / "cache",
        token_budget=settings.knowledge_token_budget,
    )

    if "--stats" in sys.argv:
        engine.knowledge.load()
        print(json.dumps(engine.knowledge.stats(), indent=2))
        return

    force = "--force" in sys.argv
    if not force:
        engine.knowledge.load()
    report = engine.knowledge.refresh(force=force)

    print(f"status   : {report['status']}")
    print(f"documents: {report.get('documents')} "
          f"(new={report.get('new', 0)} changed={report.get('changed', 0)} "
          f"removed={report.get('removed', 0)} unchanged={report.get('unchanged', 0)})")
    print(f"sections : {report.get('sections')}")
    print(f"tokens   : ~{report.get('approx_tokens')} / budget {report.get('token_budget')}")
    print(f"mode     : {'FULL PRELOAD (true CAG)' if report.get('full_preload') else 'lexically narrowed'}")
    for doc in engine.knowledge.documents():
        print(f"  - {doc['document']} [{doc['knowledge_type']}] "
              f"v{doc['version']} sections={doc['sections']}")


if __name__ == "__main__":
    main()
