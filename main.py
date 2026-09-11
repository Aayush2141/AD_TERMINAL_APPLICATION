"""
main.py
=======
CLI entry point for the "Similar Document Template Matching Algorithm".

Commands
--------
  python main.py generate-dataset
      Generates the synthetic dataset of insurance claim documents and saves
      them to the ./dataset folder along with metadata and ground-truth files.

  python main.py analyze
      Runs template extraction + pairwise similarity comparison on all documents
      in ./dataset, prints colour-coded flagged pairs, and writes a report.

  python main.py analyze --file <path>
      Compares one new document against the existing dataset instead of running
      a full pairwise comparison.

  python main.py analyze --dataset <dir>
      Override the default dataset directory (default: ./dataset).

  python main.py analyze --output <path>
      Override the default report output path (default: ./report.json).

  python main.py analyze --threshold-red <float>
      Override the RED flag threshold (default: 90.0).

  python main.py analyze --threshold-amber <float>
      Override the AMBER flag threshold (default: 70.0).
"""

import argparse
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Resolve dataset directory relative to this script's location so the tool
# works correctly regardless of the user's current working directory.
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).parent


def cmd_generate_dataset(args) -> None:
    """
    Handler for the `generate-dataset` command.

    Imports the dataset_generator module and runs the full generation pipeline.
    Prints a summary of what was created.

    Args:
        args : Parsed argparse namespace (may contain --dataset, --n flags).
    """
    from dataset_generator import generate_dataset

    output_dir = Path(args.dataset) if not Path(args.dataset).is_absolute() else Path(args.dataset)
    # Make relative paths relative to the script directory
    if not output_dir.is_absolute():
        output_dir = _SCRIPT_DIR / output_dir

    print("\n=== Generating Synthetic Dataset ===")
    result = generate_dataset(
        output_dir=str(output_dir),
        n_total=args.n,
    )
    print(f"\nDone! Dataset written to: {result['output_dir']}")
    print(f"  metadata.json      → records template_key and is_fraud for each doc")
    print(f"  ground_truth.csv   → {len(result['fraud_pairs'])} known fraud pairs (for accuracy testing)")
    print(f"\nNext step: python main.py analyze")


def cmd_analyze(args) -> None:
    """
    Handler for the `analyze` command.

    Full pipeline:
      1. Load / extract skeletons from dataset documents.
      2. Run pairwise or one-vs-all similarity comparison.
      3. Flag suspicious pairs with RED / AMBER severity.
      4. Render coloured output table.
      5. Evaluate accuracy against ground truth (if available).
      6. Save JSON report to disk.

    Args:
        args : Parsed argparse namespace.
    """
    import fraud_flagger
    import template_extractor
    import similarity_engine

    # Override thresholds from CLI if provided
    fraud_flagger.RED_THRESHOLD = args.threshold_red
    fraud_flagger.AMBER_THRESHOLD = args.threshold_amber

    dataset_dir = Path(args.dataset)
    if not dataset_dir.is_absolute():
        dataset_dir = _SCRIPT_DIR / dataset_dir

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = _SCRIPT_DIR / output_path

    print(f"\n=== Template Matching Fraud Detector ===")
    print(f"Dataset : {dataset_dir}")
    print(f"Report  : {output_path}")
    print(f"Thresholds: RED ≥ {args.threshold_red}% | AMBER ≥ {args.threshold_amber}%\n")

    # ---- Step 1: Extract skeletons from the dataset ----
    try:
        extractions = template_extractor.extract_all(str(dataset_dir))
    except FileNotFoundError as e:
        print(f"\nERROR: {e}")
        sys.exit(1)

    # ---- Step 2: Compare pairs ----
    if args.file:
        # Single-file mode: compare one new document vs the dataset
        new_file = Path(args.file)
        if not new_file.exists():
            print(f"\nERROR: File not found: {args.file}")
            sys.exit(1)
        new_extraction = template_extractor.load_and_extract(str(new_file))
        comparison_results = similarity_engine.compare_one_vs_all(new_extraction, extractions)
        # Merge the new doc into extractions so flagging can read its raw text
        extractions[new_extraction["doc_id"]] = new_extraction
    else:
        # Full dataset mode: compare every pair
        comparison_results = similarity_engine.compare_all_pairs(extractions)

    # ---- Step 3: Flag suspicious pairs ----
    flagged = fraud_flagger.flag_pairs(comparison_results, extractions)

    # ---- Step 4: Render coloured output ----
    fraud_flagger.render_flagged_pairs(flagged)

    # ---- Step 5: Accuracy evaluation (only meaningful in full-dataset mode) ----
    metrics = {}
    if not args.file:
        gt = fraud_flagger.load_ground_truth(str(dataset_dir))
        metrics = fraud_flagger.evaluate_accuracy(flagged, gt, comparison_results)

    # ---- Step 6: Save report ----
    fraud_flagger.save_report(flagged, metrics, str(output_path))

    # ---- Save similarity results JSON too (for inspection) ----
    sim_path = output_path.parent / "similarity_results.json"
    similarity_engine.save_results(comparison_results, str(sim_path))


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """
    Construct and return the top-level argument parser with subcommands.

    Returns:
        Configured argparse.ArgumentParser instance.
    """
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

    # ---- generate-dataset subcommand ----
    gen_parser = subparsers.add_parser(
        "generate-dataset",
        help="Generate the synthetic dataset of insurance claim documents.",
    )
    gen_parser.add_argument(
        "--dataset",
        default="dataset",
        metavar="DIR",
        help="Output directory for generated documents (default: ./dataset).",
    )
    gen_parser.add_argument(
        "--n",
        type=int,
        default=80,
        metavar="N",
        help="Approximate total number of documents to generate (default: 80).",
    )

    # ---- analyze subcommand ----
    ana_parser = subparsers.add_parser(
        "analyze",
        help="Run template extraction and similarity analysis on the dataset.",
    )
    ana_parser.add_argument(
        "--file",
        default=None,
        metavar="PATH",
        help=(
            "Path to a single new .txt document to compare against the "
            "existing dataset, instead of running a full pairwise comparison."
        ),
    )
    ana_parser.add_argument(
        "--dataset",
        default="dataset",
        metavar="DIR",
        help="Directory containing the dataset .txt files (default: ./dataset).",
    )
    ana_parser.add_argument(
        "--output",
        default="report.json",
        metavar="PATH",
        help="Output path for the JSON report (default: ./report.json).",
    )
    ana_parser.add_argument(
        "--threshold-red",
        type=float,
        default=90.0,
        metavar="SCORE",
        help="Similarity score (0-100) at or above which a pair is RED-flagged (default: 90).",
    )
    ana_parser.add_argument(
        "--threshold-amber",
        type=float,
        default=70.0,
        metavar="SCORE",
        help="Similarity score (0-100) at or above which a pair is AMBER-flagged (default: 70).",
    )

    return parser


def main() -> None:
    """
    Parse command-line arguments and dispatch to the appropriate handler.
    Prints usage help if no command is provided.
    """
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
