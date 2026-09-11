"""
dataset_generator.py
====================
Responsible for generating the synthetic dataset of medical insurance documents
(invoices, prescriptions, lab reports).

Design philosophy
-----------------
Fraud is simulated by having multiple documents share the *same structural
skeleton* (same template ID) while appearing to come from different providers /
patients.  The skeleton defines how a document is *laid out* – which fields
appear, in what order, with what surrounding text.  The variable fields
(names, dates, amounts, etc.) are filled with random realistic-looking data.

A separate metadata file records which documents came from the same skeleton so
that detection accuracy can be measured objectively after analysis.
"""

import csv
import json
import os
import random
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Seed the RNG for reproducibility (change or remove for different runs)
# ---------------------------------------------------------------------------
random.seed(42)

# ---------------------------------------------------------------------------
# Realistic filler pools
# ---------------------------------------------------------------------------
PATIENT_FIRST = [
    "Aarav", "Aditi", "Arjun", "Bhavya", "Chetan", "Deepa", "Eshan",
    "Farida", "Gaurav", "Hema", "Ishaan", "Jyoti", "Karan", "Lakshmi",
    "Manav", "Nisha", "Om", "Priya", "Rahul", "Simran", "Tanvi",
    "Uday", "Varun", "Yash", "Zara", "Amrita", "Bharat", "Chitra",
]
PATIENT_LAST = [
    "Sharma", "Patel", "Verma", "Singh", "Gupta", "Mehta", "Kumar",
    "Shah", "Rao", "Nair", "Iyer", "Joshi", "Malhotra", "Choudhary",
    "Reddy", "Pillai", "Bhatia", "Kapoor", "Saxena", "Trivedi",
]
PROVIDER_NAMES = [
    "Apollo Health Clinic", "Sunrise Medical Centre", "Greenleaf Hospital",
    "Metro Care Diagnostics", "Lotus Wellness Hub", "BlueCross Pharmacy",
    "LifeLine Laboratories", "NovaMed Institute", "PrimeCare Clinic",
    "HealWell Diagnostics", "MediFirst Centre", "CityHealth Hospital",
    "Omni Labs & Imaging", "SafeHands Medical", "StarMed Pharmacy",
]
PROVIDER_IDS = [f"PRV{str(i).zfill(4)}" for i in range(1001, 1030)]
CLAIM_IDS = [f"CLM{str(i).zfill(6)}" for i in range(100001, 200000)]
DOCTOR_FIRST = [
    "Rajesh", "Sunita", "Mohan", "Anitha", "Vikram", "Priyanka",
    "Suresh", "Kavitha", "Arun", "Deepika",
]
DOCTOR_LAST = [
    "Mehta", "Krishnamurthy", "Bose", "Agarwal", "Chandra", "Pillai",
    "Iyer", "Sharma", "Nambiar", "Desai",
]
DRUGS = [
    "Amoxicillin 500mg", "Metformin 1000mg", "Atorvastatin 20mg",
    "Omeprazole 20mg", "Pantoprazole 40mg", "Losartan 50mg",
    "Cetirizine 10mg", "Azithromycin 250mg", "Ibuprofen 400mg",
    "Paracetamol 650mg", "Clopidogrel 75mg", "Amlodipine 5mg",
    "Dolo 650", "Montelukast 10mg", "Vitamin D3 60000IU",
]
TESTS = [
    "Complete Blood Count (CBC)", "Lipid Profile", "HbA1c",
    "Liver Function Test (LFT)", "Kidney Function Test (KFT)",
    "Thyroid Stimulating Hormone (TSH)", "Urine Routine & Microscopy",
    "Chest X-Ray", "ECG (Electrocardiogram)", "Blood Glucose (Fasting)",
    "Blood Glucose (PP)", "Serum Creatinine", "HBsAg (Hepatitis B)",
    "Dengue NS1 Antigen", "COVID-19 RT-PCR",
]
DIAGNOSES = [
    "Type 2 Diabetes Mellitus", "Hypertension", "Upper Respiratory Tract Infection",
    "Acute Gastroenteritis", "Dyslipidemia", "Hypothyroidism",
    "Dengue Fever", "Mild Anaemia", "Vitamin D Deficiency",
    "Anxiety Disorder",
]


# ---------------------------------------------------------------------------
# Helper value generators
# ---------------------------------------------------------------------------

def _rand_patient() -> str:
    """Return a randomly composed patient full name."""
    return f"{random.choice(PATIENT_FIRST)} {random.choice(PATIENT_LAST)}"


def _rand_doctor() -> str:
    """Return a random doctor full name with title."""
    return f"Dr. {random.choice(DOCTOR_FIRST)} {random.choice(DOCTOR_LAST)}"


def _rand_provider() -> str:
    """Return a random provider name."""
    return random.choice(PROVIDER_NAMES)


def _rand_provider_id() -> str:
    """Return a random provider registration ID."""
    return random.choice(PROVIDER_IDS)


def _rand_claim_id() -> str:
    """Return a random claim ID."""
    return random.choice(CLAIM_IDS)


def _rand_date() -> str:
    """Return a random date string in DD-MM-YYYY format."""
    day = random.randint(1, 28)
    month = random.randint(1, 12)
    year = random.randint(2023, 2025)
    return f"{day:02d}-{month:02d}-{year}"


def _rand_amount() -> str:
    """Return a random monetary amount as a string (in INR)."""
    return str(random.randint(200, 45000))


def _rand_patient_id() -> str:
    """Return a random patient ID."""
    return f"PAT{random.randint(10000, 99999)}"


def _rand_drugs(n: int = None) -> list:
    """Return a list of n random drug entries (name + qty + price)."""
    n = n or random.randint(2, 5)
    chosen = random.sample(DRUGS, min(n, len(DRUGS)))
    lines = []
    for drug in chosen:
        qty = random.randint(1, 3)
        price = random.randint(50, 800)
        lines.append(f"  - {drug}  x{qty}  INR {price * qty}")
    return lines


def _rand_tests(n: int = None) -> list:
    """Return a list of n random test entries (name + result value)."""
    n = n or random.randint(2, 5)
    chosen = random.sample(TESTS, min(n, len(TESTS)))
    lines = []
    for test in chosen:
        val = round(random.uniform(0.5, 200.0), 2)
        lines.append(f"  - {test}: {val}")
    return lines


# ---------------------------------------------------------------------------
# Template skeletons
# ---------------------------------------------------------------------------
# Each skeleton is a Python callable that receives a dict of filler values and
# returns the full document text.  The *structure* (labels, line order,
# formatting, section headers) is hard-coded in the skeleton; only the VALUES
# are injected.  This means two documents from the same skeleton will have
# identical structure once their values are masked back out.

def _invoice_template_A(v: dict) -> str:
    """
    Medical Invoice – Template A
    Classic structured format: equals-separator box, provider FIRST then patient,
    itemised charges section, GST breakdown, total at bottom.
    Distinctive: '========' borders, 'Invoice No', 'ITEMISED CHARGES', 'TOTAL AMOUNT DUE'.
    """
    drugs_str = "\n".join(v["drugs"])
    return f"""\
==========================================================
                    MEDICAL INVOICE
==========================================================
Invoice No : {v['claim_id']}
Date       : {v['date']}
----------------------------------------------------------
Provider   : {v['provider']}
Provider ID: {v['provider_id']}
----------------------------------------------------------
Patient    : {v['patient']}
Patient ID : {v['patient_id']}
----------------------------------------------------------
ITEMISED CHARGES:
{drugs_str}
----------------------------------------------------------
Consultation Fee   : INR {v['consult_fee']}
Subtotal           : INR {v['subtotal']}
GST (18%)          : INR {v['gst']}
----------------------------------------------------------
TOTAL AMOUNT DUE   : INR {v['amount']}
==========================================================
Attending Physician: {v['doctor']}
Signature          : ___________________
==========================================================
"""


def _invoice_template_B(v: dict) -> str:
    """
    Medical Invoice – Template B
    Completely different layout: patient FIRST (TO: block), then provider,
    then a combined medicines+consultation line list (no subtotal breakdown),
    GST shown inline, GRAND TOTAL label used instead of TOTAL AMOUNT DUE.
    Distinctive: '*****' borders, 'HEALTHCARE BILLING DOCUMENT', 'Bill Ref',
    'TO:' block, 'PRESCRIBED ITEMS / SERVICES', 'GRAND TOTAL', 'Authorised By'.
    """
    drugs_str = "\n".join(v["drugs"])
    return f"""\
***** HEALTHCARE BILLING DOCUMENT *****
Bill Ref   : {v['claim_id']}
Bill Date  : {v['date']}
***************************************
TO:
  Patient Name : {v['patient']}
  Patient ID   : {v['patient_id']}
FROM:
  Issued By  : {v['provider']}
  Reg. No.   : {v['provider_id']}
***************************************
PRESCRIBED ITEMS / SERVICES:
{drugs_str}
- Consultation        : INR {v['consult_fee']}
- Investigations      : INR {v['subtotal']}
***************************************
GST Applied    : {v['gst_pct']}%  (INR {v['gst']})
GRAND TOTAL    : INR {v['amount']}
***************************************
Authorised By  : {v['doctor']}
***************************************
"""


def _invoice_template_C(v: dict) -> str:
    """
    Medical Invoice – Template C
    Minimalist narrative style: no separator lines at all, dense single-line
    headers, amount breakdown shown as a compact 3-column table.
    Distinctive: 'EXPENSE VOUCHER', 'Claimant', 'Facility Code', 'SERVICE ITEMS',
    'COST SUMMARY', 'Net Payable', 'Certified by'.
    """
    drugs_str = "\n".join(v["drugs"])
    return f"""\
EXPENSE VOUCHER
Voucher Ref: {v['claim_id']}
Date of Service: {v['date']}
Facility: {v['provider']} | Facility Code: {v['provider_id']}
Claimant: {v['patient']} | Claimant ID: {v['patient_id']}

SERVICE ITEMS:
{drugs_str}

COST SUMMARY:
  Consultation Fee ............... INR {v['consult_fee']}
  Tests & Medicines .............. INR {v['subtotal']}
  GST @ {v['gst_pct']}% ........................ INR {v['gst']}

Net Payable: INR {v['amount']}
Certified by: {v['doctor']}
"""


def _prescription_template_A(v: dict) -> str:
    """
    Prescription – Template A
    Formal boxed Rx format: doctor block FIRST, then patient, then diagnosis,
    then medications, then a two-field instructions block.
    Distinctive: '====' borders, 'PRESCRIPTION', 'Rx No.', 'Doctor', 'Clinic',
    'Diagnosis', 'MEDICATIONS PRESCRIBED', 'Instructions', 'Follow-up'.
    """
    drugs_str = "\n".join(v["drugs"])
    return f"""\
==================================================
                   PRESCRIPTION
==================================================
Rx No.     : {v['claim_id']}
Date       : {v['date']}
--------------------------------------------------
Doctor     : {v['doctor']}
Clinic     : {v['provider']}
Reg. No.   : {v['provider_id']}
--------------------------------------------------
Patient    : {v['patient']}
Patient ID : {v['patient_id']}
Diagnosis  : {v['diagnosis']}
--------------------------------------------------
MEDICATIONS PRESCRIBED:
{drugs_str}
--------------------------------------------------
Instructions: Take as directed. Avoid alcohol.
Follow-up   : After 7 days or as needed.
==================================================
Doctor's Signature: ___________________
==================================================
"""


def _prescription_template_B(v: dict) -> str:
    """
    Prescription – Template B
    Compact tabular style: patient block FIRST, then practitioner details,
    drugs listed as numbered items, single footer signature line.
    Distinctive: 'OUTPATIENT PRESCRIPTION', 'Ref No', 'PATIENT', 'Member ID',
    'Clinical Dx', 'PRESCRIBER', 'License', 'DRUG LIST', numbered drugs,
    'Dispensing Note', 'Rx Valid'.
    """
    drug_lines = "\n".join(
        f"  {i+1}. {d.strip().lstrip('- ')}"
        for i, d in enumerate(v["drugs"])
    )
    return f"""\
OUTPATIENT PRESCRIPTION
Ref No: {v['claim_id']}   Date Issued: {v['date']}

PATIENT
  Full Name  : {v['patient']}
  Member ID  : {v['patient_id']}
  Clinical Dx: {v['diagnosis']}

PRESCRIBER
  Name       : {v['doctor']}
  Facility   : {v['provider']}
  License    : {v['provider_id']}

DRUG LIST:
{drug_lines}

Dispensing Note: Dispense as written. No substitution.
Rx Valid Until : 30 days from date of issue.
Prescriber Seal: ___________________
"""


def _prescription_template_C(v: dict) -> str:
    """
    Prescription – Template C
    Electronic prescription stub format: single dense header line, QR-code
    placeholder, drugs in a table with units column, validity footer.
    Distinctive: 'E-PRESCRIPTION', 'TxnID', 'QR-CODE', 'Physician', 'Institute',
    'Reg', 'Patient Name', 'UHI', 'Ailment', 'MEDICINE', 'DOSE', 'DURATION',
    'REGULATORY NOTE'.
    """
    # Format drugs as a simple table with dose column
    drug_rows = []
    for d in v["drugs"]:
        # d looks like "  - Amoxicillin 500mg  x2  INR 300"
        drug_rows.append(f"  | {d.strip().lstrip('- '):<55} | As directed |")
    drug_table = "\n".join(drug_rows)
    return f"""\
E-PRESCRIPTION
TxnID: {v['claim_id']}  |  Date: {v['date']}  |  [QR-CODE: {v['claim_id']}]
Physician : {v['doctor']}   Institute: {v['provider']}   Reg: {v['provider_id']}
Patient Name: {v['patient']}   UHI: {v['patient_id']}
Ailment: {v['diagnosis']}

  +----------------------------------------------------------+-------------+
  | MEDICINE / DOSE                                          | DURATION    |
  +----------------------------------------------------------+-------------+
{drug_table}
  +----------------------------------------------------------+-------------+

REGULATORY NOTE: This e-prescription is system-generated and legally valid.
Physician Digital Signature: ___________________
"""


def _lab_template_A(v: dict) -> str:
    """
    Lab Report – Template A
    Classic diagnostic report: hash-border header, provider then patient,
    test results as a bulleted list, pathologist sign-off at the end.
    Distinctive: '###' borders, 'LABORATORY TEST REPORT', 'Report ID',
    'Laboratory', 'Lab Reg.', 'Referred By', 'TEST RESULTS', 'Verified By',
    'Pathologist'.
    """
    tests_str = "\n".join(v["tests"])
    return f"""\
##############################################
#          LABORATORY TEST REPORT            #
##############################################
Report ID  : {v['claim_id']}
Report Date: {v['date']}
----------------------------------------------
Laboratory : {v['provider']}
Lab Reg.   : {v['provider_id']}
----------------------------------------------
Patient    : {v['patient']}
Patient ID : {v['patient_id']}
Referred By: {v['doctor']}
----------------------------------------------
TEST RESULTS:
{tests_str}
----------------------------------------------
Total Charges: INR {v['amount']}
----------------------------------------------
Verified By: Lab Technician
Pathologist: {v['doctor']}
##############################################
"""


def _lab_template_B(v: dict) -> str:
    """
    Lab Report – Template B
    Invoice-style lab report: amount shown at the TOP, patient inline with
    doctor, tests listed under 'INVESTIGATIONS', no pathologist section.
    Distinctive: 'LAB REPORT', 'Ref', 'Lab', 'Lic', 'Amount' at top,
    'INVESTIGATIONS', 'digitally signed' footer.
    """
    tests_str = "\n".join(v["tests"])
    return f"""\
LAB REPORT
==========
Ref: {v['claim_id']}   Date: {v['date']}
Lab: {v['provider']}  Lic: {v['provider_id']}
Amount: INR {v['amount']}

Patient: {v['patient']}  ID: {v['patient_id']}
Doctor : {v['doctor']}

INVESTIGATIONS:
{tests_str}

Report validated and digitally signed.
"""


def _lab_template_C(v: dict) -> str:
    """
    Lab Report – Template C
    Section-based tabular format with SAMPLE DETAILS block, results in a
    numbered list, and a BILLING SUMMARY section at the end.
    Distinctive: '>>>' borders, 'DIAGNOSTIC LABORATORY REPORT',
    'SAMPLE DETAILS', 'Collected On', 'Reported On', 'LABORATORY INFO',
    'PATIENT INFO', numbered results, 'BILLING SUMMARY', 'Amount Due'.
    """
    # Format tests as a numbered list
    test_rows = "\n".join(
        f"  {i+1:02d}. {t.strip().lstrip('- ')}"
        for i, t in enumerate(v["tests"])
    )
    return f"""\
>>>>>>>>>> DIAGNOSTIC LABORATORY REPORT <<<<<<<<<<

SAMPLE DETAILS
  Collected On : {v['date']}
  Reported On  : {v['date']}
  Sample Ref   : {v['claim_id']}

LABORATORY INFO
  Name         : {v['provider']}
  Accred. No.  : {v['provider_id']}

PATIENT INFO
  Name         : {v['patient']}
  UHID         : {v['patient_id']}
  Referring Dr : {v['doctor']}

TEST FINDINGS:
{test_rows}

BILLING SUMMARY
  Amount Due   : INR {v['amount']}
  All results reviewed by a certified pathologist.

>>>>>>>>>>>>>>>>>>>>>>>>>>><<<<<<<<<<<<<<<<<<<<<<<
"""



# ---------------------------------------------------------------------------
# Registry: maps (doc_type, template_index) → callable
# We expose 3 types × 3 templates = 9 distinct skeletons.
# ---------------------------------------------------------------------------
TEMPLATE_REGISTRY = {
    ("invoice", 0): _invoice_template_A,
    ("invoice", 1): _invoice_template_B,
    ("invoice", 2): _invoice_template_C,
    ("prescription", 0): _prescription_template_A,
    ("prescription", 1): _prescription_template_B,
    ("prescription", 2): _prescription_template_C,
    ("lab", 0): _lab_template_A,
    ("lab", 1): _lab_template_B,
    ("lab", 2): _lab_template_C,
}
ALL_TEMPLATE_KEYS = list(TEMPLATE_REGISTRY.keys())
DOC_TYPES = ["invoice", "prescription", "lab"]


def _build_filler(doc_type: str) -> dict:
    """
    Build a dict of realistic random filler values for any document type.
    The filler dict is intentionally over-populated so any template can pick
    whichever keys it needs.
    """
    consult_fee = random.randint(300, 1500)
    subtotal = random.randint(500, 8000)
    gst = int((consult_fee + subtotal) * 0.18)
    total = consult_fee + subtotal + gst

    return {
        "claim_id": _rand_claim_id(),
        "date": _rand_date(),
        "provider": _rand_provider(),
        "provider_id": _rand_provider_id(),
        "patient": _rand_patient(),
        "patient_id": _rand_patient_id(),
        "doctor": _rand_doctor(),
        "diagnosis": random.choice(DIAGNOSES),
        "drugs": _rand_drugs(),
        "tests": _rand_tests(),
        "consult_fee": consult_fee,
        "subtotal": subtotal,
        "gst": gst,
        "gst_pct": 18,
        "amount": total,
    }


TEMPLATE_DEFAULT_PROVIDERS = {
    ("invoice", 0): ("Apollo Health Clinic", "PRV1001"),
    ("invoice", 1): ("Sunrise Medical Centre", "PRV1002"),
    ("invoice", 2): ("Greenleaf Hospital", "PRV1003"),
    ("prescription", 0): ("Metro Care Diagnostics", "PRV1004"),
    ("prescription", 1): ("Lotus Wellness Hub", "PRV1005"),
    ("prescription", 2): ("BlueCross Pharmacy", "PRV1006"),
    ("lab", 0): ("LifeLine Laboratories", "PRV1007"),
    ("lab", 1): ("NovaMed Institute", "PRV1008"),
    ("lab", 2): ("PrimeCare Clinic", "PRV1009"),
}

# Provider names used specifically for fraudulent claims to simulate
# the fraud pattern of reusing the same template across different "providers".
FRAUD_FAKE_PROVIDERS = [
    ("Apex Health Partners", "PRV2001"),
    ("Sterling Care Clinic", "PRV2002"),
    ("Zenith Medical Centre", "PRV2003"),
    ("Global Horizon Hospital", "PRV2004"),
    ("Elite Diagnostics Hub", "PRV2005"),
    ("Silverline Medicare", "PRV2006"),
    ("Crestview Healthcare", "PRV2007"),
    ("Pinnacle Pathology", "PRV2008"),
    ("Vanguard Clinical Labs", "PRV2009"),
    ("Trident Specialty Care", "PRV2010"),
]


def generate_document(
    doc_type: str,
    template_idx: int,
    provider: str = None,
    provider_id: str = None,
) -> str:
    """
    Generate a single document of the given doc_type using the template
    identified by template_idx.  Returns the document as a plain text string.

    Args:
        doc_type     : One of 'invoice', 'prescription', 'lab'.
        template_idx : 0, 1, or 2 – which skeleton variant to use.
        provider     : Specific provider name (overrides default).
        provider_id  : Specific provider registration ID.

    Returns:
        The full document text string.
    """
    key = (doc_type, template_idx)
    if key not in TEMPLATE_REGISTRY:
        raise ValueError(f"Unknown template key: {key}")
    filler = _build_filler(doc_type)

    # Use explicit provider if supplied, otherwise use legitimate template default
    if provider:
        filler["provider"] = provider
    elif key in TEMPLATE_DEFAULT_PROVIDERS:
        filler["provider"] = TEMPLATE_DEFAULT_PROVIDERS[key][0]

    if provider_id:
        filler["provider_id"] = provider_id
    elif key in TEMPLATE_DEFAULT_PROVIDERS:
        filler["provider_id"] = TEMPLATE_DEFAULT_PROVIDERS[key][1]

    return TEMPLATE_REGISTRY[key](filler)


# ---------------------------------------------------------------------------
# Dataset generation orchestration
# ---------------------------------------------------------------------------

def generate_dataset(output_dir: str = "dataset", n_total: int = 80) -> dict:
    """
    Generate a synthetic dataset of insurance claim documents and save them
    to *output_dir*.  Returns a metadata dict that is also written to disk.

    Strategy
    --------
    - Legitimate documents: each legitimate provider has their own distinct
      document template style. Legitimate claims reuse the provider's official
      template with random patient/date/billing data.
    - Fraudulent documents: deliberately REUSE the exact same template
      skeleton across DIFFERENT fake provider names/labels (simulating fraud rings).
      These form known fraud clusters and ground-truth fraud pairs.

    Metadata written
    ----------------
    - dataset/metadata.json   – full per-document metadata
    - dataset/ground_truth.csv – list of known fraud pairs (doc_id_A, doc_id_B)

    Args:
        output_dir : Folder path where documents and metadata are saved.
        n_total    : Approximate total number of documents to generate.

    Returns:
        The metadata dict (also written to disk as JSON).
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    metadata = {}        # doc_id → {path, doc_type, template_key, is_fraud}
    fraud_pairs = []     # list of (doc_id_a, doc_id_b) known-fraud pairs

    # ----- Define fraud clusters -----
    # 3 distinct clusters: 5 docs each = 15 fraud documents
    fraud_templates = [
        ("invoice", 1),       # Fraud cluster 1 – invoice template B
        ("prescription", 0),  # Fraud cluster 2 – prescription template A
        ("lab", 2),           # Fraud cluster 3 – lab template C
    ]
    fraud_cluster_size = 5
    n_fraud = len(fraud_templates) * fraud_cluster_size  # 15
    n_legit = n_total - n_fraud                          # 65

    doc_counter = 0

    # --- Generate fraud documents ---
    # Each fraud cluster reuses the SAME template, but assigns a DIFFERENT fake provider to each doc
    fraud_cluster_ids: dict[tuple, list] = {}
    fake_prov_idx = 0

    for ft_key in fraud_templates:
        fraud_cluster_ids[ft_key] = []
        for _ in range(fraud_cluster_size):
            doc_id = f"doc_{doc_counter:04d}"
            doc_type, tmpl_idx = ft_key

            # Pick a unique fake provider for each fraudulent document in this cluster
            fake_prov, fake_pid = FRAUD_FAKE_PROVIDERS[fake_prov_idx % len(FRAUD_FAKE_PROVIDERS)]
            fake_prov_idx += 1

            content = generate_document(doc_type, tmpl_idx, provider=fake_prov, provider_id=fake_pid)
            filepath = out / f"{doc_id}.txt"
            filepath.write_text(content, encoding="utf-8")

            metadata[doc_id] = {
                "path": str(filepath),
                "doc_type": doc_type,
                "template_key": f"{doc_type}_{tmpl_idx}",
                "provider": fake_prov,
                "is_fraud": True,
            }
            fraud_cluster_ids[ft_key].append(doc_id)
            doc_counter += 1

        # Record all pairs within this cluster as ground-truth fraud
        ids_in_cluster = fraud_cluster_ids[ft_key]
        for i in range(len(ids_in_cluster)):
            for j in range(i + 1, len(ids_in_cluster)):
                fraud_pairs.append((ids_in_cluster[i], ids_in_cluster[j]))

    # --- Generate legitimate documents ---
    available_legit = [k for k in ALL_TEMPLATE_KEYS if k not in fraud_templates]
    for _ in range(n_legit):
        doc_id = f"doc_{doc_counter:04d}"
        chosen_key = random.choice(available_legit)
        doc_type, tmpl_idx = chosen_key

        content = generate_document(doc_type, tmpl_idx)
        filepath = out / f"{doc_id}.txt"
        filepath.write_text(content, encoding="utf-8")

        legit_prov = TEMPLATE_DEFAULT_PROVIDERS[chosen_key][0]
        metadata[doc_id] = {
            "path": str(filepath),
            "doc_type": doc_type,
            "template_key": f"{doc_type}_{tmpl_idx}",
            "provider": legit_prov,
            "is_fraud": False,
        }
        doc_counter += 1

    # --- Save metadata.json ---
    meta_path = out / "metadata.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    # --- Save ground_truth.csv ---
    gt_path = out / "ground_truth.csv"
    with open(gt_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["doc_id_a", "doc_id_b"])
        writer.writerows(fraud_pairs)

    print(f"[dataset_generator] Generated {doc_counter} documents → {out}/")
    print(f"  Legitimate: {n_legit}  |  Fraud: {n_fraud} (across {len(fraud_templates)} clusters)")
    print(f"  Ground-truth fraud pairs: {len(fraud_pairs)}")

    return {
        "metadata": metadata,
        "fraud_pairs": fraud_pairs,
        "output_dir": str(out),
    }
