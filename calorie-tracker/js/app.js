/*
 * app.js — UI wiring and rendering.
 *
 * Security invariant: user- or import-controlled strings only ever reach the
 * DOM through textContent (or attribute setters on values we generated).
 * innerHTML is never used with data. Charts are built with createElementNS.
 */
"use strict";

(function () {
  const APP_VERSION = "1.4.0"; // bump on every release, with sw.js CACHE_NAME
  const N = window.Nutrition;
  const SVG_NS = "http://www.w3.org/2000/svg";
  const MEALS = ["breakfast", "lunch", "dinner", "snacks"];
  const MEAL_LABELS = {
    breakfast: "Breakfast",
    lunch: "Lunch",
    dinner: "Dinner",
    snacks: "Snacks",
  };

  let state = window.AppStorage.load();
  let viewDate = new Date();
  let editingProfile = false;

  /* ---------------------------------------------------------------- */
  /* Small DOM helpers (safe by construction)                          */
  /* ---------------------------------------------------------------- */

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function svgEl(tag, attrs) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, String(v));
    return node;
  }

  function clearNode(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function fmt(n) {
    return n.toLocaleString("en-US", { maximumFractionDigits: 1 });
  }

  function announce(message) {
    const region = document.getElementById("status-region");
    region.textContent = message;
  }

  function persist() {
    if (!window.AppStorage.save(state)) {
      announce("Warning: could not save — browser storage is full or disabled.");
    }
  }

  /* ---------------------------------------------------------------- */
  /* Food lookup                                                       */
  /* ---------------------------------------------------------------- */

  function allFoods() {
    const custom = state.customFoods.map((f, i) => ({
      id: `custom-${i}`,
      name: `${f.name} (custom)`,
      kcal: f.kcal,
      protein: f.protein,
      carbs: f.carbs,
      fat: f.fat,
    }));
    return custom.concat(window.BUILTIN_FOODS);
  }

  function searchFoods(query) {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    const words = q.split(/\s+/);
    return allFoods()
      .filter((f) => {
        const name = f.name.toLowerCase();
        return words.every((w) => name.includes(w));
      })
      .slice(0, 12);
  }

  /* ---------------------------------------------------------------- */
  /* Profile / setup view                                              */
  /* ---------------------------------------------------------------- */

  function currentUnits() {
    return document.getElementById("profile-units").value === "metric" ? "metric" : "us";
  }

  /* Show the height/weight fields matching the chosen unit system. */
  function applyUnitsToForm(units) {
    const metric = units === "metric";
    document.getElementById("height-metric-label").hidden = !metric;
    document.getElementById("height-us-wrap").hidden = metric;
    document.getElementById("weight-label").textContent = metric ? "Weight (kg)" : "Weight (lb)";
  }

  /* Read the form and normalize to metric for validation/storage. */
  function readProfileForm() {
    const units = currentUnits();
    let heightCm;
    let weightKg;
    if (units === "metric") {
      heightCm = Number(document.getElementById("profile-height").value);
      weightKg = Number(document.getElementById("profile-weight").value);
    } else {
      const ft = Number(document.getElementById("profile-height-ft").value);
      const inch = Number(document.getElementById("profile-height-in").value || 0);
      heightCm = N.ftInToCm(ft, inch);
      weightKg = N.lbToKg(Number(document.getElementById("profile-weight").value));
    }
    return {
      sex: document.getElementById("profile-sex").value,
      age: document.getElementById("profile-age").value,
      heightCm,
      weightKg: Math.round(weightKg * 10) / 10,
      activity: document.getElementById("profile-activity").value,
      goal: document.getElementById("profile-goal").value,
      units,
    };
  }

  function fillProfileForm(profile) {
    if (!profile) {
      applyUnitsToForm(currentUnits());
      return;
    }
    const units = profile.units || "metric";
    document.getElementById("profile-units").value = units;
    applyUnitsToForm(units);
    document.getElementById("profile-sex").value = profile.sex;
    document.getElementById("profile-age").value = profile.age;
    if (units === "metric") {
      document.getElementById("profile-height").value = Math.round(profile.heightCm);
      document.getElementById("profile-weight").value = profile.weightKg;
    } else {
      const { ft, inch } = N.cmToFtIn(profile.heightCm);
      document.getElementById("profile-height-ft").value = ft;
      document.getElementById("profile-height-in").value = inch;
      document.getElementById("profile-weight").value = Math.round(N.kgToLb(profile.weightKg));
    }
    document.getElementById("profile-activity").value = profile.activity;
    document.getElementById("profile-goal").value = profile.goal;
  }

  function onProfileSubmit(event) {
    event.preventDefault();
    const result = N.validateProfile(readProfileForm());
    const errorBox = document.getElementById("profile-errors");
    clearNode(errorBox);
    if (!result.ok) {
      for (const message of result.errors) errorBox.appendChild(el("li", "", message));
      return;
    }
    state.profile = result.profile;
    editingProfile = false;
    persist();
    announce("Profile saved.");
    render();
  }

  /* ---------------------------------------------------------------- */
  /* Dashboard rendering                                               */
  /* ---------------------------------------------------------------- */

  function entriesFor(key) {
    return state.log[key] || [];
  }

  function renderDateNav() {
    const label = document.getElementById("date-label");
    const key = N.dateKey(viewDate);
    const today = N.dateKey(new Date());
    label.textContent =
      key === today
        ? "Today"
        : viewDate.toLocaleDateString("en-US", {
            weekday: "short",
            month: "short",
            day: "numeric",
          });
    document.getElementById("date-next").disabled = key >= today;
  }

  function renderRing(totals, targets) {
    const mount = document.getElementById("calorie-ring");
    clearNode(mount);

    const size = 168;
    const stroke = 12;
    const r = (size - stroke) / 2;
    const c = 2 * Math.PI * r;
    const ratio = targets.kcal > 0 ? Math.min(totals.kcal / targets.kcal, 1) : 0;
    const over = totals.kcal > targets.kcal;

    const svg = svgEl("svg", {
      viewBox: `0 0 ${size} ${size}`,
      width: size,
      height: size,
      role: "img",
      "aria-label": `${fmt(totals.kcal)} of ${fmt(targets.kcal)} kilocalories eaten today`,
    });
    svg.appendChild(
      svgEl("circle", {
        cx: size / 2, cy: size / 2, r,
        fill: "none", stroke: "var(--ring-track)", "stroke-width": stroke,
      })
    );
    const arc = svgEl("circle", {
      cx: size / 2, cy: size / 2, r,
      fill: "none",
      stroke: over ? "var(--status-over)" : "var(--series-1)",
      "stroke-width": stroke,
      "stroke-linecap": "round",
      "stroke-dasharray": `${c * ratio} ${c}`,
      transform: `rotate(-90 ${size / 2} ${size / 2})`,
    });
    svg.appendChild(arc);
    mount.appendChild(svg);

    const center = el("div", "ring-center");
    center.appendChild(el("div", "ring-value", fmt(totals.kcal)));
    center.appendChild(el("div", "ring-caption", `of ${fmt(targets.kcal)} kcal`));
    const remaining = Math.round(targets.kcal - totals.kcal);
    center.appendChild(
      el(
        "div",
        over ? "ring-remaining over" : "ring-remaining",
        over ? `${fmt(-remaining)} over goal` : `${fmt(remaining)} left`
      )
    );
    mount.appendChild(center);
  }

  function renderMacros(totals, targets) {
    const mount = document.getElementById("macro-bars");
    clearNode(mount);
    const rows = [
      { label: "Protein", eaten: totals.protein, goal: targets.proteinG, cssVar: "--series-1" },
      { label: "Carbs", eaten: totals.carbs, goal: targets.carbsG, cssVar: "--series-2" },
      { label: "Fat", eaten: totals.fat, goal: targets.fatG, cssVar: "--series-3" },
    ];
    for (const row of rows) {
      const item = el("div", "macro-row");
      const head = el("div", "macro-head");
      head.appendChild(el("span", "macro-label", row.label));
      head.appendChild(el("span", "macro-value", `${fmt(row.eaten)} / ${fmt(row.goal)} g`));
      item.appendChild(head);

      const track = el("div", "macro-track");
      track.setAttribute("role", "progressbar");
      track.setAttribute("aria-label", `${row.label}: ${fmt(row.eaten)} of ${fmt(row.goal)} grams`);
      track.setAttribute("aria-valuemin", "0");
      track.setAttribute("aria-valuemax", String(row.goal));
      track.setAttribute("aria-valuenow", String(Math.min(row.eaten, row.goal)));
      const fill = el("div", "macro-fill");
      fill.style.width = `${Math.min((row.eaten / row.goal) * 100 || 0, 100)}%`;
      fill.style.background = `var(${row.cssVar})`;
      track.appendChild(fill);
      item.appendChild(track);
      mount.appendChild(item);
    }
  }

  /* 7-day bar chart: single series, goal line, per-bar hover tooltip. */
  function renderWeekChart(targets) {
    const mount = document.getElementById("week-chart");
    clearNode(mount);

    const keys = N.lastNDateKeys(viewDate, 7);
    const values = keys.map((k) => N.dayTotals(entriesFor(k)).kcal);
    const maxVal = Math.max(targets.kcal * 1.15, ...values, 1);

    const width = 320;
    const height = 150;
    const pad = { top: 10, right: 4, bottom: 22, left: 4 };
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;
    const slot = plotW / 7;
    const barW = Math.min(28, slot - 8);

    const svg = svgEl("svg", {
      viewBox: `0 0 ${width} ${height}`,
      class: "week-svg",
      role: "img",
      "aria-label": "Calories eaten over the last 7 days compared with the daily goal",
    });

    const goalY = pad.top + plotH * (1 - targets.kcal / maxVal);
    svg.appendChild(
      svgEl("line", {
        x1: pad.left, x2: width - pad.right, y1: goalY, y2: goalY,
        stroke: "var(--chart-goal)", "stroke-width": 1, "stroke-dasharray": "4 3",
      })
    );
    svg.appendChild(
      svgEl("line", {
        x1: pad.left, x2: width - pad.right,
        y1: pad.top + plotH, y2: pad.top + plotH,
        stroke: "var(--chart-baseline)", "stroke-width": 1,
      })
    );

    const tooltip = el("div", "chart-tooltip");
    tooltip.hidden = true;

    keys.forEach((key, i) => {
      const value = values[i];
      const x = pad.left + slot * i + (slot - barW) / 2;
      const barH = Math.max(value > 0 ? 3 : 0, plotH * (value / maxVal));
      const y = pad.top + plotH - barH;

      if (value > 0) {
        const bar = svgEl("path", {
          d: roundedTopBar(x, y, barW, barH, Math.min(4, barH)),
          fill: "var(--series-1)",
          class: "week-bar",
          tabindex: "0",
        });
        const dateText = new Date(`${key}T12:00:00`).toLocaleDateString("en-US", {
          weekday: "short", month: "short", day: "numeric",
        });
        const show = () => {
          tooltip.textContent = `${dateText} — ${fmt(value)} kcal`;
          tooltip.hidden = false;
          tooltip.style.left = `${((x + barW / 2) / width) * 100}%`;
        };
        const hide = () => { tooltip.hidden = true; };
        bar.addEventListener("mouseenter", show);
        bar.addEventListener("mouseleave", hide);
        bar.addEventListener("focus", show);
        bar.addEventListener("blur", hide);
        svg.appendChild(bar);
      }

      const weekday = new Date(`${key}T12:00:00`).toLocaleDateString("en-US", { weekday: "narrow" });
      svg.appendChild(
        Object.assign(svgEl("text", {
          x: pad.left + slot * i + slot / 2,
          y: height - 7,
          "text-anchor": "middle",
          class: "week-axis-label",
        }), { textContent: weekday })
      );
    });

    svg.appendChild(
      Object.assign(svgEl("text", {
        x: width - pad.right, y: goalY - 4, "text-anchor": "end", class: "week-goal-label",
      }), { textContent: `goal ${fmt(targets.kcal)}` })
    );

    mount.appendChild(svg);
    mount.appendChild(tooltip);
  }

  function roundedTopBar(x, y, w, h, r) {
    if (h <= r) return `M${x},${y + h} v${-h} h${w} v${h} Z`;
    return [
      `M${x},${y + h}`,
      `v${-(h - r)}`,
      `q0,${-r} ${r},${-r}`,
      `h${w - 2 * r}`,
      `q${r},0 ${r},${r}`,
      `v${h - r}`,
      "Z",
    ].join(" ");
  }

  /* ---------------------------------------------------------------- */
  /* Meal log                                                          */
  /* ---------------------------------------------------------------- */

  function renderLog() {
    const mount = document.getElementById("meal-sections");
    clearNode(mount);
    const key = N.dateKey(viewDate);
    const entries = entriesFor(key);

    for (const meal of MEALS) {
      const mealEntries = entries
        .map((e, index) => ({ entry: e, index }))
        .filter((x) => x.entry.meal === meal);

      const section = el("section", "meal-section");
      const head = el("div", "meal-head");
      head.appendChild(el("h3", "", MEAL_LABELS[meal]));
      const mealKcal = mealEntries.reduce((sum, x) => sum + x.entry.kcal, 0);
      head.appendChild(el("span", "meal-kcal", mealEntries.length ? `${fmt(mealKcal)} kcal` : "—"));
      section.appendChild(head);

      if (mealEntries.length) {
        const list = el("ul", "entry-list");
        for (const { entry, index } of mealEntries) {
          const li = el("li", "entry");
          const info = el("div", "entry-info");
          info.appendChild(el("span", "entry-name", entry.name));
          info.appendChild(
            el("span", "entry-detail",
              `${fmt(entry.grams)} g · ${fmt(entry.kcal)} kcal · P ${fmt(entry.protein)} · C ${fmt(entry.carbs)} · F ${fmt(entry.fat)}`)
          );
          li.appendChild(info);
          const remove = el("button", "entry-remove", "✕");
          remove.type = "button";
          remove.setAttribute("aria-label", `Remove ${entry.name}`);
          remove.addEventListener("click", () => {
            state.log[key].splice(index, 1);
            if (state.log[key].length === 0) delete state.log[key];
            persist();
            render();
          });
          li.appendChild(remove);
          list.appendChild(li);
        }
        section.appendChild(list);
      } else {
        section.appendChild(el("p", "meal-empty", "Nothing logged yet."));
      }
      mount.appendChild(section);
    }
  }

  /* ---------------------------------------------------------------- */
  /* Target overrides                                                   */
  /* ---------------------------------------------------------------- */

  function fillTargetsForm() {
    const o = state.targets || {};
    document.getElementById("target-kcal").value = o.kcal !== undefined ? o.kcal : "";
    document.getElementById("target-protein").value = o.proteinG !== undefined ? o.proteinG : "";
    document.getElementById("target-carbs").value = o.carbsG !== undefined ? o.carbsG : "";
    document.getElementById("target-fat").value = o.fatG !== undefined ? o.fatG : "";
    const recommended = N.dailyTargets(state.profile);
    document.getElementById("target-kcal").placeholder = recommended.kcal;
    document.getElementById("target-protein").placeholder = recommended.proteinG;
    document.getElementById("target-carbs").placeholder = recommended.carbsG;
    document.getElementById("target-fat").placeholder = recommended.fatG;
  }

  function onSaveTargets(event) {
    event.preventDefault();
    state.targets = N.validateTargetOverrides({
      kcal: document.getElementById("target-kcal").value,
      proteinG: document.getElementById("target-protein").value,
      carbsG: document.getElementById("target-carbs").value,
      fatG: document.getElementById("target-fat").value,
    });
    persist();
    document.getElementById("targets-feedback").textContent = state.targets
      ? "Custom targets saved."
      : "Using recommended targets.";
    render();
  }

  function onResetTargets() {
    state.targets = null;
    persist();
    fillTargetsForm();
    document.getElementById("targets-feedback").textContent = "Back to recommended targets.";
    render();
  }

  /* ---------------------------------------------------------------- */
  /* Optional USDA online search                                        */
  /* ---------------------------------------------------------------- */

  const USDA_ENDPOINT = "https://api.nal.usda.gov/fdc/v1/foods/search";

  function fillUsdaForm() {
    document.getElementById("usda-enabled").checked = state.settings.onlineSearch;
    document.getElementById("usda-key").value = state.settings.usdaApiKey;
  }

  function onSaveUsda(event) {
    event.preventDefault();
    const feedback = document.getElementById("usda-feedback");
    const rawKey = document.getElementById("usda-key").value.trim();
    state.settings = N.validateSettings({
      onlineSearch: document.getElementById("usda-enabled").checked,
      usdaApiKey: rawKey,
    });
    persist();
    fillUsdaForm();
    updateBarcodeButton();
    if (!state.settings.onlineSearch) {
      feedback.textContent = "Online lookup is off. The app makes no network requests.";
    } else if (rawKey && !state.settings.usdaApiKey) {
      feedback.textContent =
        "Barcode lookup is on. The USDA key looks invalid (letters/numbers only), so text search stays off.";
    } else if (state.settings.usdaApiKey) {
      feedback.textContent = "Barcode lookup and USDA text search are on. Only barcodes and search words are ever sent.";
    } else {
      feedback.textContent = "Barcode lookup is on. Add a USDA key to also enable online text search.";
    }
  }

  async function searchUsda(query) {
    const params = new URLSearchParams({
      api_key: state.settings.usdaApiKey,
      query,
      pageSize: "10",
      dataType: "Branded,Foundation,SR Legacy",
    });
    const response = await fetch(`${USDA_ENDPOINT}?${params}`, { method: "GET" });
    if (!response.ok) throw new Error(`USDA responded ${response.status}`);
    const data = await response.json();
    const foods = [];
    if (data && Array.isArray(data.foods)) {
      for (const item of data.foods.slice(0, 10)) {
        const mapped = N.validateFood(N.mapUsdaFood(item));
        if (mapped) foods.push(mapped);
      }
    }
    return foods;
  }

  /* ---------------------------------------------------------------- */
  /* Barcode lookup (Open Food Facts)                                   */
  /* ---------------------------------------------------------------- */

  const OFF_ENDPOINT = "https://world.openfoodfacts.org/api/v2/product/";
  let barcodeStream = null;
  let barcodeScanning = false;

  function updateBarcodeButton() {
    document.getElementById("barcode-btn").hidden = !state.settings.onlineSearch;
    if (!state.settings.onlineSearch) closeBarcodePanel();
  }

  async function lookupBarcode(code) {
    const feedback = document.getElementById("barcode-feedback");
    if (!N.BARCODE_RE.test(code)) {
      feedback.textContent = "Enter the 8–14 digit number printed under the barcode.";
      return;
    }
    feedback.textContent = "Looking up…";
    try {
      const response = await fetch(
        `${OFF_ENDPOINT}${encodeURIComponent(code)}.json?fields=product_name,brands,nutriments`
      );
      if (response.status === 404) {
        feedback.textContent = "No product found for that barcode.";
        return;
      }
      if (!response.ok) throw new Error(`OFF responded ${response.status}`);
      const food = N.validateFood(N.mapOffProduct(await response.json()));
      if (!food) {
        feedback.textContent = "Product found but it has no usable nutrition data.";
        return;
      }
      feedback.textContent = "";
      closeBarcodePanel();
      selectFood(food, true); // saved on-device like USDA picks
      announce(`Found ${food.name}.`);
    } catch (err) {
      feedback.textContent = "Lookup failed — check your connection and try again.";
    }
  }

  /* Camera scanning: the native BarcodeDetector API where the browser has
   * it (Android Chrome — fast path), otherwise our own EAN-13/UPC-A decoder
   * in js/barcode.js (iOS Safari and everything else). Frames never leave
   * the device either way. Manual number entry always remains available. */
  function acceptScan(code) {
    document.getElementById("barcode-input").value = code;
    stopBarcodeCamera();
    lookupBarcode(code);
  }

  async function startBarcodeCamera() {
    if (!navigator.mediaDevices || (!("BarcodeDetector" in window) && !window.BarcodeDecoder)) {
      return;
    }
    const video = document.getElementById("barcode-video");
    try {
      barcodeStream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment", width: { ideal: 1280 } },
        audio: false,
      });
    } catch (err) {
      return; // permission denied — manual entry still works
    }
    video.srcObject = barcodeStream;
    video.hidden = false;
    document.getElementById("barcode-hint").hidden = false;
    try {
      await video.play();
    } catch (err) {
      /* panel closed while the camera was still starting */
    }
    if (!barcodeStream) return; // stopped mid-start
    barcodeScanning = true;

    if ("BarcodeDetector" in window) {
      const detector = new window.BarcodeDetector({
        formats: ["ean_13", "ean_8", "upc_a", "upc_e"],
      });
      const scan = async () => {
        if (!barcodeScanning) return;
        try {
          const codes = await detector.detect(video);
          if (codes.length && N.BARCODE_RE.test(codes[0].rawValue)) {
            acceptScan(codes[0].rawValue);
            return;
          }
        } catch (err) {
          /* detector hiccup — keep trying */
        }
        requestAnimationFrame(scan);
      };
      requestAnimationFrame(scan);
      return;
    }

    // JS decoder path: sample ~8 frames/sec, require the same code from two
    // consecutive frames before accepting (checksum already guards each read).
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    let lastCode = null;
    const scan = () => {
      if (!barcodeScanning) return;
      if (video.videoWidth > 0) {
        const width = 800;
        const height = Math.round((video.videoHeight / video.videoWidth) * width);
        canvas.width = width;
        canvas.height = height;
        ctx.drawImage(video, 0, 0, width, height);
        let code = null;
        try {
          code = window.BarcodeDecoder.decodeImageData(ctx.getImageData(0, 0, width, height));
        } catch (err) {
          /* canvas hiccup — keep trying */
        }
        if (code && N.BARCODE_RE.test(code)) {
          if (code === lastCode) {
            acceptScan(code);
            return;
          }
          lastCode = code;
        }
      }
      setTimeout(scan, 125);
    };
    setTimeout(scan, 125);
  }

  function stopBarcodeCamera() {
    barcodeScanning = false;
    if (barcodeStream) {
      for (const track of barcodeStream.getTracks()) track.stop();
      barcodeStream = null;
    }
    const video = document.getElementById("barcode-video");
    video.srcObject = null;
    video.hidden = true;
    document.getElementById("barcode-hint").hidden = true;
  }

  function openBarcodePanel() {
    document.getElementById("barcode-panel").hidden = false;
    document.getElementById("barcode-feedback").textContent = "";
    document.getElementById("barcode-input").focus();
    startBarcodeCamera();
  }

  function closeBarcodePanel() {
    stopBarcodeCamera();
    document.getElementById("barcode-panel").hidden = true;
  }

  /* ---------------------------------------------------------------- */
  /* Weight log                                                         */
  /* ---------------------------------------------------------------- */

  function weightUnitsLabel() {
    return state.profile && state.profile.units === "us" ? "lb" : "kg";
  }

  function onLogWeight(event) {
    event.preventDefault();
    const feedback = document.getElementById("weight-feedback");
    const raw = Number(document.getElementById("weight-input").value);
    const kg = weightUnitsLabel() === "lb" ? N.lbToKg(raw) : raw;
    const rounded = Math.round(kg * 10) / 10;
    if (!Number.isFinite(rounded) || rounded < 30 || rounded > 350) {
      feedback.textContent = "Enter a weight in the normal human range.";
      return;
    }
    state.weights[N.dateKey(new Date())] = rounded;
    state.profile.weightKg = rounded; // keep recommendations current
    persist();
    feedback.textContent = "Weight logged.";
    document.getElementById("weight-input").value = "";
    render();
  }

  /* 30-day weight trend: single line series, direct min/max labels. */
  function renderWeightChart() {
    const mount = document.getElementById("weight-chart");
    clearNode(mount);
    const keys = N.lastNDateKeys(new Date(), 30);
    const points = [];
    keys.forEach((key, i) => {
      if (state.weights[key] !== undefined) points.push({ i, key, kg: state.weights[key] });
    });
    if (points.length === 0) {
      mount.appendChild(el("p", "meal-empty", "No weights logged yet."));
      return;
    }

    const toDisplay = (kg) => (weightUnitsLabel() === "lb" ? N.kgToLb(kg) : kg);
    const values = points.map((p) => toDisplay(p.kg));
    const min = Math.min(...values);
    const max = Math.max(...values);
    const pad = { top: 14, right: 8, bottom: 18, left: 8 };
    const width = 320;
    const height = 120;
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;
    const span = Math.max(max - min, 1); // avoid a flat line filling the plot
    const x = (i) => pad.left + (plotW * i) / 29;
    const y = (v) => pad.top + plotH * (1 - (v - min) / span);

    const svg = svgEl("svg", {
      viewBox: `0 0 ${width} ${height}`,
      class: "week-svg",
      role: "img",
      "aria-label": `Weight over the last 30 days, from ${fmt(values[0])} to ${fmt(values[values.length - 1])} ${weightUnitsLabel()}`,
    });
    svg.appendChild(
      svgEl("line", {
        x1: pad.left, x2: width - pad.right,
        y1: pad.top + plotH, y2: pad.top + plotH,
        stroke: "var(--chart-baseline)", "stroke-width": 1,
      })
    );
    if (points.length > 1) {
      const d = points
        .map((p, idx) => `${idx === 0 ? "M" : "L"}${x(p.i).toFixed(1)},${y(toDisplay(p.kg)).toFixed(1)}`)
        .join(" ");
      svg.appendChild(
        svgEl("path", { d, fill: "none", stroke: "var(--series-1)", "stroke-width": 2, "stroke-linejoin": "round" })
      );
    }
    for (const p of points) {
      svg.appendChild(
        svgEl("circle", {
          cx: x(p.i), cy: y(toDisplay(p.kg)), r: 3.5,
          fill: "var(--series-1)", stroke: "var(--surface)", "stroke-width": 2,
        })
      );
    }
    const last = points[points.length - 1];
    svg.appendChild(
      Object.assign(
        svgEl("text", {
          x: Math.min(x(last.i), width - pad.right - 4),
          y: Math.max(y(toDisplay(last.kg)) - 8, 10),
          "text-anchor": "end",
          class: "week-axis-label",
        }),
        { textContent: `${fmt(toDisplay(last.kg))} ${weightUnitsLabel()}` }
      )
    );
    mount.appendChild(svg);
  }

  /* ---------------------------------------------------------------- */
  /* Add-food form                                                     */
  /* ---------------------------------------------------------------- */

  let searchSelection = null;

  function selectFood(food, fromUsda) {
    searchSelection = food;
    document.getElementById("food-search").value = food.name;
    clearNode(document.getElementById("search-results"));
    document.getElementById("food-grams").focus();
    if (fromUsda) {
      // Keep picked USDA foods on-device so they work offline next time.
      const exists = state.customFoods.some((f) => f.name === food.name);
      if (!exists && state.customFoods.length < 500) {
        state.customFoods.push({
          name: food.name,
          kcal: food.kcal,
          protein: food.protein,
          carbs: food.carbs,
          fat: food.fat,
        });
        persist();
      }
    }
  }

  function resultButton(food, fromUsda) {
    const button = el("button", "search-result");
    button.type = "button";
    button.appendChild(el("span", "search-result-name", food.name));
    button.appendChild(
      el("span", "search-result-kcal", `${fmt(food.kcal)} kcal / 100 g${fromUsda ? " · USDA" : ""}`)
    );
    button.addEventListener("click", () => selectFood(food, fromUsda));
    return button;
  }

  function renderSearchResults(results, query) {
    const mount = document.getElementById("search-results");
    clearNode(mount);
    for (const food of results) mount.appendChild(resultButton(food, false));

    if (state.settings.onlineSearch && state.settings.usdaApiKey && query && query.trim().length >= 2) {
      const online = el("button", "search-result search-online");
      online.type = "button";
      online.appendChild(el("span", "search-result-name", `Search USDA for “${query.trim()}”`));
      online.appendChild(el("span", "search-result-kcal", "online"));
      online.addEventListener("click", async () => {
        online.disabled = true;
        online.firstChild.textContent = "Searching USDA…";
        try {
          const foods = await searchUsda(query.trim());
          online.remove();
          if (!foods.length) {
            mount.appendChild(el("p", "feedback", "No USDA matches found."));
          }
          for (const food of foods) mount.appendChild(resultButton(food, true));
        } catch (err) {
          online.remove();
          mount.appendChild(
            el("p", "feedback", "USDA search failed — check your connection, API key, or rate limit.")
          );
        }
      });
      mount.appendChild(online);
    }
  }

  function onAddEntry(event) {
    event.preventDefault();
    const feedback = document.getElementById("add-feedback");
    feedback.textContent = "";
    if (!searchSelection) {
      feedback.textContent = "Search for a food and pick one from the list first.";
      return;
    }
    const grams = Number(document.getElementById("food-grams").value);
    if (!Number.isFinite(grams) || grams < 1 || grams > 5000) {
      feedback.textContent = "Enter a portion between 1 and 5000 grams.";
      return;
    }
    const mealRadio = document.querySelector('input[name="meal"]:checked');
    const nutrients = N.portionNutrients(searchSelection, grams);
    const key = N.dateKey(viewDate);
    if (!state.log[key]) state.log[key] = [];
    state.log[key].push({
      name: searchSelection.name,
      meal: mealRadio ? mealRadio.value : "snacks",
      grams,
      ...nutrients,
    });
    persist();
    announce(`Added ${searchSelection.name} (${fmt(nutrients.kcal)} kcal).`);
    searchSelection = null;
    document.getElementById("food-search").value = "";
    document.getElementById("food-grams").value = "100";
    clearNode(document.getElementById("search-results"));
    render();
  }

  function onAddCustomFood(event) {
    event.preventDefault();
    const feedback = document.getElementById("custom-feedback");
    const food = N.validateFood({
      name: document.getElementById("custom-name").value,
      kcal: document.getElementById("custom-kcal").value,
      protein: document.getElementById("custom-protein").value,
      carbs: document.getElementById("custom-carbs").value,
      fat: document.getElementById("custom-fat").value,
    });
    if (!food) {
      feedback.textContent =
        "Check the values: name required; kcal 0–900 and macros 0–100 per 100 g.";
      return;
    }
    state.customFoods.push(food);
    persist();
    feedback.textContent = `Saved "${food.name}" to your foods.`;
    event.target.reset();
  }

  /* ---------------------------------------------------------------- */
  /* Export / import / reset                                           */
  /* ---------------------------------------------------------------- */

  function onExport() {
    const blob = new Blob([JSON.stringify(state, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `calorie-tracker-export-${N.dateKey(new Date())}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  function onImportFile(event) {
    const file = event.target.files && event.target.files[0];
    event.target.value = "";
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
      announce("Import failed: file is too large.");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      let imported = null;
      try {
        imported = N.validateImportedState(JSON.parse(String(reader.result)));
      } catch (e) {
        imported = null;
      }
      if (!imported) {
        announce("Import failed: not a valid calorie-tracker export file.");
        return;
      }
      state = imported;
      persist();
      announce("Data imported.");
      fillProfileForm(state.profile);
      fillUsdaForm();
      render();
    };
    reader.readAsText(file);
  }

  function onReset() {
    if (!window.confirm("Delete ALL locally stored data (profile, foods, log)?")) return;
    window.AppStorage.clear();
    state = window.AppStorage.emptyState();
    viewDate = new Date();
    announce("All data deleted.");
    render();
  }

  /* ---------------------------------------------------------------- */
  /* Top-level render                                                  */
  /* ---------------------------------------------------------------- */

  function render() {
    const setup = document.getElementById("setup-view");
    const dashboard = document.getElementById("dashboard-view");
    if (!state.profile || editingProfile) {
      setup.hidden = false;
      dashboard.hidden = true;
      return;
    }
    setup.hidden = true;
    dashboard.hidden = false;

    const targets = N.dailyTargets(state.profile, state.targets);
    const totals = N.dayTotals(entriesFor(N.dateKey(viewDate)));
    renderDateNav();
    renderRing(totals, targets);
    renderMacros(totals, targets);
    renderWeekChart(targets);
    renderLog();
    renderWeightChart();
    fillTargetsForm();
    updateBarcodeButton();
    document.getElementById("weight-log-label").textContent =
      `Today’s weight (${weightUnitsLabel()})`;
  }

  /* ---------------------------------------------------------------- */
  /* Event wiring                                                      */
  /* ---------------------------------------------------------------- */

  function init() {
    document.getElementById("profile-form").addEventListener("submit", onProfileSubmit);
    document.getElementById("add-form").addEventListener("submit", onAddEntry);
    document.getElementById("custom-form").addEventListener("submit", onAddCustomFood);
    document.getElementById("targets-form").addEventListener("submit", onSaveTargets);
    document.getElementById("targets-reset").addEventListener("click", onResetTargets);
    document.getElementById("usda-form").addEventListener("submit", onSaveUsda);
    document.getElementById("export-btn").addEventListener("click", onExport);
    document.getElementById("import-input").addEventListener("change", onImportFile);
    document.getElementById("reset-btn").addEventListener("click", onReset);
    document.getElementById("edit-profile-btn").addEventListener("click", () => {
      editingProfile = true;
      fillProfileForm(state.profile);
      render();
    });
    document.getElementById("profile-units").addEventListener("change", () => {
      applyUnitsToForm(currentUnits());
    });
    document.getElementById("weight-form").addEventListener("submit", onLogWeight);
    document.getElementById("barcode-btn").addEventListener("click", openBarcodePanel);
    document.getElementById("barcode-close").addEventListener("click", closeBarcodePanel);
    document.getElementById("barcode-lookup").addEventListener("click", () => {
      lookupBarcode(document.getElementById("barcode-input").value.trim());
    });
    document.getElementById("barcode-input").addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        lookupBarcode(e.target.value.trim());
      }
    });

    document.getElementById("food-search").addEventListener("input", (e) => {
      searchSelection = null;
      renderSearchResults(searchFoods(e.target.value), e.target.value);
    });

    document.getElementById("date-prev").addEventListener("click", () => {
      viewDate = new Date(viewDate.getFullYear(), viewDate.getMonth(), viewDate.getDate() - 1);
      render();
    });
    document.getElementById("date-next").addEventListener("click", () => {
      viewDate = new Date(viewDate.getFullYear(), viewDate.getMonth(), viewDate.getDate() + 1);
      render();
    });

    document.getElementById("app-version").textContent = `App version ${APP_VERSION}.`;
    fillProfileForm(state.profile);
    fillUsdaForm();
    render();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
