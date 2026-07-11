/*
 * nutrition.js — pure calculation and validation logic.
 * No DOM access here so the whole file is unit-testable under Node.
 */
"use strict";

const ACTIVITY_FACTORS = {
  sedentary: 1.2,
  light: 1.375,
  moderate: 1.55,
  active: 1.725,
  very_active: 1.9,
};

const GOAL_ADJUSTMENTS_KCAL = {
  lose: -500, // ~0.5 kg per week
  maintain: 0,
  gain: 300,
};

// Safety floor: never recommend below commonly cited minimum intakes.
const MIN_KCAL = { female: 1200, male: 1500 };

// Macro split of the calorie target (fractions must sum to 1).
const MACRO_SPLIT = { protein: 0.3, carbs: 0.4, fat: 0.3 };
const KCAL_PER_GRAM = { protein: 4, carbs: 4, fat: 9 };

const PROFILE_LIMITS = {
  age: { min: 13, max: 120 },
  heightCm: { min: 90, max: 250 },
  weightKg: { min: 30, max: 350 },
};

/** Mifflin–St Jeor basal metabolic rate (kcal/day). */
function bmr({ sex, age, heightCm, weightKg }) {
  const base = 10 * weightKg + 6.25 * heightCm - 5 * age;
  return sex === "male" ? base + 5 : base - 161;
}

/** Total daily energy expenditure. */
function tdee(profile) {
  const factor = ACTIVITY_FACTORS[profile.activity];
  if (!factor) throw new Error(`Unknown activity level: ${profile.activity}`);
  return bmr(profile) * factor;
}

/** Daily calorie + macro targets for a validated profile. */
function dailyTargets(profile) {
  const adjustment = GOAL_ADJUSTMENTS_KCAL[profile.goal];
  if (adjustment === undefined) throw new Error(`Unknown goal: ${profile.goal}`);
  const floor = MIN_KCAL[profile.sex];
  const kcal = Math.round(Math.max(floor, tdee(profile) + adjustment));
  return {
    kcal,
    proteinG: Math.round((kcal * MACRO_SPLIT.protein) / KCAL_PER_GRAM.protein),
    carbsG: Math.round((kcal * MACRO_SPLIT.carbs) / KCAL_PER_GRAM.carbs),
    fatG: Math.round((kcal * MACRO_SPLIT.fat) / KCAL_PER_GRAM.fat),
  };
}

/** Scale a food's per-100 g values to a portion in grams. */
function portionNutrients(foodPer100g, grams) {
  const scale = grams / 100;
  return {
    kcal: round1(foodPer100g.kcal * scale),
    protein: round1(foodPer100g.protein * scale),
    carbs: round1(foodPer100g.carbs * scale),
    fat: round1(foodPer100g.fat * scale),
  };
}

function round1(n) {
  return Math.round(n * 10) / 10;
}

/** Sum nutrients across a day's log entries. */
function dayTotals(entries) {
  const totals = { kcal: 0, protein: 0, carbs: 0, fat: 0 };
  for (const e of entries) {
    totals.kcal += e.kcal;
    totals.protein += e.protein;
    totals.carbs += e.carbs;
    totals.fat += e.fat;
  }
  for (const k of Object.keys(totals)) totals[k] = round1(totals[k]);
  return totals;
}

/** Local-timezone date key, e.g. "2026-07-11". */
function dateKey(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

/** The `days` date keys ending at (and including) `endDate`, oldest first. */
function lastNDateKeys(endDate, days) {
  const keys = [];
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(endDate.getFullYear(), endDate.getMonth(), endDate.getDate() - i);
    keys.push(dateKey(d));
  }
  return keys;
}

/* ------------------------------------------------------------------ */
/* Validation — used for form input and for untrusted JSON imports.    */
/* ------------------------------------------------------------------ */

function isFiniteNumber(v) {
  return typeof v === "number" && Number.isFinite(v);
}

function clampNumber(v, min, max) {
  if (!isFiniteNumber(v)) return null;
  return Math.min(max, Math.max(min, v));
}

/** Coerce arbitrary input into a safe, bounded display string. */
function sanitizeName(value, maxLen = 80) {
  if (typeof value !== "string") return null;
  // Strip control characters; keep everything else as plain text.
  const cleaned = value.replace(/[\u0000-\u001f\u007f]/g, "").trim();
  if (cleaned.length === 0) return null;
  return cleaned.slice(0, maxLen);
}

/** Validate a user profile object. Returns {ok, profile|errors}. */
function validateProfile(raw) {
  const errors = [];
  const sex = raw.sex === "male" || raw.sex === "female" ? raw.sex : null;
  if (!sex) errors.push("Select a body type for the calorie formula.");

  const fields = {};
  for (const [field, limit] of Object.entries(PROFILE_LIMITS)) {
    const v = Number(raw[field]);
    if (!isFiniteNumber(v) || v < limit.min || v > limit.max) {
      errors.push(`${field} must be between ${limit.min} and ${limit.max}.`);
    } else {
      fields[field] = v;
    }
  }
  if (!ACTIVITY_FACTORS[raw.activity]) errors.push("Select an activity level.");
  if (GOAL_ADJUSTMENTS_KCAL[raw.goal] === undefined) errors.push("Select a goal.");

  if (errors.length) return { ok: false, errors };
  return {
    ok: true,
    profile: { sex, ...fields, activity: raw.activity, goal: raw.goal },
  };
}

/** Validate one per-100 g food definition (custom food or import). */
function validateFood(raw) {
  const name = sanitizeName(raw && raw.name);
  if (!name) return null;
  const kcal = clampNumber(Number(raw.kcal), 0, 900);
  const protein = clampNumber(Number(raw.protein), 0, 100);
  const carbs = clampNumber(Number(raw.carbs), 0, 100);
  const fat = clampNumber(Number(raw.fat), 0, 100);
  if ([kcal, protein, carbs, fat].some((v) => v === null)) return null;
  return { name, kcal, protein, carbs, fat };
}

/** Validate one log entry from an untrusted import. */
function validateLogEntry(raw) {
  if (!raw || typeof raw !== "object") return null;
  const name = sanitizeName(raw.name);
  if (!name) return null;
  const meal = ["breakfast", "lunch", "dinner", "snacks"].includes(raw.meal)
    ? raw.meal
    : "snacks";
  const grams = clampNumber(Number(raw.grams), 1, 5000);
  const kcal = clampNumber(Number(raw.kcal), 0, 20000);
  const protein = clampNumber(Number(raw.protein), 0, 2000);
  const carbs = clampNumber(Number(raw.carbs), 0, 2000);
  const fat = clampNumber(Number(raw.fat), 0, 2000);
  if ([grams, kcal, protein, carbs, fat].some((v) => v === null)) return null;
  return { name, meal, grams, kcal, protein, carbs, fat };
}

const DATE_KEY_RE = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Validate a full exported-state object (untrusted JSON import).
 * Returns a fresh, fully sanitized state or null if the shape is wrong.
 */
function validateImportedState(raw) {
  if (!raw || typeof raw !== "object" || raw.version !== 1) return null;

  let profile = null;
  if (raw.profile) {
    const res = validateProfile(raw.profile);
    if (!res.ok) return null;
    profile = res.profile;
  }

  const customFoods = [];
  if (Array.isArray(raw.customFoods)) {
    for (const f of raw.customFoods.slice(0, 500)) {
      const valid = validateFood(f);
      if (valid) customFoods.push(valid);
    }
  }

  const log = {};
  if (raw.log && typeof raw.log === "object" && !Array.isArray(raw.log)) {
    for (const key of Object.keys(raw.log).slice(0, 3700)) {
      if (!DATE_KEY_RE.test(key) || !Array.isArray(raw.log[key])) continue;
      const entries = [];
      for (const e of raw.log[key].slice(0, 200)) {
        const valid = validateLogEntry(e);
        if (valid) entries.push(valid);
      }
      if (entries.length) log[key] = entries;
    }
  }

  return { version: 1, profile, customFoods, log };
}

const Nutrition = {
  ACTIVITY_FACTORS,
  GOAL_ADJUSTMENTS_KCAL,
  MIN_KCAL,
  MACRO_SPLIT,
  KCAL_PER_GRAM,
  PROFILE_LIMITS,
  bmr,
  tdee,
  dailyTargets,
  portionNutrients,
  dayTotals,
  dateKey,
  lastNDateKeys,
  sanitizeName,
  validateProfile,
  validateFood,
  validateLogEntry,
  validateImportedState,
};

if (typeof module !== "undefined" && module.exports) {
  module.exports = Nutrition; // Node (unit tests)
} else {
  window.Nutrition = Nutrition; // Browser
}
