"""
similarity_engine.py — Compares document skeletons to measure structural similarity.

Algorithm (combined score out of 100%):
  75% — Sequence similarity: difflib.SequenceMatcher measures character/phrase alignment.
         Two documents from the same template share identical headings and field labels.
  25% — Line count ratio: min(lines_a, lines_b) / max(lines_a, lines_b).
         Ensures matching templates have a similar overall structure length.
"""

import difflib
import itertools
import json
from pathlib import Path


def compute_similarity(skeleton_a: str, skeleton_b: str) -> dict:
    """
    Calculate a similarity score (0–100) between two masked document skeletons.

    Returns a dict with:
      sequence_sim   — raw difflib ratio (0.0–1.0)
      feature_sim    — line count ratio (0.0–1.0)
      combined_score — weighted final score (0.0–100.0)
    """
    seq_sim  = difflib.SequenceMatcher(None, skeleton_a, skeleton_b, autojunk=False).ratio()

    lines_a  = sum(1 for line in skeleton_a.splitlines() if line.strip())
    lines_b  = sum(1 for line in skeleton_b.splitlines() if line.strip())
    line_sim = min(lines_a, lines_b) / max(lines_a, lines_b, 1)

    combined = (0.75 * seq_sim + 0.25 * line_sim) * 100.0

    return {
        "sequence_sim":   round(seq_sim,  4),
        "feature_sim":    round(line_sim, 4),
        "combined_score": round(combined, 1),
    }


def compare_all_pairs(extractions: dict) -> list:
    """
    Compare every same-type pair of documents in the dataset.

    Cross-type pairs (e.g. invoice vs lab report) are skipped — they are
    structurally unrelated and would only add noise to the results.

    Returns a list of comparison records sorted by score descending.
    """
    doc_ids = sorted(extractions.keys())
    results = []
    skipped = 0

    for doc_a, doc_b in itertools.combinations(doc_ids, 2):
        type_a = extractions[doc_a].get("doc_type")
        type_b = extractions[doc_b].get("doc_type")

        if type_a and type_b and type_a != type_b:
            skipped += 1
            continue

        scores = compute_similarity(extractions[doc_a]["skeleton"], extractions[doc_b]["skeleton"])
        results.append({"doc_id_a": doc_a, "doc_id_b": doc_b, "doc_type": type_a or "unknown", **scores})

    results.sort(key=lambda r: r["combined_score"], reverse=True)
    print(f"[similarity_engine] Compared {len(results)} same-type pairs (skipped {skipped} cross-type) across {len(doc_ids)} documents.")
    return results


def compare_one_vs_all(new_doc: dict, extractions: dict) -> list:
    """
    Compare a single new document against every document in the existing dataset.
    Used for the `analyze --file <path>` CLI option.

    Returns a list of comparison records sorted by score descending.
    """
    new_id   = new_doc["doc_id"]
    new_skel = new_doc["skeleton"]

    results = [
        {"doc_id_a": new_id, "doc_id_b": doc_id, "doc_type": info.get("doc_type", "unknown"),
         **compute_similarity(new_skel, info["skeleton"])}
        for doc_id, info in extractions.items()
    ]

    results.sort(key=lambda r: r["combined_score"], reverse=True)
    print(f"[similarity_engine] Compared '{new_id}' against {len(extractions)} existing documents.")
    return results


def save_results(results: list, output_path: str) -> None:
    """Save pairwise similarity results to a JSON file."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"[similarity_engine] Similarity results saved -> {output_path}")
