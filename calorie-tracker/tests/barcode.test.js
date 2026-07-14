/*
 * barcode.test.js — unit tests for the EAN-13/UPC-A scanline decoder.
 * Run with: node tests/barcode.test.js  (no dependencies)
 */
"use strict";

const assert = require("assert");
const B = require("../js/barcode.js");

let passed = 0;
const failures = [];

function test(name, fn) {
  try {
    fn();
    passed++;
    console.log(`  ok  ${name}`);
  } catch (err) {
    failures.push({ name, err });
    console.error(`FAIL  ${name}\n      ${err.message}`);
  }
}

/* ---------------- reference encoder (test-side only) ---------------- */

const L = ["0001101","0011001","0010011","0111101","0100011","0110001","0101111","0111011","0110111","0001011"];
const PARITY = ["LLLLLL","LLGLGG","LLGGLG","LLGGGL","LGLLGG","LGGLLG","LGGGLL","LGLGLG","LGLGGL","LGGLGL"];
const complement = (s) => s.split("").map((b) => (b === "0" ? "1" : "0")).join("");
const reverse = (s) => s.split("").reverse().join("");
const R = L.map(complement);
const G = R.map(reverse);

function checkDigit(first12) {
  let sum = 0;
  for (let i = 0; i < 12; i++) sum += Number(first12[i]) * (i % 2 === 0 ? 1 : 3);
  return String((10 - (sum % 10)) % 10);
}

/** Encode 13 digits into the 95-module string. */
function encodeModules(code13) {
  const first = Number(code13[0]);
  let out = "101";
  for (let i = 0; i < 6; i++) {
    const d = Number(code13[1 + i]);
    out += PARITY[first][i] === "L" ? L[d] : G[d];
  }
  out += "01010";
  for (let i = 0; i < 6; i++) out += R[Number(code13[7 + i])];
  out += "101";
  return out;
}

/** Render modules to a luminance scanline. */
function toLuma(modules, pxPerModule, { quiet = 12, dark = 20, light = 235, noise = 0 } = {}) {
  const line = [];
  const push = (value, px) => {
    for (let i = 0; i < px; i++) {
      const jitter = noise ? Math.round((Math.sin(line.length * 7.3) + 1) * noise) : 0;
      line.push(Math.max(0, Math.min(255, value + jitter)));
    }
  };
  push(light, Math.round(quiet * pxPerModule));
  let acc = 0;
  let prev = 0;
  for (let i = 0; i < modules.length; i++) {
    // accumulate fractional module widths the way a camera would
    acc += pxPerModule;
    const px = Math.round(acc) - prev;
    prev = Math.round(acc);
    push(modules[i] === "1" ? dark : light, px);
  }
  push(light, Math.round(quiet * pxPerModule));
  return line;
}

const CODE = "4011112345621".slice(0, 12); // build a valid code below
const VALID = CODE + checkDigit(CODE); // 13 digits, checksum-correct
const UPC = "016000275270"; // 12-digit UPC-A
const UPC_AS_EAN = "0" + UPC.slice(0, 11) + checkDigit("0" + UPC.slice(0, 11));

/* ---------------- tests ---------------- */

test("checksum helper agrees with the decoder's validator", () => {
  assert.ok(B.ean13Checksum(VALID.split("").map(Number)));
  const bad = VALID.split("").map(Number);
  bad[12] = (bad[12] + 5) % 10;
  assert.ok(!B.ean13Checksum(bad));
});

test("decodes a clean scanline at 3 px/module", () => {
  const luma = toLuma(encodeModules(VALID), 3);
  assert.strictEqual(B.decodeLuminanceLine(luma), VALID);
});

test("decodes at non-integer module widths (camera scaling)", () => {
  for (const px of [2.4, 2.7, 3.3, 4.6, 5.5]) {
    const luma = toLuma(encodeModules(VALID), px);
    assert.strictEqual(B.decodeLuminanceLine(luma), VALID, `at ${px}px/module`);
  }
});

test("decodes with sensor noise and soft contrast", () => {
  const luma = toLuma(encodeModules(VALID), 3.2, { dark: 70, light: 190, noise: 12 });
  assert.strictEqual(B.decodeLuminanceLine(luma), VALID);
});

test("decodes a reversed (upside-down) scanline", () => {
  const luma = toLuma(encodeModules(VALID), 3).reverse();
  assert.strictEqual(B.decodeLuminanceLine(luma), VALID);
});

test("decodes a UPC-A code (as its EAN-13 form with leading zero)", () => {
  const luma = toLuma(encodeModules(UPC_AS_EAN), 3);
  assert.strictEqual(B.decodeLuminanceLine(luma), UPC_AS_EAN);
});

test("rejects a corrupted digit (checksum catches it)", () => {
  const modules = encodeModules(VALID);
  // flip one digit's worth of modules in the right half
  const corrupted = modules.slice(0, 55) + complement(modules.slice(55, 62)) + modules.slice(62);
  const luma = toLuma(corrupted, 3);
  assert.strictEqual(B.decodeLuminanceLine(luma), null);
});

test("rejects blank/low-contrast lines and random noise", () => {
  assert.strictEqual(B.decodeLuminanceLine(new Array(600).fill(200)), null);
  const random = Array.from({ length: 600 }, (_, i) => (i * 2654435761) % 255);
  assert.strictEqual(B.decodeLuminanceLine(random), null);
});

test("requires a quiet zone before the start guard", () => {
  const luma = toLuma(encodeModules(VALID), 3, { quiet: 0.5 });
  // with almost no quiet zone the guard is ambiguous; decoder must not crash
  const out = B.decodeLuminanceLine(luma);
  assert.ok(out === null || out === VALID);
});

test("decodeImageData finds the code on a centered scanline", () => {
  const lumaLine = toLuma(encodeModules(VALID), 3);
  const width = lumaLine.length;
  const height = 40;
  const data = new Uint8ClampedArray(width * height * 4);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const v = y > 10 && y < 30 ? lumaLine[x] : 220; // barcode band mid-frame
      const p = (y * width + x) * 4;
      data[p] = data[p + 1] = data[p + 2] = v;
      data[p + 3] = 255;
    }
  }
  assert.strictEqual(B.decodeImageData({ data, width, height }), VALID);
});

console.log(`\n${passed} passed, ${failures.length} failed`);
if (failures.length) process.exit(1);
