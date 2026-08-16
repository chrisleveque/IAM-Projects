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
2. **Master resume**: copy `profile/master_resume.example.md` to
   `profile/master_resume.md` and paste in your *longest* resume — every role,
   bullet, skill, cert. The AI only selects and rewords from this file; it is
   instructed to never invent facts, so the more that's in here, the better.
3. **Answers**: copy `profile/answers.example.yaml` to `profile/answers.yaml`
   and fill in your contact info, work authorization, salary, etc. These
   pre-fill the repetitive application questions.

   > **Your real `profile/master_resume.md` and `profile/answers.yaml` are
   > gitignored** — they never get committed, even with `git add -A`. Only the
   > `*.example` templates are tracked. Everything with a secret in it (`.env`,
   > `profile/vault.enc`, `profile/.vault.key`, `browser_profile/`,
   > `*.db`) is ignored too.
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

## Autonomous external applying (`auto-apply`)

Jobs that link out to the employer's own ATS can be completed without you, on
the systems that don't require an account:

```bash
jobagent auto-apply              # fills every form, screenshots it, submits NOTHING
jobagent auto-apply --submit     # actually submits
jobagent audit                   # every attempt, with every answer it sent
```

Start with the plain (dry-run) form. It fills each application, saves a
full-page screenshot to `output/<job>/apply/filled.png`, and prints which
questions it answered and which it refused to. Once the answers look right,
re-run with `--submit`.

**Supported:** Greenhouse and Lever (no account needed) and **Workday**
(multi-page, account-gated — see below). iCIMS, Taleo, SmartRecruiters, Ashby,
Workable and BambooHR are *detected* and parked as `blocked` with the ATS
named, so they go through `jobagent manual`.

### Workday accounts and email verification

Workday requires an account per employer tenant. The agent handles this
end-to-end **in `--submit` mode only** (creating an account under your email is
an outward action a dry run won't take):

- It generates a strong password, stores it encrypted in
  `profile/vault.enc` (the key is `profile/.vault.key`; both are gitignored),
  then creates the account. The password is vaulted *before* it's submitted, so
  a crash mid-signup can't strand an account you can't get back into.
- See your accounts any time with `jobagent accounts` (add `--show` for
  passwords). Reused automatically on later Workday jobs at the same tenant.
- If a tenant emails a verification link/code, the agent reads it over IMAP —
  set `JOBAGENT_EMAIL` and `JOBAGENT_EMAIL_APP_PASSWORD` (a Gmail **App
  Password**, not your real one) in `.env`. Without those, a tenant that
  demands verification is parked with that reason. The reader is read-only: it
  searches for the ATS's recent mail and never sends or deletes anything.
- A sign-in with a vaulted account that gets **rejected is parked, not
  retried** — repeated failures could lock your real identity out of that
  tenant. Fix it with the tenant's password reset, then
  `jobagent accounts --delete <host>` and let it re-create, or store the new
  password yourself.

Dry run still works on Workday: with an existing account it signs in and fills
every page up to Review, screenshots each one, and stops. Without an account it
parks (nothing to sign in with yet) — run `--submit` when you're ready to let
it create one.

### What it refuses to do

These are enforced in code, not merely asked of the model:

- **Never submits a form with an unanswered required question.** The job is
  parked as `blocked` naming the question, even in `--submit` mode.
- **Never guesses a legal/compliance answer.** Work authorization,
  sponsorship, salary, criminal history, clearances, drug screening: these come
  from `answers.yaml` or the application is parked. Fill in
  `profile/answers.example.yaml` — `auto-apply` warns upfront which ones are
  still missing, and each one you add converts parked applications into
  completed ones.
- **Never answers demographic self-ID questions.** Where the form offers
  "decline to self-identify" it picks that (truthful, and keeps the form
  moving); otherwise it leaves the question blank.
- **Never works around a CAPTCHA or bot wall.** It detects them and parks.
- **Never invents an option.** If the model's answer isn't one of the real
  choices, the question is parked rather than force-fitted.

Answers it works out are cached in the tracker, so the same question is
answered identically on every later form and costs no extra AI calls.

### Reviewing after the fact

`auto-apply` is unattended, so review happens after submission rather than
before: `jobagent audit` prints each attempt with every question/answer pair it
sent and everything it parked. If something went out wrong you can ask the
employer to withdraw it — which is why the audit log exists.

## When something breaks: `selftest` and `report`

Most failures here are environment-shaped — a Windows file encoding, a stale
install, a Playwright build, an expired credential — and none of them show up
in CI. Two commands turn "something's wrong, here are six screenshots" into one
answer:

```bash
jobagent selftest              # is this machine healthy? (no LinkedIn, nothing submitted)
jobagent selftest --with-ai    # also make one tiny real API call
jobagent report                # bundle everything needed to diagnose, into one file
```

`selftest` exercises the parts that actually break: your profile files (including
UTF-16/BOM encodings), the job tracker, the account vault, document generation
(asserting the borderless 70/30 layout that regressed repeatedly), a real browser
driving a real form end-to-end, and your API key + email credentials. Each check
prints a concrete fix, and one failing check never stops the others.

`report` adds recent application attempts, recent crashes, and the latest ATS
page diagnostics. **Everything is redacted** — emails, phone numbers, API keys,
app passwords and home paths are stripped — so the output is safe to paste.

Crashes are captured automatically: an unhandled error writes a redacted
traceback to `diagnostics/crash-<timestamp>.txt`, so it survives the terminal
scrolling away.

## Honesty guarantee

The tailoring prompt enforces: no invented employers, titles, dates, degrees,
certifications, metrics, or skills. It only reorders, selects, and rewords what
is in `profile/master_resume.md`. Still — proofread `output/` before applying;
you are the last reviewer.

The same rule governs form answers: the agent may only use facts from your
profile and `answers.yaml`, and parks anything it can't support.

## Grab all saved-job links in one click (bookmarklet)

If you prefer never dealing with LinkedIn logins in the agent browser: in your
normal browser, create a bookmark whose URL is the single line below. On
[linkedin.com/my-items/saved-jobs](https://www.linkedin.com/my-items/saved-jobs/),
click the bookmark — it copies every job link on the page to your clipboard.

```
javascript:(function(){var u=[...new Set([...document.querySelectorAll("a[href*='/jobs/view/']")].map(function(a){return a.href.split('?')[0]}))].join('\n');navigator.clipboard.writeText(u).then(function(){alert('Copied '+u.split('\n').length+' job links')},function(){prompt('Press Ctrl+C to copy:',u)})})();
```

Then import them all in one go:

```bash
jobagent add --paste     # paste, then press Enter on an empty line
```

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
