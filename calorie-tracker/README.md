# Calorie Tracker

A **free**, private, offline-capable calorie and macro tracker that runs
entirely in your browser. No account, no server, no ads, no tracking — your
data never leaves your device.

This is an independent open-source project. It is **not affiliated with,
endorsed by, or derived from any commercial nutrition app**. All code is
original and the nutrition data is derived from the USDA FoodData Central
public-domain dataset.

## Features

- **Personal daily goal** — calorie target computed with the Mifflin–St Jeor
  equation from your age, height, weight, activity level, and goal
  (lose / maintain / gain), with a built-in safety floor.
- **Macro targets** — protein / carbs / fat goals (30 / 40 / 30 split) with
  progress bars.
- **Food logging** — search 55+ built-in foods (per-100 g values from USDA
  data), log portions in grams to breakfast, lunch, dinner, or snacks.
- **Custom foods** — add your own foods with per-100 g nutrition values.
- **Progress views** — calorie ring, macro bars, and a 7-day history chart
  with your goal line.
- **Day navigation** — browse and edit past days.
- **Your data, portable** — export/import everything as JSON; delete all data
  with one button.
- **Accessible** — keyboard-navigable chart bars, ARIA labels and live
  regions, light and dark themes, colorblind-safe palette.

## Running it

It's a static site — no build step, no dependencies.

```bash
cd calorie-tracker
python3 -m http.server 8000
# then open http://localhost:8000
```

Or deploy the folder to any static host (GitHub Pages works out of the box).
Opening `index.html` directly from disk also works in most browsers.

## Running the tests

```bash
cd calorie-tracker
node tests/nutrition.test.js
```

26 unit tests cover the calorie/macro math, portion scaling, date handling,
input validation, and the hardened JSON-import validator.

## Privacy & security

- All data is stored in `localStorage` in your browser; the app makes **zero
  network requests** (enforced by a strict Content-Security-Policy).
- Everything read from storage or imported from a file is treated as
  untrusted and passes through a strict validator.
- User text only ever reaches the page via `textContent`, never `innerHTML`,
  so injected HTML/scripts render as inert text.

See [SECURITY_REVIEW.md](SECURITY_REVIEW.md) for the full review and test
report.

## Disclaimer

Calorie targets and nutrition figures are general estimates for healthy
adults, not medical or dietary advice. Consult a professional before making
significant dietary changes.

## License

MIT — see [LICENSE](LICENSE).
