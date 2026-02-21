# /// script
# dependencies = [
#   "requests",
#   "beautifulsoup4",
#   "google-api-python-client",
#   "google-auth",
#   "google-auth-oauthlib",
# ]
# ///
"""
Job Scraper → Google Sheets
Scrapes LinkedIn for software/AI/automation jobs in Bangalore & Hyderabad
(1-2 years experience) and writes results to a new Google Sheet.
"""

import json
import time
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# ── Credential paths ──────────────────────────────────────────────────────────
CREDS_FILE = "/home/parvez/.config/gdrive-mcp/.gdrive-server-credentials.json"
KEYS_FILE  = "/home/parvez/.config/gdrive-mcp/gcp-oauth.keys.json"

# ── Search configuration ──────────────────────────────────────────────────────
SEARCH_QUERIES = [
    ("software developer",        "Bangalore, Karnataka"),
    ("software developer",        "Hyderabad, Telangana"),
    ("AI automation engineer",    "Bangalore, Karnataka"),
    ("AI automation engineer",    "Hyderabad, Telangana"),
    ("machine learning engineer", "Bangalore, Karnataka"),
    ("machine learning engineer", "Hyderabad, Telangana"),
]

PAGES_PER_QUERY = 3          # 3 pages × 25 = up to 75 jobs per query
RATE_LIMIT_DELAY = 1.5       # seconds between detail requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ── Data model ────────────────────────────────────────────────────────────────
@dataclass
class Job:
    job_id: str
    company: str = ""
    title: str = ""
    location: str = ""
    salary: str = ""
    experience: str = ""
    skills: str = ""
    apply_url: str = ""
    description: str = ""
    date_scraped: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M"))

    def to_row(self) -> list:
        apply_formula = f'=HYPERLINK("{self.apply_url}","View & Apply")' if self.apply_url else ""
        return [
            self.company,
            self.title,
            self.location,
            self.salary,
            self.experience,
            self.skills,
            apply_formula,
            self.description[:500],
            self.date_scraped,
        ]


# ── OAuth ─────────────────────────────────────────────────────────────────────
def load_credentials() -> Credentials:
    with open(KEYS_FILE) as f:
        keys = json.load(f)["installed"]
    with open(CREDS_FILE) as f:
        saved = json.load(f)

    creds = Credentials(
        token=saved["access_token"],
        refresh_token=saved["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=keys["client_id"],
        client_secret=keys["client_secret"],
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )

    if creds.expired or not creds.valid:
        print("  Refreshing OAuth token...")
        creds.refresh(Request())
        # Persist refreshed token so the next run doesn't need to refresh again
        saved["access_token"] = creds.token
        with open(CREDS_FILE, "w") as f:
            json.dump(saved, f, indent=2)
        print("  Token refreshed and saved.")

    return creds


# ── LinkedIn scraping ─────────────────────────────────────────────────────────
LINKEDIN_SEARCH_URL = (
    "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
)
LINKEDIN_DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{}"


def fetch_job_ids(keywords: str, location: str) -> list[str]:
    """Return a deduplicated list of job IDs for this keyword+location combo."""
    job_ids = []
    for page in range(PAGES_PER_QUERY):
        params = {
            "keywords": keywords,
            "location": location,
            "f_E": "2,3",          # Entry level + Associate
            "start": page * 25,
        }
        try:
            resp = requests.get(
                LINKEDIN_SEARCH_URL, params=params, headers=HEADERS, timeout=15
            )
            if resp.status_code != 200:
                print(f"    Search returned {resp.status_code}, stopping pagination.")
                break
            soup = BeautifulSoup(resp.text, "html.parser")
            # LinkedIn uses data-entity-urn="urn:li:jobPosting:1234567"
            cards = soup.find_all(attrs={"data-entity-urn": True})
            if not cards:
                # Fallback: try old data-job-id attribute
                cards = soup.find_all(attrs={"data-job-id": True})
                for card in cards:
                    jid = card["data-job-id"].strip()
                    if jid:
                        job_ids.append(jid)
                if not cards:
                    break
                continue
            for card in cards:
                urn = card["data-entity-urn"]
                # urn format: urn:li:jobPosting:4367778343
                if "jobPosting:" in urn:
                    jid = urn.split("jobPosting:")[-1].strip()
                    if jid:
                        job_ids.append(jid)
        except requests.RequestException as e:
            print(f"    Request error on page {page}: {e}")
            break
        time.sleep(0.8)  # brief pause between search pages

    return job_ids


def _text(soup: BeautifulSoup, *selectors) -> str:
    """Try each CSS selector in order, return first match stripped."""
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            return el.get_text(separator=" ", strip=True)
    return ""


def _extract_experience(text: str) -> str:
    """Pull '1-2 years', '2+ years', etc. from description text."""
    patterns = [
        r"\b(\d[\d\-–+]*\s*(?:to|-|–)\s*\d+\s*years?)\b",
        r"\b(\d+\+?\s*years?\s*(?:of\s+)?(?:experience|exp)?)\b",
        r"\b(fresher|entry[\s-]?level|0[\s-]?to[\s-]?\d+\s*years?)\b",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


def _extract_skills(text: str) -> str:
    """Pull common skill keywords from description text."""
    skill_keywords = [
        "Python", "JavaScript", "TypeScript", "Java", "C\\+\\+", "Go", "Rust",
        "React", "Node\\.js", "Django", "FastAPI", "Flask", "Spring",
        "SQL", "PostgreSQL", "MySQL", "MongoDB", "Redis",
        "AWS", "GCP", "Azure", "Docker", "Kubernetes", "Terraform",
        "TensorFlow", "PyTorch", "scikit-learn", "LangChain", "LLM",
        "Machine Learning", "Deep Learning", "NLP", "RAG",
        "REST", "GraphQL", "Microservices", "CI/CD", "Git",
        "Automation", "n8n", "Zapier", "Airflow",
    ]
    found = []
    for kw in skill_keywords:
        if re.search(rf"\b{kw}\b", text, re.IGNORECASE):
            found.append(kw.replace("\\", ""))  # un-escape regex chars
    return ", ".join(found[:10])  # cap at 10 to keep column readable


def fetch_job_detail(job_id: str) -> Optional[Job]:
    """Fetch and parse a single job posting page."""
    url = LINKEDIN_DETAIL_URL.format(job_id)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")

        title = _text(
            soup,
            ".top-card-layout__title",
            "h1.topcard__title",
            "h1",
        )
        company = _text(
            soup,
            ".topcard__org-name-link",
            ".topcard__flavor--metadata a",
            ".topcard__flavor:not(.topcard__flavor--bullet)",
        )
        location = _text(soup, ".topcard__flavor--bullet", ".job-details-jobs-unified-top-card__primary-description-container span")

        salary = _text(soup, ".salary.compensation__salary", ".compensation__salary")

        # Apply URL — LinkedIn's guest API doesn't expose the real external apply
        # URL without login. Instead: extract the clean job listing URL from the
        # topcard title link (e.g. https://in.linkedin.com/jobs/view/title-at-co-ID),
        # which takes the user directly to the posting where they can click Apply.
        apply_url = ""
        SKIP_DOMAINS = ("linkedin.com/login", "linkedin.com/uas", "linkedin.com/signup",
                        "linkedin.com/authwall")

        # 1. Try the topcard title link — it's always the canonical job listing URL
        title_link = soup.select_one(
            "a.base-card__full-link, "
            "a[data-tracking-control-name='public_jobs_topcard-title'], "
            ".top-card-layout__title a, "
            "h2.top-card-layout__title a"
        )
        if title_link and title_link.get("href"):
            href = title_link["href"].split("?")[0]
            if not any(skip in href for skip in SKIP_DOMAINS):
                apply_url = href

        # 2. Fallback: construct the listing URL from the job ID
        if not apply_url:
            apply_url = f"https://www.linkedin.com/jobs/view/{job_id}"

        # Description
        desc_el = soup.select_one(
            ".show-more-less-html__markup, "
            ".description__text, "
            "#job-details"
        )
        description = desc_el.get_text(separator=" ", strip=True) if desc_el else ""

        experience = _extract_experience(description)
        skills = _extract_skills(description)

        # Skip postings with no title (likely blocked / expired)
        if not title:
            return None

        return Job(
            job_id=job_id,
            company=company,
            title=title,
            location=location,
            salary=salary,
            experience=experience,
            skills=skills,
            apply_url=apply_url,
            description=description,
        )

    except requests.RequestException as e:
        print(f"    Detail fetch error for {job_id}: {e}")
        return None


# ── Google Sheets ─────────────────────────────────────────────────────────────
SHEET_HEADERS = [
    "Company", "Job Title", "Location", "Salary",
    "Experience Required", "Key Skills", "Apply Link",
    "Job Description (preview)", "Date Scraped",
]


def create_sheet_and_write(jobs: list[Job], creds: Credentials) -> str:
    """Create a new Google Sheet, write jobs, format it. Returns the URL."""
    service = build("sheets", "v4", credentials=creds)

    date_str = datetime.now().strftime("%Y-%m-%d")
    spreadsheet = service.spreadsheets().create(body={
        "properties": {"title": f"Job Listings — Bangalore/Hyderabad ({date_str})"},
        "sheets": [{"properties": {"title": "Jobs", "sheetId": 0}}],
    }).execute()

    sheet_id = spreadsheet["spreadsheetId"]
    sheet_gid = 0  # sheetId for formatting requests

    # Write data
    values = [SHEET_HEADERS] + [job.to_row() for job in jobs]
    service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range="Jobs!A1",
        valueInputOption="USER_ENTERED",  # needed so =HYPERLINK() formulas evaluate
        body={"values": values},
    ).execute()

    # Format: bold header row + freeze row 1 + auto-resize all columns
    requests_body = [
        # Bold header row
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_gid,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                },
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {
                            "bold": True,
                            "foregroundColor": {"red": 1, "green": 1, "blue": 1},
                        },
                        "backgroundColor": {"red": 0.23, "green": 0.47, "blue": 0.85},
                    }
                },
                "fields": "userEnteredFormat(textFormat,backgroundColor)",
            }
        },
        # Freeze row 1
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_gid,
                    "gridProperties": {"frozenRowCount": 1},
                },
                "fields": "gridProperties.frozenRowCount",
            }
        },
        # Auto-resize all columns
        {
            "autoResizeDimensions": {
                "dimensions": {
                    "sheetId": sheet_gid,
                    "dimension": "COLUMNS",
                    "startIndex": 0,
                    "endIndex": len(SHEET_HEADERS),
                }
            }
        },
    ]

    service.spreadsheets().batchUpdate(
        spreadsheetId=sheet_id,
        body={"requests": requests_body},
    ).execute()

    return f"https://docs.google.com/spreadsheets/d/{sheet_id}"


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("Job Scraper → Google Sheets")
    print("=" * 60)

    # 1. Load OAuth credentials
    print("\n[1/4] Loading Google OAuth credentials...")
    creds = load_credentials()
    print("  Credentials ready.")

    # 2. Collect job IDs from LinkedIn search
    print("\n[2/4] Searching LinkedIn for jobs...")
    all_job_ids: dict[str, str] = {}  # job_id → query label

    for keywords, location in SEARCH_QUERIES:
        label = f"{keywords} / {location}"
        print(f"  Searching: {label}")
        ids = fetch_job_ids(keywords, location)
        new_count = 0
        for jid in ids:
            if jid not in all_job_ids:
                all_job_ids[jid] = label
                new_count += 1
        print(f"    Found {len(ids)} job IDs ({new_count} new, {len(ids)-new_count} duplicates)")

    print(f"\n  Total unique job IDs: {len(all_job_ids)}")

    # 3. Fetch job details
    print(f"\n[3/4] Fetching job details (this takes ~{len(all_job_ids)*1.5:.0f}s)...")
    jobs: list[Job] = []
    failed = 0

    for i, job_id in enumerate(all_job_ids.keys(), 1):
        if i % 10 == 0:
            print(f"  Progress: {i}/{len(all_job_ids)} jobs fetched...")
        job = fetch_job_detail(job_id)
        if job:
            jobs.append(job)
        else:
            failed += 1
        time.sleep(RATE_LIMIT_DELAY)

    print(f"  Fetched: {len(jobs)} jobs  |  Failed/skipped: {failed}")

    if not jobs:
        print("\nNo jobs found. LinkedIn may be rate-limiting. Try again later.")
        return

    # 4. Write to Google Sheets
    print(f"\n[4/4] Writing {len(jobs)} jobs to Google Sheets...")
    sheet_url = create_sheet_and_write(jobs, creds)

    print("\n" + "=" * 60)
    print(f"✓ Scraped {len(jobs)} jobs (after deduplication)")
    print(f"✓ Google Sheet created: {sheet_url}")
    print("=" * 60)


if __name__ == "__main__":
    main()
