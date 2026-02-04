# Underclass Internship Scanner

A production-grade Python application that finds internship opportunities specifically targeted at underclassmen (freshmen and sophomores) and generates tailored application materials.

## Features

- **Triple-LLM Search**: Uses Claude, OpenAI, and Grok (X.AI) for maximum coverage
- **Accelerator Discovery**: Auto-discovers job boards from YC portfolio (5,600+ companies)
- **Smart Filtering**: Excludes postings for juniors/seniors, MS/PhD based on your profile
- **URL Validation**: Verifies positions are still open before including them
- **Personalized Profile**: Configure your year, target roles, skills, and preferences
- **Auto-Generated Documents**: Creates tailored resumes (PDF) and cover letters (TXT)
- **Anti-Fabrication**: Strict rules prevent LLMs from exaggerating or inventing content
- **Multi-Source Discovery**: Fetches from Greenhouse, Lever, Ashby ATS platforms
- **Email Digest**: Sends results with attachments (only when matches found)
- **Deduplication**: SQLite-based state prevents duplicate emails
- **Source Tracking**: "Sourced By" column shows which LLM found each posting

## Quick Start

### 1. Install

```bash
git clone https://github.com/jsahasi/internship-finder.git
cd internship-finder
pip install -r requirements.txt
```

### 2. Configure Your Profile

Edit `config/seeking.txt` with your preferences:

```yaml
# Your current year
year: freshman

# Expected graduation
graduation_year: 2029

# Target roles
roles:
- software engineering
- product management
- consulting

# Your skills (for document generation)
skills:
- Python
- JavaScript
- React

# About yourself (for cover letters)
about_me: |
  I'm a passionate CS student eager to apply my skills...
```

### 3. Add Your Resume (Optional)

Place your resume PDF in the `config/` folder with "resume" in the filename:
- `config/my_resume.pdf`
- `config/John_Doe_Resume.pdf`

The scanner will extract text and use it to generate tailored application materials.

### 4. Set Up API Keys

Create a `.env` file from the example:

```bash
cp .env.example .env
```

Add your API keys:

```bash
# LLM Search Providers (at least one required)
ANTHROPIC_API_KEY=sk-ant-...    # Claude - primary search
OPENAI_API_KEY=sk-...           # GPT-4o - additional coverage
XAI_API_KEY=xai-...             # Grok - real-time web search

# Email (choose one)
SENDGRID_API_KEY=SG...
# OR
SMTP_HOST=smtp.gmail.com
SMTP_USER=you@gmail.com
SMTP_PASSWORD=app_password      # Use Gmail App Password
```

### 5. Run

```bash
# Dry run (see results without sending email)
python -m app.main --dry_run

# Full run with email and document generation
python -m app.main

# Skip document generation (faster)
python -m app.main --no_documents
```

## Configuration Files

### `config/seeking.txt` - Your Job Search Profile

```yaml
year: freshman                    # freshman, sophomore, junior, senior
graduation_year: 2029             # Your expected graduation year
roles:                            # Target role types
- software engineering
- product management
industries:                       # Preferred industries
- tech
- fintech
locations:                        # Location preferences
- San Francisco, CA
- Remote
skills:                           # Skills to highlight
- Python
- React
additional_criteria: |            # Plain English requirements
  Looking for strong mentorship programs.
  Interested in AI/ML projects.
about_me: |                       # Used in cover letters
  I'm a passionate student...
```

### `config.yaml` - Application Settings

```yaml
recipients:
  - your.email@example.com

search:
  provider: claude               # claude, google_cse, bing, serpapi
  recency_days: 7

targets:
  ats_companies:
    greenhouse: [google, stripe, airbnb]
    lever: [netflix]
    ashby: [openai]

# Custom function families (add your own!)
functions:
  families:
    DataScience:
      display_name: "Data Science"
      title_patterns: ['\bdata\s+scien']
      boost_keywords: [python, tensorflow]
      target: true
```

### `.env` - API Keys

```bash
ANTHROPIC_API_KEY=sk-ant-...     # Claude search & document generation
OPENAI_API_KEY=sk-...            # Optional, GPT-4o search
XAI_API_KEY=xai-...              # Optional, Grok search
SENDGRID_API_KEY=SG...           # Or use SMTP_* variables
```

### `CLAUDE.md` - Development Lessons

Contains lessons learned during development to prevent repeating mistakes. Updated automatically after runs.

## How It Works

1. **Profile Loading**: Reads your preferences from `config/seeking.txt`
2. **Resume Extraction**: Extracts text from your PDF resume
3. **Smart Search**: Uses Claude (and OpenAI if available) to find relevant postings
4. **Filtering**: Applies rules based on your year and preferences
5. **Document Generation**: Creates tailored resume and cover letter for each match
6. **Email Delivery**: Sends digest with PDF attachments

## Triple-LLM Search

Configure any combination of API keys for broader coverage:

| Provider | API Key | Strengths |
|----------|---------|-----------|
| Claude (Anthropic) | `ANTHROPIC_API_KEY` | Web search, accurate parsing |
| GPT-4o (OpenAI) | `OPENAI_API_KEY` | General search capabilities |
| Grok (X.AI) | `XAI_API_KEY` | Real-time web access |

- All providers search simultaneously when keys are configured
- Results are automatically deduplicated by URL
- "Sourced By" column shows which LLM found each posting
- More providers = better coverage of job postings

## Accelerator Discovery

Automatically discover job boards from startup accelerator portfolios:

```bash
# Discover company job boards from YC portfolio
python -m app.main --discover_accelerators --max_discover 100

# Use discovered boards in your scan
python -m app.main --use_accelerators --dry_run
```

The discovery process:
1. Fetches the Y Combinator company list (5,600+ active companies)
2. Tests each company for Greenhouse, Lever, or Ashby job boards
3. Caches verified boards in `cache/verified_boards_yc.json`
4. Run periodically to discover new companies

Found companies include: Stripe, Airbnb, Gusto, Amplitude, HackerRank, and many more.

## CLI Options

| Flag | Description |
|------|-------------|
| `--config PATH` | Path to config YAML (default: config.yaml) |
| `--profile_dir PATH` | Directory with seeking.txt and resume (default: config) |
| `--dry_run` | Print results without sending email |
| `--no_documents` | Skip generating tailored resumes/cover letters |
| `--force` | Ignore deduplication, reprocess all |
| `--max_results N` | Limit postings to process |
| `--log_level LEVEL` | DEBUG, INFO, WARNING, ERROR |
| `--discover_accelerators` | Discover job boards from YC portfolio |
| `--use_accelerators` | Include discovered accelerator boards in scan |
| `--max_discover N` | Max companies to check during discovery (default: 50) |

## Email Output

The email digest includes:
- **HTML Report**: Formatted table of matching internships
- **CSV Attachment**: All postings in spreadsheet format
- **PDF Attachments**: Tailored resume and cover letter for each match

## Project Structure

```
internship-finder/
├── config/                      # User profile directory
│   ├── seeking.txt              # Your job search preferences
│   └── *resume*.pdf             # Your resume (optional)
├── app/
│   ├── main.py                  # CLI entry point
│   ├── config.py                # Configuration loading
│   ├── profile/                 # Profile & document generation
│   │   ├── seeker.py            # Parse seeking.txt
│   │   └── documents.py         # Resume/cover letter generation
│   ├── sources/                 # Job fetchers
│   │   ├── claude_search.py     # Claude-powered search
│   │   ├── openai_search.py     # OpenAI-powered search
│   │   ├── grok_search.py       # Grok (X.AI) search
│   │   ├── accelerators.py      # YC portfolio scraper
│   │   ├── greenhouse.py        # Greenhouse ATS
│   │   ├── lever.py             # Lever ATS
│   │   └── ashby.py             # Ashby ATS
│   ├── filtering/               # Filtering engine
│   ├── llm/                     # LLM classification
│   ├── storage/                 # SQLite deduplication
│   └── reporting/               # Email & rendering
├── config.yaml                  # Application config
├── config.example.yaml          # Example config
├── .env                         # API keys (create from .env.example)
└── requirements.txt
```

## Docker

```bash
# Build and run
docker compose up --build

# Run with custom profile directory
docker compose run -v ./my_profile:/app/config scanner
```

## Testing

```bash
pytest tests/ -v
```

## License

MIT
