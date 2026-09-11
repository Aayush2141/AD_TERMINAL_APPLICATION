"""
fraud_flagger.py — Decides which document pairs are suspicious (fraud).

HOW IT WORKS:
  After the similarity engine scores every pair of documents (0-100%),
  this module looks at each score and decides whether to raise an alert:

  RED   flag → score ≥ 90% AND documents come from DIFFERENT providers
               → Almost certainly fraud (same template, different fake clinic)

  AMBER flag → score 70–89% AND documents come from DIFFERENT providers
               → Suspicious, worth a human review

  No flag    → score < 70%, OR the documents are from the SAME provider
               → Legitimate (either too different, or same clinic using its own template)
"""

import csv
import json
import re
from pathlib import Path

# ── Optional pretty-printing ─────────────────────────────────────────────────
# If the 'rich' library is installed, alerts are shown in a nice colored table.
# If not, we fall back to plain terminal output with ANSI color codes.
try:
    from rich.console import Console
    from rich.table import Table
    from rich import box
    _RICH_AVAILABLE = True
    console = Console()
except ImportError:
    _RICH_AVAILABLE = False
    console = None

# ── Thresholds ────────────────────────────────────────────────────────────────
# These can be changed from the CLI with --threshold-red / --threshold-amber.
RED_THRESHOLD   = 90.0   # pairs at or above this score → RED alert
AMBER_THRESHOLD = 70.0   # pairs at or above this score → AMBER alert


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — IDENTIFY THE PROVIDER
# ─────────────────────────────────────────────────────────────────────────────

def _get_provider(raw_text: str) -> str:
    """
    Read a document and extract the name of the provider/clinic.

    We need the provider name so we can check whether two suspicious
    documents actually come from the SAME clinic (legitimate) or from
    DIFFERENT clinics (potential fraud).

    The function tries three strategies, from most specific to least:
      1. Look for a 'LABORATORY INFO' section (lab reports).
      2. Look for a labelled field like 'Provider:', 'Clinic:', 'Facility:'.
      3. Fall back to the first readable line of the document.
    """
    # Strategy 1 — lab reports have a dedicated "LABORATORY INFO" block
    match = re.search(r"LABORATORY INFO\s*\n\s*Name\s*:\s*([^|\n\r]+)", raw_text, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    # Strategy 2 — look for a labelled provider field anywhere in the document
    match = re.search(
        r"(?:Provider|Issued By|Laboratory|Clinic|Facility|Institution|Institute|Lab)\s*[:|]\s*([^|\n\r]+)",
        raw_text,
        re.IGNORECASE,
    )
    if match:
        name = match.group(1).strip()
        # Strip trailing license/registration codes like "Lic: PRV1020"
        name = re.sub(r"\s*(?:Lic|Reg|Facility Code|\(ID|ID).*$", "", name, flags=re.IGNORECASE).strip()
        name = name.rstrip("| -:").strip()
        if name:
            return name

    # Strategy 3 — use the first non-decorative line (e.g. not "======" or "####")
    for line in raw_text.splitlines():
        clean = line.strip()
        if clean and not all(c in "=*#-><  " for c in clean):
            return clean[:50]  # cap at 50 chars to avoid returning a full paragraph

    return "UNKNOWN"


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — FLAG SUSPICIOUS PAIRS
# ─────────────────────────────────────────────────────────────────────────────

def flag_pairs(comparison_results: list, extractions: dict) -> dict:
    """
    Go through every compared document pair and decide if it should be flagged.

    A pair is flagged only when BOTH conditions are true:
      - The similarity score is high enough (≥ AMBER_THRESHOLD)
      - The two documents claim to be from DIFFERENT providers

    Args:
        comparison_results: Output from similarity_engine — a list of pairs
                            with their similarity scores.
        extractions:        The full document data (needed to read provider names
                            from the raw document text).

    Returns:
        A dict with three keys:
          'red'         → list of RED-flagged pairs
          'amber'       → list of AMBER-flagged pairs
          'all_flagged' → both lists combined (convenient for reporting)
    """
    red_pairs   = []
    amber_pairs = []

    for result in comparison_results:
        score = result["combined_score"]

        # Skip pairs that are not similar enough to be worth investigating
        if score < AMBER_THRESHOLD:
            continue

        # Look up the provider name for each document in the pair
        doc_a_text = extractions.get(result["doc_id_a"], {}).get("raw_text", "")
        doc_b_text = extractions.get(result["doc_id_b"], {}).get("raw_text", "")
        provider_a = _get_provider(doc_a_text)
        provider_b = _get_provider(doc_b_text)

        # If both documents belong to the same provider, this is NOT fraud —
        # it just means one clinic consistently uses the same form layout.
        if provider_a.lower() == provider_b.lower():
            continue

        # Build the record we'll store for this flagged pair
        flagged_pair = {
            **result,                    # copy all score fields from comparison
            "provider_a":    provider_a,
            "provider_b":    provider_b,
            "same_provider": False,
        }

        # Assign the severity level
        if score >= RED_THRESHOLD:
            flagged_pair["flag"] = "RED"
            red_pairs.append(flagged_pair)
        else:
            flagged_pair["flag"] = "AMBER"
            amber_pairs.append(flagged_pair)

    return {
        "red":         red_pairs,
        "amber":       amber_pairs,
        "all_flagged": red_pairs + amber_pairs,
    }


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — DISPLAY RESULTS IN THE TERMINAL
# ─────────────────────────────────────────────────────────────────────────────

def render_flagged_pairs(flagged: dict) -> None:
    """
    Print the flagged pairs to the terminal in a readable, color-coded format.

    Uses a styled table if the 'rich' library is installed.
    Falls back to plain colored text using ANSI escape codes otherwise.
    """
    all_pairs = flagged["all_flagged"]

    # Nothing found — print a success message and exit early
    if not all_pairs:
        msg = "\n[✓] No suspicious template reuse detected."
        if _RICH_AVAILABLE:
            console.print(f"[bold green]{msg}[/bold green]")
        else:
            print(f"\033[92m{msg}\033[0m")  # \033[92m = green, \033[0m = reset
        return

    # ── Rich table display (installed) ───────────────────────────────────────
    if _RICH_AVAILABLE:
        table = Table(title="Fraud Detection Alerts", box=box.ROUNDED, show_lines=True)
        table.add_column("Alert",      justify="center", style="bold", width=8)
        table.add_column("Doc A",      justify="left",   width=10)
        table.add_column("Doc B",      justify="left",   width=10)
        table.add_column("Score",      justify="right",  width=8)
        table.add_column("Provider A", justify="left",   width=25)
        table.add_column("Provider B", justify="left",   width=25)

        for p in flagged["red"]:
            table.add_row(
                "[bold red]RED[/bold red]",
                p["doc_id_a"], p["doc_id_b"],
                f"[bold red]{p['combined_score']:.1f}%[/bold red]",
                p["provider_a"][:25], p["provider_b"][:25],
            )
        for p in flagged["amber"]:
            table.add_row(
                "[bold yellow]AMBER[/bold yellow]",
                p["doc_id_a"], p["doc_id_b"],
                f"[bold yellow]{p['combined_score']:.1f}%[/bold yellow]",
                p["provider_a"][:25], p["provider_b"][:25],
            )

        console.print()
        console.print(table)
        console.print(
            f"[bold]Summary:[/bold] "
            f"[bold red]{len(flagged['red'])} RED[/bold red] | "
            f"[bold yellow]{len(flagged['amber'])} AMBER[/bold yellow] | "
            f"{len(all_pairs)} Total Flagged Pairs\n"
        )

    # ── Plain ANSI fallback (no rich installed) ───────────────────────────────
    else:
        RED_COLOR   = "\033[91m"   # bright red
        AMBER_COLOR = "\033[93m"   # bright yellow
        RESET       = "\033[0m"    # back to default color

        print("\n" + "=" * 70)
        print("  FRAUD DETECTION ALERTS")
        print("=" * 70)

        for p in flagged["red"]:
            print(f"{RED_COLOR}[RED  ] {p['doc_id_a']} <-> {p['doc_id_b']} "
                  f"| Score: {p['combined_score']:.1f}% "
                  f"| {p['provider_a']} vs {p['provider_b']}{RESET}")

        for p in flagged["amber"]:
            print(f"{AMBER_COLOR}[AMBER] {p['doc_id_a']} <-> {p['doc_id_b']} "
                  f"| Score: {p['combined_score']:.1f}% "
                  f"| {p['provider_a']} vs {p['provider_b']}{RESET}")

        print(f"\nSummary: {len(flagged['red'])} RED | {len(flagged['amber'])} AMBER | {len(all_pairs)} total\n")


# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — LOAD GROUND TRUTH (for accuracy testing)
# ─────────────────────────────────────────────────────────────────────────────

def load_ground_truth(dataset_dir: str = "dataset") -> set:
    """
    Load the list of known fraud pairs from ground_truth.csv.

    This file is generated by dataset_generator.py and lists every pair
    of documents that we KNOW are fraudulent (because we created them that way).
    We use it to measure how accurately the algorithm detected the fraud.

    Returns:
        A set of frozensets like {frozenset({'doc_0001', 'doc_0002'}), ...}.
        Uses frozensets so that pair order doesn't matter (A,B == B,A).
        Returns an empty set if the file doesn't exist.
    """
    path = Path(dataset_dir) / "ground_truth.csv"
    if not path.exists():
        return set()  # no ground truth available, skip accuracy evaluation

    with open(path, newline="", encoding="utf-8") as f:
        return {frozenset({row["doc_id_a"], row["doc_id_b"]}) for row in csv.DictReader(f)}


# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — MEASURE ACCURACY
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_accuracy(flagged: dict, ground_truth: set, all_results: list) -> dict:
    """
    Compare our flagged pairs against the known fraud pairs to measure accuracy.

    The four possible outcomes for each pair:
      TP (True Positive)  — we flagged it AND it really is fraud  ✓ correct
      FP (False Positive) — we flagged it BUT it's actually legit  ✗ false alarm
      FN (False Negative) — we missed it AND it really was fraud   ✗ missed fraud
      TN (True Negative)  — we didn't flag it AND it's legit       ✓ correct

    Metrics derived from those counts:
      Precision = TP / (TP + FP)  → "Of everything we flagged, how much was real fraud?"
      Recall    = TP / (TP + FN)  → "Of all real fraud, how much did we catch?"
      F1 Score  = harmonic mean of Precision and Recall (overall performance)
    """
    if not ground_truth:
        print("[!] No ground_truth.csv found; skipping accuracy metrics.")
        return {}

    # Convert flagged pairs and all compared pairs into sets for easy comparison
    flagged_set = {frozenset({p["doc_id_a"], p["doc_id_b"]}) for p in flagged["all_flagged"]}
    all_pairs   = {frozenset({p["doc_id_a"], p["doc_id_b"]}) for p in all_results}

    # Count the four outcome categories using set operations
    tp = len(flagged_set & ground_truth)          # flagged AND known fraud
    fp = len(flagged_set - ground_truth)          # flagged BUT not fraud
    fn = len(ground_truth - flagged_set)          # not flagged BUT was fraud
    tn = len(all_pairs - flagged_set - ground_truth)  # not flagged AND not fraud

    # Calculate the three accuracy metrics (guard against division by zero)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1        = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    metrics = {
        "precision": round(precision * 100, 1),
        "recall":    round(recall    * 100, 1),
        "f1":        round(f1        * 100, 1),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "total_fraud_pairs": len(ground_truth),
        "total_flagged":     len(flagged_set),
    }

    print("--- DETECTION ACCURACY ---")
    print(f"  True Positives  (TP) : {tp}  (Correctly caught fraud pairs)")
    print(f"  False Positives (FP) : {fp}  (Legitimate pairs wrongly flagged)")
    print(f"  False Negatives (FN) : {fn}  (Fraud pairs missed)")
    print(f"  True Negatives  (TN) : {tn}  (Legitimate pairs correctly cleared)")
    print(f"  Precision            : {metrics['precision']}%")
    print(f"  Recall               : {metrics['recall']}%")
    print(f"  F1 Score             : {metrics['f1']}%\n")

    return metrics


# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — SAVE THE REPORT
# ─────────────────────────────────────────────────────────────────────────────

def save_report(flagged: dict, metrics: dict, output_path: str) -> None:
    """
    Write the results to disk in two formats:
      - JSON (report.json) — full structured data, good for parsing/inspection
      - CSV  (report.csv)  — flat table, easy to open in Excel or Google Sheets

    Args:
        flagged:     The flagged pairs from flag_pairs().
        metrics:     The accuracy metrics from evaluate_accuracy().
        output_path: Where to write the JSON file (e.g. 'report.json').
                     The CSV is saved to the same path with a .csv extension.
    """
    json_path = Path(output_path)
    csv_path  = json_path.with_suffix(".csv")
    json_path.parent.mkdir(parents=True, exist_ok=True)

    # ── JSON report ───────────────────────────────────────────────────────────
    report = {
        "summary": {
            "red_alerts":    len(flagged["red"]),
            "amber_alerts":  len(flagged["amber"]),
            "total_flagged": len(flagged["all_flagged"]),
        },
        "accuracy_metrics": metrics,
        "flagged_pairs":    flagged["all_flagged"],
    }
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    # ── CSV report ────────────────────────────────────────────────────────────
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["flag", "doc_id_a", "doc_id_b", "score", "provider_a", "provider_b"])
        for p in flagged["all_flagged"]:
            writer.writerow([
                p.get("flag"),
                p.get("doc_id_a"),
                p.get("doc_id_b"),
                p.get("combined_score"),
                p.get("provider_a"),
                p.get("provider_b"),
            ])

    print(f"[fraud_flagger] Report written to '{json_path}' and '{csv_path}'")
