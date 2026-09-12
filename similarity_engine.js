/**
 * similarity_engine.js — Compares document skeletons to measure structural similarity.
 *
 * HOW IT WORKS:
 *   After template_extractor.js replaces variable fields with placeholder tokens,
 *   this engine computes how similar any two document skeletons are.
 *
 * THE SCORING ALGORITHM (Combined Score 0–100%):
 *   75% — Sequence Similarity:
 *         Measures how closely the characters, section headers, and field labels
 *         align using the Ratcliff-Obershelp algorithm (same as Python difflib).
 *   25% — Line Count Ratio:
 *         Ensures two documents with similar wording also have a matching length
 *         min(lines_a, lines_b) / max(lines_a, lines_b).
 */

const fs = require("fs");
const path = require("path");

// ─────────────────────────────────────────────────────────────────────────────
// STEP 1 — SEQUENCE MATCHER (Ratcliff-Obershelp Algorithm)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Fast JavaScript port of Python's difflib.SequenceMatcher.
 *
 * How Ratcliff-Obershelp works:
 *   1. Find the longest contiguous matching substring between string A and string B.
 *   2. Recursively find the longest matches in the portions to the left and right.
 *   3. Sum all matching character lengths (M).
 *   4. Ratio = 2.0 * M / (length(A) + length(B)).
 */
class SequenceMatcher {
  /**
   * @param {string} a - First skeleton sequence
   * @param {string} b - Second skeleton sequence
   */
  constructor(a, b) {
    this.a = a;
    this.b = b;

    // Build an inverted index of characters in string B.
    // Maps each character -> array of positions where it appears in B.
    // This turns a naive O(N*M) search into a fast hash lookup.
    this.b2j = new Map();
    for (let j = 0; j < b.length; j++) {
      const ch = b[j];
      let arr = this.b2j.get(ch);
      if (!arr) {
        arr = [];
        this.b2j.set(ch, arr);
      }
      arr.push(j);
    }
  }

  /**
   * Find the single longest common substring between a[alo..ahi] and b[blo..bhi].
   *
   * @param {number} alo - Lower index in sequence A
   * @param {number} ahi - Upper index in sequence A
   * @param {number} blo - Lower index in sequence B
   * @param {number} bhi - Upper index in sequence B
   * @returns {[number, number, number]} [bestIndexA, bestIndexB, matchLength]
   */
  findLongestMatch(alo, ahi, blo, bhi) {
    let besti = alo;
    let bestj = blo;
    let bestsize = 0;

    // j2len maps position in B to length of common match ending there
    let j2len = new Map();

    for (let i = alo; i < ahi; i++) {
      const ch = this.a[i];
      const newj2len = new Map();
      const occurrences = this.b2j.get(ch);

      if (occurrences) {
        for (let idx = 0; idx < occurrences.length; idx++) {
          const j = occurrences[idx];
          if (j < blo) continue;
          if (j >= bhi) break;

          // If the previous character also matched, extend the run length (+1)
          const k = (j2len.get(j - 1) || 0) + 1;
          newj2len.set(j, k);

          if (k > bestsize) {
            besti = i - k + 1;
            bestj = j - k + 1;
            bestsize = k;
          }
        }
      }
      j2len = newj2len;
    }

    return [besti, bestj, bestsize];
  }

  /**
   * Find all non-overlapping maximal matching blocks across both sequences.
   *
   * @returns {Array<[number, number, number]>} Array of [indexA, indexB, size]
   */
  getMatchingBlocks() {
    const queue = [[0, this.a.length, 0, this.b.length]];
    const matchingBlocks = [];

    while (queue.length > 0) {
      const [alo, ahi, blo, bhi] = queue.pop();
      const [i, j, k] = this.findLongestMatch(alo, ahi, blo, bhi);

      if (k > 0) {
        matchingBlocks.push([i, j, k]);

        // Search left remainder (before the match)
        if (alo < i && blo < j) {
          queue.push([alo, i, blo, j]);
        }

        // Search right remainder (after the match)
        if (i + k < ahi && j + k < bhi) {
          queue.push([i + k, ahi, j + k, bhi]);
        }
      }
    }

    return matchingBlocks;
  }

  /**
   * Return similarity ratio between 0.0 (completely different) and 1.0 (identical).
   *
   * Formula: 2.0 * total_matching_characters / (length_a + length_b)
   *
   * @returns {number}
   */
  ratio() {
    if (this.a.length === 0 && this.b.length === 0) return 1.0;
    if (this.a.length === 0 || this.b.length === 0) return 0.0;

    const blocks = this.getMatchingBlocks();
    let matches = 0;
    for (let i = 0; i < blocks.length; i++) {
      matches += blocks[i][2];
    }

    return (2.0 * matches) / (this.a.length + this.b.length);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// STEP 2 — COMBINED SIMILARITY SCORING
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Calculate a weighted similarity score (0–100) between two document skeletons.
 *
 * @param {string} skeletonA - Masked skeleton of first document
 * @param {string} skeletonB - Masked skeleton of second document
 * @returns {{sequence_sim: number, feature_sim: number, combined_score: number}}
 */
function computeSimilarity(skeletonA, skeletonB) {
  // 1. Ratcliff-Obershelp sequence alignment (0.0 to 1.0)
  const seqSim = new SequenceMatcher(skeletonA, skeletonB).ratio();

  // 2. Proportion of line counts (0.0 to 1.0)
  const linesA = skeletonA.split("\n").filter((l) => l.trim().length > 0).length;
  const linesB = skeletonB.split("\n").filter((l) => l.trim().length > 0).length;
  const lineSim = Math.min(linesA, linesB) / Math.max(linesA, linesB, 1);

  // 3. 75% sequence alignment + 25% structural length
  const combined = (0.75 * seqSim + 0.25 * lineSim) * 100.0;

  return {
    sequence_sim: Math.round(seqSim * 10000) / 10000,
    feature_sim: Math.round(lineSim * 10000) / 10000,
    combined_score: Math.round(combined * 10) / 10,
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// STEP 3 — PAIRWISE COMPARISONS
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Compare every same-type pair of documents in the dataset.
 *
 * Optimization:
 *   Cross-type pairs (e.g. invoice vs lab report) are skipped because they
 *   are structurally unrelated and would never be from the same template.
 *
 * @param {Record<string, {doc_id: string, skeleton: string, doc_type?: string}>} extractions
 * @returns {Array<{doc_id_a: string, doc_id_b: string, doc_type: string, sequence_sim: number, feature_sim: number, combined_score: number}>}
 */
function compareAllPairs(extractions) {
  const docIds = Object.keys(extractions).sort();
  const results = [];
  let skipped = 0;

  for (let i = 0; i < docIds.length; i++) {
    for (let j = i + 1; j < docIds.length; j++) {
      const docA = docIds[i];
      const docB = docIds[j];
      const typeA = extractions[docA].doc_type;
      const typeB = extractions[docB].doc_type;

      // Skip comparing an invoice with a lab report or prescription
      if (typeA && typeB && typeA !== typeB) {
        skipped++;
        continue;
      }

      const scores = computeSimilarity(
        extractions[docA].skeleton,
        extractions[docB].skeleton
      );

      results.push({
        doc_id_a: docA,
        doc_id_b: docB,
        doc_type: typeA || "unknown",
        ...scores,
      });
    }
  }

  // Sort highest similarity pairs first
  results.sort((a, b) => b.combined_score - a.combined_score);
  console.log(
    `[similarity_engine] Compared ${results.length} same-type pairs (skipped ${skipped} cross-type) across ${docIds.length} documents.`
  );
  return results;
}

/**
 * Compare a single target document against all existing documents.
 * (Used for the CLI `analyze --file <path>` option)
 *
 * @param {{doc_id: string, skeleton: string}} newDoc
 * @param {Record<string, {doc_id: string, skeleton: string, doc_type?: string}>} extractions
 * @returns {Array<any>}
 */
function compareOneVsAll(newDoc, extractions) {
  const newId = newDoc.doc_id;
  const newSkel = newDoc.skeleton;

  const results = Object.keys(extractions).map((docId) => {
    const info = extractions[docId];
    return {
      doc_id_a: newId,
      doc_id_b: docId,
      doc_type: info.doc_type || "unknown",
      ...computeSimilarity(newSkel, info.skeleton),
    };
  });

  results.sort((a, b) => b.combined_score - a.combined_score);
  console.log(
    `[similarity_engine] Compared '${newId}' against ${Object.keys(extractions).length} existing documents.`
  );
  return results;
}

// ─────────────────────────────────────────────────────────────────────────────
// STEP 4 — SAVE SIMILARITY RESULTS
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Save pairwise similarity results to disk as JSON.
 *
 * @param {Array<any>} results
 * @param {string} outputPath
 */
function saveResults(results, outputPath) {
  const fullPath = path.resolve(outputPath);
  fs.mkdirSync(path.dirname(fullPath), { recursive: true });
  fs.writeFileSync(fullPath, JSON.stringify(results, null, 2), "utf-8");
  console.log(`[similarity_engine] Similarity results saved -> ${outputPath}`);
}

module.exports = {
  SequenceMatcher,
  computeSimilarity,
  compareAllPairs,
  compareOneVsAll,
  saveResults,
};
