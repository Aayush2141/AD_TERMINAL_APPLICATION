"""
dataset_generator.py — Generates a synthetic dataset of medical claims.

Document types: Invoices, Prescriptions, Lab Reports (3 template styles each = 9 total).

How fraud is simulated:
  Fraudulent documents reuse the EXACT SAME layout skeleton across DIFFERENT fake
  provider names. The algorithm detects these pairs because their underlying structure
  is identical, despite having different surface-level provider and patient details.

  Legitimate documents each come from a unique official provider and use their own template.
"""

import csv
import itertools
import json
import random
from pathlib import Path

random.seed(42)  # Fixed seed for reproducible dataset generation

# --- Filler Data Pools ---
FIRST_NAMES = ["Aarav", "Aditi", "Arjun", "Bhavya", "Chetan", "Deepa", "Eshan", "Farida",
               "Gaurav", "Hema", "Karan", "Priya", "Rahul", "Simran", "Zara"]
LAST_NAMES  = ["Sharma", "Patel", "Verma", "Singh", "Gupta", "Mehta", "Kumar", "Shah",
               "Rao", "Nair", "Iyer", "Joshi", "Kapoor"]
DOCTORS     = ["Dr. Rajesh Mehta", "Dr. Sunita Rao", "Dr. Vikram Agarwal",
               "Dr. Deepika Pillai", "Dr. Suresh Sharma", "Dr. Kavitha Iyer"]
DIAGNOSES   = ["Type 2 Diabetes Mellitus", "Hypertension", "Acute Gastroenteritis",
               "Upper Respiratory Infection", "Hypothyroidism", "Vitamin D Deficiency"]
DRUGS = [
    "Amoxicillin 500mg", "Metformin 1000mg", "Atorvastatin 20mg", "Omeprazole 20mg",
    "Pantoprazole 40mg", "Cetirizine 10mg", "Paracetamol 650mg", "Dolo 650", "Amlodipine 5mg",
]
TESTS = [
    "Complete Blood Count (CBC)", "Lipid Profile", "HbA1c", "Liver Function Test (LFT)",
    "Kidney Function Test (KFT)", "Thyroid Stimulating Hormone (TSH)", "Serum Creatinine",
]

# Official providers for each legitimate template
TEMPLATE_DEFAULT_PROVIDERS = {
    ("invoice",      0): ("Apollo Health Clinic",    "PRV1001"),
    ("invoice",      1): ("Sunrise Medical Centre",  "PRV1002"),
    ("invoice",      2): ("Greenleaf Hospital",      "PRV1003"),
    ("prescription", 0): ("Metro Care Diagnostics",  "PRV1004"),
    ("prescription", 1): ("Lotus Wellness Hub",      "PRV1005"),
    ("prescription", 2): ("BlueCross Pharmacy",      "PRV1006"),
    ("lab",          0): ("LifeLine Laboratories",   "PRV1007"),
    ("lab",          1): ("NovaMed Institute",        "PRV1008"),
    ("lab",          2): ("PrimeCare Clinic",         "PRV1009"),
}

# Fake provider names used exclusively on fraudulent claims
FRAUD_FAKE_PROVIDERS = [
    ("Apex Health Partners",     "PRV2001"), ("Sterling Care Clinic",    "PRV2002"),
    ("Zenith Medical Centre",    "PRV2003"), ("Global Horizon Hospital", "PRV2004"),
    ("Elite Diagnostics Hub",    "PRV2005"), ("Silverline Medicare",     "PRV2006"),
    ("Crestview Healthcare",     "PRV2007"), ("Pinnacle Pathology",      "PRV2008"),
    ("Vanguard Clinical Labs",   "PRV2009"), ("Trident Specialty Care",  "PRV2010"),
]


def _build_filler(doc_type: str) -> dict:
    """Generate random realistic data fields to fill any document template."""
    consult  = random.randint(300, 1500)
    subtotal = random.randint(500, 8000)
    gst      = int((consult + subtotal) * 0.18)

    drugs = [f"  - {d}  x{random.randint(1, 3)}  INR {random.randint(80, 400)}"
             for d in random.sample(DRUGS, random.randint(2, 4))]
    tests = [f"  - {t}: {round(random.uniform(1.0, 150.0), 2)}"
             for t in random.sample(TESTS, random.randint(2, 4))]

    return {
        "claim_id":   f"CLM{random.randint(100000, 999999)}",
        "date":       f"{random.randint(1, 28):02d}-{random.randint(1, 12):02d}-2024",
        "patient":    f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}",
        "patient_id": f"PAT{random.randint(10000, 99999)}",
        "doctor":     random.choice(DOCTORS),
        "diagnosis":  random.choice(DIAGNOSES),
        "drugs":      drugs,
        "tests":      tests,
        "consult_fee": consult,
        "subtotal":    subtotal,
        "gst":         gst,
        "amount":      consult + subtotal + gst,
    }


# ===========================================================================
# 9 Template Functions (3 Invoices, 3 Prescriptions, 3 Lab Reports)
# ===========================================================================

def _invoice_0(v: dict) -> str:
    """Invoice Style 0: Classic box format — provider first, then patient."""
    return f"""==========================================================
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
{chr(10).join(v['drugs'])}
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


def _invoice_1(v: dict) -> str:
    """Invoice Style 1: Billing document — patient (TO:) first, then provider (FROM:)."""
    return f"""***** HEALTHCARE BILLING DOCUMENT *****
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
{chr(10).join(v['drugs'])}
- Consultation        : INR {v['consult_fee']}
- Investigations      : INR {v['subtotal']}
***************************************
GST Applied    : 18%  (INR {v['gst']})
GRAND TOTAL    : INR {v['amount']}
***************************************
Authorised By  : {v['doctor']}
***************************************
"""


def _invoice_2(v: dict) -> str:
    """Invoice Style 2: Plain expense voucher — no decorative borders."""
    return f"""EXPENSE VOUCHER
Voucher Ref: {v['claim_id']}
Date of Service: {v['date']}
Facility: {v['provider']} | Facility Code: {v['provider_id']}
Claimant: {v['patient']} | Claimant ID: {v['patient_id']}

SERVICE ITEMS:
{chr(10).join(v['drugs'])}

COST SUMMARY:
  Consultation Fee ............... INR {v['consult_fee']}
  Tests & Medicines .............. INR {v['subtotal']}
  GST @ 18% ........................ INR {v['gst']}

Net Payable: INR {v['amount']}
Certified by: {v['doctor']}
"""


def _prescription_0(v: dict) -> str:
    """Prescription Style 0: Formal Rx format — doctor first, then patient."""
    return f"""==================================================
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
{chr(10).join(v['drugs'])}
--------------------------------------------------
Instructions: Take as directed. Avoid alcohol.
Follow-up   : After 7 days or as needed.
==================================================
Doctor's Signature: ___________________
==================================================
"""


def _prescription_1(v: dict) -> str:
    """Prescription Style 1: Outpatient form with numbered drug list."""
    drug_lines = "\n".join(f"  {i+1}. {d.strip().lstrip('- ')}" for i, d in enumerate(v["drugs"]))
    return f"""OUTPATIENT PRESCRIPTION
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


def _prescription_2(v: dict) -> str:
    """Prescription Style 2: Table-grid e-prescription format."""
    drug_rows = "\n".join(f"  | {d.strip().lstrip('- '):<55} | As directed |" for d in v["drugs"])
    return f"""E-PRESCRIPTION
TxnID: {v['claim_id']}  |  Date: {v['date']}  |  [QR-CODE: {v['claim_id']}]
Physician : {v['doctor']}   Institute: {v['provider']}   Reg: {v['provider_id']}
Patient Name: {v['patient']}   UHI: {v['patient_id']}
Ailment: {v['diagnosis']}

  +----------------------------------------------------------+-------------+
  | MEDICINE / DOSE                                          | DURATION    |
  +----------------------------------------------------------+-------------+
{drug_rows}
  +----------------------------------------------------------+-------------+

REGULATORY NOTE: This e-prescription is system-generated and legally valid.
Physician Digital Signature: ___________________
"""


def _lab_0(v: dict) -> str:
    """Lab Report Style 0: Classic diagnostic report with hash borders."""
    return f"""##############################################
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
{chr(10).join(v['tests'])}
----------------------------------------------
Total Charges: INR {v['amount']}
----------------------------------------------
Verified By: Lab Technician
Pathologist: {v['doctor']}
##############################################
"""


def _lab_1(v: dict) -> str:
    """Lab Report Style 1: Compact lab slip — amount shown at the top."""
    return f"""LAB REPORT
==========
Ref: {v['claim_id']}   Date: {v['date']}
Lab: {v['provider']}  Lic: {v['provider_id']}
Amount: INR {v['amount']}

Patient: {v['patient']}  ID: {v['patient_id']}
Doctor : {v['doctor']}

INVESTIGATIONS:
{chr(10).join(v['tests'])}

Report validated and digitally signed.
"""


def _lab_2(v: dict) -> str:
    """Lab Report Style 2: Sectional report with Sample Details and Billing Summary."""
    test_rows = "\n".join(f"  {i+1:02d}. {t.strip().lstrip('- ')}" for i, t in enumerate(v["tests"]))
    return f""">>>>>>>>>> DIAGNOSTIC LABORATORY REPORT <<<<<<<<<<

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

>>>>>>>>>>>>>>>>>>>>>>>>>>><<<<<<<<<<<<<<<<<<<<<
"""


TEMPLATE_REGISTRY = {
    ("invoice",      0): _invoice_0,
    ("invoice",      1): _invoice_1,
    ("invoice",      2): _invoice_2,
    ("prescription", 0): _prescription_0,
    ("prescription", 1): _prescription_1,
    ("prescription", 2): _prescription_2,
    ("lab",          0): _lab_0,
    ("lab",          1): _lab_1,
    ("lab",          2): _lab_2,
}
ALL_TEMPLATE_KEYS = list(TEMPLATE_REGISTRY.keys())


def generate_document(doc_type: str, template_idx: int, provider: str = None, provider_id: str = None) -> str:
    """Generate a text document using the specified template and random filler data."""
    key    = (doc_type, template_idx)
    filler = _build_filler(doc_type)
    filler["provider"]    = provider    or TEMPLATE_DEFAULT_PROVIDERS[key][0]
    filler["provider_id"] = provider_id or TEMPLATE_DEFAULT_PROVIDERS[key][1]
    return TEMPLATE_REGISTRY[key](filler)


def generate_dataset(output_dir: str = "dataset", n_total: int = 80) -> dict:
    """
    Generate synthetic claim documents and save them with metadata and ground-truth fraud pairs.

    Structure:
      - 15 Fraudulent claims: 3 clusters of 5 documents each, where all documents in a cluster
        share the same template skeleton but carry different fake provider names.
      - Remaining: Legitimate claims from official providers using their own templates.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    metadata    = {}
    fraud_pairs = []

    fraud_templates    = [("invoice", 1), ("prescription", 0), ("lab", 2)]
    fraud_cluster_size = 5
    n_fraud            = len(fraud_templates) * fraud_cluster_size
    n_legit            = n_total - n_fraud

    doc_counter    = 0
    fake_providers = itertools.cycle(FRAUD_FAKE_PROVIDERS)

    # 1. Generate fraud clusters
    for doc_type, tmpl_idx in fraud_templates:
        cluster_ids = []

        for _ in range(fraud_cluster_size):
            doc_id              = f"doc_{doc_counter:04d}"
            fake_prov, fake_pid = next(fake_providers)

            content = generate_document(doc_type, tmpl_idx, provider=fake_prov, provider_id=fake_pid)
            (out / f"{doc_id}.txt").write_text(content, encoding="utf-8")

            metadata[doc_id] = {
                "path":         str(out / f"{doc_id}.txt"),
                "doc_type":     doc_type,
                "template_key": f"{doc_type}_{tmpl_idx}",
                "provider":     fake_prov,
                "is_fraud":     True,
            }
            cluster_ids.append(doc_id)
            doc_counter += 1

        # All pairs within a cluster are ground-truth fraud pairs
        fraud_pairs.extend(itertools.combinations(cluster_ids, 2))

    # 2. Generate legitimate claims (from templates not reserved for fraud)
    legit_templates = [k for k in ALL_TEMPLATE_KEYS if k not in fraud_templates]
    for _ in range(n_legit):
        doc_id              = f"doc_{doc_counter:04d}"
        doc_type, tmpl_idx  = random.choice(legit_templates)

        content = generate_document(doc_type, tmpl_idx)
        (out / f"{doc_id}.txt").write_text(content, encoding="utf-8")

        metadata[doc_id] = {
            "path":         str(out / f"{doc_id}.txt"),
            "doc_type":     doc_type,
            "template_key": f"{doc_type}_{tmpl_idx}",
            "provider":     TEMPLATE_DEFAULT_PROVIDERS[(doc_type, tmpl_idx)][0],
            "is_fraud":     False,
        }
        doc_counter += 1

    # Save outputs
    (out / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    with open(out / "ground_truth.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["doc_id_a", "doc_id_b"])
        writer.writerows(fraud_pairs)

    print(f"[dataset_generator] Generated {doc_counter} documents in '{out}/'")
    print(f"  Legitimate : {n_legit} documents")
    print(f"  Fraudulent : {n_fraud} documents (3 clusters, {len(fraud_pairs)} fraud pairs)")

    return {"metadata": metadata, "fraud_pairs": fraud_pairs, "output_dir": str(out)}
