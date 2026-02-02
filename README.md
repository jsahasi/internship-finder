# Underclass Internship Scanner

A production-grade Python application that finds internship opportunities specifically targeted at underclassmen (freshmen and sophomores) and generates tailored application materials.

## Features

- **Multi-LLM Search**: Uses Claude and/or OpenAI to intelligently search for internships
- **Smart Filtering**: Excludes postings for juniors/seniors based on your graduation year
- **Personalized Profile**: Configure your year, target roles, skills, and preferences
- **Auto-Generated Documents**: Creates tailored resumes and cover letters for each match
- **Multi-Source Discovery**: Fetches from Greenhouse, Lever, Ashby ATS platforms
- **Email Digest**: Sends results with PDF attachments via SendGrid or SMTP
- **Deduplication**: SQLite-based state to avoid duplicate notifications

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
# Required: At least one LLM key
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...  # Optional, for broader search

# Email (choose one)
SENDGRID_API_KEY=SG...
# OR
SMTP_HOST=smtp.gmail.com
SMTP_USER=you@gmail.com
SMTP_PASSWORD=app_password
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
ANTHROPIC_API_KEY=sk-ant-...     # Required for Claude
OPENAI_API_KEY=sk-...            # Optional, enables dual-LLM search
SENDGRID_API_KEY=SG...           # Or use SMTP_* variables
```

## How It Works

1. **Profile Loading**: Reads your preferences from `config/seeking.txt`
2. **Resume Extraction**: Extracts text from your PDF resume
3. **Smart Search**: Uses Claude (and OpenAI if available) to find relevant postings
4. **Filtering**: Applies rules based on your year and preferences
5. **Document Generation**: Creates tailored resume and cover letter for each match
6. **Email Delivery**: Sends digest with PDF attachments

## Multi-LLM Search

When both `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` are set:
- Both Claude and GPT-4 search for internships
- Results are deduplicated by URL
- Broader coverage of job postings

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
