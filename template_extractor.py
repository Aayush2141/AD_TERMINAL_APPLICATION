"""
template_extractor.py — Extracts a structural "skeleton" from a medical document.

How it works:
  Variable fields (names, dates, amounts, IDs) are replaced with placeholder
  tokens like <DATE>, <AMOUNT>, <PATIENT>, etc. Two documents generated from
  the same template will then produce nearly identical skeletons, making fraud
  easy to detect even when the surface text looks different.
"""

import json
import re
from pathlib import Path


def extract_skeleton(text: str) -> str:
    """
    Replace variable content in a document with structural placeholder tokens.

    Masking order (order matters — more specific patterns run first):
      1. Reference & Claim IDs  (CLM123, PRV123, PAT123)  → <REF_ID>
      2. Dates                  (DD-MM-YYYY, Month DD YYYY) → <DATE>
      3. Currency amounts        (INR 1,500)               → <AMOUNT>
      4. Doctor names            (Dr. Firstname Lastname)  → <DOCTOR>
      5. Percentages             (18%, 5.5%)               → <PERCENT>
      6. Decimal numbers         (14.5, 0.95)              → <NUMBER>
      7. Quantities & dosages    (x2, 500mg, 10ml)         → <QTY>
      8. Patient name values                               → <PATIENT>
      9. Provider name values                              → <PROVIDER>
      10. Remaining large numbers (3+ digits)              → <NUMBER>
    """
    s = text

    # 1. Claim / Provider / Patient IDs
    s = re.sub(r"\b(CLM\d+|PRV\d+|PAT\d+)\b", "<REF_ID>", s)

    # 2. Dates
    s = re.sub(
        r"\b(?:\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{4}[-/]\d{2}[-/]\d{2}|"
        r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})\b",
        "<DATE>", s, flags=re.IGNORECASE,
    )

    # 3. Currency amounts (INR 2,500 or INR 500)
    s = re.sub(r"\bINR\s+[\d,]+(?:\.\d{2})?\b", "<AMOUNT>", s, flags=re.IGNORECASE)

    # 4. Doctor names (Dr. Firstname Lastname)
    s = re.sub(r"\bDr\.\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", "<DOCTOR>", s)

    # 5. Percentages
    s = re.sub(r"\b\d+(?:\.\d+)?%", "<PERCENT>", s)

    # 6. Decimal numbers
    s = re.sub(r"\b\d+\.\d+\b", "<NUMBER>", s)

    # 7. Quantities & dosages (x2, 500mg, 10ml, 60000IU)
    s = re.sub(r"\bx\d+\b", "<QTY>", s, flags=re.IGNORECASE)
    s = re.sub(r"\b\d+(?:\.\d+)?\s*(?:mg|mcg|ml|IU|g|units?|tab|caps?)\b", "<QTY>", s, flags=re.IGNORECASE)

    # 8. Patient name values (after labels like "Patient:", "Full Name:", etc.)
    s = re.sub(
        r"(?i)(Patient(?:\s+Name)?|Full\s+Name|Claimant|Member\s+ID|UHID?)\s*[:|]\s*([^\n\r|]+)",
        r"\1: <PATIENT>", s,
    )

    # 9. Provider name values (after labels like "Provider:", "Clinic:", etc.)
    s = re.sub(
        r"(?i)(Provider|Issued\s+By|Laboratory|Clinic|Facility|Institution|Institute|Lab(?:\s+Name)?)\s*[:|]\s*([^\n\r|]+)",
        r"\1: <PROVIDER>", s,
    )

    # 10. Any remaining large standalone numbers
    s = re.sub(r"\b\d{3,}\b", "<NUMBER>", s)

    return s


def load_and_extract(filepath: str) -> dict:
    """
    Read a document file and extract its structural skeleton.

    Returns:
        {'doc_id', 'raw_text', 'skeleton', 'lines'}
    """
    path = Path(filepath)
    raw_text = path.read_text(encoding="utf-8")
    skeleton = extract_skeleton(raw_text)

    return {
        "doc_id":    path.stem,
        "raw_text":  raw_text,
        "skeleton":  skeleton,
        "lines":     sum(1 for line in skeleton.splitlines() if line.strip()),
    }


def extract_all(dataset_dir: str = "dataset") -> dict:
    """
    Extract skeletons for every .txt document in dataset_dir.
    Attaches each document's doc_type from metadata.json if available.

    Returns:
        Mapping of doc_id -> extraction info dict.

    Raises:
        FileNotFoundError: If no .txt files are found in dataset_dir.
    """
    folder = Path(dataset_dir)
    files  = sorted(folder.glob("*.txt"))

    if not files:
        raise FileNotFoundError(f"No .txt documents found in '{dataset_dir}'. Run `generate-dataset` first.")

    meta_path = folder / "metadata.json"
    metadata  = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    extractions = {}
    for filepath in files:
        doc = load_and_extract(str(filepath))
        doc["doc_type"] = metadata.get(doc["doc_id"], {}).get("doc_type", "unknown")
        extractions[doc["doc_id"]] = doc

    print(f"[template_extractor] Extracted skeletons for {len(extractions)} documents.")
    return extractions
