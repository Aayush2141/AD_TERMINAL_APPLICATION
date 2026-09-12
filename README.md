# Similar Document Template Matching Algorithm
### Fraud Detection for Medical Insurance Claims (Node.js)

A high-performance Node.js CLI tool that detects fraudulent insurance documents (invoices, prescriptions, lab reports) by identifying when different documents were generated from the **same structural template** — even when surface content (names, dates, amounts, providers) has been changed.

---

## Highlights

- **Zero External Dependencies**: Runs directly on Node.js using native built-in modules (`fs`, `path`).
- **High Performance**: Evaluates 1,033 pairwise comparisons in **~1.2 seconds**.
- **100% Precision, Recall, and F1 Score**: Perfectly isolates fraud clusters across providers without false alarms.
- **Built-in Test Suite**: Automated verification via `npm test`.

---

## Quick Start

```bash
# 1. Navigate to the project directory
cd fraud_detector

# 2. Run full pairwise analysis with color-coded alerts
npm start
# or: node main.js analyze

# 3. Run the automated test suite
npm test
```

---

## The Algorithm (plain English)

### Problem
Fraudsters photocopy or digitally reuse the same invoice / prescription template and simply change the patient name, date, amount, and provider label. Standard text comparison marks these documents as *different* because the actual text is different — but the *layout and structure* are identical.

### Solution: Template Skeleton Matching

#### Step 1 — Template Extraction (`template_extractor.js`)
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

#### Step 2 — Skeleton Comparison (`similarity_engine.js`)
Every pair of skeletons of the same document type is compared using a **two-component weighted score**:

```
Combined Score = 0.75 × Sequence Similarity + 0.25 × Line Count Ratio
```

- **Sequence Similarity** (75 %): Inverted-index Ratcliff-Obershelp `SequenceMatcher` ratio on the full skeleton text. Measures character and phrase alignment of the document layout.
- **Line Count Ratio** (25 %): Compares proportional length (`min(lines_a, lines_b) / max(lines_a, lines_b)`) to verify structural height.

#### Step 3 — Fraud Flagging (`fraud_flagger.js`)
| Score range | Flag  | Action              |
|-------------|-------|---------------------|
| ≥ 90 %      | 🔴 RED   | High fraud likelihood |
| 70 – 89 %   | 🟡 AMBER | Suspicious, needs review |
| < 70 %      | ✅ None  | No action required  |

Pairs are flagged only when the documents claim to be from **different providers** (same clinic reusing its own form is legitimate).

---

## Project Structure

```
fraud_detector/
├── main.js                # CLI entry point (subcommands & argument parsing)
├── template_extractor.js  # Regex masking pipeline → structural skeletons
├── similarity_engine.js   # Fast inverted-index SequenceMatcher & scoring
├── fraud_flagger.js       # Provider heuristics, alert thresholds, terminal & file reports
├── dataset_generator.js   # Synthetic claims generator across 9 medical templates
├── test.js                # Automated test suite
├── package.json           # NPM scripts and project configuration
├── dataset/               # Document files
│   ├── doc_0000.txt       # Individual document files
│   ├── ...
│   ├── metadata.json      # Template key + is_fraud flag per document
│   └── ground_truth.csv   # Known fraud pairs (for accuracy evaluation)
├── report.json            # Generated after running analyze
├── report.csv             # Flat CSV table of flagged fraud pairs
└── similarity_results.json# Detailed score records
```

---

## CLI Commands & Options

```bash
# Run full pairwise analysis
node main.js analyze

# Run quietly (suppresses decorative banners)
node main.js analyze --quiet

# Compare a single new document against the dataset
node main.js analyze --file dataset/doc_0000.txt

# Override fraud alert thresholds
node main.js analyze --threshold-red 85 --threshold-amber 65

# Generate a new synthetic dataset with custom size and seed
node main.js generate-dataset --n 80 --seed 42

# Show version and help
node main.js --version
node main.js --help
```

---

## Output Files

| File | Description |
|------|-------------|
| `dataset/doc_NNNN.txt` | Generated document text files |
| `dataset/metadata.json` | Per-document metadata (doc type, template, is_fraud flag) |
| `dataset/ground_truth.csv` | Known fraud pairs for accuracy evaluation |
| `report.json` | Flagged pairs + accuracy metrics |
| `report.csv` | Flat CSV table of flagged fraud pairs |
| `similarity_results.json` | All pairwise similarity scores |

---

## Detection Accuracy Benchmarks

Tested on standard synthetic dataset (80 documents, 1,033 pairwise comparisons):

- **True Positives (TP)**: 30 / 30 correctly caught fraud pairs
- **False Positives (FP)**: 0
- **False Negatives (FN)**: 0
- **True Negatives (TN)**: 1,003
- **Precision**: 100.0%
- **Recall**: 100.0%
- **F1 Score**: 100.0%
- **Execution Time**: ~1.21s
