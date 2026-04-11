# Autonomous Job Application Agent

A Python-based agent that scrapes job listings from **LinkedIn**, **Indeed**, and **Naukri.com**, analyses them against your resume, tailors your resume per-JD for maximum ATS score, and logs everything for human review.

## Architecture

```
main.py                       ← CLI entry point
config.yaml                   ← Your profile, search criteria, thresholds
agent/
├── orchestrator.py            ← Pipeline controller (scrape → analyse → tailor → log)
├── models.py                  ← Shared data models
├── config_loader.py           ← YAML config loading + validation
├── scrapers/
│   ├── base.py                ← Anti-detection headers, throttling, browser setup
│   ├── linkedin_scraper.py    ← LinkedIn public job search
│   ├── indeed_scraper.py      ← Indeed public job search
│   └── naukri_scraper.py      ← Naukri.com job search (India)
├── analysis/
│   ├── keyword_extractor.py   ← Categorised keyword extraction (tech/soft/certs)
│   └── ats_analyzer.py        ← Weighted ATS scoring engine
├── resume/
│   └── modifier.py            ← Resume tailoring (no hallucination guarantee)
├── safety/
│   ├── dedup.py               ← JSON-based duplicate application guard
│   └── rate_limiter.py        ← Per-run application cap
└── logging_system/
    └── audit_logger.py        ← CSV + JSON + Markdown audit trail
```

## Supported Platforms

| Platform | Region | Login Required |
|----------|--------|---------------|
| LinkedIn | Global | No (public search) |
| Indeed | Global | No |
| Naukri.com | India | No (public search) |

## Pipeline Flow

```
┌─────────────┐     ┌─────────────┐     ┌──────────────┐
│  Scrape Jobs │────▶│  ATS Analyse│────▶│ Tailor Resume│
│ (Playwright) │     │  (Keywords) │     │  (Markdown)  │
└─────────────┘     └─────────────┘     └──────┬───────┘
                                               │
                                    ┌──────────▼──────────┐
                                    │  Score >= 90%?       │
                                    │  YES → Log & Save    │
                                    │  NO  → Re-iterate    │
                                    │        (max 3x)      │
                                    └──────────┬──────────┘
                                               │
                                    ┌──────────▼──────────┐
                                    │  Audit Log (CSV/JSON)│
                                    │  + Run Summary (MD)  │
                                    └─────────────────────┘
```

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure

Edit `config.yaml` with your details:

```yaml
profile:
  job_title: "Software Test Engineer"
  location: "Pune, India"
  master_resume_path: "data/resumes/master_resume.md"

scraping:
  platforms:
    - linkedin
    - indeed
    - naukri          # Naukri.com support
```

### 3. Edit your master resume

Replace the sample at `data/resumes/master_resume.md` with your own.

### 4. Run

```bash
# Full run (all platforms)
python main.py

# Dry run (scrape + score only, nothing logged)
python main.py --dry-run

# Debug logging
python main.py --verbose
```

## Automation

### GitHub Actions (recommended)

The workflow at `.github/workflows/job_agent.yml` runs daily at 08:00 UTC. To enable:
1. Push this repo to GitHub
2. Ensure GitHub Actions is enabled
3. The workflow will also commit the dedup database back to the repo

You can trigger it manually from the **Actions** tab.

## Output & Logs

After each run, check:

| File | Location | Description |
|------|----------|-------------|
| Run Summary | `output/run_summary_*.md` | Table of all jobs processed with ATS scores |
| Application CSV | `data/logs/applications_*.csv` | Spreadsheet-friendly application log |
| Detail JSON | `data/logs/detail_*.json` | Per-job ATS breakdown (matches/gaps) |
| Tailored Resumes | `output/resume_*.md` | Each job-specific resume version |
| Dedup Database | `data/logs/applied_jobs.json` | Prevents duplicate applications |
| Agent Log | `data/logs/agent.log` | Full execution log |

## Safety Features

- **Deduplication:** SHA-256 UIDs prevent applying to the same job twice across runs
- **Rate Limiting:** Configurable cap per run (default: 10)
- **Anti-Detection:** Rotating user agents, realistic browser headers, randomised delays
- **Resource Blocking:** Images/fonts blocked to reduce scraper footprint
- **No Hallucination:** Resume modifier only surfaces skills already in your master resume

## Anti-Hallucination Guarantee

The resume modifier follows strict rules:
1. It **never invents** roles, companies, dates, or metrics
2. Missing JD keywords are only added to the resume if they **already exist somewhere in the master resume**
3. Bullet points are **re-ordered** by relevance, not fabricated
4. The Professional Summary may add a "key competencies" line, but only with skills you actually have
