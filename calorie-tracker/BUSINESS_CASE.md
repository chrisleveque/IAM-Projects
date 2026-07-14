# Business Case: A Low-Cost Calorie-Tracking App

*Prepared 2026-07-12. Figures are estimates for planning, not financial advice.*

## 1. The opportunity

- **The market consolidated.** MyFitnessPal acquired Cal AI in March 2026, so
  the two best-known trackers share an owner. Consolidation usually means
  higher prices and slower innovation — good conditions for a challenger.
- **Incumbent pricing (2026):** MyFitnessPal Premium ≈ $79.99/yr, Premium+ ≈
  $99.99/yr; Cal AI ≈ $29.99/yr (with aggressive paywall A/B tests, e.g.
  $2.99/wk variants).
- **The wedge:** an honest, cheap (or free) tracker with no paywall tricks,
  strong privacy (data stays on-device), and the two features people actually
  pay for: a big food database and effortless logging.
- **Proof it's possible:** Cal AI itself was built by a tiny team and won via
  short-form video marketing, not superior technology.

## 2. What already exists (this repo, $0 spent)

Web/PWA app installable on iOS/Android: personalized calorie targets
(Mifflin–St Jeor), body-weight-anchored macros with manual override, US/metric
units, 285-food offline database, opt-in USDA branded-food search (free
government API), 7-day trends, JSON export/import, zero-network privacy
architecture, full test suite and CI.

## 3. Cost model

### One-time / annual fixed costs

| Item | Cost |
|---|---|
| Apple Developer Program (App Store) | $99/yr |
| Google Play developer account | $25 once |
| Domain + static hosting (Pages/Netlify/Cloudflare) | $0–30/yr |
| Native wrapper (Capacitor) build effort | ~0 cash, days of work |
| LLC + basic terms/privacy policy (optional at start) | $200–1,000 |

### Variable costs (the reason competitors charge)

| Item | Driver | Estimate |
|---|---|---|
| AI photo-scan (vision model API) | per scan | ~$0.002–0.02/scan; a daily scanner ≈ $0.5–2/mo |
| Barcode/branded food data | USDA + Open Food Facts are free; Nutritionix/FatSecret licenses | $0 to $1k+/mo |
| Accounts + sync backend | per active user | ~$0.01–0.05/user/mo at small scale (serverless) |
| Support, moderation, compliance | users | grows with scale |

### Scenario totals

| Scenario | Year-1 cash |
|---|---|
| Keep it a free PWA (today's path) | ≈ $0–150 |
| Solo dev, App Store presence, no AI scan | ≈ $500–2,000 |
| Solo dev + AI photo scanning (usage-capped free tier) | ≈ $2,000–10,000 |
| Contracted team building native iOS+Android+backend | $50,000–200,000 |
| Funded push to take real market share (mostly marketing) | $100,000–$1M+ |

## 4. Revenue options that stay "cheap and honest"

1. **Free core + $9.99–14.99/yr Plus** (AI scans, sync). Undercuts Cal AI ~2×
   and MyFitnessPal ~6× while covering variable costs with margin.
2. **Bring-your-own-API-key** free tier: power users pay their own AI costs;
   you pay nothing for them.
3. **One-time purchase** ($15–20 lifetime) — simple message, no
   subscription fatigue; riskier long-term because AI costs recur.
4. Avoid ads: they destroy the privacy story, which is the differentiator.

## 5. Feature-parity roadmap

| Phase | Features | Cost driver |
|---|---|---|
| ✅ Now | targets, macros, logging, 285 foods, USDA search, offline PWA | none |
| Next | barcode scanning (camera + Open Food Facts), recipes/meals, weight-trend log, streaks | dev time only |
| Then | native wrapper via Capacitor → App Store / Play listing | $99+$25 fees |
| Later | AI photo scanning (needs a small backend proxy to hold the API key), optional encrypted sync | first real recurring costs |
| Scale | social/coach features, integrations (HealthKit/Google Fit), marketing | marketing budget |

## 6. Honest risks

- **Distribution is the moat, not code.** Incumbents spend heavily on
  acquisition; a superior free app with no marketing gets ~0 users. Budget for
  short-form video content or accept organic/word-of-mouth pace.
- **Food-database quality** is MyFitnessPal's real asset; USDA + Open Food
  Facts close much of the gap for US groceries but crowd-sourced accuracy work
  never ends.
- **"Free forever" + AI scanning don't mix** without a sponsor for the
  inference bill; pick a sustainable model before launching photo features.
- **Health-data trust:** publishing a privacy-first tracker means keeping the
  zero-tracking promise as the app grows — one analytics SDK breaks the pitch.

## 7. Recommendation

Ship the current PWA to friends/family, iterate on logging speed (barcode
next), and defer paid AI features until there's a small but real user base.
Total exposure until then: under $200. Decide on the App Store step
($99/yr + Capacitor work) once weekly active users, not features, justify it.
