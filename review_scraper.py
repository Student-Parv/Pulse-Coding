import argparse
import json
import time
import random
from datetime import datetime
from playwright.sync_api import sync_playwright
from dateutil import parser

# --- CONFIGURATION ---
def get_selectors(source):
    """Returns CSS selectors based on the source website."""
    if source == 'https://www.g2.com/':
        return {
            'review_card': 'div.paper',  # G2 review container often changes, generic fallback
            'title': 'div.review-content__title a',
            'body': 'div[itemprop="reviewBody"]',
            'date': 'time',
            'rating': 'meta[itemprop="ratingValue"]', # often hidden in meta
            'next_btn': 'a.pagination__named-link.js-log-click'
        }
    elif source == 'https://www.capterra.in/':
        return {
            'review_card': 'div.review-card',
            'title': 'h3.review-card-title',
            'body': 'div.review-card-text',
            'date': 'div.review-card-date',
            'rating': 'div.star-rating',
            'next_btn': 'button.pagination-next'
        }
    elif source == 'sourceforge': # BONUS SOURCE
        return {
            'review_card': 'section.topic',
            'title': 'p.lead',
            'body': 'div.content',
            'date': 'span.posted-date',
            'rating': 'div.stars', # Count stars or parse class
            'next_btn': 'a.pagination-next'
        }
    return None

def parse_date(date_str):
    try:
        # Remove common prefixes like "Written on "
        clean_str = date_str.replace("Written on", "").replace("Posted on", "").strip()
        return parser.parse(clean_str)
    except:
        return datetime.now() # Fallback

def scrape_reviews(company, start_date, end_date, source):
    reviews_data = []
    
    # Format Dates
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    with sync_playwright() as p:
        # Launch Browser (Headless=False to bypass basic bot detection visually)
        browser = p.chromium.launch(headless=False, slow_mo=500)
        page = browser.new_page()
        
        # 1. URL Construction (Heuristic - effective for assignment)
        if source == 'g2':
            url = f"https://www.g2.com/products/{company.lower()}/reviews"
        elif source == 'capterra':
            url = f"https://www.capterra.com/p/{company.lower()}/reviews" # Note: Capterra URLs are tricky, often need ID.
            # Ideally, use site search. For this MVP, we try direct slug.
        elif source == 'sourceforge':
            url = f"https://sourceforge.net/software/product/{company}/reviews"
        
        print(f"[*] Navigating to {url}...")
        page.goto(url, timeout=60000)
        
        # Manual Interaction Pause (Crucial for Anti-Bot)
        # If a CAPTCHA appears, you have 15 seconds to solve it manually
        print("[-] Waiting 10s for page load/manual captcha solving...")
        time.sleep(10)

        selectors = get_selectors(source)
        
        while True:
            # Get all review cards
            cards = page.query_selector_all(selectors['review_card'])
            print(f"[-] Found {len(cards)} reviews on this page.")
            
            if not cards:
                print("[!] No reviews found. Check URL or Selectors.")
                break

            found_old_review = False

            for card in cards:
                try:
                    # Extract Date First to check range
                    date_el = card.query_selector(selectors['date'])
                    date_text = date_el.inner_text() if date_el else str(datetime.now())
                    review_date = parse_date(date_text)

                    # Filter Logic
                    if review_date < start:
                        found_old_review = True
                        break # Optimization: Reviews are usually chronological
                    
                    if start <= review_date <= end:
                        # Extract Content
                        title_el = card.query_selector(selectors['title'])
                        body_el = card.query_selector(selectors['body'])
                        
                        item = {
                            "source": source,
                            "title": title_el.inner_text().strip() if title_el else "No Title",
                            "description": body_el.inner_text().strip() if body_el else "",
                            "date": review_date.strftime("%Y-%m-%d"),
                            "rating": "N/A" # Simplified for MVP
                        }
                        reviews_data.append(item)
                except Exception as e:
                    continue

            if found_old_review:
                print("[-] Reached reviews older than start date. Stopping.")
                break
            
            # Pagination Logic
            next_btn = page.query_selector(selectors['next_btn'])
            if next_btn and next_btn.is_enabled():
                print("[-] Clicking Next Page...")
                next_btn.click()
                time.sleep(random.uniform(3, 6)) # Random sleep to be human-like
            else:
                print("[-] No more pages.")
                break

        browser.close()

    return reviews_data

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Pulse Coding Assignment Scraper')
    parser.add_argument('--company', required=True, help='Company name (slug format preferred, e.g., slack)')
    parser.add_argument('--start_date', required=True, help='YYYY-MM-DD')
    parser.add_argument('--end_date', required=True, help='YYYY-MM-DD')
    parser.add_argument('--source', required=True, choices=['g2', 'capterra', 'sourceforge'], help='Source to scrape')

    args = parser.parse_args()

    print(f"Starting scrape for {args.company} on {args.source}...")
    data = scrape_reviews(args.company, args.start_date, args.end_date, args.source)
    
    filename = f"{args.company}_{args.source}_reviews.json"
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    
    print(f"[SUCCESS] Scraped {len(data)} reviews. Saved to {filename}")