"""
fraud_flagger.py
================
Applies threshold-based rules to similarity scores and renders colour-coded
output in the terminal using the ``rich`` library.

Flagging thresholds
-------------------
  RED   (HIGH FRAUD LIKELIHOOD)  : combined_score ≥ 90
  AMBER (SUSPICIOUS, NEEDS REVIEW): 70 ≤ combined_score < 90
  GREEN (NO FLAG)                 : combined_score < 70

The provider check
------------------
Two documents that come from the *same* provider legitimately sharing a
template skeleton is not fraud – it just means the same clinic uses the same
format for all its invoices.  So we only flag a pair when the two documents
claim to be from *different* providers.  We infer the provider from the raw
text by looking for the first occurrence of any known provider substring.

Accuracy evaluation
-------------------
After flagging, we compare flagged pairs against the known ground-truth fraud
pairs (loaded from dataset/ground_truth.csv) and print precision, recall, and
F1 score so you can see how well the detection actually works.
"""

import csv
import json
from pathlib import Path

# Rich library for coloured terminal output
try:
    from rich.console import Console
    from rich.table import Table
    from rich import box
    from rich.text import Text
    _RICH_AVAILABLE = True
except ImportError:
    _RICH_AVAILABLE = False

console = Console() if _RICH_AVAILABLE else None


# ---------------------------------------------------------------------------
# Threshold constants
# ---------------------------------------------------------------------------
RED_THRESHOLD = 90.0    # ≥ this → HIGH fraud likelihood
AMBER_THRESHOLD = 70.0  # ≥ this (and < RED) → Suspicious


# ---------------------------------------------------------------------------
# Provider extraction from raw text
# ---------------------------------------------------------------------------

def _infer_provider_from_text(raw_text: str) -> str:
    """
    Attempt to identify which provider a document claims to be from by
    scanning for provider labels ('Provider', 'Issued By', 'Laboratory',
    'Clinic', 'Facility', 'Institution', 'Institute', 'Lab') in the raw text.

    Args:
        raw_text : The original (un-masked) document text.

    Returns:
        Clean provider name string used to check whether two documents claim
        different providers.
    """
    import re

    # 1. Check for LABORATORY INFO block
    m_lab = re.search(r"LABORATORY INFO\s*\n\s*Name\s*:\s*([^|\n\r]+)", raw_text, re.IGNORECASE)
    if m_lab:
        return m_lab.group(1).strip()

    # 2. Check general provider labels
    patterns = [
        r"(?:Provider|Issued By|Laboratory|Clinic|Facility|Institution|Institute|Lab)\s*[:\|]\s*([^|\n\r]+)",
    ]
    for pat in patterns:
        m = re.search(pat, raw_text, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            # Clean trailing license, reg, ID, etc.
            val = re.sub(r"\s*(?:Lic|Reg|Facility Code|\(ID|ID).*$", "", val, flags=re.IGNORECASE).strip()
            val = val.rstrip("| -:").strip()
            if val:
                return val

    # 3. Fallback: first non-empty line
    for line in raw_text.splitlines():
        stripped = line.strip()
        if stripped and not all(c in "=*#->< " for c in stripped):
            return stripped[:60]

    return "UNKNOWN"


def flag_pairs(
    comparison_results: list,
    extractions: dict,
) -> dict:
    """
    Apply fraud-flagging thresholds to a list of comparison results and
    return a dict of flagged pairs grouped by severity.

    Rules (per Requirement 4):
      - similarity >= 90% AND different providers/customers -> RED flag
      - similarity 70-89% AND different providers/customers -> AMBER flag
      - same provider legitimately reusing their own template -> NOT flagged
      - below 70% -> no flag

    Args:
        comparison_results : List of dicts from similarity_engine.compare_all_pairs.
        extractions        : dict of doc_id → extraction result (contains raw_text).

    Returns:
        dict with keys 'red', 'amber', 'all_flagged'.
    """
    red_pairs = []
    amber_pairs = []

    for r in comparison_results:
        score = r["combined_score"]
        if score < AMBER_THRESHOLD:
            continue

        doc_a = r["doc_id_a"]
        doc_b = r["doc_id_b"]

        # Determine providers from raw text
        raw_a = extractions.get(doc_a, {}).get("raw_text", "")
        raw_b = extractions.get(doc_b, {}).get("raw_text", "")
        prov_a = _infer_provider_from_text(raw_a)
        prov_b = _infer_provider_from_text(raw_b)
        same_provider = prov_a.lower() == prov_b.lower()

        # Legitimate documents from the SAME provider sharing a template is expected;
        # fraud is when DIFFERENT providers/entities reuse the same structural template.
        if same_provider:
            continue

        enriched = {
            **r,
            "provider_a": prov_a,
            "provider_b": prov_b,
            "same_provider": same_provider,
        }

        if score >= RED_THRESHOLD:
            enriched["flag"] = "RED"
            red_pairs.append(enriched)
        else:
            enriched["flag"] = "AMBER"
            amber_pairs.append(enriched)

    all_flagged = red_pairs + amber_pairs

    return {
        "red": red_pairs,
        "amber": amber_pairs,
        "all_flagged": all_flagged,
    }


# ---------------------------------------------------------------------------
# Terminal rendering
# ---------------------------------------------------------------------------

def _fallback_print(flagged: dict) -> None:
    """
    Render flagged pairs using plain print() when rich is not available.
    Uses ANSI escape codes directly for colour.

    Args:
        flagged : The flagged dict returned by flag_pairs().
    """
    RED_ANSI = "\033[91m"
    AMBER_ANSI = "\033[93m"
    RESET = "\033[0m"

    print("\n" + "=" * 70)
    print("  FRAUD DETECTION REPORT")
    print("=" * 70)

    for r in flagged["red"]:
        sp = " [SAME PROVIDER]" if r["same_provider"] else ""
        print(
            f"{RED_ANSI}[RED  ] {r['doc_id_a']} ↔ {r['doc_id_b']}  "
            f"Score: {r['combined_score']:.1f}%{sp}{RESET}"
        )

    for r in flagged["amber"]:
        sp = " [SAME PROVIDER]" if r["same_provider"] else ""
        print(
            f"{AMBER_ANSI}[AMBER] {r['doc_id_a']} ↔ {r['doc_id_b']}  "
            f"Score: {r['combined_score']:.1f}%{sp}{RESET}"
        )

    print(
        f"\nSummary: {len(flagged['red'])} RED alerts | "
        f"{len(flagged['amber'])} AMBER alerts"
    )


def render_flagged_pairs(flagged: dict) -> None:
    """
    Print a colour-coded table of flagged document pairs to the terminal.

    Uses the ``rich`` library if available; falls back to ANSI codes otherwise.

    Colour coding:
        - RED  rows  → high fraud likelihood (score ≥ 90 %)
        - AMBER rows → suspicious (score 70–89 %)

    Args:
        flagged : The flagged dict returned by flag_pairs().
    """
    if not _RICH_AVAILABLE:
        _fallback_print(flagged)
        return

    console.print()
    console.rule("[bold white]FRAUD DETECTION REPORT[/bold white]")

    if not flagged["all_flagged"]:
        console.print("[bold green]✓ No suspicious document pairs detected.[/bold green]")
        return

    table = Table(
        title="Flagged Document Pairs",
        box=box.ROUNDED,
        show_lines=True,
        header_style="bold white on dark_blue",
    )
    table.add_column("Flag", style="bold", justify="center", width=7)
    table.add_column("Doc A", justify="left", width=12)
    table.add_column("Doc B", justify="left", width=12)
    table.add_column("Score", justify="right", width=8)
    table.add_column("Seq Sim", justify="right", width=9)
    table.add_column("Feat Sim", justify="right", width=9)
    table.add_column("Same Provider?", justify="center", width=15)
    table.add_column("Provider A (truncated)", justify="left", width=28)
    table.add_column("Provider B (truncated)", justify="left", width=28)

    for r in flagged["red"]:
        prov_a = r["provider_a"][:26] + ".." if len(r["provider_a"]) > 26 else r["provider_a"]
        prov_b = r["provider_b"][:26] + ".." if len(r["provider_b"]) > 26 else r["provider_b"]
        sp_label = "[yellow]YES[/yellow]" if r["same_provider"] else "[green]NO[/green]"
        table.add_row(
            "[bold red]🔴 RED[/bold red]",
            r["doc_id_a"],
            r["doc_id_b"],
            f"[bold red]{r['combined_score']:.1f}%[/bold red]",
            f"{r['sequence_sim']*100:.1f}%",
            f"{r['feature_sim']*100:.1f}%",
            sp_label,
            prov_a,
            prov_b,
        )

    for r in flagged["amber"]:
        prov_a = r["provider_a"][:26] + ".." if len(r["provider_a"]) > 26 else r["provider_a"]
        prov_b = r["provider_b"][:26] + ".." if len(r["provider_b"]) > 26 else r["provider_b"]
        sp_label = "[yellow]YES[/yellow]" if r["same_provider"] else "[green]NO[/green]"
        table.add_row(
            "[bold yellow]🟡 AMBER[/bold yellow]",
            r["doc_id_a"],
            r["doc_id_b"],
            f"[bold yellow]{r['combined_score']:.1f}%[/bold yellow]",
            f"{r['sequence_sim']*100:.1f}%",
            f"{r['feature_sim']*100:.1f}%",
            sp_label,
            prov_a,
            prov_b,
        )

    console.print(table)

    # Summary line
    total = len(flagged["all_flagged"])
    r_count = len(flagged["red"])
    a_count = len(flagged["amber"])
    console.print(
        f"\n[bold]Summary:[/bold] "
        f"[bold red]{r_count} RED[/bold red] | "
        f"[bold yellow]{a_count} AMBER[/bold yellow] | "
        f"{total} total flagged pairs\n"
    )


# ---------------------------------------------------------------------------
# Accuracy / precision / recall evaluation
# ---------------------------------------------------------------------------

def load_ground_truth(dataset_dir: str = "dataset") -> set:
    """
    Load the ground-truth fraud pairs from the CSV generated alongside the
    synthetic dataset.

    Args:
        dataset_dir : Directory containing ground_truth.csv.

    Returns:
        A set of frozensets, each containing two doc IDs that are known to be
        a fraud pair.  Using frozensets makes order-independent lookup easy.
    """
    gt_path = Path(dataset_dir) / "ground_truth.csv"
    if not gt_path.exists():
        return set()

    pairs = set()
    with open(gt_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pairs.add(frozenset({row["doc_id_a"], row["doc_id_b"]}))

    return pairs


def evaluate_accuracy(
    flagged: dict,
    ground_truth_pairs: set,
    all_comparison_results: list,
) -> dict:
    """
    Compare flagged pairs against the known ground-truth to compute precision,
    recall, and F1 score, then print a summary to the terminal.

    Definitions used
    ----------------
    True Positive  (TP) : Pair that is a ground-truth fraud pair AND was flagged.
    False Positive (FP) : Pair that is NOT ground-truth fraud but WAS flagged.
    False Negative (FN) : Pair that IS ground-truth fraud but was NOT flagged.
    True Negative  (TN) : Pair that is NOT fraud and was NOT flagged.

    Precision = TP / (TP + FP)
    Recall    = TP / (TP + FN)
    F1        = 2 × Precision × Recall / (Precision + Recall)

    Args:
        flagged               : The flagged dict from flag_pairs().
        ground_truth_pairs    : Set of frozensets from load_ground_truth().
        all_comparison_results: Full list of comparison results (to count TN/FN).

    Returns:
        dict with 'precision', 'recall', 'f1', 'tp', 'fp', 'fn', 'tn'.
    """
    if not ground_truth_pairs:
        if _RICH_AVAILABLE:
            console.print("[yellow]⚠ No ground truth data found – skipping accuracy evaluation.[/yellow]")
        else:
            print("⚠ No ground truth data found – skipping accuracy evaluation.")
        return {}

    # All pairs that were flagged (red or amber)
    flagged_set = {
        frozenset({r["doc_id_a"], r["doc_id_b"]})
        for r in flagged["all_flagged"]
    }

    # All pairs that were compared (the universe)
    all_pairs_set = {
        frozenset({r["doc_id_a"], r["doc_id_b"]})
        for r in all_comparison_results
    }

    tp = len(flagged_set & ground_truth_pairs)
    fp = len(flagged_set - ground_truth_pairs)
    fn = len(ground_truth_pairs - flagged_set)
    tn = len(all_pairs_set - flagged_set - ground_truth_pairs)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    metrics = {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "total_fraud_pairs": len(ground_truth_pairs),
        "total_flagged": len(flagged_set),
    }

    _render_accuracy(metrics)
    return metrics


def _render_accuracy(m: dict) -> None:
    """
    Render the accuracy metrics table to the terminal.

    Args:
        m : Metrics dict from evaluate_accuracy().
    """
    if not _RICH_AVAILABLE:
        print("\n--- DETECTION ACCURACY ---")
        print(f"  TP={m['tp']}  FP={m['fp']}  FN={m['fn']}  TN={m['tn']}")
        print(f"  Precision : {m['precision']*100:.1f}%")
        print(f"  Recall    : {m['recall']*100:.1f}%")
        print(f"  F1 Score  : {m['f1']*100:.1f}%")
        return

    console.rule("[bold white]DETECTION ACCURACY[/bold white]")

    table = Table(box=box.SIMPLE_HEAVY, show_header=False)
    table.add_column("Metric", style="bold cyan", width=30)
    table.add_column("Value", justify="right", width=15)

    table.add_row("Ground-truth fraud pairs", str(m["total_fraud_pairs"]))
    table.add_row("Total pairs flagged", str(m["total_flagged"]))
    table.add_row("True Positives  (TP)", f"[bold green]{m['tp']}[/bold green]")
    table.add_row("False Positives (FP)", f"[bold red]{m['fp']}[/bold red]")
    table.add_row("False Negatives (FN)", f"[bold red]{m['fn']}[/bold red]")
    table.add_row("True Negatives  (TN)", f"[bold green]{m['tn']}[/bold green]")
    table.add_row("─" * 30, "─" * 15)
    table.add_row(
        "Precision",
        f"[bold]{m['precision']*100:.1f}%[/bold]"
    )
    table.add_row(
        "Recall",
        f"[bold]{m['recall']*100:.1f}%[/bold]"
    )
    f1_color = "green" if m["f1"] >= 0.8 else ("yellow" if m["f1"] >= 0.5 else "red")
    table.add_row(
        "F1 Score",
        f"[bold {f1_color}]{m['f1']*100:.1f}%[/bold {f1_color}]"
    )

    console.print(table)


# ---------------------------------------------------------------------------
# Saving the flagged report
# ---------------------------------------------------------------------------

def save_report(flagged: dict, metrics: dict, output_path: str) -> None:
    """
    Write the flagged pairs and accuracy metrics to a JSON report file.

    Args:
        flagged     : The flagged dict from flag_pairs().
        metrics     : The accuracy metrics dict (may be empty if no ground truth).
        output_path : File path to write the report to.
    """
    report = {
        "flagged_pairs": flagged["all_flagged"],
        "summary": {
            "red_count": len(flagged["red"]),
            "amber_count": len(flagged["amber"]),
            "total_flagged": len(flagged["all_flagged"]),
        },
        "accuracy_metrics": metrics,
    }
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    # Also write CSV report for convenience
    csv_path = p.with_suffix(".csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "flag",
            "doc_id_a",
            "doc_id_b",
            "doc_type",
            "combined_score",
            "sequence_sim",
            "feature_sim",
            "provider_a",
            "provider_b",
        ])
        for row in flagged["all_flagged"]:
            writer.writerow([
                row.get("flag", ""),
                row.get("doc_id_a", ""),
                row.get("doc_id_b", ""),
                row.get("doc_type", ""),
                row.get("combined_score", ""),
                row.get("sequence_sim", ""),
                row.get("feature_sim", ""),
                row.get("provider_a", ""),
                row.get("provider_b", ""),
            ])

    if _RICH_AVAILABLE:
        console.print(f"\n[dim]Report saved → {output_path} and {csv_path}[/dim]")
    else:
        print(f"\nReport saved → {output_path} and {csv_path}")
