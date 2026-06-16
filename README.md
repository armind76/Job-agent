# Job Agent

Autonomous job application agent for systems/C++ engineers. Scrapes job boards, classifies listings by tier, selects the best resume, generates cover letters, and submits applications — all driven by Claude AI.

## Setup

### 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your API key and credentials
```

Required in `.env`:

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `LINKEDIN_EMAIL` / `LINKEDIN_PASSWORD` | LinkedIn login |
| `INDEED_EMAIL` / `INDEED_PASSWORD` | Indeed login (optional) |
| `GLASSDOOR_EMAIL` / `GLASSDOOR_PASSWORD` | Glassdoor login (optional) |
| `USER_FULL_NAME` | Your name (used in forms/cover letters) |
| `USER_EMAIL` | Contact email |
| `USER_PHONE` | Phone number |
| `USER_LOCATION` | e.g. `"New York, NY"` |
| `USER_LINKEDIN_URL` | LinkedIn profile URL |
| `USER_GITHUB_URL` | GitHub profile URL |

### 3. Add resumes

Drop PDF resumes into `data/resumes/`. The AI will select the best one per job.

## Usage

```bash
# Activate venv first
source .venv/bin/activate
```

### Basic commands

```bash
# Scrape jobs from a source and enter interactive review
python -m job_agent --source builtin --limit 5
python -m job_agent --source linkedin --limit 10
python -m job_agent --source indeed --limit 10
python -m job_agent --source glassdoor --limit 10

# Scrape all sources
python -m job_agent --limit 20

# Dry run (scrape + classify, no applications submitted)
python -m job_agent --dry-run --source indeed --limit 3

# Auto-apply without manual review
python -m job_agent --auto --limit 10

# Skip scraping, review already-scraped jobs
python -m job_agent --review-only

# Show DB stats
python -m job_agent --stats
```

### Interactive review keys

When in review mode, press:

| Key | Action |
|---|---|
| `a` | Apply to this job |
| `s` | Skip / reject |
| `A` | Apply to all remaining |
| `v` | View job details |
| `q` | Quit |

## Job Tier System

Jobs are classified into tiers by the AI:

| Tier | Focus |
|---|---|
| **Tier 1** | C++ / low-latency / HFT / trading systems (highest priority) |
| **Tier 2** | Low-level / embedded / compilers / Rust |
| **Tier 3** | Graphics / GPU / simulation / HPC |
| **Tier 4** | General SWE (lowest, still relevant) |

## Project Structure

```
job_agent/
├── main.py               # Entry point
├── ai/
│   ├── client.py         # Claude API client
│   ├── classifier.py     # Job tier classification
│   ├── resume_selector.py
│   └── cover_letter.py
├── scrapers/
│   ├── base.py           # BaseScraper ABC
│   ├── linkedin.py
│   ├── indeed.py
│   ├── glassdoor.py
│   ├── builtin_nyc.py
│   └── ats/
│       ├── greenhouse.py
│       └── lever.py
├── application/
│   ├── applicator.py     # Orchestrator
│   └── form_filler.py    # Claude-driven generic form filler
├── db/
│   ├── models.py
│   └── store.py          # JobStore (SQLite, thread-safe)
└── ui/
    └── cli.py            # Rich interactive UI

config/
├── settings.py           # Pydantic settings
└── job_targets.py        # Keyword taxonomy & search queries

data/
├── jobs.db               # SQLite database (auto-created)
├── resumes/              # Drop PDFs here
└── sessions/             # Playwright browser profiles (auto-created)
```

## Running Tests

```bash
pytest
pytest -v              # verbose
pytest tests/test_db.py  # single file
```

## Notes

- **LinkedIn**: First run opens a visible browser for manual login. Session is saved to `data/sessions/linkedin/` and reused.
- **CAPTCHAs**: LinkedIn may show CAPTCHAs — the terminal will prompt you to solve them manually.
- **Selectors**: Indeed/Glassdoor DOM selectors may need updates if sites change.
- **Generic forms**: `GenericFormFiller` uses Claude to fill unknown ATS forms on a best-effort basis.
