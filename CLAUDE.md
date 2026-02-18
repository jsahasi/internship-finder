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

### Always Validate Positions Are Still Open (Conservative)
- Job postings can be taken down at any time
- Before including a position in the email, validate it's still active by:
  1. Checking the URL returns HTTP 200 (any non-200 = reject)
  2. Looking for "position closed" / "expired" indicators in the page content
  3. Verifying presence of an apply button/link (no apply button = reject)
  4. Platform-specific checks: Workday `postingAvailable: false`, LinkedIn auth walls
- **Conservative defaults**: if we can't confirm a posting is open, exclude it
  - Page unreachable → reject (was: assume open)
  - No apply button found → reject (was: assume open)
  - Non-200 HTTP status → reject (was: assume open for non-404)
- Better to skip a valid position than include a closed one
- Log all removals at INFO level so they're visible in scan output

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

### Diminishing Returns After ~1000 Companies
- After checking ~1000 YC companies, most major companies with job boards are found
- Found 47 boards total: 29 Greenhouse, 3 Lever, 15 Ashby
- Further discovery yields very few new boards (3 per 500 companies checked)
- The YC list has 5,600+ companies but most are small startups without public job boards
- Weekly discovery runs are sufficient to catch new companies

### Job Count Impact
- 47 accelerator boards added ~1,000 new job postings to each scan
- Major contributors: Airbnb (248), Dropbox (162), Instacart (159), Reddit (151), Fivetran (146)
- Even without underclass programs now, these companies may add them seasonally
- The infrastructure is in place to catch them when they do

## Target Company Search

### Batch Company Searches Need Rate Limit Delays
- Sending 100 companies per prompt to Claude uses ~80K+ tokens
- The 30K tokens/minute rate limit on lower tiers will block batch searches without delays
- A 65-second delay between batch API calls keeps within the per-minute budget
- The broad search (no companies) should run first with no delay
- Batch searches run after with delays between each

### ATS Slugs Must Be Verified
- Many guessed ATS slugs return 404 (e.g., `notion`, `doordash`, `rivian`, `netflix` on Greenhouse)
- Companies change ATS platforms or use custom slugs (e.g., Netflix uses their own careers site)
- Two Sigma, Citadel, DE Shaw, Bridgewater don't use Greenhouse despite being finance firms
- Ashby boards for OpenAI, Anthropic, Ramp, Vanta all returned no data — they may have switched platforms
- Always verify slugs before adding; remove 404s promptly to avoid wasted API calls
- Verified working Greenhouse boards (Feb 2026): stripe, coinbase, robinhood, brex, figma, scaleai, andurilindustries, a16z, spacex, databricks, point72, janestreet, instacart, reddit, dropbox, gusto, faire, airbnb, pinterest, twitch, fivetran, flexport, samsara, checkr

### LLM Search Providers Have Different Strengths
- Claude with web search found Palantir internship via Lever
- Grok found Jane Street Early Insight Program
- OpenAI (GPT-4o) returned 0 results — lacks real web search in API mode
- The `target_companies` list in config.yaml (278 companies) is passed to LLM search prompts in batches of 100
- Companies are organized by category: Dow 30, Fortune 500, Nasdaq 100, VCs, IBs, hedge funds, PE firms, YC/accelerator companies

## Workday ATS Integration

### Workday CXS API
- Workday's career sites use a CXS API at `POST https://{tenant}.{instance}.myworkdayjobs.com/wday/cxs/{tenant}/{portal}/jobs`
- Each company needs 3 fields: `tenant`, `instance` (wd1-wd5, wd12), `portal` (career site name)
- Page size MUST be 20 or less — larger values (e.g., 200) return HTTP 400
- Workday blocks bot User-Agent strings — must use a browser-like UA string
- `externalPath` from the API already includes `/job/` prefix — don't double it in URL construction
- Date strings use relative format: "Posted Today", "Posted Yesterday", "Posted N Days Ago", "Posted 30+ Days Ago"

### Verified Workday Boards (Feb 2026)
- **Big Tech**: nvidia.wd5, salesforce.wd12, adobe.wd5, netflix.wd1, cisco.wd5, intel.wd1, broadcom.wd1, snapchat.wd1, crowdstrike.wd5, paypal.wd1
- **Entertainment/Consumer**: disney.wd5, walmart.wd5, chevron.wd5
- **Finance**: ms.wd5 (Morgan Stanley), spgi.wd5 (S&P Global), nasdaq.wd1, dowjones.wd1, mtb.wd5, lplfinancial.wd1
- **Defense**: boeing.wd1 (INTERN portal only), ngc.wd1 (Northrop Grumman)
- 21 boards total, ~14,000+ jobs across all boards
- Many major finance firms (Goldman Sachs, JPMorgan, Citi, Wells Fargo) do NOT use myworkdayjobs.com
- Wells Fargo uses myworkdaysite.com (different platform, different API)

### Discovering New Workday Boards
- Search `"myworkdayjobs.com" {company} careers` to find the URL
- Extract tenant, instance, and portal from the URL pattern
- Verify with CXS API POST before adding to config
- Brute-force discovery is slow (5 instances x N companies) — web search is more efficient

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
