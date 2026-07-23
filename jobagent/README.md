# jobagent — LinkedIn + Indeed application copilot

An AI agent pipeline that **scans** LinkedIn and Indeed for jobs, **scores** them
against your master resume, **tailors** a resume + cover letter per job with
Claude, and **pre-fills** the application forms in a real browser — then stops
so **you** review and click Submit.

```
scan  ──►  score  ──►  (review)  ──►  tailor  ──►  apply
browser     Claude      you           Claude       browser + you
```

## ⚠️ Read this first: terms-of-service risk

LinkedIn and Indeed do **not** allow automated access in their terms of
service, and LinkedIn actively detects automation and can restrict or ban
accounts. This tool reduces that risk — it runs a single visible browser with
your real session, uses randomized human-like delays, caps applications per
day, and never clicks Submit itself — but **it does not eliminate it**. Use it
deliberately: keep the daily cap low, don't run scans in a loop, and stop if
you get a warning from either platform. You accept this risk by using the tool.

Two lower-risk ways to use it:
- **Saved-jobs mode**: browse LinkedIn yourself, save jobs, then run the
  pipeline only on your hand-picked list (see "Saved-jobs workflow" below).
- **Prepare-only**: skip `jobagent apply` entirely and use the tailored
  resume/cover-letter files from `output/` to apply manually.

## Requirements

- Python 3.10+
- Google Chrome-compatible environment (Playwright downloads Chromium)
- An [Anthropic API key](https://console.anthropic.com) (used for scoring,
  tailoring, and drafting answers to form questions)
- Optional: LibreOffice, for PDF versions of the resume (otherwise .docx only)

## Setup (once)

```bash
cd jobagent
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
playwright install chromium
```

1. **API key**: create one at [console.anthropic.com](https://console.anthropic.com)
   → *API Keys* → copy `.env.example` to `.env` and paste it in. (New accounts
   need a small credit balance; tailoring one job costs on the order of a cent.)
2. **Master resume**: edit `profile/master_resume.md`. Paste your *longest*
   resume — every role, bullet, skill, cert. The AI only selects and rewords
   from this file; it is instructed to never invent facts, so the more that's
   in here, the better the tailoring.
3. **Answers**: edit `profile/answers.yaml` with your contact info, work
   authorization, salary, etc. These pre-fill the repetitive application
   questions.
4. **Searches**: edit `config.yaml` with your queries, locations, and limits.
5. Check everything: `jobagent doctor`
6. Log in once: `jobagent login` (a browser opens; log in to LinkedIn and
   Indeed yourself, 2FA and all — the session persists in `browser_profile/`,
   which never leaves your machine and is gitignored).

## Daily use

```bash
jobagent scan            # run configured searches (add --saved for LinkedIn saved jobs)
jobagent score           # AI-score each discovered job against your resume, 0-100
jobagent review          # optional: eyeball scores, queue/skip jobs
jobagent tailor          # tailored resume + cover letter per job -> output/<company>-<title>/
jobagent apply           # pre-fills each application; YOU click Submit in the browser
jobagent status          # pipeline overview
```

### Saved-jobs workflow

Jobs imported from your LinkedIn saved list are tagged (shown as ★ in
`jobagent status`), so you can run the whole pipeline on just the jobs you
hand-picked while browsing:

```bash
jobagent scan --saved-only   # import ONLY your LinkedIn saved jobs (skips config searches)
jobagent score
jobagent tailor --saved      # tailor only saved jobs
jobagent apply --saved       # apply only to saved jobs
```

`scan --saved` (without `-only`) runs your configured searches *and* imports
saved jobs; the tag survives re-scans either way.

During `apply`, the agent walks the Easy Apply / Indeed Apply steps, uploads
the tailored resume, and fills questions from `answers.yaml`. Unknown questions
get an AI-drafted answer **shown to you in the terminal first** — accept, edit,
or skip — and confirmed answers are saved back to `answers.yaml` so you're only
asked once. Jobs that link out to an external ATS (Workday, Greenhouse, …) are
left in the tracker with their tailored docs ready for a manual apply.

## Honesty guarantee

The tailoring prompt enforces: no invented employers, titles, dates, degrees,
certifications, metrics, or skills. It only reorders, selects, and rewords what
is in `profile/master_resume.md`. Still — proofread `output/` before applying;
you are the last reviewer.

## When LinkedIn won't let you sign in

If LinkedIn's sign-in page loops or the URL shows
`errorKey=challenge_global_internal_error`, LinkedIn's security challenge is
refusing the automated browser — retyping your password won't help. Import
your session from your normal browser instead:

```bash
jobagent login --linkedin-cookie
```

It walks you through copying the `li_at` cookie from your regular Chrome
(F12 → Application → Cookies → linkedin.com). That value IS your logged-in
session — treat it like a password. It's stored only in the local
`browser_profile/` folder and typically stays valid for months.

## When scraping breaks

LinkedIn and Indeed change their page markup regularly. All selectors live in
one `SELECTORS` block at the top of each file:

- `src/jobagent/scrapers/linkedin.py`, `src/jobagent/scrapers/indeed.py`
- `src/jobagent/apply/linkedin_easy_apply.py`, `src/jobagent/apply/indeed_apply.py`

If a stage stops finding things, update the selectors there (open the site in
the jobagent browser, right-click → Inspect the element that moved).

## Development

```bash
pytest              # unit tests (no browser, no API key needed)
jobagent doctor     # environment sanity check
```

Data lives in `jobagent.db` (SQLite). Statuses: `discovered → scored →
(queued) → tailored → applied`, plus `skipped`. Nothing sensitive is committed:
`.env`, `browser_profile/`, `output/`, and the database are gitignored.
