"""
template_extractor.py
=====================
Converts a raw document into a "skeleton" by replacing all variable fields
(names, dates, amounts, IDs, etc.) with typed placeholder tokens.

Why this works for fraud detection
-----------------------------------
Two documents generated from the same template will contain different patient
names, dates, amounts, and provider names – so a naive text comparison sees
them as very different.  But once we *mask out* those variable fields, what
remains is the structural skeleton: the same labels, same section headers,
same line order, same punctuation, same surrounding text.  Comparing skeletons
therefore compares *structure*, not content.

Masking rules (applied in order, so longer / more specific patterns win)
------------------------------------------------------------------------
1. Claim / Bill / Report reference IDs (CLMxxxxxx, PATxxxxx, PRVxxxx) → <REF_ID>
2. Dates (DD-MM-YYYY, YYYY-MM-DD, etc.)  → <DATE>
3. Indian Rupee amounts (INR + digits)   → <AMOUNT>
4. Doctor names (Dr. Firstname Lastname) → <DOCTOR>
5. Percentages (18%)                     → <PERCENT>
6. Decimal numbers / result values       → <NUMBER>
7. Quantity notation (x2, x3 …)         → <QTY>
8. Patient names: lines where label is 'Patient' / 'Claimant' / 'Member' / 'Name' → <PATIENT_NAME>
9. Provider names: lines where label is 'Provider' / 'Lab:' / 'Issued By' etc.    → <PROVIDER_NAME>
10. Remaining large integers (3+ digits) → <NUMBER>

Key design decision – line-aware name masking
---------------------------------------------
Instead of a greedy proper-noun regex that destroys document labels, we scan
each line for a known field-label prefix and mask only the VALUE portion.
This preserves structural labels ("Provider   :", "Patient    :") which are
the most distinctive part of the skeleton, while still removing the
identifying content after the colon.
"""

import re
from pathlib import Path


# ---------------------------------------------------------------------------
# Compiled regex patterns (ordered from most to least specific)
# ---------------------------------------------------------------------------

# Reference / claim IDs like CLM123456, PRV1001, PAT12345
_RE_REF_ID = re.compile(r"\b(CLM\d{5,}|PRV\d{3,}|PAT\d{4,})\b")

# Dates: 01-01-2024, 2024-01-01, 01/01/2024, January 1 2024
_RE_DATE = re.compile(
    r"\b(?:\d{1,2}[-/]\d{1,2}[-/]\d{2,4}"
    r"|\d{4}[-/]\d{2}[-/]\d{2}"
    r"|(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
    r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+\d{1,2},?\s+\d{4})\b",
    re.IGNORECASE,
)

# Indian Rupee amounts: INR 1234 or INR 12,345
_RE_INR = re.compile(r"\bINR\s+[\d,]+\b", re.IGNORECASE)

# Doctor names: "Dr. Firstname Lastname"
_RE_DOCTOR = re.compile(r"\bDr\.\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b")

# Percentages: 18%
_RE_PERCENT = re.compile(r"\b\d+(\.\d+)?%")

# Decimal numbers (lab values like "132.50"): must have a decimal point
_RE_DECIMAL = re.compile(r"\b\d+\.\d+\b")

# Quantity notation used in prescriptions: x2, x3
_RE_QTY = re.compile(r"\bx\d+\b", re.IGNORECASE)

# Standalone integers that look like meaningful values (≥ 3 digits)
_RE_INTEGER = re.compile(r"\b\d{3,}\b")

# Drug dosages like "500mg", "60000IU", "20mg" — variable medical content
_RE_DOSAGE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:mg|mcg|ml|IU|g|units?|tab|caps?)\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Line-aware name masking
# ---------------------------------------------------------------------------
# Labels that indicate the REST of the line (after the colon) is a
# human name or provider name – to be masked without touching the label.
#
# The pattern captures:
#   Group 1: the label + colon/separator (preserved)
#   Group 2: everything after the separator (masked)
#
# We use a generous "separator" that allows : | [ and surrounding spaces.

_PATIENT_LABELS = (
    r"Patient(?:\s+Name)?\s*[:\|]",
    r"Full\s+Name\s*[:\|]",
    r"Patient\s+Name\s*[:\|]",
    r"Claimant\s*[:\|]",
    r"Patient\s*:",
    r"Name\s*:",          # inside indented blocks like "  Name  :"
    r"UHI\s*:",
)

_PROVIDER_LABELS = (
    r"Provider\s*[:\|]",
    r"Issued\s+By\s*[:\|]",
    r"Lab\s*:",
    r"Facility\s*[:\|]",
    r"Institution\s*[:\|]",
    r"Clinic\s*[:\|]",
    r"Practitioner\s*[:\|]",
    r"Referring\s+Dr\s*[:\|]",
    r"Laboratory\s*[:\|]",
    r"Pathologist\s*[:\|]",
    r"Verified\s+By\s*[:\|]",
)

# Build combined patterns: match label, then capture the rest of line as value
_build_label_re = lambda labels: re.compile(
    r"(" + "|".join(labels) + r")\s*(.*)",
    re.IGNORECASE,
)

_RE_PATIENT_LINE = _build_label_re(_PATIENT_LABELS)
_RE_PROVIDER_LINE = _build_label_re(_PROVIDER_LABELS)

# Also mask "Signed: Dr. X" / "Authorised By: Dr. X" lines
_RE_SIGNED_LINE = re.compile(
    r"(Signed\s*:|Authorised\s+By\s*:|Certified\s+by\s*:|Prescriber\s+Seal\s*:)\s*(.*)",
    re.IGNORECASE,
)

# Physician/Doctor inline (e.g. "Physician : Dr. Rajesh Mehta  Institute: ...")
# This is a catch-all for remaining single title-case words that look like names
# when they appear after field markers — we DON'T do this globally so labels survive.


def _mask_name_lines(text: str) -> str:
    """
    Scan text line by line and mask the value portion of lines whose label
    indicates a human name or provider name.

    This is more precise than a global proper-noun regex because it only
    targets the VALUE after the label, leaving the label text intact.
    The label is the structural identifier; the value is the variable content.

    Args:
        text : Document text (possibly already partially masked).

    Returns:
        Text with name/provider values replaced by <PATIENT_NAME> or
        <PROVIDER_NAME> placeholders.
    """
    masked_lines = []
    for line in text.splitlines():
        m_patient = _RE_PATIENT_LINE.search(line)
        m_provider = _RE_PROVIDER_LINE.search(line)
        m_signed = _RE_SIGNED_LINE.search(line)

        if m_patient:
            # Preserve everything up to and including the label+colon,
            # then replace the rest with <PATIENT_NAME>
            prefix = line[: m_patient.end(1)]
            line = prefix + " <PATIENT_NAME>"
        elif m_provider:
            prefix = line[: m_provider.end(1)]
            line = prefix + " <PROVIDER_NAME>"
        elif m_signed:
            prefix = line[: m_signed.end(1)]
            line = prefix + " <DOCTOR>"

        masked_lines.append(line)

    return "\n".join(masked_lines)


def extract_skeleton(text: str) -> str:
    """
    Replace all variable fields in *text* with structural placeholder tokens
    and return the resulting skeleton string.

    The replacement is done in a careful order so that longer/more-specific
    patterns (e.g. full INR amounts) are handled before generic ones (e.g.
    bare integers).  Name masking is done line-by-line rather than globally
    to avoid destroying structural label text.

    Args:
        text : Raw document text.

    Returns:
        A string with variable fields replaced by tokens like <DATE>,
        <AMOUNT>, <DOCTOR>, <PATIENT_NAME>, <PROVIDER_NAME>, etc.
        Structural labels ("Provider   :", "Patient    :") are preserved.
    """
    s = text

    # 1. Mask reference IDs (CLM…, PRV…, PAT…)
    s = _RE_REF_ID.sub("<REF_ID>", s)

    # 2. Mask dates
    s = _RE_DATE.sub("<DATE>", s)

    # 3. Mask INR amounts (must come before general integer masking)
    s = _RE_INR.sub("<AMOUNT>", s)

    # 4. Mask doctor names (Dr. Firstname Lastname)
    s = _RE_DOCTOR.sub("<DOCTOR>", s)

    # 5. Mask percentages
    s = _RE_PERCENT.sub("<PERCENT>", s)

    # 6. Mask decimal numbers (lab result values)
    s = _RE_DECIMAL.sub("<NUMBER>", s)

    # 7. Mask quantity notation (x2, x3)
    s = _RE_QTY.sub("<QTY>", s)

    # 7b. Mask drug dosage units (500mg, 60000IU) — variable content
    s = _RE_DOSAGE.sub("<DOSE>", s)

    # 8. Mask remaining large integers
    s = _RE_INTEGER.sub("<NUMBER>", s)

    # 9. Line-aware name masking (after numbers are gone, so "INR 500" won't
    #    confuse the name extractor)
    s = _mask_name_lines(s)

    return s


def load_and_extract(filepath: str) -> dict:
    """
    Load a document from *filepath*, extract its skeleton, and return both
    the raw text and the skeleton in a convenient dict.

    Args:
        filepath : Path to the .txt document file.

    Returns:
        dict with keys:
            'doc_id'   – filename stem (e.g. 'doc_0001')
            'raw_text' – original document content
            'skeleton' – masked skeleton string
            'lines'    – number of non-empty lines in the skeleton
    """
    p = Path(filepath)
    raw = p.read_text(encoding="utf-8")
    skeleton = extract_skeleton(raw)
    non_empty_lines = [ln for ln in skeleton.splitlines() if ln.strip()]
    return {
        "doc_id": p.stem,
        "raw_text": raw,
        "skeleton": skeleton,
        "lines": len(non_empty_lines),
    }


def extract_all(dataset_dir: str = "dataset") -> dict:
    """
    Walk the dataset directory, extract the skeleton for every .txt document,
    and return a dict mapping doc_id → extraction result dict.

    Metadata enrichment
    -------------------
    If a metadata.json file is present in dataset_dir (created by the dataset
    generator), each extraction result is enriched with the 'doc_type' field
    from metadata.  The similarity engine uses doc_type to restrict comparisons
    to same-type document pairs only, eliminating cross-type false positives.

    Args:
        dataset_dir : Path to the folder containing .txt document files.

    Returns:
        Dict keyed by doc_id (e.g. 'doc_0001') with extraction results.
        Each result includes: 'doc_id', 'raw_text', 'skeleton', 'lines',
        and 'doc_type' (if metadata is available).
    """
    import json

    d = Path(dataset_dir)
    txt_files = sorted(d.glob("*.txt"))
    if not txt_files:
        raise FileNotFoundError(
            f"No .txt documents found in '{dataset_dir}'. "
            "Run `python main.py generate-dataset` first."
        )

    # Load metadata if it exists, for doc_type annotations
    metadata = {}
    meta_path = d / "metadata.json"
    if meta_path.exists():
        with open(meta_path, encoding="utf-8") as f:
            metadata = json.load(f)

    results = {}
    for fp in txt_files:
        result = load_and_extract(str(fp))
        doc_id = result["doc_id"]

        # Enrich with doc_type from metadata if available
        if doc_id in metadata:
            result["doc_type"] = metadata[doc_id].get("doc_type", "unknown")
        else:
            result["doc_type"] = "unknown"

        results[doc_id] = result

    print(f"[template_extractor] Extracted skeletons for {len(results)} documents.")
    return results
