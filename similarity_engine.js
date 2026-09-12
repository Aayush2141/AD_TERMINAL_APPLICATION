/**
 * similarity_engine.js — Compares document skeletons to measure structural similarity.
 *
 * Algorithm (combined score out of 100%):
 *   75% — Sequence similarity: SequenceMatcher measures character/phrase alignment.
 *          Two documents from the same template share identical headings and field labels.
 *   25% — Line count ratio: min(lines_a, lines_b) / max(lines_a, lines_b).
 *          Ensures matching templates have a similar overall structure length.
 */

const fs = require("fs");
const path = require("path");

/**
 * Ratcliff-Obershelp SequenceMatcher algorithm (exact match to Python's difflib.SequenceMatcher)
 */
class SequenceMatcher {
  /**
   * @param {string} a - First sequence
   * @param {string} b - Second sequence
   */
  constructor(a, b) {
    this.a = a;
    this.b = b;

    // Build inverted index of elements in b
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
   * Find longest common substring between a[alo..ahi] and b[blo..bhi].
   */
  findLongestMatch(alo, ahi, blo, bhi) {
    let besti = alo;
    let bestj = blo;
    let bestsize = 0;
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
   * Find all non-overlapping maximal matching blocks.
   */
  getMatchingBlocks() {
    const queue = [[0, this.a.length, 0, this.b.length]];
    const matchingBlocks = [];

    while (queue.length > 0) {
      const [alo, ahi, blo, bhi] = queue.pop();
      const [i, j, k] = this.findLongestMatch(alo, ahi, blo, bhi);
      if (k > 0) {
        matchingBlocks.push([i, j, k]);
        if (alo < i && blo < j) {
          queue.push([alo, i, blo, j]);
        }
        if (i + k < ahi && j + k < bhi) {
          queue.push([i + k, ahi, j + k, bhi]);
        }
      }
    }

    return matchingBlocks;
  }

  /**
   * Calculate similarity ratio: 2.0 * matches / (len(a) + len(b))
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

/**
 * Calculate a similarity score (0–100) between two masked document skeletons.
 *
 * @param {string} skeletonA
 * @param {string} skeletonB
 * @returns {{sequence_sim: number, feature_sim: number, combined_score: number}}
 */
function computeSimilarity(skeletonA, skeletonB) {
  const seqSim = new SequenceMatcher(skeletonA, skeletonB).ratio();

  const linesA = skeletonA.split("\n").filter((l) => l.trim().length > 0).length;
  const linesB = skeletonB.split("\n").filter((l) => l.trim().length > 0).length;
  const lineSim = Math.min(linesA, linesB) / Math.max(linesA, linesB, 1);

  const combined = (0.75 * seqSim + 0.25 * lineSim) * 100.0;

  return {
    sequence_sim: Math.round(seqSim * 10000) / 10000,
    feature_sim: Math.round(lineSim * 10000) / 10000,
    combined_score: Math.round(combined * 10) / 10,
  };
}

/**
 * Compare every same-type pair of documents in the dataset.
 *
 * Cross-type pairs (e.g. invoice vs lab report) are skipped — they are
 * structurally unrelated and would only add noise to the results.
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

  results.sort((a, b) => b.combined_score - a.combined_score);
  console.log(
    `[similarity_engine] Compared ${results.length} same-type pairs (skipped ${skipped} cross-type) across ${docIds.length} documents.`
  );
  return results;
}

/**
 * Compare a single new document against every document in the existing dataset.
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

/**
 * Save pairwise similarity results to a JSON file.
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
