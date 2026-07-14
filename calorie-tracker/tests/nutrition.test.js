/*
 * nutrition.test.js — unit tests for all pure logic.
 * Run with: node tests/nutrition.test.js  (no dependencies)
 */
"use strict";

const assert = require("assert");
const N = require("../js/nutrition.js");
const FOODS = require("../js/foods.js");

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

/* ---------------- BMR / TDEE / targets ---------------- */

test("BMR matches Mifflin–St Jeor for a reference male", () => {
  // 10*80 + 6.25*180 - 5*30 + 5 = 800 + 1125 - 150 + 5 = 1780
  const value = N.bmr({ sex: "male", age: 30, heightCm: 180, weightKg: 80 });
  assert.strictEqual(value, 1780);
});

test("BMR matches Mifflin–St Jeor for a reference female", () => {
  // 10*60 + 6.25*165 - 5*25 - 161 = 600 + 1031.25 - 125 - 161 = 1345.25
  const value = N.bmr({ sex: "female", age: 25, heightCm: 165, weightKg: 60 });
  assert.strictEqual(value, 1345.25);
});

test("TDEE applies the activity factor", () => {
  const profile = { sex: "male", age: 30, heightCm: 180, weightKg: 80, activity: "moderate" };
  assert.strictEqual(N.tdee(profile), 1780 * 1.55);
});

test("TDEE rejects unknown activity levels", () => {
  assert.throws(() =>
    N.tdee({ sex: "male", age: 30, heightCm: 180, weightKg: 80, activity: "extreme" })
  );
});

test("dailyTargets applies the weight-loss deficit", () => {
  const profile = { sex: "male", age: 30, heightCm: 180, weightKg: 80, activity: "moderate", goal: "lose" };
  const t = N.dailyTargets(profile);
  assert.strictEqual(t.kcal, Math.round(1780 * 1.55 - 500));
});

test("dailyTargets never goes below the safety floor", () => {
  const profile = { sex: "female", age: 60, heightCm: 150, weightKg: 45, activity: "sedentary", goal: "lose" };
  const t = N.dailyTargets(profile);
  assert.strictEqual(t.kcal, 1200);
});

test("protein target is anchored to body weight and goal", () => {
  const base = { sex: "male", age: 30, heightCm: 180, weightKg: 80, activity: "moderate" };
  assert.strictEqual(N.dailyTargets({ ...base, goal: "lose" }).proteinG, 160); // 2.0 g/kg
  assert.strictEqual(N.dailyTargets({ ...base, goal: "maintain" }).proteinG, 128); // 1.6 g/kg
  assert.strictEqual(N.dailyTargets({ ...base, goal: "gain" }).proteinG, 144); // 1.8 g/kg
});

test("macros are internally consistent with the calorie target", () => {
  const t = N.dailyTargets({ sex: "female", age: 45, heightCm: 165, weightKg: 70, activity: "light", goal: "lose" });
  const macroKcal = t.proteinG * 4 + t.carbsG * 4 + t.fatG * 9;
  assert.ok(Math.abs(macroKcal - t.kcal) < 25, `macro kcal ${macroKcal} vs target ${t.kcal}`);
  assert.ok(t.carbsG >= 0 && t.fatG > 0);
});

test("protein is capped at 35% of calories for light people on a cut", () => {
  const t = N.dailyTargets({ sex: "female", age: 25, heightCm: 160, weightKg: 90, activity: "sedentary", goal: "lose" });
  assert.ok(t.proteinG <= Math.round((t.kcal * 0.35) / 4) + 1);
});

test("target overrides replace computed values, others recompute", () => {
  const profile = { sex: "male", age: 30, heightCm: 180, weightKg: 80, activity: "moderate", goal: "lose" };
  const t = N.dailyTargets(profile, { kcal: 2000, proteinG: 150 });
  assert.strictEqual(t.kcal, 2000);
  assert.strictEqual(t.proteinG, 150);
  assert.ok(t.carbsG > 0 && t.fatG > 0);
});

test("validateTargetOverrides clamps, rounds, and drops blanks", () => {
  assert.deepStrictEqual(N.validateTargetOverrides({ kcal: "2100", proteinG: "", carbsG: "abc", fatG: 5000 }), { kcal: 2100, fatG: 2000 });
  assert.strictEqual(N.validateTargetOverrides({ kcal: "", proteinG: "" }), null);
  assert.strictEqual(N.validateTargetOverrides("junk"), null);
  assert.deepStrictEqual(N.validateTargetOverrides({ kcal: 100 }), { kcal: 800 }); // clamped up
});

test("unit conversions round-trip", () => {
  assert.ok(Math.abs(N.lbToKg(180) - 81.65) < 0.01);
  assert.ok(Math.abs(N.kgToLb(N.lbToKg(180)) - 180) < 1e-9);
  assert.ok(Math.abs(N.ftInToCm(5, 11) - 180.34) < 0.01);
  assert.deepStrictEqual(N.cmToFtIn(180.34), { ft: 5, inch: 11 });
  assert.deepStrictEqual(N.cmToFtIn(182.88), { ft: 6, inch: 0 }); // inch rollover
});

test("validateProfile stores the unit system, defaulting to metric", () => {
  const base = { sex: "male", age: 30, heightCm: 180, weightKg: 80, activity: "moderate", goal: "lose" };
  assert.strictEqual(N.validateProfile(base).profile.units, "metric");
  assert.strictEqual(N.validateProfile({ ...base, units: "us" }).profile.units, "us");
  assert.strictEqual(N.validateProfile({ ...base, units: "bogus" }).profile.units, "metric");
});

test("validateSettings: consent toggle independent of key; bad keys dropped", () => {
  assert.deepStrictEqual(N.validateSettings({ onlineSearch: true, usdaApiKey: "abcDEF123" }), { onlineSearch: true, usdaApiKey: "abcDEF123" });
  assert.deepStrictEqual(N.validateSettings({ onlineSearch: true }), { onlineSearch: true, usdaApiKey: "" }); // barcode-only mode
  assert.deepStrictEqual(N.validateSettings({ onlineSearch: true, usdaApiKey: "bad key!<script>" }), { onlineSearch: true, usdaApiKey: "" });
  assert.deepStrictEqual(N.validateSettings(null), { onlineSearch: false, usdaApiKey: "" });
  assert.deepStrictEqual(N.validateSettings({ onlineSearch: "yes" }), { onlineSearch: false, usdaApiKey: "" }); // strict boolean
});

test("mapOffProduct extracts Open Food Facts nutrition per 100 g", () => {
  const payload = {
    product: {
      product_name: "Honey Nut Oat Cereal",
      brands: "SomeBrand, OtherBrand",
      serving_quantity: 28,
      nutriments: { "energy-kcal_100g": 379, proteins_100g: 8.9, carbohydrates_100g: 79.3, fat_100g: 4.9 },
    },
  };
  const mapped = N.mapOffProduct(payload);
  assert.deepStrictEqual(mapped.food, {
    name: "Honey Nut Oat Cereal — SomeBrand", kcal: 379, protein: 8.9, carbs: 79.3, fat: 4.9,
  });
  assert.strictEqual(mapped.servingG, 28);
  assert.strictEqual(mapped.macrosSuspect, false);
  assert.strictEqual(N.mapOffProduct({ product: { product_name: "x", nutriments: {} } }), null); // no energy
  assert.strictEqual(N.mapOffProduct({ product: { nutriments: { "energy-kcal_100g": 100 } } }), null); // no name
  assert.strictEqual(N.mapOffProduct(null), null);
});

test("mapOffProduct falls back to per-serving values when _100g is missing", () => {
  const payload = {
    product: {
      product_name: "Serving-Only Snack",
      serving_quantity: 40,
      nutriments: {
        "energy-kcal_serving": 160, proteins_serving: 4, carbohydrates_serving: 24, fat_serving: 5.2,
      },
    },
  };
  const mapped = N.mapOffProduct(payload);
  assert.deepStrictEqual(mapped.food, {
    name: "Serving-Only Snack", kcal: 400, protein: 10, carbs: 60, fat: 13,
  });
  assert.strictEqual(mapped.servingG, 40);
  assert.strictEqual(mapped.macrosSuspect, false);
});

test("mapOffProduct flags macro data that can't explain the calories", () => {
  const mapped = N.mapOffProduct({
    product: {
      product_name: "Bad Data Bar",
      nutriments: { "energy-kcal_100g": 450, proteins_100g: 0, carbohydrates_100g: 0, fat_100g: 0 },
    },
  });
  assert.strictEqual(mapped.macrosSuspect, true);
  // and impossible values are rejected downstream by validateFood
  const junk = N.mapOffProduct({
    product: {
      product_name: "Unit Error Bar",
      nutriments: { "energy-kcal_100g": 100, proteins_100g: 2900, carbohydrates_100g: 10, fat_100g: 2 },
    },
  });
  assert.strictEqual(N.validateFood(junk.food), null);
});

test("barcode format accepts EAN/UPC digit strings only", () => {
  assert.ok(N.BARCODE_RE.test("016000275270"));
  assert.ok(N.BARCODE_RE.test("40111445"));
  assert.ok(!N.BARCODE_RE.test("123"));
  assert.ok(!N.BARCODE_RE.test("abc123456789"));
  assert.ok(!N.BARCODE_RE.test("1".repeat(15)));
});

test("validateWeights keeps valid dated entries and clamps values", () => {
  const weights = N.validateWeights({
    "2026-07-01": 81.55,
    "2026-07-02": "82",
    "not-a-date": 80,
    "2026-07-03": 9999,
    "2026-07-04": "junk",
  });
  assert.deepStrictEqual(weights, { "2026-07-01": 81.6, "2026-07-02": 82, "2026-07-03": 350 });
  assert.deepStrictEqual(N.validateWeights(null), {});
  assert.deepStrictEqual(N.validateWeights([1, 2]), {});
});

test("mapUsdaFood extracts per-100g nutrients and brand", () => {
  const item = {
    description: "CHEERIOS",
    brandOwner: "General Mills",
    foodNutrients: [
      { nutrientId: 1008, value: 367 },
      { nutrientId: 1003, value: 12.1 },
      { nutrientId: 1005, value: 73.2 },
      { nutrientId: 1004, value: 6.7 },
    ],
  };
  assert.deepStrictEqual(N.mapUsdaFood(item), { name: "CHEERIOS — General Mills", kcal: 367, protein: 12.1, carbs: 73.2, fat: 6.7 });
  assert.strictEqual(N.mapUsdaFood({ description: "x", foodNutrients: [] }), null); // no energy
  assert.strictEqual(N.mapUsdaFood(null), null);
  // hostile values are rejected downstream by validateFood
  assert.strictEqual(N.validateFood(N.mapUsdaFood({ description: "", foodNutrients: [{ nutrientId: 1008, value: 100 }] })), null);
});

/* ---------------- portions and totals ---------------- */

test("portionNutrients scales per-100g values", () => {
  const food = { kcal: 200, protein: 10, carbs: 20, fat: 5 };
  assert.deepStrictEqual(N.portionNutrients(food, 50), { kcal: 100, protein: 5, carbs: 10, fat: 2.5 });
});

test("portionNutrients rounds to one decimal", () => {
  const food = { kcal: 52, protein: 0.3, carbs: 13.8, fat: 0.2 };
  const p = N.portionNutrients(food, 182);
  assert.strictEqual(p.kcal, 94.6);
  assert.strictEqual(p.carbs, 25.1);
});

test("dayTotals sums entries", () => {
  const totals = N.dayTotals([
    { kcal: 100.5, protein: 5, carbs: 10, fat: 2 },
    { kcal: 200.2, protein: 15, carbs: 20, fat: 8 },
  ]);
  assert.deepStrictEqual(totals, { kcal: 300.7, protein: 20, carbs: 30, fat: 10 });
});

test("dayTotals of an empty day is zero", () => {
  assert.deepStrictEqual(N.dayTotals([]), { kcal: 0, protein: 0, carbs: 0, fat: 0 });
});

/* ---------------- dates ---------------- */

test("dateKey formats local dates as YYYY-MM-DD", () => {
  assert.strictEqual(N.dateKey(new Date(2026, 6, 11)), "2026-07-11");
  assert.strictEqual(N.dateKey(new Date(2026, 0, 2)), "2026-01-02");
});

test("lastNDateKeys spans month boundaries", () => {
  const keys = N.lastNDateKeys(new Date(2026, 6, 2), 7); // Jul 2 back to Jun 26
  assert.strictEqual(keys.length, 7);
  assert.strictEqual(keys[0], "2026-06-26");
  assert.strictEqual(keys[6], "2026-07-02");
});

/* ---------------- profile validation ---------------- */

test("validateProfile accepts a sensible profile", () => {
  const res = N.validateProfile({ sex: "female", age: "29", heightCm: "170", weightKg: "64.5", activity: "light", goal: "maintain" });
  assert.strictEqual(res.ok, true);
  assert.strictEqual(res.profile.weightKg, 64.5);
});

test("validateProfile rejects out-of-range and missing values", () => {
  const res = N.validateProfile({ sex: "robot", age: 5, heightCm: 500, weightKg: -1, activity: "none", goal: "hover" });
  assert.strictEqual(res.ok, false);
  assert.ok(res.errors.length >= 5);
});

/* ---------------- food / entry validation ---------------- */

test("validateFood accepts numeric strings and trims names", () => {
  const food = N.validateFood({ name: "  My Bar  ", kcal: "250", protein: "10", carbs: "30", fat: "8" });
  assert.deepStrictEqual(food, { name: "My Bar", kcal: 250, protein: 10, carbs: 30, fat: 8 });
});

test("validateFood rejects non-numeric and empty names", () => {
  assert.strictEqual(N.validateFood({ name: "", kcal: 1, protein: 1, carbs: 1, fat: 1 }), null);
  assert.strictEqual(N.validateFood({ name: "x", kcal: "abc", protein: 1, carbs: 1, fat: 1 }), null);
  assert.strictEqual(N.validateFood(null), null);
});

test("validateFood REJECTS impossible per-100g values instead of clamping", () => {
  // clamping protein to 100 g/100 g made logged protein equal the portion size
  assert.strictEqual(N.validateFood({ name: "junk", kcal: 100, protein: 2900, carbs: 10, fat: 2 }), null);
  assert.strictEqual(N.validateFood({ name: "junk", kcal: 5000, protein: 10, carbs: 10, fat: 2 }), null);
  assert.strictEqual(N.validateFood({ name: "junk", kcal: 100, protein: -5, carbs: 10, fat: 2 }), null);
  // macros summing past 100 g per 100 g are physically impossible too
  assert.strictEqual(N.validateFood({ name: "junk", kcal: 600, protein: 60, carbs: 60, fat: 20 }), null);
  // legitimate extremes still pass
  assert.ok(N.validateFood({ name: "Olive oil", kcal: 884, protein: 0, carbs: 0, fat: 100 }));
});

test("macrosConsistent flags foods whose macros don't explain their kcal", () => {
  assert.ok(N.macrosConsistent({ kcal: 379, protein: 8.9, carbs: 79.3, fat: 4.9 }));
  assert.ok(!N.macrosConsistent({ kcal: 379, protein: 0, carbs: 0, fat: 0 }));
  assert.ok(!N.macrosConsistent({ kcal: 50, protein: 25, carbs: 25, fat: 10 }));
});

test("sanitizeName strips control characters and caps length", () => {
  assert.strictEqual(N.sanitizeName("a bc"), "abc");
  assert.strictEqual(N.sanitizeName("x".repeat(500)).length, 80);
  assert.strictEqual(N.sanitizeName(12345), null);
  assert.strictEqual(N.sanitizeName("   "), null);
});

test("sanitizeName keeps HTML as inert text (rendered via textContent)", () => {
  const name = N.sanitizeName('<img src=x onerror=alert(1)>');
  assert.strictEqual(name, '<img src=x onerror=alert(1)>'); // stays a plain string
});

/* ---------------- import validation (untrusted JSON) ---------------- */

const validExport = {
  version: 1,
  profile: { sex: "male", age: 30, heightCm: 180, weightKg: 80, activity: "moderate", goal: "lose" },
  customFoods: [{ name: "Bar", kcal: 250, protein: 10, carbs: 30, fat: 8 }],
  log: {
    "2026-07-10": [{ name: "Apple (raw, with skin)", meal: "snacks", grams: 150, kcal: 78, protein: 0.5, carbs: 20.7, fat: 0.3 }],
  },
};

test("validateImportedState round-trips a valid export", () => {
  const state = N.validateImportedState(JSON.parse(JSON.stringify(validExport)));
  assert.ok(state);
  assert.strictEqual(state.profile.age, 30);
  assert.strictEqual(state.customFoods.length, 1);
  assert.strictEqual(state.log["2026-07-10"].length, 1);
});

test("validateImportedState carries targets and settings with safe defaults", () => {
  const withExtras = JSON.parse(JSON.stringify(validExport));
  withExtras.targets = { kcal: 2100, proteinG: 9999 };
  withExtras.settings = { onlineSearch: true, usdaApiKey: "key123" };
  const state = N.validateImportedState(withExtras);
  assert.deepStrictEqual(state.targets, { kcal: 2100, proteinG: 2000 });
  assert.deepStrictEqual(state.settings, { onlineSearch: true, usdaApiKey: "key123" });

  const legacy = N.validateImportedState(JSON.parse(JSON.stringify(validExport)));
  assert.strictEqual(legacy.targets, null); // old exports still import
  assert.deepStrictEqual(legacy.settings, { onlineSearch: false, usdaApiKey: "" });
});

test("validateImportedState rejects wrong versions and non-objects", () => {
  assert.strictEqual(N.validateImportedState(null), null);
  assert.strictEqual(N.validateImportedState("hi"), null);
  assert.strictEqual(N.validateImportedState({ version: 2 }), null);
  assert.strictEqual(N.validateImportedState([]), null);
});

test("validateImportedState drops malformed log keys and entries", () => {
  const state = N.validateImportedState({
    version: 1,
    profile: null,
    customFoods: "not-an-array",
    log: {
      "not-a-date": [{ name: "x", grams: 10, kcal: 1, protein: 0, carbs: 0, fat: 0 }],
      "2026-07-01": [
        { name: "ok", meal: "lunch", grams: 100, kcal: 100, protein: 1, carbs: 1, fat: 1 },
        { name: "", grams: 100, kcal: 100, protein: 1, carbs: 1, fat: 1 },
        "garbage",
        { name: "bad numbers", grams: "NaN", kcal: {}, protein: [], carbs: null, fat: 1 },
      ],
    },
  });
  assert.ok(state);
  assert.strictEqual(state.log["not-a-date"], undefined);
  assert.strictEqual(state.log["2026-07-01"].length, 1);
  assert.strictEqual(state.log["2026-07-01"][0].name, "ok");
});

test("validateImportedState drops foods with hostile numeric values", () => {
  const state = N.validateImportedState({
    version: 1,
    profile: null,
    customFoods: [
      { name: "hax", kcal: 1e308, protein: -50, carbs: 1e9, fat: 3 },
      { name: "fine", kcal: 250, protein: 10, carbs: 30, fat: 8 },
    ],
    log: {},
  });
  assert.strictEqual(state.customFoods.length, 1);
  assert.strictEqual(state.customFoods[0].name, "fine");
});

test("validateImportedState rejects imports with an invalid profile", () => {
  const bad = JSON.parse(JSON.stringify(validExport));
  bad.profile.age = 99999;
  assert.strictEqual(N.validateImportedState(bad), null);
});

test("validateImportedState ignores prototype-pollution style keys", () => {
  const state = N.validateImportedState({
    version: 1,
    profile: null,
    customFoods: [],
    log: { __proto__: [], constructor: [], "2026-07-01": [] },
  });
  assert.ok(state);
  assert.deepStrictEqual(state.log, {});
  assert.strictEqual({}.polluted, undefined);
});

/* ---------------- built-in food data sanity ---------------- */

test("every built-in food is valid, unique, and energy-consistent", () => {
  const ids = new Set();
  for (const food of FOODS) {
    assert.ok(!ids.has(food.id), `duplicate id ${food.id}`);
    ids.add(food.id);
    assert.ok(N.validateFood(food), `food fails validation: ${food.id}`);
    // 4/4/9 Atwater check: derived kcal should be within 20% of stated kcal.
    const derived = food.protein * 4 + food.carbs * 4 + food.fat * 9;
    const tolerance = Math.max(20, food.kcal * 0.2);
    assert.ok(
      Math.abs(derived - food.kcal) <= tolerance,
      `${food.id}: stated ${food.kcal} kcal vs derived ${derived.toFixed(0)} kcal`
    );
  }
});

/* ---------------- summary ---------------- */

console.log(`\n${passed} passed, ${failures.length} failed`);
if (failures.length) process.exit(1);
