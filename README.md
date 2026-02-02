# Underclass Internship Scanner

A production-grade Python application that finds internship opportunities specifically targeted at underclassmen (freshmen and sophomores) in Software Engineering, Product Management, Consulting, and Investment Banking.

## Features

- **Multi-source discovery**: Fetches from Greenhouse, Lever, Ashby ATS platforms + search APIs
- **Smart filtering**: Excludes postings for juniors/seniors (Class of 2027/2028)
- **Underclass targeting**: Only includes postings with explicit freshman/sophomore signals
- **LLM classification**: Uses Claude for role categorization and summary generation
- **Deduplication**: SQLite-based state to avoid emailing duplicate postings
- **Email digest**: HTML-formatted reports via SendGrid or SMTP

## Quick Start

### 1. Clone and Install

```bash
git clone <repo-url>
cd internship-finder
pip install -r requirements.txt
```

### 2. Configure

```bash
# Copy example configs
cp config.example.yaml config.yaml
cp .env.example .env

# Edit config.yaml with your target companies and recipients
# Edit .env with your API keys
```

### 3. Run

```bash
# Dry run (print results, no email)
python -m app.main --config config.yaml --dry_run

# Full run with email
python -m app.main --config config.yaml

# Force reprocess (ignore deduplication)
python -m app.main --config config.yaml --force
```

## Configuration

### config.yaml

```yaml
recipients:
  - your.email@example.com

search:
  provider: google_cse  # google_cse, bing, or serpapi
  recency_days: 7

targets:
  ats_companies:
    greenhouse:
      - google
      - stripe
      - airbnb
    lever:
      - netflix
    ashby:
      - openai
```

### Environment Variables (.env)

```bash
# Search API (Google CSE recommended - 100 free queries/day)
GOOGLE_CSE_API_KEY=your_key
GOOGLE_CSE_CX=your_cx_id

# LLM (for classification)
ANTHROPIC_API_KEY=your_key

# Email (SendGrid or SMTP)
SENDGRID_API_KEY=your_key
# OR
SMTP_HOST=smtp.gmail.com
SMTP_USER=your@email.com
SMTP_PASSWORD=app_password
```

## Filtering Rules

### Hard Exclusions
- Contains "2027" or "2028" (current junior/senior graduation years)
- Contains: junior, senior, penultimate, rising senior, final year, upperclassmen
- Post date > 7 days ago or missing

### Required for Inclusion
- Contains underclass signal: freshman, sophomore, first-year, second-year, underclassmen, discovery, pre-internship, early insight
- Role is: Software Engineering, Product Management, Consulting, or Investment Banking

## Target Companies

The scanner fetches from ATS platforms using their public APIs:

| ATS | API Format | Example |
|-----|------------|---------|
| Greenhouse | `boards-api.greenhouse.io/v1/boards/{company}/jobs` | google, stripe |
| Lever | `api.lever.co/v0/postings/{company}?mode=json` | netflix |
| Ashby | `jobs.ashbyhq.com/{company}` (HTML) | openai |

Find company slugs by visiting their careers pages.

## Docker

```bash
# Build and run
docker compose up --build

# Run tests
docker compose --profile test up test
```

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_rules.py -v
```

## Project Structure

```
app/
├── main.py              # CLI entry point
├── config.py            # Configuration loading
├── logging_config.py    # Logging setup
├── sources/             # Data fetchers
│   ├── greenhouse.py    # Greenhouse ATS adapter
│   ├── lever.py         # Lever ATS adapter
│   ├── ashby.py         # Ashby ATS adapter
│   └── search_provider.py # Search API integrations
├── extract/             # Data normalization
│   ├── normalize.py     # Posting data model
│   ├── dates.py         # Date parsing
│   └── canonical.py     # URL canonicalization
├── filtering/           # Filtering engine
│   ├── rules.py         # Exclusion/inclusion rules
│   └── taxonomy.py      # Role classification
├── llm/                 # Claude integration
│   ├── claude_client.py # API client
│   ├── prompts.py       # Prompt templates
│   └── schema.py        # Response validation
├── storage/             # Persistence
│   └── state.py         # SQLite deduplication
└── reporting/           # Output generation
    ├── render.py        # HTML/text rendering
    └── emailer.py       # Email delivery
```

## CLI Options

| Flag | Description |
|------|-------------|
| `--config PATH` | Path to config YAML (default: config.yaml) |
| `--dry_run` | Print results without sending email |
| `--force` | Ignore deduplication, process all |
| `--max_results N` | Limit postings to process |
| `--log_level LEVEL` | DEBUG, INFO, WARNING, ERROR |

## Output

### Included Postings
```
Company | Role | Function | Location | Posted | Evidence | Why Fits | URL
```

### Near Misses
Top 10 excluded postings with reasons (e.g., "Contains 2027", "No underclass signal")

## License

MIT
