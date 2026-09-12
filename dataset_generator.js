/**
 * dataset_generator.js — Generates a synthetic dataset of medical claims.
 *
 * Document types: Invoices, Prescriptions, Lab Reports (3 template styles each = 9 total).
 *
 * How fraud is simulated:
 *   Fraudulent documents reuse the EXACT SAME layout skeleton across DIFFERENT fake
 *   provider names. The algorithm detects these pairs because their underlying structure
 *   is identical, despite having different surface-level provider and patient details.
 *
 *   Legitimate documents each come from a unique official provider and use their own template.
 */

const fs = require("fs");
const path = require("path");

// ─────────────────────────────────────────────────────────────────────────────
// STEP 1 — REPRODUCIBLE PSEUDO-RANDOM NUMBER GENERATOR (PRNG) & DATA POOLS
// ─────────────────────────────────────────────────────────────────────────────

/**
 * 32-bit Mulberry32 PRNG.
 * Ensures the exact same synthetic dataset can be deterministically reproduced.
 */
function createRng(seed = 42) {
  let s = seed >>> 0;
  return function () {
    s |= 0;
    s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

let rng = createRng(42);

function randInt(min, max) {
  return Math.floor(rng() * (max - min + 1)) + min;
}

function randChoice(arr) {
  return arr[Math.floor(rng() * arr.length)];
}

function randSample(arr, n) {
  const copy = [...arr];
  const sample = [];
  for (let i = 0; i < n && copy.length > 0; i++) {
    const idx = Math.floor(rng() * copy.length);
    sample.push(copy.splice(idx, 1)[0]);
  }
  return sample;
}

// ─────────────────────────────────────────────────────────────────────────────
// STEP 2 — FILLER DATA POOLS
// ─────────────────────────────────────────────────────────────────────────────
const FIRST_NAMES = [
  "Aarav", "Aditi", "Arjun", "Bhavya", "Chetan", "Deepa", "Eshan", "Farida",
  "Gaurav", "Hema", "Karan", "Priya", "Rahul", "Simran", "Zara",
];
const LAST_NAMES = [
  "Sharma", "Patel", "Verma", "Singh", "Gupta", "Mehta", "Kumar", "Shah",
  "Rao", "Nair", "Iyer", "Joshi", "Kapoor",
];
const DOCTORS = [
  "Dr. Rajesh Mehta", "Dr. Sunita Rao", "Dr. Vikram Agarwal",
  "Dr. Deepika Pillai", "Dr. Suresh Sharma", "Dr. Kavitha Iyer",
];
const DIAGNOSES = [
  "Type 2 Diabetes Mellitus", "Hypertension", "Acute Gastroenteritis",
  "Upper Respiratory Infection", "Hypothyroidism", "Vitamin D Deficiency",
];
const DRUGS = [
  "Amoxicillin 500mg", "Metformin 1000mg", "Atorvastatin 20mg", "Omeprazole 20mg",
  "Pantoprazole 40mg", "Cetirizine 10mg", "Paracetamol 650mg", "Dolo 650", "Amlodipine 5mg",
];
const TESTS = [
  "Complete Blood Count (CBC)", "Lipid Profile", "HbA1c", "Liver Function Test (LFT)",
  "Kidney Function Test (KFT)", "Thyroid Stimulating Hormone (TSH)", "Serum Creatinine",
];

// Official providers for each legitimate template
const TEMPLATE_DEFAULT_PROVIDERS = {
  "invoice_0": ["Apollo Health Clinic", "PRV1001"],
  "invoice_1": ["Sunrise Medical Centre", "PRV1002"],
  "invoice_2": ["Greenleaf Hospital", "PRV1003"],
  "prescription_0": ["Metro Care Diagnostics", "PRV1004"],
  "prescription_1": ["Lotus Wellness Hub", "PRV1005"],
  "prescription_2": ["BlueCross Pharmacy", "PRV1006"],
  "lab_0": ["LifeLine Laboratories", "PRV1007"],
  "lab_1": ["NovaMed Institute", "PRV1008"],
  "lab_2": ["PrimeCare Clinic", "PRV1009"],
};

// Fake provider names used exclusively on fraudulent claims
const FRAUD_FAKE_PROVIDERS = [
  ["Apex Health Partners", "PRV2001"],
  ["Sterling Care Clinic", "PRV2002"],
  ["Zenith Medical Centre", "PRV2003"],
  ["Global Horizon Hospital", "PRV2004"],
  ["Elite Diagnostics Hub", "PRV2005"],
  ["Silverline Medicare", "PRV2006"],
  ["Crestview Healthcare", "PRV2007"],
  ["Pinnacle Pathology", "PRV2008"],
  ["Vanguard Clinical Labs", "PRV2009"],
  ["Trident Specialty Care", "PRV2010"],
];

// ─────────────────────────────────────────────────────────────────────────────
// STEP 3 — DYNAMIC FILLER GENERATOR
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Generate randomized realistic values to populate any document template.
 * Computes consistent fees, itemized medicine/test rows, GST, and totals.
 */
function buildFiller() {
  const consult = randInt(300, 1500);
  const subtotal = randInt(500, 8000);
  const gst = Math.floor((consult + subtotal) * 0.18);

  const drugCount = randInt(2, 4);
  const drugs = randSample(DRUGS, drugCount).map(
    (d) => `  - ${d}  x${randInt(1, 3)}  INR ${randInt(80, 400)}`
  );

  const testCount = randInt(2, 4);
  const tests = randSample(TESTS, testCount).map(
    (t) => `  - ${t}: ${(rng() * 149.0 + 1.0).toFixed(2)}`
  );

  const day = String(randInt(1, 28)).padStart(2, "0");
  const month = String(randInt(1, 12)).padStart(2, "0");

  return {
    claim_id: `CLM${randInt(100000, 999999)}`,
    date: `${day}-${month}-2024`,
    patient: `${randChoice(FIRST_NAMES)} ${randChoice(LAST_NAMES)}`,
    patient_id: `PAT${randInt(10000, 99999)}`,
    doctor: randChoice(DOCTORS),
    diagnosis: randChoice(DIAGNOSES),
    drugs,
    tests,
    consult_fee: consult,
    subtotal,
    gst,
    amount: consult + subtotal + gst,
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// STEP 4 — TEMPLATE DEFINITIONS (3 Invoices, 3 Prescriptions, 3 Lab Reports)
// ─────────────────────────────────────────────────────────────────────────────

// 9 Templates
function invoice0(v) {
  return `==========================================================
                    MEDICAL INVOICE
==========================================================
Invoice No : ${v.claim_id}
Date       : ${v.date}
----------------------------------------------------------
Provider   : ${v.provider}
Provider ID: ${v.provider_id}
----------------------------------------------------------
Patient    : ${v.patient}
Patient ID : ${v.patient_id}
----------------------------------------------------------
ITEMISED CHARGES:
${v.drugs.join("\n")}
----------------------------------------------------------
Consultation Fee   : INR ${v.consult_fee}
Subtotal           : INR ${v.subtotal}
GST (18%)          : INR ${v.gst}
----------------------------------------------------------
TOTAL AMOUNT DUE   : INR ${v.amount}
==========================================================
Attending Physician: ${v.doctor}
Signature          : ___________________
==========================================================
`;
}

function invoice1(v) {
  return `***** HEALTHCARE BILLING DOCUMENT *****
Bill Ref   : ${v.claim_id}
Bill Date  : ${v.date}
***************************************
TO:
  Patient Name : ${v.patient}
  Patient ID   : ${v.patient_id}
FROM:
  Issued By  : ${v.provider}
  Reg. No.   : ${v.provider_id}
***************************************
PRESCRIBED ITEMS / SERVICES:
${v.drugs.join("\n")}
- Consultation        : INR ${v.consult_fee}
- Investigations      : INR ${v.subtotal}
***************************************
GST Applied    : 18%  (INR ${v.gst})
GRAND TOTAL    : INR ${v.amount}
***************************************
Authorised By  : ${v.doctor}
***************************************
`;
}

function invoice2(v) {
  return `EXPENSE VOUCHER
Voucher Ref: ${v.claim_id}
Date of Service: ${v.date}
Facility: ${v.provider} | Facility Code: ${v.provider_id}
Claimant: ${v.patient} | Claimant ID: ${v.patient_id}

SERVICE ITEMS:
${v.drugs.join("\n")}

COST SUMMARY:
  Consultation Fee ............... INR ${v.consult_fee}
  Tests & Medicines .............. INR ${v.subtotal}
  GST @ 18% ........................ INR ${v.gst}

Net Payable: INR ${v.amount}
Certified by: ${v.doctor}
`;
}

function prescription0(v) {
  return `==================================================
                   PRESCRIPTION
==================================================
Rx No.     : ${v.claim_id}
Date       : ${v.date}
--------------------------------------------------
Doctor     : ${v.doctor}
Clinic     : ${v.provider}
Reg. No.   : ${v.provider_id}
--------------------------------------------------
Patient    : ${v.patient}
Patient ID : ${v.patient_id}
Diagnosis  : ${v.diagnosis}
--------------------------------------------------
MEDICATIONS PRESCRIBED:
${v.drugs.join("\n")}
--------------------------------------------------
Instructions: Take as directed. Avoid alcohol.
Follow-up   : After 7 days or as needed.
==================================================
Doctor's Signature: ___________________
==================================================
`;
}

function prescription1(v) {
  const drugLines = v.drugs
    .map((d, i) => `  ${i + 1}. ${d.trim().replace(/^-\s*/, "")}`)
    .join("\n");
  return `OUTPATIENT PRESCRIPTION
Ref No: ${v.claim_id}   Date Issued: ${v.date}

PATIENT
  Full Name  : ${v.patient}
  Member ID  : ${v.patient_id}
  Clinical Dx: ${v.diagnosis}

PRESCRIBER
  Name       : ${v.doctor}
  Facility   : ${v.provider}
  License    : ${v.provider_id}

DRUG LIST:
${drugLines}

Dispensing Note: Dispense as written. No substitution.
Rx Valid Until : 30 days from date of issue.
Prescriber Seal: ___________________
`;
}

function prescription2(v) {
  const drugRows = v.drugs
    .map(
      (d) =>
        `  | ${d.trim().replace(/^-\s*/, "").padEnd(55, " ")} | As directed |`
    )
    .join("\n");
  return `E-PRESCRIPTION
TxnID: ${v.claim_id}  |  Date: ${v.date}  |  [QR-CODE: ${v.claim_id}]
Physician : ${v.doctor}   Institute: ${v.provider}   Reg: ${v.provider_id}
Patient Name: ${v.patient}   UHI: ${v.patient_id}
Ailment: ${v.diagnosis}

  +----------------------------------------------------------+-------------+
  | MEDICINE / DOSE                                          | DURATION    |
  +----------------------------------------------------------+-------------+
${drugRows}
  +----------------------------------------------------------+-------------+

REGULATORY NOTE: This e-prescription is system-generated and legally valid.
Physician Digital Signature: ___________________
`;
}

function lab0(v) {
  return `##############################################
#          LABORATORY TEST REPORT            #
##############################################
Report ID  : ${v.claim_id}
Report Date: ${v.date}
----------------------------------------------
Laboratory : ${v.provider}
Lab Reg.   : ${v.provider_id}
----------------------------------------------
Patient    : ${v.patient}
Patient ID : ${v.patient_id}
Referred By: ${v.doctor}
----------------------------------------------
TEST RESULTS:
${v.tests.join("\n")}
----------------------------------------------
Total Charges: INR ${v.amount}
----------------------------------------------
Verified By: Lab Technician
Pathologist: ${v.doctor}
##############################################
`;
}

function lab1(v) {
  return `LAB REPORT
==========
Ref: ${v.claim_id}   Date: ${v.date}
Lab: ${v.provider}  Lic: ${v.provider_id}
Amount: INR ${v.amount}

Patient: ${v.patient}  ID: ${v.patient_id}
Doctor : ${v.doctor}

INVESTIGATIONS:
${v.tests.join("\n")}

Report validated and digitally signed.
`;
}

function lab2(v) {
  const testRows = v.tests
    .map(
      (t, i) =>
        `  ${String(i + 1).padStart(2, "0")}. ${t.trim().replace(/^-\s*/, "")}`
    )
    .join("\n");
  return `>>>>>>>>>> DIAGNOSTIC LABORATORY REPORT <<<<<<<<<<

SAMPLE DETAILS
  Collected On : ${v.date}
  Reported On  : ${v.date}
  Sample Ref   : ${v.claim_id}

LABORATORY INFO
  Name         : ${v.provider}
  Accred. No.  : ${v.provider_id}

PATIENT INFO
  Name         : ${v.patient}
  UHID         : ${v.patient_id}
  Referring Dr : ${v.doctor}

TEST FINDINGS:
${testRows}

BILLING SUMMARY
  Amount Due   : INR ${v.amount}
  All results reviewed by a certified pathologist.

>>>>>>>>>>>>>>>>>>>>>>>>>>><<<<<<<<<<<<<<<<<<<<<
`;
}

const TEMPLATE_REGISTRY = {
  invoice_0: invoice0,
  invoice_1: invoice1,
  invoice_2: invoice2,
  prescription_0: prescription0,
  prescription_1: prescription1,
  prescription_2: prescription2,
  lab_0: lab0,
  lab_1: lab1,
  lab_2: lab2,
};

const ALL_TEMPLATE_KEYS = Object.keys(TEMPLATE_REGISTRY);

function generateDocument(docType, templateIdx, provider, providerId) {
  const key = `${docType}_${templateIdx}`;
  const filler = buildFiller();
  filler.provider = provider || TEMPLATE_DEFAULT_PROVIDERS[key][0];
  filler.provider_id = providerId || TEMPLATE_DEFAULT_PROVIDERS[key][1];
  return TEMPLATE_REGISTRY[key](filler);
}

// ─────────────────────────────────────────────────────────────────────────────
// STEP 5 — DATASET GENERATION (Fraud Clusters & Ground Truth)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Generate synthetic claim documents and save them with metadata and ground-truth fraud pairs.
 *
 * Structure:
 *   - 15 Fraudulent claims: 3 clusters of 5 documents each, where all documents in a cluster
 *     share the same template skeleton but carry different fake provider names.
 *   - Remaining: Legitimate claims from official providers using their own templates.
 *
 * @param {string} [outputDir="dataset"]
 * @param {number} [nTotal=80]
 * @param {number} [seed=42]
 * @returns {{metadata: Record<string, any>, fraud_pairs: Array<[string, string]>, output_dir: string}}
 */
function generateDataset(outputDir = "dataset", nTotal = 80, seed = 42) {
  rng = createRng(seed);
  const out = path.resolve(outputDir);
  fs.mkdirSync(out, { recursive: true });

  const metadata = {};
  const fraudPairs = [];

  const fraudTemplates = [
    ["invoice", 1],
    ["prescription", 0],
    ["lab", 2],
  ];
  const fraudClusterSize = 5;
  const nFraud = fraudTemplates.length * fraudClusterSize;
  const nLegit = nTotal - nFraud;

  let docCounter = 0;
  let fakeProvIdx = 0;

  // 1. Generate fraud clusters
  for (const [docType, tmplIdx] of fraudTemplates) {
    const clusterIds = [];

    for (let i = 0; i < fraudClusterSize; i++) {
      const docId = `doc_${String(docCounter).padStart(4, "0")}`;
      const [fakeProv, fakePid] =
        FRAUD_FAKE_PROVIDERS[fakeProvIdx % FRAUD_FAKE_PROVIDERS.length];
      fakeProvIdx++;

      const content = generateDocument(docType, tmplIdx, fakeProv, fakePid);
      const filePath = path.join(out, `${docId}.txt`);
      fs.writeFileSync(filePath, content, "utf-8");

      metadata[docId] = {
        path: filePath,
        doc_type: docType,
        template_key: `${docType}_${tmplIdx}`,
        provider: fakeProv,
        is_fraud: true,
      };
      clusterIds.push(docId);
      docCounter++;
    }

    // All combinations within cluster
    for (let i = 0; i < clusterIds.length; i++) {
      for (let j = i + 1; j < clusterIds.length; j++) {
        fraudPairs.push([clusterIds[i], clusterIds[j]]);
      }
    }
  }

  // 2. Generate legitimate claims
  const fraudKeys = new Set(fraudTemplates.map(([t, i]) => `${t}_${i}`));
  const legitTemplates = ALL_TEMPLATE_KEYS.filter((k) => !fraudKeys.has(k));

  for (let i = 0; i < nLegit; i++) {
    const docId = `doc_${String(docCounter).padStart(4, "0")}`;
    const key = randChoice(legitTemplates);
    const [docType, tmplIdx] = key.split("_");

    const content = generateDocument(docType, parseInt(tmplIdx, 10));
    const filePath = path.join(out, `${docId}.txt`);
    fs.writeFileSync(filePath, content, "utf-8");

    metadata[docId] = {
      path: filePath,
      doc_type: docType,
      template_key: key,
      provider: TEMPLATE_DEFAULT_PROVIDERS[key][0],
      is_fraud: false,
    };
    docCounter++;
  }

  // Save metadata and ground truth
  fs.writeFileSync(
    path.join(out, "metadata.json"),
    JSON.stringify(metadata, null, 2),
    "utf-8"
  );

  const gtCsv = [
    "doc_id_a,doc_id_b",
    ...fraudPairs.map(([a, b]) => `${a},${b}`),
  ].join("\n") + "\n";

  fs.writeFileSync(path.join(out, "ground_truth.csv"), gtCsv, "utf-8");

  console.log(`[dataset_generator] Generated ${docCounter} documents in '${outputDir}/'`);
  console.log(`  Legitimate : ${nLegit} documents`);
  console.log(`  Fraudulent : ${nFraud} documents (3 clusters, ${fraudPairs.length} fraud pairs)`);

  return {
    metadata,
    fraud_pairs: fraudPairs,
    output_dir: outputDir,
  };
}

module.exports = {
  generateDocument,
  generateDataset,
};
