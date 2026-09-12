/**
 * fraud_flagger.js — Decides which document pairs are suspicious (fraud).
 *
 * HOW IT WORKS:
 *   After the similarity engine scores every pair of documents (0-100%),
 *   this module looks at each score and decides whether to raise an alert:
 *
 *   RED   flag → score ≥ 90% AND documents come from DIFFERENT providers
 *                → Almost certainly fraud (same template, different fake clinic)
 *
 *   AMBER flag → score 70–89% AND documents come from DIFFERENT providers
 *                → Suspicious, worth a human review
 *
 *   No flag    → score < 70%, OR the documents are from the SAME provider
 *                → Legitimate (either too different, or same clinic using its own template)
 */

const fs = require("fs");
const path = require("path");

let RED_THRESHOLD = 90.0;
let AMBER_THRESHOLD = 70.0;

function setThresholds(red, amber) {
  if (typeof red === "number" && !isNaN(red)) RED_THRESHOLD = red;
  if (typeof amber === "number" && !isNaN(amber)) AMBER_THRESHOLD = amber;
}

// ─────────────────────────────────────────────────────────────────────────────
// STEP 1 — IDENTIFY THE PROVIDER
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Read a document and extract the name of the provider/clinic.
 *
 * The function tries three strategies, from most specific to least:
 *   1. Look for a 'LABORATORY INFO' section (lab reports).
 *   2. Look for a labelled field like 'Provider:', 'Clinic:', 'Facility:'.
 *   3. Fall back to the first readable line of the document.
 *
 * @param {string} rawText
 * @returns {string}
 */
function getProvider(rawText) {
  if (!rawText) return "UNKNOWN";

  // Strategy 1 — lab reports have a dedicated "LABORATORY INFO" block
  const labMatch = rawText.match(/LABORATORY INFO\s*\n\s*Name\s*:\s*([^|\n\r]+)/i);
  if (labMatch) {
    return labMatch[1].trim();
  }

  // Strategy 2 — look for a labelled provider field anywhere in the document
  const fieldMatch = rawText.match(
    /(?:Provider|Issued By|Laboratory|Clinic|Facility|Institution|Institute|Lab)\s*[:|]\s*([^|\n\r]+)/i
  );
  if (fieldMatch) {
    let name = fieldMatch[1].trim();
    // Strip trailing license/registration codes like "Lic: PRV1020" without cutting into words like "Trident"
    name = name.replace(/\s*(?:\bLic\b|\bReg\b|\bFacility Code\b|\(ID\b|\bID\b).*$/i, "").trim();
    name = name.replace(/[| \-:]+$/, "").trim();
    if (name) return name;
  }

  // Strategy 3 — use the first non-decorative line
  for (const line of rawText.split("\n")) {
    const clean = line.trim();
    if (clean && !/^[\=\*\#\-\>\< ]+$/.test(clean)) {
      return clean.slice(0, 50);
    }
  }

  return "UNKNOWN";
}

// ─────────────────────────────────────────────────────────────────────────────
// STEP 2 — FLAG SUSPICIOUS PAIRS
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Go through every compared document pair and decide if it should be flagged.
 *
 * @param {Array<any>} comparisonResults
 * @param {Record<string, {raw_text: string}>} extractions
 * @returns {{red: Array<any>, amber: Array<any>, all_flagged: Array<any>}}
 */
function flagPairs(comparisonResults, extractions) {
  const redPairs = [];
  const amberPairs = [];

  for (const result of comparisonResults) {
    const score = result.combined_score;

    if (score < AMBER_THRESHOLD) {
      continue;
    }

    const docAText = extractions[result.doc_id_a]?.raw_text || "";
    const docBText = extractions[result.doc_id_b]?.raw_text || "";
    const providerA = getProvider(docAText);
    const providerB = getProvider(docBText);

    if (providerA.toLowerCase() === providerB.toLowerCase()) {
      continue;
    }

    const flaggedPair = {
      ...result,
      provider_a: providerA,
      provider_b: providerB,
      same_provider: false,
    };

    if (score >= RED_THRESHOLD) {
      flaggedPair.flag = "RED";
      redPairs.push(flaggedPair);
    } else {
      flaggedPair.flag = "AMBER";
      amberPairs.push(flaggedPair);
    }
  }

  return {
    red: redPairs,
    amber: amberPairs,
    all_flagged: [...redPairs, ...amberPairs],
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// STEP 3 — DISPLAY RESULTS IN THE TERMINAL
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Print the flagged pairs to the terminal in a readable, color-coded format.
 *
 * @param {{red: Array<any>, amber: Array<any>, all_flagged: Array<any>}} flagged
 */
function renderFlaggedPairs(flagged) {
  const allPairs = flagged.all_flagged;

  if (allPairs.length === 0) {
    console.log("\x1b[92m\n[✓] No suspicious template reuse detected.\x1b[0m");
    return;
  }

  const RED_COLOR = "\x1b[91m";
  const AMBER_COLOR = "\x1b[93m";
  const RESET = "\x1b[0m";
  const BOLD = "\x1b[1m";

  console.log("\n" + "=".repeat(70));
  console.log("  FRAUD DETECTION ALERTS");
  console.log("=".repeat(70));

  for (const p of flagged.red) {
    const score = p.combined_score.toFixed(1);
    console.log(
      `${RED_COLOR}[RED  ] ${p.doc_id_a} <-> ${p.doc_id_b} | Score: ${score}% | ${p.provider_a} vs ${p.provider_b}${RESET}`
    );
  }

  for (const p of flagged.amber) {
    const score = p.combined_score.toFixed(1);
    console.log(
      `${AMBER_COLOR}[AMBER] ${p.doc_id_a} <-> ${p.doc_id_b} | Score: ${score}% | ${p.provider_a} vs ${p.provider_b}${RESET}`
    );
  }

  console.log(
    `\nSummary: ${BOLD}${RED_COLOR}${flagged.red.length} RED${RESET} | ` +
      `${BOLD}${AMBER_COLOR}${flagged.amber.length} AMBER${RESET} | ` +
      `${allPairs.length} total\n`
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// STEP 4 — LOAD GROUND TRUTH
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Load the set of known fraud pairs from ground_truth.csv.
 *
 * @param {string} [datasetDir="dataset"]
 * @returns {Set<string>}
 */
function loadGroundTruth(datasetDir = "dataset") {
  const gtPath = path.join(datasetDir, "ground_truth.csv");
  if (!fs.existsSync(gtPath)) {
    return new Set();
  }

  const content = fs.readFileSync(gtPath, "utf-8");
  const lines = content.split("\n").map((l) => l.trim()).filter(Boolean);
  const fraudPairs = new Set();

  for (let i = 1; i < lines.length; i++) {
    const parts = lines[i].split(",").map((p) => p.trim());
    if (parts.length >= 2) {
      const key = [parts[0], parts[1]].sort().join("::");
      fraudPairs.add(key);
    }
  }

  return fraudPairs;
}

// ─────────────────────────────────────────────────────────────────────────────
// STEP 5 — MEASURE ACCURACY
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Compare flagged pairs against known fraud pairs to compute accuracy.
 *
 * @param {{all_flagged: Array<any>}} flagged
 * @param {Set<string>} groundTruth
 * @param {Array<any>} allResults
 * @returns {Record<string, any>}
 */
function evaluateAccuracy(flagged, groundTruth, allResults) {
  if (!groundTruth || groundTruth.size === 0) {
    console.log("[!] No ground_truth.csv found; skipping accuracy metrics.");
    return {};
  }

  const flaggedSet = new Set(
    flagged.all_flagged.map((p) => [p.doc_id_a, p.doc_id_b].sort().join("::"))
  );
  const allSet = new Set(
    allResults.map((p) => [p.doc_id_a, p.doc_id_b].sort().join("::"))
  );

  let tp = 0;
  let fp = 0;
  for (const pair of flaggedSet) {
    if (groundTruth.has(pair)) tp++;
    else fp++;
  }

  let fn = 0;
  for (const pair of groundTruth) {
    if (!flaggedSet.has(pair)) fn++;
  }

  let tn = 0;
  for (const pair of allSet) {
    if (!flaggedSet.has(pair) && !groundTruth.has(pair)) tn++;
  }

  const precision = tp + fp > 0 ? tp / (tp + fp) : 0.0;
  const recall = tp + fn > 0 ? tp / (tp + fn) : 0.0;
  const f1 = precision + recall > 0 ? (2 * precision * recall) / (precision + recall) : 0.0;

  const metrics = {
    precision: Math.round(precision * 1000) / 10,
    recall: Math.round(recall * 1000) / 10,
    f1: Math.round(f1 * 1000) / 10,
    tp,
    fp,
    fn,
    tn,
    total_fraud_pairs: groundTruth.size,
    total_flagged: flaggedSet.size,
  };

  console.log("--- DETECTION ACCURACY ---");
  console.log(`  True Positives  (TP) : ${tp}  (Correctly caught fraud pairs)`);
  console.log(`  False Positives (FP) : ${fp}  (Legitimate pairs wrongly flagged)`);
  console.log(`  False Negatives (FN) : ${fn}  (Fraud pairs missed)`);
  console.log(`  True Negatives  (TN) : ${tn}  (Legitimate pairs correctly cleared)`);
  console.log(`  Precision            : ${metrics.precision}%`);
  console.log(`  Recall               : ${metrics.recall}%`);
  console.log(`  F1 Score             : ${metrics.f1}%\n`);

  return metrics;
}

// ─────────────────────────────────────────────────────────────────────────────
// STEP 6 — SAVE THE REPORT
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Write the results to disk in both JSON and CSV formats.
 *
 * @param {{red: Array<any>, amber: Array<any>, all_flagged: Array<any>}} flagged
 * @param {Record<string, any>} metrics
 * @param {string} outputPath
 */
function saveReport(flagged, metrics, outputPath) {
  const jsonPath = path.resolve(outputPath);
  const dir = path.dirname(jsonPath);
  fs.mkdirSync(dir, { recursive: true });

  const csvPath = jsonPath.replace(/\.json$/i, "") + ".csv";

  // JSON report
  const report = {
    summary: {
      red_alerts: flagged.red.length,
      amber_alerts: flagged.amber.length,
      total_flagged: flagged.all_flagged.length,
    },
    accuracy_metrics: metrics,
    flagged_pairs: flagged.all_flagged,
  };
  fs.writeFileSync(jsonPath, JSON.stringify(report, null, 2), "utf-8");

  // CSV report
  const csvRows = ["flag,doc_id_a,doc_id_b,score,provider_a,provider_b"];
  for (const p of flagged.all_flagged) {
    const esc = (val) => {
      const s = String(val ?? "");
      return s.includes(",") || s.includes('"') || s.includes("\n")
        ? `"${s.replace(/"/g, '""')}"`
        : s;
    };
    csvRows.push(
      [
        esc(p.flag),
        esc(p.doc_id_a),
        esc(p.doc_id_b),
        esc(p.combined_score),
        esc(p.provider_a),
        esc(p.provider_b),
      ].join(",")
    );
  }
  fs.writeFileSync(csvPath, csvRows.join("\n") + "\n", "utf-8");

  console.log(`[fraud_flagger] Report written to '${jsonPath}' and '${csvPath}'`);
}

module.exports = {
  get RED_THRESHOLD() {
    return RED_THRESHOLD;
  },
  get AMBER_THRESHOLD() {
    return AMBER_THRESHOLD;
  },
  setThresholds,
  getProvider,
  flagPairs,
  renderFlaggedPairs,
  loadGroundTruth,
  evaluateAccuracy,
  saveReport,
};
