/*
 * barcode.js — dependency-free EAN-13 / UPC-A decoder for camera frames.
 *
 * Used on browsers without the native BarcodeDetector API (notably iOS
 * Safari). All processing happens locally on the device: a few horizontal
 * scanlines are sampled from each video frame, binarized, run-length
 * encoded, and matched against the EAN-13 module patterns. A result is only
 * returned when its checksum passes; callers additionally require the same
 * code from two consecutive frames before accepting it.
 *
 * No DOM access here so the decoder is fully unit-testable under Node.
 */
"use strict";

/* L-codes for digits 0-9 (left half, odd parity). G = reversed R.
 * R = bitwise complement of L. Patterns are 7 modules each. */
const L_CODES = [
  "0001101", "0011001", "0010011", "0111101", "0100011",
  "0110001", "0101111", "0111011", "0110111", "0001011",
];

/* Parity sequence of the 6 left digits encodes the (implicit) first digit. */
const PARITY_TABLE = [
  "LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG",
  "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL",
];

/** Run-length signature (4 runs summing to 7 modules) of a 7-module code. */
function runsOf(code) {
  const out = [];
  let count = 1;
  for (let i = 1; i < code.length; i++) {
    if (code[i] === code[i - 1]) count++;
    else {
      out.push(count);
      count = 1;
    }
  }
  out.push(count);
  return out;
}

const L_RUNS = L_CODES.map(runsOf); // space,bar,space,bar
const G_RUNS = L_CODES.map((c) =>
  runsOf(c.split("").map((b) => (b === "0" ? "1" : "0")).reverse().join(""))
); // G = reverse(complement(L)); starts with space
const R_RUNS = L_CODES.map((c) =>
  runsOf(c.split("").map((b) => (b === "0" ? "1" : "0")).join(""))
); // R = complement(L); starts with bar

/** Match 4 raw run widths against a pattern table. Returns {digit, error}. */
function matchDigit(widths, table) {
  const total = widths[0] + widths[1] + widths[2] + widths[3];
  if (total <= 0) return { digit: -1, error: Infinity };
  let best = -1;
  let bestErr = Infinity;
  for (let d = 0; d < 10; d++) {
    const pattern = table[d];
    let err = 0;
    for (let k = 0; k < 4; k++) {
      err += Math.abs((widths[k] * 7) / total - pattern[k]);
    }
    if (err < bestErr) {
      bestErr = err;
      best = d;
    }
  }
  return { digit: best, error: bestErr };
}

/* Max normalized error per digit (in modules). Generous enough for camera
 * blur, tight enough that the checksum rarely sees garbage. */
const MAX_DIGIT_ERROR = 1.8;

function ean13Checksum(digits) {
  let sum = 0;
  for (let i = 0; i < 13; i++) sum += digits[i] * (i % 2 === 0 ? 1 : 3);
  return sum % 10 === 0;
}

/** Whether three runs look like a 1:1:1 guard at module width ~m. */
function guardLike(a, b, c) {
  const m = (a + b + c) / 3;
  if (m <= 0) return false;
  return (
    Math.abs(a - m) / m < 0.55 && Math.abs(b - m) / m < 0.55 && Math.abs(c - m) / m < 0.55
  );
}

/**
 * Decode one binarized scanline given as run-lengths with the color of the
 * first run. `runs` is an array of positive widths; `firstIsBar` says
 * whether runs[0] is dark. Returns a 13-digit string or null.
 */
function decodeRuns(runs, firstIsBar) {
  // A full EAN-13 is 59 runs: 3 start + 24 left + 5 center + 24 right + 3 end.
  for (let start = 0; start + 59 <= runs.length; start++) {
    const barAt = (idx) => (idx % 2 === 0) === firstIsBar;
    if (!barAt(start)) continue; // start guard begins with a bar
    if (!guardLike(runs[start], runs[start + 1], runs[start + 2])) continue;
    const module = (runs[start] + runs[start + 1] + runs[start + 2]) / 3;

    // Quiet zone: the space before the start guard should be wide.
    if (start > 0 && runs[start - 1] < module * 3) continue;

    const digits = [];
    let parity = "";
    let ok = true;

    // 6 left digits (space,bar,space,bar each)
    let i = start + 3;
    for (let d = 0; d < 6 && ok; d++, i += 4) {
      const widths = [runs[i], runs[i + 1], runs[i + 2], runs[i + 3]];
      const asL = matchDigit(widths, L_RUNS);
      const asG = matchDigit(widths, G_RUNS);
      const pick = asL.error <= asG.error ? { ...asL, p: "L" } : { ...asG, p: "G" };
      if (pick.error > MAX_DIGIT_ERROR) ok = false;
      digits.push(pick.digit);
      parity += pick.p;
    }
    if (!ok) continue;

    // center guard: 5 runs ~1 module each, starting with a space
    if (!guardLike(runs[i], runs[i + 1], runs[i + 2]) || !guardLike(runs[i + 2], runs[i + 3], runs[i + 4])) {
      continue;
    }
    i += 5;

    // 6 right digits (bar,space,bar,space each), R patterns
    for (let d = 0; d < 6 && ok; d++, i += 4) {
      const widths = [runs[i], runs[i + 1], runs[i + 2], runs[i + 3]];
      const asR = matchDigit(widths, R_RUNS);
      if (asR.error > MAX_DIGIT_ERROR) ok = false;
      digits.push(asR.digit);
    }
    if (!ok) continue;

    // end guard
    if (!guardLike(runs[i], runs[i + 1], runs[i + 2])) continue;

    const first = PARITY_TABLE.indexOf(parity);
    if (first === -1) continue;
    const all = [first, ...digits];
    if (!ean13Checksum(all)) continue;
    return all.join("");
  }
  return null;
}

/** Binarize a luminance array and RLE it. Returns {runs, firstIsBar}. */
function toRuns(luma) {
  let min = 255;
  let max = 0;
  for (let i = 0; i < luma.length; i++) {
    if (luma[i] < min) min = luma[i];
    if (luma[i] > max) max = luma[i];
  }
  if (max - min < 40) return null; // not enough contrast to be a barcode
  const threshold = (min + max) / 2;
  const runs = [];
  let firstIsBar = luma[0] < threshold;
  let current = firstIsBar;
  let count = 1;
  for (let i = 1; i < luma.length; i++) {
    const dark = luma[i] < threshold;
    if (dark === current) count++;
    else {
      runs.push(count);
      current = dark;
      count = 1;
    }
  }
  runs.push(count);
  return { runs, firstIsBar };
}

/** Decode a single luminance scanline (Uint8-ish array). */
function decodeLuminanceLine(luma) {
  const rle = toRuns(luma);
  if (!rle) return null;
  const forward = decodeRuns(rle.runs, rle.firstIsBar);
  if (forward) return forward;
  const reversedRuns = rle.runs.slice().reverse();
  const lastIsBar = rle.runs.length % 2 === 1 ? rle.firstIsBar : !rle.firstIsBar;
  return decodeRuns(reversedRuns, lastIsBar);
}

/**
 * Decode an RGBA ImageData frame by sampling several horizontal scanlines.
 * Returns a 13-digit string or null.
 */
function decodeImageData(imageData) {
  const { data, width, height } = imageData;
  const fractions = [0.5, 0.44, 0.56, 0.38, 0.62, 0.3, 0.7];
  const luma = new Uint8Array(width);
  for (const f of fractions) {
    const y = Math.floor(height * f);
    const rowStart = y * width * 4;
    for (let x = 0; x < width; x++) {
      const p = rowStart + x * 4;
      // integer Rec.601 luma
      luma[x] = (data[p] * 77 + data[p + 1] * 150 + data[p + 2] * 29) >> 8;
    }
    const code = decodeLuminanceLine(luma);
    if (code) return code;
  }
  return null;
}

const BarcodeDecoder = {
  decodeImageData,
  decodeLuminanceLine,
  decodeRuns,
  ean13Checksum,
};

if (typeof module !== "undefined" && module.exports) {
  module.exports = BarcodeDecoder;
} else {
  window.BarcodeDecoder = BarcodeDecoder;
}
