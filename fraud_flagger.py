"""
fraud_flagger.py — Flags suspicious document pairs as RED or AMBER.

Flagging Rules:
  RED   (≥ 90% similar, different providers) → High fraud likelihood
  AMBER (70–89% similar, different providers) → Suspicious, needs review
  None  (< 70% similar, or same provider)    → Legitimate
"""

import csv
import json
import re
from pathlib import Path

try:
    from rich.console import Console
    from rich.table import Table
    from rich import box
    _RICH_AVAILABLE = True
    console = Console()
except ImportError:
    _RICH_AVAILABLE = False
    console = None

# Default thresholds (can be overridden from the CLI)
RED_THRESHOLD = 90.0
AMBER_THRESHOLD = 70.0


def _get_provider(raw_text: str) -> str:
    """
    Extract the provider/clinic name from a document's raw text.
    Tries common label patterns (Provider, Facility, Lab, etc.) and
    falls back to the first meaningful line if nothing matches.
    """
    # Check for a LABORATORY INFO section first (most specific)
    m = re.search(r"LABORATORY INFO\s*\n\s*Name\s*:\s*([^|\n\r]+)", raw_text, re.IGNORECASE)
    if m:
        return m.group(1).strip()

    # Check general provider labels
    m = re.search(
        r"(?:Provider|Issued By|Laboratory|Clinic|Facility|Institution|Institute|Lab)\s*[:|]\s*([^|\n\r]+)",
        raw_text,
        re.IGNORECASE,
    )
    if m:
        name = m.group(1).strip()
        name = re.sub(r"\s*(?:Lic|Reg|Facility Code|\(ID|ID).*$", "", name, flags=re.IGNORECASE).strip()
        name = name.rstrip("| -:").strip()
        if name:
            return name

    # Fallback: use the first non-decorative line
    for line in raw_text.splitlines():
        clean = line.strip()
        if clean and not all(c in "=*#-><  " for c in clean):
            return clean[:50]

    return "UNKNOWN"


def flag_pairs(comparison_results: list, extractions: dict) -> dict:
    """
    Apply fraud thresholds to all compared pairs and return flagged results.

    Args:
        comparison_results: List of pair dicts with similarity scores.
        extractions: Map of doc_id -> document info (used to read provider names).

    Returns:
        {'red': [...], 'amber': [...], 'all_flagged': [...]}
    """
    red_pairs, amber_pairs = [], []

    for r in comparison_results:
        score = r["combined_score"]
        if score < AMBER_THRESHOLD:
            continue  # below minimum threshold, skip

        prov_a = _get_provider(extractions.get(r["doc_id_a"], {}).get("raw_text", ""))
        prov_b = _get_provider(extractions.get(r["doc_id_b"], {}).get("raw_text", ""))

        if prov_a.lower() == prov_b.lower():
            continue  # same provider = legitimate template reuse, not fraud

        pair = {**r, "provider_a": prov_a, "provider_b": prov_b, "same_provider": False}

        if score >= RED_THRESHOLD:
            pair["flag"] = "RED"
            red_pairs.append(pair)
        else:
            pair["flag"] = "AMBER"
            amber_pairs.append(pair)

    return {"red": red_pairs, "amber": amber_pairs, "all_flagged": red_pairs + amber_pairs}


def render_flagged_pairs(flagged: dict) -> None:
    """
    Print flagged pairs to the terminal with color coding.
    Uses the `rich` library if available, otherwise falls back to ANSI colors.
    """
    all_pairs = flagged["all_flagged"]

    if not all_pairs:
        msg = "\n[✓] No suspicious template reuse detected."
        if _RICH_AVAILABLE:
            console.print(f"[bold green]{msg}[/bold green]")
        else:
            print(f"\033[92m{msg}\033[0m")
        return

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
                "[bold red]RED[/bold red]", p["doc_id_a"], p["doc_id_b"],
                f"[bold red]{p['combined_score']:.1f}%[/bold red]",
                p["provider_a"][:25], p["provider_b"][:25],
            )
        for p in flagged["amber"]:
            table.add_row(
                "[bold yellow]AMBER[/bold yellow]", p["doc_id_a"], p["doc_id_b"],
                f"[bold yellow]{p['combined_score']:.1f}%[/bold yellow]",
                p["provider_a"][:25], p["provider_b"][:25],
            )

        console.print()
        console.print(table)
        console.print(
            f"[bold]Summary:[/bold] [bold red]{len(flagged['red'])} RED[/bold red] | "
            f"[bold yellow]{len(flagged['amber'])} AMBER[/bold yellow] | "
            f"{len(all_pairs)} Total Flagged Pairs\n"
        )
    else:
        RED   = "\033[91m"
        AMBER = "\033[93m"
        RESET = "\033[0m"

        print("\n" + "=" * 70)
        print("  FRAUD DETECTION ALERTS")
        print("=" * 70)
        for p in flagged["red"]:
            print(f"{RED}[RED  ] {p['doc_id_a']} <-> {p['doc_id_b']} | Score: {p['combined_score']:.1f}% | {p['provider_a']} vs {p['provider_b']}{RESET}")
        for p in flagged["amber"]:
            print(f"{AMBER}[AMBER] {p['doc_id_a']} <-> {p['doc_id_b']} | Score: {p['combined_score']:.1f}% | {p['provider_a']} vs {p['provider_b']}{RESET}")
        print(f"\nSummary: {len(flagged['red'])} RED | {len(flagged['amber'])} AMBER | {len(all_pairs)} total\n")


def load_ground_truth(dataset_dir: str = "dataset") -> set:
    """
    Load known fraud pairs from ground_truth.csv.

    Returns:
        Set of frozensets, each containing {doc_id_a, doc_id_b}.
        Empty set if the file doesn't exist.
    """
    path = Path(dataset_dir) / "ground_truth.csv"
    if not path.exists():
        return set()

    with open(path, newline="", encoding="utf-8") as f:
        return {frozenset({row["doc_id_a"], row["doc_id_b"]}) for row in csv.DictReader(f)}


def evaluate_accuracy(flagged: dict, ground_truth: set, all_results: list) -> dict:
    """
    Compute precision, recall, and F1 against known ground-truth fraud pairs.

    True Positive  (TP): Known fraud pair that was correctly flagged.
    False Positive (FP): Legitimate pair that was incorrectly flagged.
    False Negative (FN): Known fraud pair that was missed.
    True Negative  (TN): Legitimate pair that was correctly cleared.
    """
    if not ground_truth:
        print("[!] No ground_truth.csv found; skipping accuracy metrics.")
        return {}

    flagged_set  = {frozenset({p["doc_id_a"], p["doc_id_b"]}) for p in flagged["all_flagged"]}
    universe     = {frozenset({p["doc_id_a"], p["doc_id_b"]}) for p in all_results}

    tp = len(flagged_set & ground_truth)
    fp = len(flagged_set - ground_truth)
    fn = len(ground_truth - flagged_set)
    tn = len(universe - flagged_set - ground_truth)

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


def save_report(flagged: dict, metrics: dict, output_path: str) -> None:
    """
    Save flagged alerts to both JSON and CSV files.

    Args:
        flagged:     Flagged pair records from flag_pairs().
        metrics:     Accuracy metrics from evaluate_accuracy().
        output_path: Base file path (e.g. 'report.json').
    """
    json_path = Path(output_path)
    csv_path  = json_path.with_suffix(".csv")
    json_path.parent.mkdir(parents=True, exist_ok=True)

    # JSON report
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

    # CSV report
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["flag", "doc_id_a", "doc_id_b", "score", "provider_a", "provider_b"])
        for p in flagged["all_flagged"]:
            writer.writerow([p.get("flag"), p.get("doc_id_a"), p.get("doc_id_b"),
                             p.get("combined_score"), p.get("provider_a"), p.get("provider_b")])

    print(f"[fraud_flagger] Report written to '{json_path}' and '{csv_path}'")
