# Similar Document Template Matching Algorithm
### Fraud Detection for Medical Insurance Claims (Python & Node.js)

A high-performance CLI tool (available in both **Python** and **Node.js**) that detects fraudulent insurance documents (invoices, prescriptions, lab reports) by identifying when different documents were generated from the **same structural template** — even when surface content (names, dates, amounts, providers) has been changed.

---

## Quick Start

### Option A: Node.js (Zero external dependencies)
```bash
# Navigate to the project directory
cd fraud_detector

# Run full analysis with color-coded fraud report
node main.js analyze
# Or using npm
npm start
```

### Option B: Python
```bash
# 1. Install optional pretty-printing dependency (optional)
pip install rich

# 2. Run full analysis
python main.py analyze
```

---

## The Algorithm (plain English)

### Problem
Fraudsters photocopy or digitally reuse the same invoice / prescription template and simply change the patient name, date, amount, and provider label. Standard text comparison marks these documents as *different* because the actual text is different — but the *layout and structure* are identical.

### Solution: Template Skeleton Matching

#### Step 1 — Template Extraction (`template_extractor.js` / `.py`)
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

#### Step 2 — Skeleton Comparison (`similarity_engine.js` / `.py`)
Every pair of skeletons of the same document type is compared using a **two-component weighted score**:

```
Combined Score = 0.75 × Sequence Similarity + 0.25 × Line Count Ratio
```

- **Sequence Similarity** (75 %): Ratcliff-Obershelp / SequenceMatcher ratio on the full skeleton text. Measures character and phrase alignment of the document layout.
- **Line Count Ratio** (25 %): Compares proportional length (`min(lines_a, lines_b) / max(lines_a, lines_b)`) to verify structural height.

#### Step 3 — Fraud Flagging (`fraud_flagger.js` / `.py`)
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
├── main.js                # Node.js CLI entry point
├── template_extractor.js  # Node.js skeleton extractor
├── similarity_engine.js   # Node.js fast SequenceMatcher & scoring
├── fraud_flagger.js       # Node.js alert flagger, evaluator, reporter
├── dataset_generator.js   # Node.js synthetic dataset generator
├── test.js                # Node.js test suite
├── package.json           # Node.js metadata and scripts
├── main.py                # Python CLI entry point
├── template_extractor.py  # Python skeleton extractor
├── similarity_engine.py   # Python similarity engine
├── fraud_flagger.py       # Python alert flagger
├── dataset_generator.py   # Python dataset generator
├── dataset/               # Document files
│   ├── doc_0000.txt       # Individual document files
│   ├── ...
│   ├── metadata.json      # Template key + is_fraud flag per document
│   └── ground_truth.csv   # Known fraud pairs (for accuracy testing)
├── report.json            # Generated after running analyze
├── report.csv             # CSV report of flagged pairs
└── similarity_results.json
```

---

## CLI Commands

### Node.js
```bash
# Run full analysis
node main.js analyze

# Compare a single new document against the existing dataset
node main.js analyze --file dataset/doc_0000.txt

# Override fraud thresholds
node main.js analyze --threshold-red 85 --threshold-amber 65

# Generate new synthetic dataset (default: 80 documents)
node main.js generate-dataset --n 80

# Run automated tests
npm test
```

### Python
```bash
# Run full analysis
python main.py analyze

# Compare a single new document against the existing dataset
python main.py analyze --file dataset/doc_0000.txt

# Override fraud thresholds
python main.py analyze --threshold-red 85 --threshold-amber 65

# Generate new synthetic dataset (default: 80 documents)
python main.py generate-dataset --n 80
```

---

## Performance Comparison

| Metric | Python | Node.js |
|---|---|---|
| **Runtime (80 documents, 1,033 comparisons)** | ~4.64s | **~1.21s (~4x faster)** |
| **Precision** | 100.0% | **100.0%** |
| **Recall** | 100.0% | **100.0%** |
| **F1 Score** | 100.0% | **100.0%** |
| **External Dependencies** | `rich` (optional) | **Zero (Native Node.js built-ins)** |

---

## Output Files

| File | Description |
|------|-------------|
| `dataset/doc_NNNN.txt` | Generated document files |
| `dataset/metadata.json` | Per-document metadata (doc type, template, is_fraud flag) |
| `dataset/ground_truth.csv` | Known fraud pairs for accuracy evaluation |
| `report.json` | Flagged pairs + accuracy metrics |
| `report.csv` | Flat CSV table of flagged fraud pairs |
| `similarity_results.json` | All pairwise similarity scores |

---

## Dataset Design

The synthetic dataset deliberately simulates the fraud pattern:

- **~65 legitimate documents** — random combinations of document type and template.
- **~15 fraud documents** — 3 "fraud clusters" of 5 documents each. Each cluster uses the *same structural skeleton* but with different patient names, dates, amounts, and provider labels.
- **30 known fraud pairs** — recorded in `ground_truth.csv` (5 documents × C(5,2) = 10 pairs per cluster × 3 clusters).

This design allows objective accuracy measurement (100% precision, recall, and F1 score).
