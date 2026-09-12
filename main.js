#!/usr/bin/env node
/**
 * main.js — CLI entry point for the Fraud Detector (Node.js version).
 *
 * Commands:
 *   node main.js generate-dataset          Generate the synthetic dataset
 *   node main.js analyze                   Run full pairwise analysis
 *   node main.js analyze --file <path>     Compare one document vs dataset
 *   node main.js analyze --dataset <dir>   Override dataset directory
 *   node main.js analyze --output <path>   Override report output path
 *   node main.js analyze --threshold-red   Override RED flag threshold (default 90.0)
 *   node main.js analyze --threshold-amber Override AMBER flag threshold (default 70.0)
 */

const fs = require("fs");
const path = require("path");

const VERSION = "1.0.0";
const SCRIPT_DIR = __dirname;

function resolvePath(raw) {
  if (!raw) return SCRIPT_DIR;
  return path.isAbsolute(raw) ? raw : path.resolve(SCRIPT_DIR, raw);
}

function printHelp() {
  console.log(`usage: main.js [-h] [-v] {generate-dataset,analyze} ...

Similar Document Template Matching Algorithm (Node.js)
Detects fraudulent medical insurance documents that reuse the same
structural template across different providers/patients.

positional arguments:
  {generate-dataset,analyze}
                        Available commands
    generate-dataset    Generate the synthetic dataset.
    analyze             Run template extraction and similarity analysis.

options:
  -h, --help            show this help message and exit
  -v, --version         show program's version number and exit
  -q, --quiet           suppress non-essential logs and banner
  --seed SEED           random seed for dataset generation (default: 42)
`);
}

function parseArgs(argv) {
  const args = {
    command: null,
    dataset: "dataset",
    output: "report.json",
    file: null,
    n: 80,
    seed: 42,
    thresholdRed: 90.0,
    thresholdAmber: 70.0,
    quiet: false,
    version: false,
    help: false,
  };

  const rawArgs = argv.slice(2);
  let i = 0;

  while (i < rawArgs.length) {
    const arg = rawArgs[i];

    if (arg === "-h" || arg === "--help") {
      args.help = true;
      i++;
    } else if (arg === "-v" || arg === "--version") {
      args.version = true;
      i++;
    } else if (arg === "-q" || arg === "--quiet") {
      args.quiet = true;
      i++;
    } else if (!args.command && (arg === "generate-dataset" || arg === "analyze")) {
      args.command = arg;
      i++;
    } else if (arg === "--dataset") {
      args.dataset = rawArgs[++i];
      i++;
    } else if (arg === "--output") {
      args.output = rawArgs[++i];
      i++;
    } else if (arg === "--file") {
      args.file = rawArgs[++i];
      i++;
    } else if (arg === "-n" || arg === "--n") {
      args.n = parseInt(rawArgs[++i], 10);
      i++;
    } else if (arg === "--seed") {
      args.seed = parseInt(rawArgs[++i], 10);
      i++;
    } else if (arg === "--threshold-red") {
      args.thresholdRed = parseFloat(rawArgs[++i]);
      i++;
    } else if (arg === "--threshold-amber") {
      args.thresholdAmber = parseFloat(rawArgs[++i]);
      i++;
    } else {
      console.error(`Unknown argument: ${arg}`);
      printHelp();
      process.exit(1);
    }
  }

  return args;
}

function validateArgs(args) {
  if (args.command === "analyze") {
    if (isNaN(args.thresholdRed) || args.thresholdRed < 0 || args.thresholdRed > 100) {
      console.error("ERROR: --threshold-red must be a number between 0 and 100.");
      process.exit(1);
    }
    if (isNaN(args.thresholdAmber) || args.thresholdAmber < 0 || args.thresholdAmber > 100) {
      console.error("ERROR: --threshold-amber must be a number between 0 and 100.");
      process.exit(1);
    }
    if (args.thresholdAmber > args.thresholdRed) {
      console.error("ERROR: --threshold-amber cannot be greater than --threshold-red.");
      process.exit(1);
    }
  } else if (args.command === "generate-dataset") {
    if (isNaN(args.n) || args.n < 15) {
      console.error("ERROR: -n / --n must be an integer >= 15 (to house the 3 fraud clusters).");
      process.exit(1);
    }
    if (isNaN(args.seed)) {
      console.error("ERROR: --seed must be a valid number.");
      process.exit(1);
    }
  }
}

function cmdGenerateDataset(args) {
  const { generateDataset } = require("./dataset_generator");
  const outputDir = resolvePath(args.dataset);

  if (!args.quiet) {
    console.log("\n=== Generating Synthetic Dataset ===");
  }
  const result = generateDataset(outputDir, args.n, args.seed);
  if (!args.quiet) {
    console.log(`\nDone! Dataset written to: ${result.output_dir}`);
    console.log(`  metadata.json    → template_key and is_fraud for each document`);
    console.log(`  ground_truth.csv → ${result.fraud_pairs.length} known fraud pairs`);
    console.log(`\nNext step: node main.js analyze`);
  }
}

function cmdAnalyze(args) {
  const startTime = Date.now();

  const fraudFlagger = require("./fraud_flagger");
  const templateExtractor = require("./template_extractor");
  const similarityEngine = require("./similarity_engine");

  fraudFlagger.setThresholds(args.thresholdRed, args.thresholdAmber);

  const datasetDir = resolvePath(args.dataset);
  const outputPath = resolvePath(args.output);

  if (!args.quiet) {
    console.log(`\n=== Template Matching Fraud Detector (Node.js) ===`);
    console.log(`Dataset   : ${datasetDir}`);
    console.log(`Report    : ${outputPath}`);
    console.log(
      `Thresholds: RED ≥ ${args.thresholdRed}% | AMBER ≥ ${args.thresholdAmber}%\n`
    );
  }

  // Step 1: Extract skeletons
  let extractions;
  try {
    extractions = templateExtractor.extractAll(datasetDir);
  } catch (err) {
    console.error(`\nERROR: ${err.message}`);
    process.exit(1);
  }

  // Step 2: Compare document pairs
  let comparisonResults;
  if (args.file) {
    const newFilePath = resolvePath(args.file);
    if (!fs.existsSync(newFilePath)) {
      console.error(`\nERROR: File not found: ${args.file}`);
      process.exit(1);
    }
    const newExtraction = templateExtractor.loadAndExtract(newFilePath);
    comparisonResults = similarityEngine.compareOneVsAll(
      newExtraction,
      extractions
    );
    extractions[newExtraction.doc_id] = newExtraction;
  } else {
    comparisonResults = similarityEngine.compareAllPairs(extractions);
  }

  // Step 3: Flag suspicious pairs
  const flagged = fraudFlagger.flagPairs(comparisonResults, extractions);

  // Step 4: Display results
  fraudFlagger.renderFlaggedPairs(flagged);

  // Step 5: Accuracy evaluation (full-dataset mode only)
  let metrics = {};
  if (!args.file) {
    const groundTruth = fraudFlagger.loadGroundTruth(datasetDir);
    metrics = fraudFlagger.evaluateAccuracy(
      flagged,
      groundTruth,
      comparisonResults
    );
  }

  // Step 6: Save reports
  fraudFlagger.saveReport(flagged, metrics, outputPath);
  const simPath = path.join(
    path.dirname(outputPath),
    "similarity_results.json"
  );
  similarityEngine.saveResults(comparisonResults, simPath);

  const elapsed = ((Date.now() - startTime) / 1000).toFixed(2);
  console.log(`\n[✓] Analysis complete in ${elapsed}s`);
}

function main() {
  const args = parseArgs(process.argv);

  if (args.version) {
    console.log(`Fraud Detector v${VERSION}`);
    process.exit(0);
  }

  if (args.help || !args.command) {
    printHelp();
    process.exit(args.help ? 0 : 1);
  }

  validateArgs(args);

  if (args.command === "generate-dataset") {
    cmdGenerateDataset(args);
  } else if (args.command === "analyze") {
    cmdAnalyze(args);
  }
}

if (require.main === module) {
  main();
}
