# Claude Code Lessons Learned

This document captures lessons learned while developing and maintaining the internship-finder project to avoid repeating mistakes.

## Deduplication and State Management

### Don't Use --force for Daily Runs
- The `--force` flag bypasses deduplication entirely, causing the same internships to be emailed repeatedly
- Only use `--force` for testing or when you explicitly want to reprocess all postings
- For scheduled daily runs, the batch file should NOT include `--force`

### Track Emailed vs Seen Separately
- `postings_seen` table tracks when postings were first/last seen
- `emailed_at` column tracks when a posting was actually emailed to the user
- Must filter by `emailed_at IS NULL` to avoid re-sending the same postings
- A posting can be "seen" (for dedup) but not yet "emailed" (if run was dry-run)

### Always Filter Already-Emailed (Even with --force)
- The `--force` flag should only skip "seen" deduplication
- Already-emailed postings must ALWAYS be filtered out
- Users should never receive duplicate emails for the same posting
- Bug fixed: Previously `--force` bypassed both filters, causing repeated emails

## URL and Position Validation

### Always Validate Positions Are Still Open
- Job postings can be taken down at any time
- Before including a position in the email, validate it's still active by:
  1. Checking the URL returns 200 (not 404)
  2. Looking for "position closed" indicators in the page content
  3. Verifying presence of an apply button/link
- Better to skip a valid position than include a closed one

### LLMs Fabricate URLs
- LLM search providers (Claude, OpenAI, Grok) often return fabricated/hallucinated URLs
- These URLs look valid but redirect to generic careers pages
- Example: `boards.greenhouse.io/datadog/jobs/6153233002` → `careers.datadoghq.com/`
- Detection strategies:
  1. Check if URL redirects to a different host
  2. Check if final URL path loses the job ID (e.g., `/jobs/12345` → `/positions/`)
  3. Look for generic listing page indicators (job counts, filters)
- URLs from direct ATS API fetches are reliable; LLM-found URLs need extra validation
- Always validate LLM-sourced URLs before including in emails

## Document Generation

### Anti-Fabrication Rules Are Critical
- LLMs will happily invent experiences, skills, and metrics if not explicitly prevented
- Always include explicit instructions like:
  - "Do NOT fabricate, invent, or add ANY information not in the original"
  - "Do NOT exaggerate metrics, numbers, or achievements"
  - "ONLY reference experiences that appear in the resume"
- Test generated documents carefully for accuracy

### Cover Letters Should Be Text Files
- PDFs are harder to edit if the user wants to customize
- Plain text (.txt) files are more practical for cover letters
- Resumes can remain as PDFs since they need formatting

## API Configuration

### Add Environment Variables Before Using New Providers
- When adding a new search provider (like Grok), always:
  1. Add the API key to `.env.example` with documentation
  2. Add the key to `EnvSettings` in `config.py`
  3. Check if the key exists before attempting to use the provider
- Missing API keys should be handled gracefully with warnings, not errors

### Handle Rate Limits Gracefully
- All LLM APIs have rate limits
- Use exponential backoff with retries (tenacity library)
- Log rate limit errors clearly so users understand the issue
- Consider adding delays between API calls in batch operations

## Configuration Management

### config.yaml vs config.example.yaml
- `config.yaml` is gitignored (contains user-specific settings)
- `config.example.yaml` is tracked and should be updated for new features
- When adding new exclusions or settings, update BOTH files
- Never commit API keys or passwords to config.example.yaml

## Email Configuration

### Gmail SMTP Requires App Passwords
- Regular Gmail passwords won't work with SMTP
- Users need to generate an App Password at https://myaccount.google.com/apppasswords
- App Passwords are 16 characters with no spaces
- The `from_address` should match the SMTP user

## Scheduled Tasks

### Windows Task Scheduler
- Use PowerShell `Register-ScheduledTask` for reliable task creation
- Create a batch file wrapper to set environment (PYTHONPATH, working directory)
- Tasks run in the user's timezone by default
- Use `-StartWhenAvailable` to run missed tasks when computer wakes up

## LLM Provider Management

### Model Names Change Frequently
- LLM providers deprecate models regularly (e.g., `grok-beta` → `grok-3`)
- Always check for the latest model name when a provider fails
- Error messages usually indicate the correct model to use
- Consider making model names configurable in .env or config.yaml

### Test Providers Individually
- Before running full scans, test each search provider in isolation
- Use a simple Python snippet to verify API connectivity:
  ```python
  from app.sources.grok_search import GrokSearchProvider
  grok = GrokSearchProvider(api_key='...')
  results = grok.search(['SWE'], ['freshman'], recency_days=7)
  ```
- This catches auth issues and model deprecations quickly

### Rate Limits Are Real
- Claude has strict rate limits (30,000 tokens/minute on some tiers)
- Multiple consecutive runs will hit rate limits
- The scanner already has retry logic, but back-to-back runs will fail
- For testing, use `--no_documents` to reduce token usage
- Wait at least 1-2 minutes between full runs

### Multiple Providers Increase Coverage
- Different LLMs find different results
- Claude found 1 posting, Grok found 3 additional ones
- Always enable all available providers for best coverage
- Results are automatically deduplicated by URL

## Accelerator Discovery

### Use Official APIs When Available
- Y Combinator has a community API at `yc-oss.github.io/api/companies/all.json`
- This is updated daily and contains 5,600+ companies
- Much more reliable than scraping the YC website directly
- Cache the company list locally to avoid repeated API calls

### ATS Platform Detection Has Pitfalls
- Greenhouse and Lever APIs are reliable - they return job counts
- Ashby detection is tricky - many false positives from HTML pages
- Always verify by checking if actual jobs exist, not just if page loads
- Use the ATS APIs directly (`boards-api.greenhouse.io`, `api.lever.co`) instead of scraping

### Discovery Is Slow But Worth It
- Checking 500 companies takes ~45 minutes due to rate limiting
- Each company must be tested against 3 ATS platforms
- Run discovery periodically (weekly) to find new companies
- Cache results in `cache/verified_boards_yc.json` for reuse

### Big YC Companies Found
- Major companies with Greenhouse boards: Stripe, Airbnb, Dropbox, Reddit, Twitch, Instacart, Coinbase, Gusto, Figma
- These are valuable sources even if they don't have underclass programs now
- Companies add/remove internship programs seasonally

### Ashby False Positives
- Ashby pages often return 200 status even without job data
- The improved API check (`api.ashbyhq.com/posting-api/job-board/{slug}`) is more reliable
- Still some false positives - the scanner handles this gracefully by logging "No job data found"

## Code Quality

### Avoid Over-Engineering
- Don't add features that weren't requested
- Keep solutions simple and focused
- A bug fix doesn't need surrounding code cleaned up
- Don't add comments to code you didn't change

### Test Before Committing
- Run the scanner at least once after changes to verify it works
- Check that emails are actually sent and contain expected content
- Verify attachments are correct format (txt for cover letters, pdf for resumes)
