import argparse
import json
import os
import random
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from dateparser import parse as dateparse
from playwright.sync_api import Browser, Page, sync_playwright, TimeoutError as PlaywrightTimeoutError
from playwright_stealth.stealth import Stealth


# ---------------------------
# Config & Utilities
# ---------------------------

USER_AGENTS = [
    # A few realistic desktop UA strings
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6_3) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
]


def human_sleep(a: float = 0.8, b: float = 1.8) -> None:
    time.sleep(random.uniform(a, b))


def now_utc() -> datetime:
    return datetime.utcnow()


def parse_date_str(s: str) -> Optional[datetime]:
    if not s:
        return None
    # Robust parsing including relative dates like "2 days ago"
    dt = dateparse(
        s,
        settings={
            "PREFER_DAY_OF_MONTH": "first",
            "RELATIVE_BASE": now_utc(),
            "RETURN_AS_TIMEZONE_AWARE": False,
        },
    )
    return dt


def iso_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


@dataclass
class Selectors:
    review_card: str
    title: str
    body: str
    date: str
    rating: Optional[str]
    next_btn: Optional[str]


def get_selectors(source: str) -> Optional[Selectors]:
    s = source.lower()
    if s == "g2":
        return Selectors(
            review_card="div.paper, div.review",
            title="div.review-content__title a, a.review-title, h3, h4",
            body="[itemprop='reviewBody'], div.review-body, div.review-content__body",
            date="time, span.time-ago, span.display-date",
            rating="meta[itemprop='ratingValue'], [data-test='star-rating'], div.stars, span[aria-label*='star']",
            next_btn="a[aria-label='Next'], a.pagination__next, a[rel='next'], button[aria-label='Next']",
        )
    if s == "capterra":
        return Selectors(
            review_card="div.review-card, article[data-testid='review-card'], div[data-automation='review-card']",
            title="h3.review-card-title, h3[data-testid='review-title'], h3",
            body="div.review-card-text, div[data-testid='review-text'], [itemprop='reviewBody']",
            date="div.review-card-date, time, span[data-testid='review-date']",
            rating="div.star-rating, [data-testid='star-rating'], span[aria-label*='star']",
            next_btn="button[aria-label='Next'], button.pagination-next, a[rel='next']",
        )
    if s == "sourceforge":
        return Selectors(
            review_card="section.topic, div.review, article.review",
            title="p.lead, h3, h4, a.title",
            body="div.content, div.review-body, div.body",
            date="span.posted-date, time, span.date",
            rating="div.stars, span[aria-label*='star'], [itemprop='ratingValue']",
            next_btn="a.pagination-next, a[rel='next'], a[aria-label='Next'], button[aria-label='Next']",
        )
    return None


def detect_and_handle_captcha(page: Page, max_wait_seconds: int = 120) -> None:
    # Simple signals for captchas; if detected, give operator time to solve manually
    captcha_signals = [
        "iframe[src*='hcaptcha']",
        "iframe[src*='recaptcha']",
        "#challenge-stage",  # Cloudflare
        "#cf-challenge-running",
    ]
    try:
        for sel in captcha_signals:
            frame = page.query_selector(sel)
            if frame:
                print("[CAPTCHA] Detected challenge. Please solve it in the browser window.")
                deadline = time.time() + max_wait_seconds
                while time.time() < deadline:
                    human_sleep(1.0, 2.0)
                    # Re-check if the signal disappeared
                    if not page.query_selector(sel):
                        print("[CAPTCHA] Challenge solved or cleared.")
                        return
                print("[CAPTCHA] Timeout waiting for manual solve; continuing.")
                return
    except Exception:
        # Never fail on captcha detection; just continue
        pass


def try_click(page: Page, selector: str, timeout_ms: int = 3000) -> bool:
    try:
        el = page.wait_for_selector(selector, timeout=timeout_ms, state="visible")
        if el and el.is_enabled():
            el.click()
            return True
    except PlaywrightTimeoutError:
        return False
    except Exception:
        return False
    return False


def accept_cookies_if_any(page: Page) -> None:
    possible_accepts = [
        "button#onetrust-accept-btn-handler",
        "button[aria-label='Accept all']",
        "button:has-text('Accept All')",
        "button:has-text('I Agree')",
        "button:has-text('Accept')",
        "button:has-text('Got it')",
    ]
    for sel in possible_accepts:
        if try_click(page, sel, timeout_ms=1500):
            print(f"[cookies] Clicked '{sel}'")
            human_sleep()
            break


def scroll_page(page: Page, steps: int = 6) -> None:
    for _ in range(steps):
        page.mouse.wheel(0, random.randint(800, 1400))
        human_sleep(0.4, 1.0)


def extract_text_safe(root, selector: str) -> str:
    try:
        el = root.query_selector(selector)
        if not el:
            return ""
        txt = (el.inner_text() or "").strip()
        return txt
    except Exception:
        return ""


def extract_rating_safe(root, selector: Optional[str]) -> str:
    if not selector:
        return ""
    # Try numeric first
    try:
        el = root.query_selector(selector)
        if el:
            # Try common patterns
            aria = el.get_attribute("aria-label") or ""
            if aria:
                # e.g., "4 out of 5 stars"
                import re

                m = re.search(r"([0-9]+(\.[0-9]+)?)\s*out of\s*([0-9]+)", aria, re.I)
                if m:
                    return m.group(1)
            content = (el.inner_text() or "").strip()
            if content:
                # Last resort, return inner text
                return content
    except Exception:
        pass
    return ""


def build_url(source: str, company: str) -> str:
    s = source.lower()
    slug = company.strip().lower().replace(" ", "-")
    if s == "g2":
        return f"https://www.g2.com/products/{slug}/reviews"
    if s == "capterra":
        # Heuristic: direct product slug path often requires internal id.
        # Try generic reviews path; if it fails, the script still supports manual navigation.
        return f"https://www.capterra.com/p/{slug}/reviews"
    if s == "sourceforge":
        return f"https://sourceforge.net/software/product/{slug}/reviews"
    return ""


def within_range(dt: datetime, start: datetime, end: datetime) -> bool:
    return start <= dt <= end


def scrape_reviews(
    company: str,
    start_date: str,
    end_date: str,
    source: str,
    headless: bool = False,
    user_data_dir: Optional[str] = None,
    start_url: Optional[str] = None,
    wait_after_nav: int = 0,
) -> List[Dict]:
    selectors = get_selectors(source)
    if not selectors:
        raise ValueError(f"Unsupported source: {source}")

    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    if end < start:
        raise ValueError("end_date must be >= start_date")

    results: List[Dict] = []

    with sync_playwright() as p:
        ua = random.choice(USER_AGENTS)
        launch_slow_mo = random.randint(200, 600)

        if user_data_dir:
            # Persistent context can reuse cookies/session to reduce friction after manual solves.
            context = p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=headless,
                slow_mo=launch_slow_mo,
                user_agent=ua,
                locale="en-US",
                viewport={"width": random.randint(1280, 1680), "height": random.randint(800, 1050)},
                timezone_id="UTC",
            )
            page = context.pages[0] if context.pages else context.new_page()
        else:
            browser = p.chromium.launch(headless=headless, slow_mo=launch_slow_mo)
            context = browser.new_context(
                user_agent=ua,
                locale="en-US",
                viewport={"width": random.randint(1280, 1680), "height": random.randint(800, 1050)},
                timezone_id="UTC",
            )
            page = context.new_page()

        # Apply stealth tweaks
        Stealth().apply_stealth_sync(page)

        url = start_url or build_url(source, company)
        print(f"[*] Navigating to: {url}")
        try:
            page.goto(url, timeout=60000, wait_until="domcontentloaded")
        except PlaywrightTimeoutError:
            print("[!] Initial navigation timed out; attempting to continue.")

        accept_cookies_if_any(page)
        detect_and_handle_captcha(page)

        if wait_after_nav > 0:
            print(f"[pause] Waiting {wait_after_nav}s for manual actions (solve CAPTCHA, log in, navigate).")
            time.sleep(wait_after_nav)

        # Small warm-up: scroll a bit to let JS-heavy pages render reviews
        scroll_page(page, steps=5)

        old_review_reached = False
        page_index = 1

        while True:
            detect_and_handle_captcha(page)

            # Wait briefly for review cards on each page
            try:
                page.wait_for_selector(selectors.review_card, timeout=15000)
            except PlaywrightTimeoutError:
                print("[!] No reviews detected on page; stopping.")
                break

            cards = page.query_selector_all(selectors.review_card)
            print(f"[-] Page {page_index}: Found {len(cards)} review candidates")

            if not cards:
                break

            for card in cards:
                try:
                    date_raw = extract_text_safe(card, selectors.date)
                    if not date_raw:
                        # Some sources put the date attribute in <time datetime="..."></time>
                        date_el = card.query_selector(selectors.date)
                        date_raw = date_el.get_attribute("datetime") if date_el else ""

                    dt = parse_date_str(date_raw)
                    if not dt:
                        continue

                    if dt < start:
                        old_review_reached = True
                        # Continue looping to capture any newer cards above, but mark flag
                        continue

                    if within_range(dt, start, end):
                        title = extract_text_safe(card, selectors.title) or ""
                        body = extract_text_safe(card, selectors.body) or ""
                        rating = extract_rating_safe(card, selectors.rating) or ""
                        results.append(
                            {
                                "source": source.lower(),
                                "title": title,
                                "description": body,
                                "date": iso_date(dt),
                                "rating": rating or "N/A",
                            }
                        )
                except Exception:
                    # Skip individual card failures
                    continue

            # If we saw an older review, we can stop paginating to save time
            if old_review_reached:
                print("[-] Encountered reviews older than start_date; stopping pagination.")
                break

            # Try pagination: click next button if present
            has_next = False
            if selectors.next_btn:
                # Bring the bottom into view and try multiple times
                for _ in range(2):
                    scroll_page(page, steps=3)
                has_next = try_click(page, selectors.next_btn, timeout_ms=3000)

            if not has_next:
                print("[-] No further pages detected.")
                break

            page_index += 1
            human_sleep(2.0, 4.0)

        context.close()

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="SaaS Reviews Scraper (Playwright + Stealth)")
    parser.add_argument("--company", required=True, help="Company/product slug (e.g., 'slack')")
    parser.add_argument("--start_date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end_date", required=True, help="YYYY-MM-DD")
    parser.add_argument(
        "--source",
        required=True,
        choices=["g2", "capterra", "sourceforge"],
        help="Review source to scrape",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode (default is headful to reduce bot detection)",
    )
    parser.add_argument(
        "--user_data_dir",
        default=None,
        help="Optional path to persistent user data dir to reuse cookies/sessions (helps after manual CAPTCHA solve)",
    )
    parser.add_argument(
        "--start_url",
        default=None,
        help="Override the auto-built URL; useful if the slug is not resolvable or you want to paste a known reviews URL",
    )
    parser.add_argument(
        "--wait_after_nav",
        type=int,
        default=0,
        help="Seconds to pause after initial navigation for manual solving/navigating before extraction",
    )

    args = parser.parse_args()

    print(
        f"Starting scrape: company={args.company}, source={args.source}, range={args.start_date}..{args.end_date}"
    )
    data = scrape_reviews(
        company=args.company,
        start_date=args.start_date,
        end_date=args.end_date,
        source=args.source,
        headless=args.headless,
        user_data_dir=args.user_data_dir,
        start_url=args.start_url,
        wait_after_nav=args.wait_after_nav,
    )

    out_name = f"{args.company}_{args.source}_reviews.json"
    with open(out_name, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"[SUCCESS] Saved {len(data)} reviews -> {out_name}")


if __name__ == "__main__":
    main()
