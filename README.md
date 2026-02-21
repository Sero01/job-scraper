# Job Scraper → Google Sheets

Scrapes LinkedIn for software/AI/automation developer jobs in **Bangalore** and **Hyderabad** targeting **1-2 years of experience**, then writes results into a new Google Sheet with direct apply links.

## Quick Start

```bash
chmod +x scrape_jobs.sh   # first time only
./scrape_jobs.sh
```

That's it. The script will:
1. Load your existing Google OAuth credentials (no browser login needed)
2. Search LinkedIn for ~6 keyword+location combinations
3. Fetch full details for each unique job posting
4. Create a new Google Sheet and print its URL

Expected output:
```
======================================================================
Job Scraper → Google Sheets
======================================================================

[1/4] Loading Google OAuth credentials...
  Credentials ready.

[2/4] Searching LinkedIn for jobs...
  Searching: software developer / Bangalore, Karnataka
    Found 75 job IDs (75 new, 0 duplicates)
  ...
  Total unique job IDs: 143

[3/4] Fetching job details (this takes ~215s)...
  Progress: 10/143 jobs fetched...
  ...
  Fetched: 131 jobs  |  Failed/skipped: 12

[4/4] Writing 131 jobs to Google Sheets...

======================================================================
✓ Scraped 131 jobs (after deduplication)
✓ Google Sheet created: https://docs.google.com/spreadsheets/d/...
======================================================================
```

## Sheet Columns

| Column | Description |
|--------|-------------|
| A — Company | Employer name |
| B — Job Title | Position title |
| C — Location | City (Bangalore / Hyderabad) |
| D — Salary | If listed (often blank for India postings) |
| E — Experience Required | Extracted from description (e.g. "1-2 years") |
| F — Key Skills | Up to 10 detected skills (Python, React, AWS, etc.) |
| G — Apply Link | Clickable `=HYPERLINK()` formula → opens job page |
| H — Job Description (preview) | First 500 characters of full description |
| I — Date Scraped | Timestamp of when the script ran |

## Customization

### Change search keywords or cities

Edit the `SEARCH_QUERIES` list near the top of `job_scraper.py`:

```python
SEARCH_QUERIES = [
    ("software developer",        "Bangalore, Karnataka"),
    ("data engineer",             "Chennai, Tamil Nadu"),   # add a new city/role
]
```

### Scrape more (or fewer) pages per query

Change `PAGES_PER_QUERY` (each page = 25 results):

```python
PAGES_PER_QUERY = 5   # up to 125 jobs per query
```

Keep total jobs under ~150 per run to avoid LinkedIn rate-limits.

### Change the experience filter

`f_E=2,3` in the search URL maps to LinkedIn's experience levels:
- `1` = Internship
- `2` = Entry level
- `3` = Associate
- `4` = Mid-Senior level

Edit `fetch_job_ids()` in `job_scraper.py` to change or combine levels.

## Re-authentication

The script reuses the OAuth tokens from the GDrive MCP setup. If you see an auth error:

1. Check that these files exist and are valid JSON:
   - `/home/parvez/.config/gdrive-mcp/.gdrive-server-credentials.json`
   - `/home/parvez/.config/gdrive-mcp/gcp-oauth.keys.json`

2. If the `refresh_token` has been revoked (rare), re-run the original GDrive OAuth setup:
   ```bash
   # From the gdrive-mcp server directory
   npx @modelcontextprotocol/server-gdrive auth
   ```

## How It Works

```
scrape_jobs.sh
    └── uv run job_scraper.py          # auto-installs deps via PEP 723
            ├── load_credentials()      # reuse GDrive MCP OAuth tokens
            ├── fetch_job_ids()         # LinkedIn guest search API → job IDs
            ├── fetch_job_detail()      # LinkedIn job detail API → full HTML
            └── create_sheet_and_write()  # Google Sheets API → new spreadsheet
```

LinkedIn's guest API (`/jobs-guest/`) is publicly accessible without login. The script parses the returned HTML with BeautifulSoup to extract structured data.

## Dependencies

Managed automatically by `uv` via PEP 723 inline metadata in `job_scraper.py`:
- `requests` — HTTP client
- `beautifulsoup4` — HTML parsing
- `google-api-python-client` — Sheets API
- `google-auth` — OAuth credential management
- `google-auth-oauthlib` — Token refresh
