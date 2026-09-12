/**
 * template_extractor.js — Extracts a structural "skeleton" from a medical document.
 *
 * How it works:
 *   Variable fields (names, dates, amounts, IDs) are replaced with placeholder
 *   tokens like <DATE>, <AMOUNT>, <PATIENT>, etc. Two documents generated from
 *   the same template will then produce nearly identical skeletons, making fraud
 *   easy to detect even when the surface text looks different.
 */

const fs = require("fs");
const path = require("path");

/**
 * Replace variable content in a document with structural placeholder tokens.
 *
 * Masking order (order matters — more specific patterns run first):
 *   1. Reference & Claim IDs  (CLM123, PRV123, PAT123)  → <REF_ID>
 *   2. Dates                  (DD-MM-YYYY, Month DD YYYY) → <DATE>
 *   3. Currency amounts        (INR 1,500)               → <AMOUNT>
 *   4. Doctor names            (Dr. Firstname Lastname)  → <DOCTOR>
 *   5. Percentages             (18%, 5.5%)               → <PERCENT>
 *   6. Decimal numbers         (14.5, 0.95)              → <NUMBER>
 *   7. Quantities & dosages    (x2, 500mg, 10ml)         → <QTY>
 *   8. Patient name values                               → <PATIENT>
 *   9. Provider name values                              → <PROVIDER>
 *   10. Remaining large numbers (3+ digits)              → <NUMBER>
 *
 * @param {string} text - The raw document text
 * @returns {string} The masked skeleton text
 */
function extractSkeleton(text) {
  let s = text;

  // 1. Claim / Provider / Patient IDs
  s = s.replace(/\b(CLM\d+|PRV\d+|PAT\d+)\b/g, "<REF_ID>");

  // 2. Dates
  s = s.replace(
    /\b(?:\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{4}[-/]\d{2}[-/]\d{2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})\b/gi,
    "<DATE>"
  );

  // 3. Currency amounts (INR 2,500 or INR 500)
  s = s.replace(/\bINR\s+[\d,]+(?:\.\d{2})?\b/gi, "<AMOUNT>");

  // 4. Doctor names (Dr. Firstname Lastname)
  s = s.replace(/\bDr\.\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b/g, "<DOCTOR>");

  // 5. Percentages
  s = s.replace(/\b\d+(?:\.\d+)?%/g, "<PERCENT>");

  // 6. Decimal numbers
  s = s.replace(/\b\d+\.\d+\b/g, "<NUMBER>");

  // 7. Quantities & dosages (x2, 500mg, 10ml, 60000IU)
  s = s.replace(/\bx\d+\b/gi, "<QTY>");
  s = s.replace(/\b\d+(?:\.\d+)?\s*(?:mg|mcg|ml|IU|g|units?|tab|caps?)\b/gi, "<QTY>");

  // 8. Patient name values (after labels like "Patient:", "Full Name:", etc.)
  s = s.replace(
    /(Patient(?:\s+Name)?|Full\s+Name|Claimant|Member\s+ID|UHID?)\s*[:|]\s*([^\n\r|]+)/gi,
    "$1: <PATIENT>"
  );

  // 9. Provider name values (after labels like "Provider:", "Clinic:", etc.)
  s = s.replace(
    /(Provider|Issued\s+By|Laboratory|Clinic|Facility|Institution|Institute|Lab(?:\s+Name)?)\s*[:|]\s*([^\n\r|]+)/gi,
    "$1: <PROVIDER>"
  );

  // 10. Any remaining large standalone numbers
  s = s.replace(/\b\d{3,}\b/g, "<NUMBER>");

  return s;
}

/**
 * Read a document file and extract its structural skeleton.
 *
 * @param {string} filepath - Path to the document
 * @returns {{doc_id: string, raw_text: string, skeleton: string, lines: number}}
 */
function loadAndExtract(filepath) {
  const resolved = path.resolve(filepath);
  const rawText = fs.readFileSync(resolved, "utf-8");
  const skeleton = extractSkeleton(rawText);
  const lines = skeleton.split("\n").filter((l) => l.trim().length > 0).length;

  return {
    doc_id: path.basename(resolved, path.extname(resolved)),
    raw_text: rawText,
    skeleton,
    lines,
  };
}

/**
 * Extract skeletons for every .txt document in datasetDir.
 * Attaches each document's doc_type from metadata.json if available.
 *
 * @param {string} [datasetDir="dataset"] - Directory containing the document files
 * @returns {Record<string, {doc_id: string, raw_text: string, skeleton: string, lines: number, doc_type: string}>}
 */
function extractAll(datasetDir = "dataset") {
  const folder = path.resolve(datasetDir);
  if (!fs.existsSync(folder)) {
    throw new Error(`Directory '${datasetDir}' does not exist.`);
  }

  const files = fs
    .readdirSync(folder)
    .filter((f) => f.endsWith(".txt"))
    .sort();

  if (files.length === 0) {
    throw new Error(`No .txt documents found in '${datasetDir}'. Run \`generate-dataset\` first.`);
  }

  const metaPath = path.join(folder, "metadata.json");
  let metadata = {};
  if (fs.existsSync(metaPath)) {
    try {
      metadata = JSON.parse(fs.readFileSync(metaPath, "utf-8"));
    } catch {
      metadata = {};
    }
  }

  const extractions = {};
  for (const file of files) {
    const filePath = path.join(folder, file);
    const doc = loadAndExtract(filePath);
    doc.doc_type = metadata[doc.doc_id]?.doc_type || "unknown";
    extractions[doc.doc_id] = doc;
  }

  console.log(`[template_extractor] Extracted skeletons for ${Object.keys(extractions).length} documents.`);
  return extractions;
}

module.exports = {
  extractSkeleton,
  loadAndExtract,
  extractAll,
};
