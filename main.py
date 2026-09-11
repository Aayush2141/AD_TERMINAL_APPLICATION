"""
main.py — CLI entry point for the Fraud Detector.

Commands:
  python main.py generate-dataset          Generate the synthetic dataset
  python main.py analyze                   Run full pairwise analysis
  python main.py analyze --file <path>     Compare one document vs dataset
  python main.py analyze --dataset <dir>   Override dataset directory
  python main.py analyze --output <path>   Override report output path
  python main.py analyze --threshold-red   Override RED flag threshold (default 90.0)
  python main.py analyze --threshold-amber Override AMBER flag threshold (default 70.0)
"""

import argparse
import sys
from pathlib import Path

# Dataset paths are relative to this script's location so the tool works
# regardless of the user's current working directory.
_SCRIPT_DIR = Path(__file__).parent


def _resolve_path(raw: str) -> Path:
    """Return an absolute Path, resolving relative paths against the script directory."""
    p = Path(raw)
    return p if p.is_absolute() else _SCRIPT_DIR / p


def cmd_generate_dataset(args) -> None:
    """Generate a synthetic dataset of insurance claim documents."""
    from dataset_generator import generate_dataset

    output_dir = _resolve_path(args.dataset)
    print("\n=== Generating Synthetic Dataset ===")
    result = generate_dataset(output_dir=str(output_dir), n_total=args.n)
    print(f"\nDone! Dataset written to: {result['output_dir']}")
    print(f"  metadata.json    → template_key and is_fraud for each document")
    print(f"  ground_truth.csv → {len(result['fraud_pairs'])} known fraud pairs")
    print(f"\nNext step: python main.py analyze")


def cmd_analyze(args) -> None:
    """
    Run the full fraud detection pipeline:
      1. Extract structural skeletons from dataset documents.
      2. Compare document pairs for similarity.
      3. Flag suspicious pairs as RED or AMBER.
      4. Display color-coded results in the terminal.
      5. Evaluate accuracy against ground truth (full-dataset mode only).
      6. Save JSON and CSV reports to disk.
    """
    import fraud_flagger
    import template_extractor
    import similarity_engine

    # Apply CLI threshold overrides
    fraud_flagger.RED_THRESHOLD = args.threshold_red
    fraud_flagger.AMBER_THRESHOLD = args.threshold_amber

    dataset_dir = _resolve_path(args.dataset)
    output_path = _resolve_path(args.output)

    print(f"\n=== Template Matching Fraud Detector ===")
    print(f"Dataset   : {dataset_dir}")
    print(f"Report    : {output_path}")
    print(f"Thresholds: RED ≥ {args.threshold_red}% | AMBER ≥ {args.threshold_amber}%\n")

    # Step 1: Extract skeletons
    try:
        extractions = template_extractor.extract_all(str(dataset_dir))
    except FileNotFoundError as e:
        print(f"\nERROR: {e}")
        sys.exit(1)

    # Step 2: Compare document pairs
    if args.file:
        new_file = _resolve_path(args.file)
        if not new_file.exists():
            print(f"\nERROR: File not found: {args.file}")
            sys.exit(1)
        new_extraction = template_extractor.load_and_extract(str(new_file))
        comparison_results = similarity_engine.compare_one_vs_all(new_extraction, extractions)
        extractions[new_extraction["doc_id"]] = new_extraction  # needed for provider lookup
    else:
        comparison_results = similarity_engine.compare_all_pairs(extractions)

    # Step 3: Flag suspicious pairs
    flagged = fraud_flagger.flag_pairs(comparison_results, extractions)

    # Step 4: Display results
    fraud_flagger.render_flagged_pairs(flagged)

    # Step 5: Accuracy evaluation (only in full-dataset mode)
    metrics = {}
    if not args.file:
        ground_truth = fraud_flagger.load_ground_truth(str(dataset_dir))
        metrics = fraud_flagger.evaluate_accuracy(flagged, ground_truth, comparison_results)

    # Step 6: Save reports
    fraud_flagger.save_report(flagged, metrics, str(output_path))
    sim_path = output_path.parent / "similarity_results.json"
    similarity_engine.save_results(comparison_results, str(sim_path))


def build_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="main.py",
        description=(
            "Similar Document Template Matching Algorithm\n"
            "Detects fraudulent medical insurance documents that reuse the same\n"
            "structural template across different providers/patients."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- generate-dataset ---
    gen = subparsers.add_parser("generate-dataset", help="Generate the synthetic dataset.")
    gen.add_argument("--dataset", default="dataset", metavar="DIR",
                     help="Output directory (default: ./dataset).")
    gen.add_argument("--n", type=int, default=80, metavar="N",
                     help="Number of documents to generate (default: 80).")

    # --- analyze ---
    ana = subparsers.add_parser("analyze", help="Run template extraction and similarity analysis.")
    ana.add_argument("--file", default=None, metavar="PATH",
                     help="Compare a single document against the dataset instead of full pairwise.")
    ana.add_argument("--dataset", default="dataset", metavar="DIR",
                     help="Dataset directory (default: ./dataset).")
    ana.add_argument("--output", default="report.json", metavar="PATH",
                     help="Report output path (default: ./report.json).")
    ana.add_argument("--threshold-red", type=float, default=90.0, metavar="SCORE",
                     help="RED flag threshold 0-100 (default: 90).")
    ana.add_argument("--threshold-amber", type=float, default=70.0, metavar="SCORE",
                     help="AMBER flag threshold 0-100 (default: 70).")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "generate-dataset":
        cmd_generate_dataset(args)
    elif args.command == "analyze":
        cmd_analyze(args)
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
