"""
Standalone Playwright apply worker — called as a subprocess from application_agent.py.
Runs in its own fresh Python process, no asyncio event loop conflicts.

Args (sys.argv):
  1: JSON-encoded dict with keys: job, parsed_resume, user_profile, cover_letter, resume_path

Output: JSON dict to stdout.
"""
import sys
import json
import random
import time
import httpx
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

OLLAMA_BASE = "http://localhost:11434"
SCREENSHOTS_DIR = Path(__file__).parent / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)

ESSAY_PROMPT = """Answer this job application question professionally in 2-4 sentences.
Question: {question}
Applicant: {background}
Job: {title} at {company}
Return only the answer text."""


def _chat_sync(prompt: str) -> str:
    try:
        resp = httpx.post(
            f"{OLLAMA_BASE}/api/chat",
            json={"model": "qwen2.5:7b", "messages": [{"role": "user", "content": prompt}], "stream": False},
            timeout=60,
        )
        return resp.json()["message"]["content"].strip()
    except Exception:
        return ""


def _extract_company(title: str) -> str:
    parts = title.split(" at ")
    return parts[-1].strip() if len(parts) > 1 else ""


def _url_slug(url: str) -> str:
    return url.rstrip("/").split("/")[-1][:40] or "job"


def _fill_form(page, parsed_resume: dict, user_profile: dict,
               cover_letter: str, resume_path: str, job: dict):
    """Fill all form fields on the current page."""
    field_map = {
        "input[name*='name' i]":        parsed_resume.get("name", ""),
        "input[type='email']":           parsed_resume.get("email", ""),
        "input[type='tel']":             parsed_resume.get("phone", ""),
        "input[name*='address' i]":      user_profile.get("address", ""),
        "input[name*='city' i]":         user_profile.get("city", ""),
        "input[name*='linkedin' i]":     parsed_resume.get("linkedin", ""),
        "input[name*='github' i]":       parsed_resume.get("github", ""),
        "input[name*='notice' i]":       user_profile.get("notice_period", ""),
        "input[name*='salary' i]":       user_profile.get("expected_ctc", ""),
        "input[name*='experience' i]":   user_profile.get("total_experience", ""),
    }
    for sel, value in field_map.items():
        if value:
            try:
                page.fill(sel, str(value))
                time.sleep(random.uniform(0.2, 0.5))
            except Exception:
                pass

    # Upload resume
    for fi in page.query_selector_all("input[type='file']"):
        try:
            accept = fi.get_attribute("accept") or ""
            if "pdf" in accept.lower() and not resume_path.endswith(".pdf"):
                continue
            fi.set_input_files(resume_path)
            time.sleep(1.5)
            break
        except Exception:
            pass

    # Cover letter textarea
    if cover_letter:
        for sel in ["textarea[name*='cover' i]", "textarea[name*='letter' i]",
                    "textarea[placeholder*='cover' i]"]:
            try:
                el = page.query_selector(sel)
                if el:
                    el.fill(cover_letter)
                    time.sleep(0.3)
                    break
            except Exception:
                pass

    # Answer unknown textarea questions via Ollama
    company = job.get("company") or _extract_company(job.get("title", ""))
    for ta in page.query_selector_all("textarea"):
        try:
            if ta.input_value():
                continue
            label = page.evaluate(
                """el => {
                    const id = el.id;
                    if (id) { const l = document.querySelector('label[for="'+id+'"]'); if (l) return l.innerText; }
                    return el.placeholder || el.getAttribute('aria-label') || el.name || '';
                }""", ta)
            if label and len(label) > 5:
                answer = _chat_sync(ESSAY_PROMPT.format(
                    question=label,
                    background=f"{parsed_resume.get('name','')} — {parsed_resume.get('summary','')}",
                    title=job.get("title", ""),
                    company=company,
                ))
                if answer:
                    ta.fill(answer)
                    time.sleep(0.3)
        except Exception:
            pass


def apply_sync(job: dict, parsed_resume: dict, user_profile: dict,
               cover_letter: str, resume_path: str) -> dict:
    url    = job.get("url", "")
    result = {"url": url, "title": job.get("title", ""), "status": "pending"}

    # LinkedIn search pages can't be auto-applied — send user there manually
    if "linkedin.com/jobs/search" in url:
        result["status"] = "manual_action"
        result["reason"] = "LinkedIn search page — open manually to apply"
        return result

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, slow_mo=40)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        try:
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            time.sleep(random.uniform(1, 2))

            # Find Apply button
            apply_btn = None
            for sel in ["button:has-text('Apply')", "a:has-text('Apply')",
                        "button:has-text('Easy Apply')", "a[href*='apply']",
                        "[data-automation='job-detail-apply']"]:
                try:
                    apply_btn = page.wait_for_selector(sel, timeout=3000)
                    if apply_btn:
                        break
                except PWTimeout:
                    continue

            if not apply_btn:
                result["status"] = "manual_action"
                result["reason"] = "Apply button not found"
                browser.close()
                return result

            # Click Apply — watch for a popup/new tab opening
            pages_before = len(context.pages)
            apply_btn.click()
            time.sleep(random.uniform(1.5, 2.5))

            # Switch to the new page if Apply opened a popup/new tab
            if len(context.pages) > pages_before:
                page = context.pages[-1]
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=10000)
                except Exception:
                    pass
                time.sleep(1)

            # CAPTCHA check
            if page.query_selector("iframe[src*='recaptcha'], .h-captcha, iframe[src*='hcaptcha']"):
                result["status"] = "manual_action"
                result["reason"] = "CAPTCHA detected"
                browser.close()
                return result

            # Fill form fields
            _fill_form(page, parsed_resume, user_profile, cover_letter, resume_path, job)

            # Screenshot before submit
            preview_path = str(SCREENSHOTS_DIR / f"{_url_slug(url)}_preview.png")
            page.screenshot(path=preview_path, full_page=True)
            result["screenshot"] = preview_path

            # Submit
            submitted = False
            for sel in ["button[type='submit']", "button:has-text('Submit')",
                        "button:has-text('Send Application')", "input[type='submit']"]:
                try:
                    btn = page.wait_for_selector(sel, timeout=3000)
                    if btn:
                        btn.click()
                        time.sleep(2.5)
                        submitted = True
                        break
                except PWTimeout:
                    continue

            final_path = str(SCREENSHOTS_DIR / f"{_url_slug(url)}_submitted.png")
            page.screenshot(path=final_path, full_page=True)

            if submitted:
                result["status"] = "applied"
                result["confirmation_screenshot"] = final_path
            else:
                result["status"] = "manual_action"
                result["reason"] = "Submit button not found"

        except PWTimeout:
            result["status"] = "manual_action"
            result["reason"]  = "Page timed out"
        except Exception as e:
            result["status"] = "error"
            result["reason"]  = str(e)
        finally:
            browser.close()

    return result


def main():
    payload = json.loads(sys.argv[1])
    result = apply_sync(
        job=payload["job"],
        parsed_resume=payload["parsed_resume"],
        user_profile=payload["user_profile"],
        cover_letter=payload["cover_letter"],
        resume_path=payload["resume_path"],
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
