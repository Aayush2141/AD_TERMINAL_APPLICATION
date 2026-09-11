"""
similarity_engine.py
====================
Compares pairs of document skeletons to produce a similarity score (0–100 %).

Two-component scoring
---------------------
We combine two complementary measures so that neither alone can produce a
false positive:

1. **Sequence similarity** (weight 70 %)
   Uses ``difflib.SequenceMatcher`` on the full skeleton text.  This catches
   when the same structural phrases, labels, and placeholder patterns appear in
   the same order – which is very characteristic of a shared template.

2. **Structural feature similarity** (weight 30 %)
   Compares a small vector of coarse structural features extracted from the
   skeleton:
     - Number of non-empty lines
     - Number of unique placeholder token types present (<DATE>, <AMOUNT>, …)
     - Number of section-header-like lines (ALL CAPS lines)
     - Whether a separator line (====, ----) is present
     - Length of the skeleton in characters
   These features catch cases where two skeletons look different character-for-
   character but share the same high-level structure (e.g. same number of
   sections, same field types).

Final score = 0.70 × sequence_sim + 0.30 × feature_sim, scaled to 0–100.
"""

import difflib
import itertools
import json
import re
from pathlib import Path


# Placeholder tokens that the extractor inserts
_PLACEHOLDER_TOKENS = {
    "<REF_ID>", "<DATE>", "<AMOUNT>", "<DOCTOR>",
    "<PERCENT>", "<NUMBER>", "<QTY>", "<NAME>",
}

# Pattern for separator lines (all dashes, equals, asterisks, hashes)
_RE_SEPARATOR = re.compile(r"^[\-=\*#\>< ]{5,}$")

# Pattern for ALL-CAPS section header lines (at least 4 consecutive caps)
_RE_HEADER = re.compile(r"\b[A-Z]{4,}(?:\s+[A-Z]+)*\b")


def _extract_features(skeleton: str) -> dict:
    """
    Compute a small set of structural features from a skeleton string.
    These features are template-level properties that survive the masking step.

    Args:
        skeleton : The masked skeleton text (output of template_extractor).

    Returns:
        dict with numeric/boolean feature values.
    """
    lines = skeleton.splitlines()
    non_empty = [ln for ln in lines if ln.strip()]

    # Which placeholder types appear in this skeleton?
    present_tokens = {tok for tok in _PLACEHOLDER_TOKENS if tok in skeleton}

    # Count lines that look like ALL-CAPS section headers
    header_lines = sum(1 for ln in non_empty if _RE_HEADER.search(ln))

    # Does the document use separator lines?
    has_separator = any(_RE_SEPARATOR.match(ln.strip()) for ln in lines)

    return {
        "line_count": len(non_empty),
        "token_types": len(present_tokens),
        "header_lines": header_lines,
        "has_separator": int(has_separator),   # 1 / 0 for easy arithmetic
        "char_len": len(skeleton),
    }


def _feature_similarity(feat_a: dict, feat_b: dict) -> float:
    """
    Compute a 0–1 similarity score between two feature dicts.

    Each numeric feature contributes a normalised closeness score:
        1 - |a - b| / max(a, b, 1)
    Boolean features contribute 1.0 if equal, 0.0 otherwise.
    All contributions are averaged.

    Args:
        feat_a, feat_b : Feature dicts from _extract_features().

    Returns:
        Float in [0, 1].
    """
    scores = []

    for key in ("line_count", "token_types", "header_lines", "char_len"):
        a, b = feat_a[key], feat_b[key]
        denom = max(a, b, 1)
        scores.append(1.0 - abs(a - b) / denom)

    # Boolean feature
    scores.append(1.0 if feat_a["has_separator"] == feat_b["has_separator"] else 0.0)

    return sum(scores) / len(scores)


def compute_similarity(skeleton_a: str, skeleton_b: str) -> dict:
    """
    Compute the combined similarity score between two skeleton strings.

    Args:
        skeleton_a : Masked skeleton of document A.
        skeleton_b : Masked skeleton of document B.

    Returns:
        dict with keys:
            'sequence_sim'  – SequenceMatcher ratio (0–1)
            'feature_sim'   – structural feature similarity (0–1)
            'combined_score'– weighted combined score (0–100, rounded to 1 dp)
    """
    # Sequence similarity (character-level)
    seq_sim = difflib.SequenceMatcher(
        None, skeleton_a, skeleton_b, autojunk=False
    ).ratio()

    # Feature similarity
    feat_a = _extract_features(skeleton_a)
    feat_b = _extract_features(skeleton_b)
    feat_sim = _feature_similarity(feat_a, feat_b)

    # Weighted combination
    combined = (0.70 * seq_sim + 0.30 * feat_sim) * 100

    return {
        "sequence_sim": round(seq_sim, 4),
        "feature_sim": round(feat_sim, 4),
        "combined_score": round(combined, 1),
    }


def compare_all_pairs(extractions: dict) -> list:
    """
    Compare every unique pair of extracted skeletons **of the same document
    type** and return a list of result records sorted by combined_score
    descending.

    Why same-type only?
    -------------------
    An invoice and a lab report will never be fraudulently confused with each
    other — they are completely different document types.  Comparing across
    types creates noise (cross-type pairs always score low) and bloats the
    output.  Restricting to same-type pairs cuts the search space by ~67 % and
    eliminates an entire category of false positives.

    The doc_type is stored in each extraction result dict under the key
    'doc_type'.  If that key is missing (e.g. for externally loaded docs),
    the pair is still compared as a fallback.

    Args:
        extractions : dict of doc_id → extraction result (from template_extractor.extract_all).

    Returns:
        List of dicts, one per same-type pair:
            'doc_id_a', 'doc_id_b', 'doc_type', 'sequence_sim', 'feature_sim', 'combined_score'
    """
    doc_ids = sorted(extractions.keys())
    pairs = list(itertools.combinations(doc_ids, 2))

    results = []
    skipped = 0
    for doc_a, doc_b in pairs:
        type_a = extractions[doc_a].get("doc_type")
        type_b = extractions[doc_b].get("doc_type")

        # Skip cross-type comparisons (they're never fraud and add noise)
        if type_a and type_b and type_a != type_b:
            skipped += 1
            continue

        skel_a = extractions[doc_a]["skeleton"]
        skel_b = extractions[doc_b]["skeleton"]
        scores = compute_similarity(skel_a, skel_b)
        results.append({
            "doc_id_a": doc_a,
            "doc_id_b": doc_b,
            "doc_type": type_a or "unknown",
            **scores,
        })

    # Sort highest similarity first – makes the flagging output easy to scan
    results.sort(key=lambda r: r["combined_score"], reverse=True)

    compared = len(results)
    print(
        f"[similarity_engine] Compared {compared} same-type pairs "
        f"(skipped {skipped} cross-type pairs) across {len(doc_ids)} documents."
    )
    return results


def compare_one_vs_all(new_doc_extraction: dict, dataset_extractions: dict) -> list:
    """
    Compare a single new document's skeleton against every document already
    in the dataset.  Returns results sorted by combined_score descending.

    Used for the `analyze --file <path>` CLI mode.

    Args:
        new_doc_extraction   : Extraction result dict for the new document.
        dataset_extractions  : dict of doc_id → extraction results for existing docs.

    Returns:
        List of comparison dicts sorted by combined_score descending.
    """
    new_id = new_doc_extraction["doc_id"]
    new_skel = new_doc_extraction["skeleton"]

    results = []
    for doc_id, ext in dataset_extractions.items():
        scores = compute_similarity(new_skel, ext["skeleton"])
        results.append({
            "doc_id_a": new_id,
            "doc_id_b": doc_id,
            **scores,
        })

    results.sort(key=lambda r: r["combined_score"], reverse=True)
    print(f"[similarity_engine] Compared new document '{new_id}' against {len(dataset_extractions)} docs.")
    return results


def save_results(results: list, output_path: str) -> None:
    """
    Write comparison results to a JSON file at *output_path*.

    Args:
        results     : List of comparison dicts.
        output_path : Where to write the JSON file.
    """
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"[similarity_engine] Results saved → {output_path}")
