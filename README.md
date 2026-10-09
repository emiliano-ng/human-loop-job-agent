# Job Agent: search & tailor, human applies

A tool that finds relevant job postings and drafts a tailored resume for
each one, but **never applies on your behalf**. You review, you click
apply. That line is intentional, not a missing feature.

## Why not full auto-apply?

1. **Terms of Service.** LinkedIn, Indeed, and most job boards explicitly
   prohibit automated scraping/applying. This tool only pulls from
   public, documented sources: Greenhouse, Lever, and Ashby's public job
   board APIs (the kind companies expose on purpose for their own careers
   pages), plus community-maintained GitHub repos of postings (like
   SimplifyJobs' internship/new-grad trackers) via the public raw GitHub
   content API. Workday and other JS-rendered, no-public-API boards aren't
   scraped; use `manual` for those (see below).
2. **ATS bot detection.** Workday, Greenhouse, etc. increasingly flag
   automated submissions. Getting auto-flagged as spam is worse than not
   applying.
3. **Quality.** A resume an LLM freely rewrites per job can quietly drift
   into claims that aren't quite true. This tool refuses to let that
   happen structurally (see "How fabrication is prevented" below), and a
   human still reviews before anything is sent.

## How fabrication is prevented (the important part)

Everything the system is allowed to say about you lives in
**`data/profile.json`**: your real skills and real projects, each with a
stable ID and the *exact* bullet text you've already written and are happy
to stand behind.

The LLM's job is narrow: given a posting, decide *which* of those existing
IDs are relevant and how to order/select them, plus write a short, honest
rationale. It is never asked to invent new resume prose or new claims. Its
output passes through **`app/validate.py`**, which strips any skill/project
ID that doesn't exist in `profile.json` before anything reaches a resume
draft. Run `python -m app.validate` to see this self-test in action; it
deliberately feeds the validator a fabricated skill and project and
confirms both get rejected.

There's also a deterministic, non-LLM disqualifier pass
(`check_hard_disqualifiers` in `app/scoring.py`, rules defined in your own
`profile.json`) that regex-matches for red flags like ITAR/export-control
language, "no immigration sponsorship," citizenship/clearance requirements,
graduate-degree requirements, and high years-of-experience thresholds, so
these get caught even if the LLM misses them.

Separately, `app/github_source.py` hard-*excludes* (not just flags)
postings located in a configurable list of countries, and postings that
require U.S. citizenship or offer no sponsorship, before they're even
scored, both via the tracker's own legend emoji and via a text regex
safety net.

## Setup

```bash
git clone https://github.com/emiliano-ng/human-loop-job-agent
cd human-loop-job-agent
python -m venv venv
source venv/bin/activate          # Windows: .\venv\Scripts\Activate.ps1
pip install -r requirements.txt

cp data/profile.example.json data/profile.json
cp data/companies.example.json data/companies.json
cp .env.example .env
```

Then:
1. Edit **`data/profile.json`** with your real name, contact info, skills,
   projects, and experience; see the `_readme` field inside it and inside
   `profile.example.json` for the schema.
2. Edit **`data/companies.json`** with the companies/job-boards you want
   scanned; see `companies.example.json`'s `_readme` field for the format
   and how to find a company's slug.
3. By default this uses a local [Ollama](https://ollama.com) model (free,
   unlimited, no API key):
   ```bash
   ollama pull llama3.1:8b
   ```
   To use Groq, OpenAI, or another OpenAI-compatible provider instead,
   edit `.env`; see `app/llm_client.py`'s docstring for ready-to-paste
   configs. Only three env vars change; nothing else in the code does.
4. (Optional, for PDF export) Install
   [LibreOffice](https://www.libreoffice.org/) so `.docx` drafts also get
   converted to `.pdf` automatically. Without it, you still get the
   `.docx`; just open it in Word and use Save As.

> **Privacy:** `data/profile.json`, `data/companies.json`, `.env`, the SQLite
> cache and `drafts/` hold your personal data and are all gitignored. Never
> use "Upload files" on GitHub's web UI with a folder that contains them (that
> bypasses `.gitignore`). Before your first commit, run `git status` and
> `git ls-files` and confirm none of them appear.

## Usage

```bash
# Fetch + score every configured posting, draft resumes for anything scoring >= 60
python -m app.main scan --min-score 60

# Quick test run against just the first 5 postings (skips the rest, useful while tuning)
python -m app.main scan --min-score 60 --limit 5

# Only internships, or only new-grad roles
python -m app.main scan --level internship
python -m app.main scan --level new_grad

# Turn off career-level filtering entirely (includes senior/staff/principal
# titles too, for whenever that becomes relevant)
python -m app.main scan --level all

# Re-generate a draft for something already scanned/cached, by URL
python -m app.main draft "https://boards.greenhouse.io/apptronik/jobs/12345"

# Paste in a posting found outside your configured sources (e.g. a
# Workday-based company, or one you found on LinkedIn) and score + draft it
# regardless of score, since you already decided it's worth a look
python -m app.main manual
```

`scan` prints each new posting with its fit score, a plain-language
rationale, any hard-disqualifier flags, and the URL as it's scored, and
skips anything already cached from a previous run with an unchanged
description (SQLite-backed, `job_agent_cache.db`, gitignored). For
anything at or above `--min-score`, it writes a per-posting folder under
`drafts/<company>_<title>/` containing:

- `<your_name>_CV_<Company>_<Title>.docx`: the tailored resume
- `<your_name>_CV_<Company>_<Title>.pdf`: same, converted (if LibreOffice
  is installed)
- `info.txt`: the posting URL, score, rationale, and any flags, so you
  don't have to dig through the terminal output later

Before scoring, postings are cheaply pre-filtered (no LLM call spent) to
drop obviously irrelevant titles (sales, recruiting, HR, non-engineering
leadership, etc.), excluded-location postings, and anything outside
`--level`'s career-stage filter; see `app/scoring.py`'s
`is_obviously_irrelevant`, `looks_technical`, `is_excluded_location`, and
`classify_level` if you want to adjust those for your own situation.

### `--level`: internship vs. new grad vs. senior

Every posting's title is classified into `internship`, `new_grad`,
`senior`, or `unspecified` (no level keyword found at all, common at
smaller companies, treated as open to entry-level by default). `--level`
accepts either a preset (`entry` [default], `internship`, `new_grad`,
`senior`, `all`) or your own comma-separated list of those four bucket
names, e.g. `--level internship,unspecified`. `entry` is `internship` +
`new_grad` + `unspecified`, i.e. everything except explicitly
senior-leveled titles, which is this tool's original default behavior.
`--level all` turns level filtering off completely, which is the hook for
adding other career stages later (e.g. actually applying to senior roles
down the line) without touching any code.

## Adding more sources

- **Greenhouse / Lever / Ashby**: add an entry with the company's slug to
  `data/companies.json`; see `companies.example.json`'s `_readme`.
- **GitHub-hosted posting trackers** (like SimplifyJobs' repos): add an
  entry under `github_job_lists` in `companies.json`.
- **Anything else** (Workday-based companies, LinkedIn/Indeed postings you
  found yourself): use `python -m app.main manual`; this is also the
  right call for scraping-prohibited sites, since this tool deliberately
  never automates against them.

## Data sources and responsible use

- Posting data comes from the companies' own public job board APIs (Greenhouse,
  Lever, Ashby) and from community lists on GitHub such as
  [SimplifyJobs/Summer2026-Internships](https://github.com/SimplifyJobs/Summer2026-Internships)
  and [New-Grad-Positions](https://github.com/SimplifyJobs/New-Grad-Positions),
  maintained by Simplify and the Pitt Computer Science Club. Credit for those
  lists belongs to their maintainers.
- This repo contains no copy of that data. Lists are downloaded when you scan
  and kept in a local, gitignored cache. The postings belong to the companies
  that publish them, and the MIT license covers this project's code only.
- All requests go through a shared HTTP client (`app/net.py`) that sends a
  User-Agent, waits between requests, retries 429 and 5xx responses with
  backoff (honoring `Retry-After`), and reuses the local copy of a GitHub list
  when the server reports it unchanged (ETag).
- Tune it with `JOB_AGENT_REQUEST_DELAY` (seconds between requests, default
  0.5) and `JOB_AGENT_USER_AGENT` in `.env`. If you scan many boards, set a
  User-Agent with your contact info and read each provider's terms first.
- Do not commit cached listings or screenshots that show real postings.

## Project layout

```
app/
  ingest.py        fetch from Greenhouse/Lever/Ashby (data/companies.json-driven)
  github_source.py fetch + parse GitHub-hosted posting tracker tables
  net.py           shared HTTP client: User-Agent, spacing, retries
  scoring.py        LLM scoring + deterministic disqualifier checks + pre-filters
  validate.py       the only place allowed to decide a skill/project claim is real
  llm_client.py     provider-agnostic OpenAI-compatible chat client
  docx_export.py    builds the ATS-friendly .docx and converts it to .pdf
  cache.py          SQLite cache so re-running `scan` doesn't re-score unchanged postings
  main.py           CLI (scan / draft / manual)
data/
  profile.json          your real data (gitignored)
  profile.example.json  template to copy from
  companies.json         your real scan list (gitignored)
  companies.example.json template to copy from
```

## License

MIT, see LICENSE. Point it at your own `profile.json` and `companies.json`
and it's yours.
