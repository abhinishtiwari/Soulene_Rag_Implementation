from __future__ import annotations

import json
from pathlib import Path

RUN_ROOT = Path(__file__).resolve().parents[1]


def validate(entries, edges, subsystems, unresolved):
    ids = [row["id"] for row in entries]
    assert len(ids) == len(set(ids)) and {row["kind"] for row in entries} == {"user", "executable", "test", "deployment"}
    entry_ids = set(ids)
    required_edge = {"source_component","destination_component","validation","authentication","authorization","trust_boundary","failure_behavior","backend_variant","evidence_refs"}
    assert edges and all(row["entry_point_id"] in entry_ids and required_edge <= set(row) for row in edges)
    assert all(value["files"] and value["interfaces"] and value["upstream"] and value["downstream"] for value in subsystems.values())
    assert all(row["path"] and row["missing_evidence"] for row in unresolved)


def main():
    architecture = RUN_ROOT / "architecture"
    entries = json.loads((architecture / "entrypoints.json").read_text(encoding="utf-8"))
    edges = [json.loads(line) for line in (architecture / "trace-edges.jsonl").read_text(encoding="utf-8").splitlines() if line]
    subsystems = json.loads((architecture / "subsystems.json").read_text(encoding="utf-8"))
    unresolved = json.loads((architecture / "unresolved-paths.json").read_text(encoding="utf-8"))
    validate(entries, edges, subsystems, unresolved)
    # Negative synthetic examples: incomplete trust edge, duplicate entry ID, isolated subsystem without rationale.
    try:
        validate(entries + [dict(entries[0])], edges, subsystems, unresolved)
    except AssertionError:
        pass
    else:
        raise AssertionError("duplicate entry ID accepted")
    bad_edge = dict(edges[0]); bad_edge.pop("authorization")
    try:
        validate(entries, [bad_edge], subsystems, unresolved)
    except AssertionError:
        pass
    else:
        raise AssertionError("incomplete trust edge accepted")
    result = {"status":"passed","entrypoints":len(entries),"edges":len(edges),"subsystems":len(subsystems),"negative_examples":2}
    (RUN_ROOT / "validation" / "architecture-result.json").write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
