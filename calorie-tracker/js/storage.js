/*
 * storage.js — localStorage persistence.
 *
 * All data stays in the user's browser. Anything read back from storage is
 * treated as untrusted and passed through the same validator used for file
 * imports, so a corrupted or tampered value can never poison the UI.
 */
"use strict";

(function () {
  const STORAGE_KEY = "calorie-tracker.v1";

  function emptyState() {
    return { version: 1, profile: null, customFoods: [], log: {} };
  }

  function load() {
    let raw;
    try {
      raw = localStorage.getItem(STORAGE_KEY);
    } catch (e) {
      return emptyState(); // storage disabled (private mode etc.)
    }
    if (!raw) return emptyState();
    try {
      const validated = window.Nutrition.validateImportedState(JSON.parse(raw));
      return validated || emptyState();
    } catch (e) {
      return emptyState();
    }
  }

  function save(state) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
      return true;
    } catch (e) {
      return false; // quota exceeded or storage disabled
    }
  }

  function clear() {
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch (e) {
      /* nothing to do */
    }
  }

  window.AppStorage = { load, save, clear, emptyState, STORAGE_KEY };
})();
