/**
 * test.js — Test suite to verify the Node.js fraud detector implementation.
 */

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const { extractSkeleton, loadAndExtract } = require("./template_extractor");
const { SequenceMatcher, computeSimilarity } = require("./similarity_engine");
const { getProvider } = require("./fraud_flagger");

console.log("=== Running Node.js Fraud Detector Test Suite ===\n");

// Test 1: Skeleton extraction replaces tokens
console.log("Test 1: Masking tokens in template extractor...");
const sampleText = `MEDICAL INVOICE
Invoice No : CLM981244
Date       : 15-08-2024
Provider   : Apex Health Partners
Patient    : Aarav Sharma
Patient ID : PAT44122
Consultation Fee : INR 1,500
Attending Physician: Dr. Rajesh Mehta
`;
const skeleton = extractSkeleton(sampleText);
assert(skeleton.includes("<REF_ID>"), "Should mask claim ID with <REF_ID>");
assert(skeleton.includes("<DATE>"), "Should mask date with <DATE>");
assert(skeleton.includes("<PROVIDER>"), "Should mask provider with <PROVIDER>");
assert(skeleton.includes("<PATIENT>"), "Should mask patient with <PATIENT>");
assert(skeleton.includes("<AMOUNT>"), "Should mask INR currency with <AMOUNT>");
assert(skeleton.includes("<DOCTOR>"), "Should mask Dr. name with <DOCTOR>");
console.log("  ✓ Skeletons correctly masked");

// Test 2: SequenceMatcher accuracy
console.log("\nTest 2: SequenceMatcher scoring...");
const sm1 = new SequenceMatcher("ABCDE", "ABCDE");
assert.strictEqual(sm1.ratio(), 1.0, "Identical strings must have ratio 1.0");

const sm2 = new SequenceMatcher("ABCDE", "FGHIJ");
assert.strictEqual(sm2.ratio(), 0.0, "Disjoint strings must have ratio 0.0");

const sim = computeSimilarity(
  "BILLING DOC <REF_ID> <DATE>",
  "BILLING DOC <REF_ID> <DATE>"
);
assert.strictEqual(sim.combined_score, 100.0, "Identical skeletons must score 100.0");
console.log("  ✓ SequenceMatcher logic passes");

// Test 3: Provider extraction heuristic
console.log("\nTest 3: Provider extraction heuristics...");
assert.strictEqual(
  getProvider("LABORATORY INFO\nName : LifeLine Laboratories | Code: 123"),
  "LifeLine Laboratories"
);
assert.strictEqual(
  getProvider("Provider: Apex Health Partners | Lic: PRV2001"),
  "Apex Health Partners"
);
assert.strictEqual(
  getProvider("Issued By: Sterling Care Clinic"),
  "Sterling Care Clinic"
);
console.log("  ✓ Provider extractor correctly isolates provider names");

// Test 4: End-to-end full run on dataset
console.log("\nTest 4: Full dataset detection and ground truth verification...");
const { extractAll } = require("./template_extractor");
const { compareAllPairs } = require("./similarity_engine");
const { flagPairs, loadGroundTruth, evaluateAccuracy } = require("./fraud_flagger");

const extractions = extractAll("dataset");
const comparisons = compareAllPairs(extractions);
const flagged = flagPairs(comparisons, extractions);
const groundTruth = loadGroundTruth("dataset");
const metrics = evaluateAccuracy(flagged, groundTruth, comparisons);

assert.strictEqual(metrics.precision, 100.0, "Precision must be 100%");
assert.strictEqual(metrics.recall, 100.0, "Recall must be 100%");
assert.strictEqual(metrics.f1, 100.0, "F1 must be 100%");
assert.strictEqual(flagged.all_flagged.length, 30, "Exactly 30 fraud pairs should be flagged");

console.log("\n✅ ALL TESTS PASSED SUCCESSFULLY!");
