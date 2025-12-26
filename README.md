## SaaS Reviews Scraper (Playwright + Stealth)

This tool scrapes SaaS product reviews from G2, Capterra, and SourceForge using Playwright (Python) with stealth techniques to better mimic real users. It supports pagination, relative/absolute date parsing, and filtering by date range. Output is a JSON array of review objects.

### Features
- Playwright sync API with stealth (`playwright-stealth`)
- Headful by default to reduce anti-bot triggers (optional `--headless`)
- Pagination via "Next" button when available
- Relative and absolute date parsing to ISO `YYYY-MM-DD`
- Configurable CSS selectors via `get_selectors(source)`

### Requirements
- Python 3.9+
- Playwright browsers installed (`python -m playwright install`)

### Install
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install
```

If you prefer Node Playwright alongside Python, that's optional and not required here.

### Usage
Run in PowerShell (Windows):
```powershell
# G2 example
python scraper.py --company slack --start_date 2024-01-01 --end_date 2024-12-31 --source g2

# Capterra example
python scraper.py --company slack --start_date 2024-01-01 --end_date 2024-12-31 --source capterra

# SourceForge example
python scraper.py --company slack --start_date 2024-01-01 --end_date 2024-12-31 --source sourceforge

# Headless mode (optional)
python scraper.py --company slack --start_date 2024-01-01 --end_date 2024-12-31 --source g2 --headless
```

Output will be written to a file named like `slack_g2_reviews.json`.

### Architecture
- `scraper.py`
  - `get_selectors(source)`: centralizes CSS selectors per source.
  - `parse_date_str()`: uses `dateparser` to handle relative dates (e.g., "2 days ago").
  - `scrape_reviews()`: sets up Playwright (stealth, headful by default), navigates to a heuristic URL, accepts cookies, detects simple captcha states, paginates via a "Next" selector, extracts review fields, filters by date range, and returns structured results.
  - Anti-bot strategy: realistic user agents, varying viewport, slow motion, headful mode, scrolling, cookie acceptance, simple captcha detection with manual solving window.

### Notes on Sources
- G2 and Capterra actively change markup and deploy anti-bot protections. Selectors are best-effort and may require adjustments over time. For Capterra, some products require an internal ID for the canonical `p/{slug}/reviews` URL; the scraper will still work if you manually navigate in the opened browser to the product reviews tab.
- SourceForge is integrated as the bonus source.

### Troubleshooting
- If a CAPTCHA appears, the script pauses to let you solve it manually in the open browser window. If unresolved after ~120s, the script continues.
- If no reviews are found: verify the product slug and consider manually navigating to the correct reviews page in the same browser window; pagination and extraction will continue from there.

### Development Tips
- Update selectors in `get_selectors()` as needed when site structures change.
- For debugging anti-bot flows, run without `--headless` to watch behavior.
