/*
 * app.js — UI wiring and rendering.
 *
 * Security invariant: user- or import-controlled strings only ever reach the
 * DOM through textContent (or attribute setters on values we generated).
 * innerHTML is never used with data. Charts are built with createElementNS.
 */
"use strict";

(function () {
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

  function readProfileForm() {
    return {
      sex: document.getElementById("profile-sex").value,
      age: document.getElementById("profile-age").value,
      heightCm: document.getElementById("profile-height").value,
      weightKg: document.getElementById("profile-weight").value,
      activity: document.getElementById("profile-activity").value,
      goal: document.getElementById("profile-goal").value,
    };
  }

  function fillProfileForm(profile) {
    if (!profile) return;
    document.getElementById("profile-sex").value = profile.sex;
    document.getElementById("profile-age").value = profile.age;
    document.getElementById("profile-height").value = profile.heightCm;
    document.getElementById("profile-weight").value = profile.weightKg;
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
  /* Add-food form                                                     */
  /* ---------------------------------------------------------------- */

  let searchSelection = null;

  function renderSearchResults(results) {
    const mount = document.getElementById("search-results");
    clearNode(mount);
    if (!results.length) return;
    for (const food of results) {
      const button = el("button", "search-result");
      button.type = "button";
      button.appendChild(el("span", "search-result-name", food.name));
      button.appendChild(el("span", "search-result-kcal", `${fmt(food.kcal)} kcal / 100 g`));
      button.addEventListener("click", () => {
        searchSelection = food;
        document.getElementById("food-search").value = food.name;
        clearNode(mount);
        document.getElementById("food-grams").focus();
      });
      mount.appendChild(button);
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

    const targets = N.dailyTargets(state.profile);
    const totals = N.dayTotals(entriesFor(N.dateKey(viewDate)));
    renderDateNav();
    renderRing(totals, targets);
    renderMacros(totals, targets);
    renderWeekChart(targets);
    renderLog();
  }

  /* ---------------------------------------------------------------- */
  /* Event wiring                                                      */
  /* ---------------------------------------------------------------- */

  function init() {
    document.getElementById("profile-form").addEventListener("submit", onProfileSubmit);
    document.getElementById("add-form").addEventListener("submit", onAddEntry);
    document.getElementById("custom-form").addEventListener("submit", onAddCustomFood);
    document.getElementById("export-btn").addEventListener("click", onExport);
    document.getElementById("import-input").addEventListener("change", onImportFile);
    document.getElementById("reset-btn").addEventListener("click", onReset);
    document.getElementById("edit-profile-btn").addEventListener("click", () => {
      editingProfile = true;
      fillProfileForm(state.profile);
      render();
    });

    document.getElementById("food-search").addEventListener("input", (e) => {
      searchSelection = null;
      renderSearchResults(searchFoods(e.target.value));
    });

    document.getElementById("date-prev").addEventListener("click", () => {
      viewDate = new Date(viewDate.getFullYear(), viewDate.getMonth(), viewDate.getDate() - 1);
      render();
    });
    document.getElementById("date-next").addEventListener("click", () => {
      viewDate = new Date(viewDate.getFullYear(), viewDate.getMonth(), viewDate.getDate() + 1);
      render();
    });

    fillProfileForm(state.profile);
    render();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
