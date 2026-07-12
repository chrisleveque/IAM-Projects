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
  (lose / maintain / gain), with a built-in safety floor. US (lb, ft/in) and
  metric units.
- **Smart macro targets** — protein anchored to your body weight and goal
  (2.0 g/kg cutting, 1.6 maintaining, 1.8 gaining), a fat floor, carbs from
  the remainder — plus manual override of any target.
- **Food logging** — search 285 built-in foods (per-100 g values from USDA
  data), log portions in grams to breakfast, lunch, dinner, or snacks.
- **Optional USDA online search** — off by default; enable it with a free
  api.data.gov key to search hundreds of thousands of branded grocery
  products. Only your search words are sent — never your profile or log.
  Picked foods are saved on-device for offline reuse.
- **Barcode lookup** — with online lookup enabled, scan a product barcode
  with the camera on any platform: the native BarcodeDetector API where
  available (Android Chrome), or the app's own built-in EAN-13/UPC-A decoder
  (`js/barcode.js`) on iOS Safari and elsewhere. Camera frames are processed
  entirely on-device; only the decoded barcode number is sent to Open Food
  Facts. Manual number entry always remains available.
- **Weight trend** — log your weight (lb or kg) and see a 30-day trend chart;
  logging also updates your profile so recommendations stay current.
- **Custom foods** — add your own foods with per-100 g nutrition values.
- **Progress views** — calorie ring, macro bars, and a 7-day history chart
  with your goal line.
- **Day navigation** — browse and edit past days.
- **Your data, portable** — export/import everything as JSON; delete all data
  with one button.
- **Accessible** — keyboard-navigable chart bars, ARIA labels and live
  regions, light and dark themes, colorblind-safe palette.

## Installing on iPhone / iPad (PWA)

The app is a Progressive Web App: once it's hosted over HTTPS you can
install it on iOS like a native app — free, no App Store or Mac required.

1. **Host it.** This repo ships a GitHub Actions workflow
   (`.github/workflows/deploy-pages.yml`) that runs the tests and publishes
   the app to GitHub Pages on every push. In the repo go to
   **Settings → Pages** and set **Source: GitHub Actions** (one time), then
   the site appears at `https://<user>.github.io/<repo>/`.
2. **Open that URL in Safari** on your iPhone.
3. Tap the **Share** button → **Add to Home Screen** → **Add**.

You now have a full-screen app with its own icon that works offline (a
service worker caches the app shell) and keeps all data on the device.

## Running it locally

It's a static site — no build step, no dependencies.

```bash
cd calorie-tracker
python3 -m http.server 8000
# then open http://localhost:8000
```

Or deploy the folder to any static host. Opening `index.html` directly from
disk also works in most browsers (without the offline service worker, which
requires HTTPS or localhost).

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
