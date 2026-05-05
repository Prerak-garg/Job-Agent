"""
Standalone Playwright scraper — called as a subprocess from job_search.py.
Runs in its own fresh Python process, no asyncio event loop conflicts.
Output: JSON array to stdout.
"""
import sys
import json
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup


def parse_naukri(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    results = []
    for card in soup.select("article.jobTuple, div[class*='srp-jobtuple'], div[class*='jobTuple']")[:15]:
        title_el   = card.select_one("a.title, a[class*='title'], h2 a")
        company_el = card.select_one("a.subTitle, a[class*='comp-name'], span[class*='comp-name']")
        desc_el    = card.select_one("span.ellipsis, div[class*='job-description'], li[class*='tag']")
        if not title_el:
            continue
        title   = title_el.get_text(strip=True)
        href    = title_el.get("href", "")
        company = company_el.get_text(strip=True) if company_el else ""
        desc    = desc_el.get_text(strip=True) if desc_el else ""
        url     = href if href.startswith("http") else f"https://www.naukri.com{href}"
        if not url or url == "https://www.naukri.com":
            continue
        results.append({
            "title":   f"{title} at {company}" if company else title,
            "url":     url,
            "snippet": desc[:300],
            "source":  "Naukri",
            "company": company,
        })
    print(f"[worker] naukri: {len(results)} jobs", file=sys.stderr)
    return results


def parse_indeed(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    results = []
    for card in soup.select("div.job_seen_beacon, div[class*='jobCard']")[:15]:
        title_el   = card.select_one("h2 a span[title], h2 a")
        company_el = card.select_one("[class*='companyName'], [data-testid='company-name']")
        desc_el    = card.select_one("[class*='summary'], [class*='snippet']")
        link_el    = card.select_one("h2 a")
        if not title_el or not link_el:
            continue
        title   = title_el.get("title") or title_el.get_text(strip=True)
        href    = link_el.get("href", "")
        company = company_el.get_text(strip=True) if company_el else ""
        desc    = desc_el.get_text(strip=True) if desc_el else ""
        url     = f"https://in.indeed.com{href}" if href.startswith("/") else href
        results.append({
            "title":   f"{title} at {company}" if company else title,
            "url":     url,
            "snippet": desc[:300],
            "source":  "Indeed",
            "company": company,
        })
    print(f"[worker] indeed: {len(results)} jobs", file=sys.stderr)
    return results


def main():
    urls_with_source = json.loads(sys.argv[1])
    results = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="en-IN",
            viewport={"width": 1280, "height": 800},
        )
        for url, source in urls_with_source:
            page = context.new_page()
            try:
                print(f"[worker] loading {source}: {url[:80]}", file=sys.stderr)
                page.goto(url, timeout=25000, wait_until="domcontentloaded")
                page.wait_for_timeout(2500)
                html = page.content()
                if source == "Naukri":
                    results.extend(parse_naukri(html))
                elif source == "Indeed":
                    results.extend(parse_indeed(html))
            except Exception as e:
                print(f"[worker] {source} error: {e}", file=sys.stderr)
            finally:
                page.close()
        browser.close()

    print(json.dumps(results))


if __name__ == "__main__":
    main()
