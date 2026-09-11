# Similar Document Template Matching Algorithm
### Fraud Detection for Medical Insurance Claims

A Python CLI tool that detects fraudulent insurance documents (invoices, prescriptions, lab reports) by identifying when different documents were generated from the **same structural template** — even when surface content (names, dates, amounts) has been changed.

---

## Quick Start

```bash
# 1. Install the only external dependency
pip install rich

# 2. Navigate to the project directory
cd fraud_detector

# 3. Generate the synthetic dataset (~80 documents)
python main.py generate-dataset

# 4. Run full analysis with colour-coded fraud report
python main.py analyze
```

---

## The Algorithm (plain English)

### Problem
Fraudsters photocopy or digitally reuse the same invoice / prescription template and simply change the patient name, date, amount, and provider label. Standard text comparison marks these documents as *different* because the actual text is different — but the *layout and structure* are identical.

### Solution: Template Skeleton Matching

#### Step 1 — Template Extraction (`template_extractor.py`)
Every document is passed through a **masking pipeline** that uses regular expressions to find and replace variable fields:

| Pattern type          | Replaced with   |
|-----------------------|-----------------|
| Reference & Claim IDs | `<REF_ID>`      |
| Dates (DD-MM-YYYY, …) | `<DATE>`        |
| Monetary amounts      | `<AMOUNT>`      |
| Doctor names (Dr. …)  | `<DOCTOR>`      |
| Percentages (18%)     | `<PERCENT>`     |
| Decimal numbers       | `<NUMBER>`      |
| Quantities & dosages  | `<QTY>`         |
| Patient name values   | `<PATIENT>`     |
| Provider name values  | `<PROVIDER>`    |

What remains is the **structural skeleton** — section headers, field labels, separator lines, and placeholder tokens in the original order.

#### Step 2 — Skeleton Comparison (`similarity_engine.py`)
Every pair of skeletons of the same document type is compared using a **two-component weighted score**:

```
Combined Score = 0.75 × Sequence Similarity + 0.25 × Line Count Ratio
```

- **Sequence Similarity** (75 %): `difflib.SequenceMatcher` ratio on the full skeleton text. Measures character and phrase alignment of the document layout.
- **Line Count Ratio** (25 %): Compares proportional length (`min(lines_a, lines_b) / max(lines_a, lines_b)`) to verify structural height.

#### Step 3 — Fraud Flagging (`fraud_flagger.py`)
| Score range | Flag  | Action              |
|-------------|-------|---------------------|
| ≥ 90 %      | 🔴 RED   | High fraud likelihood |
| 70 – 89 %   | 🟡 AMBER | Suspicious, needs review |
| < 70 %      | ✅ None  | No action required  |

---

## Project Structure

```
fraud_detector/
├── main.py                # CLI entry point (argparse)
├── dataset_generator.py   # Synthetic document generation + fraud clusters
├── template_extractor.py  # Regex-based masking → structural skeleton
├── similarity_engine.py   # Pairwise similarity scoring
├── fraud_flagger.py       # Threshold flagging + rich terminal output
├── dataset/               # Generated after running generate-dataset
│   ├── doc_0000.txt       # Individual document files
│   ├── ...
│   ├── metadata.json      # Template key + is_fraud flag per document
│   └── ground_truth.csv   # Known fraud pairs (for accuracy testing)
├── report.json            # Generated after running analyze
└── similarity_results.json
```

---

## All CLI Commands

```bash
# Generate dataset (default: 80 documents in ./dataset/)
python main.py generate-dataset

# Generate with custom count and directory
python main.py generate-dataset --n 100 --dataset my_data/

# Run full analysis
python main.py analyze

# Analyze with custom dataset directory and report path
python main.py analyze --dataset my_data/ --output my_report.json

# Compare a single new document against the existing dataset
python main.py analyze --file path/to/new_doc.txt

# Override fraud thresholds
python main.py analyze --threshold-red 85 --threshold-amber 65
```

---

## Output Files

| File | Description |
|------|-------------|
| `dataset/doc_NNNN.txt` | Generated document files |
| `dataset/metadata.json` | Per-document metadata (doc type, template, is_fraud flag) |
| `dataset/ground_truth.csv` | Known fraud pairs for accuracy evaluation |
| `report.json` | Flagged pairs + accuracy metrics |
| `similarity_results.json` | All pairwise similarity scores |

---

## Understanding the Output

The terminal will show a colour-coded table:

- **🔴 RED rows**: Documents that are almost certainly from the same template (score ≥ 90%). Strong fraud signal.
- **🟡 AMBER rows**: Structurally similar documents (score 70–89%). Warrant manual review.
- **Same Provider? YES**: Both documents claim the same provider — may be legitimate (same clinic, same format). Less suspicious.
- **Same Provider? NO**: Different providers with near-identical structure — the primary fraud signal.

After the table, a **detection accuracy section** shows Precision, Recall, and F1 score computed against the known ground-truth fraud pairs.

---

## Dependencies

| Library   | Purpose                      | Install         |
|-----------|------------------------------|-----------------|
| `rich`    | Colour terminal tables       | `pip install rich` |
| Python stdlib | `re`, `difflib`, `json`, `csv`, `random`, `argparse`, `pathlib` | built-in |

The tool degrades gracefully if `rich` is not installed — it falls back to ANSI escape codes for colours.

---

## Dataset Design

The synthetic dataset deliberately simulates the fraud pattern:

- **~65 legitimate documents** — random combinations of document type and template.
- **~15 fraud documents** — 3 "fraud clusters" of 5 documents each. Each cluster uses the *same structural skeleton* but with different patient names, dates, amounts, and provider labels. These are the documents the algorithm must identify.
- **30 known fraud pairs** — recorded in `ground_truth.csv` (5 documents × C(5,2) = 10 pairs per cluster × 3 clusters).

This design lets you measure detection accuracy objectively after each run.
