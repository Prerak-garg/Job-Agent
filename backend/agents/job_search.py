import json
import asyncio
import subprocess
import sys
from pathlib import Path
from utils.ollama_client import chat

WORKER_PATH = Path(__file__).parent.parent / "playwright_worker.py"

SYSTEM = """You are a job matching expert. Return ONLY valid JSON."""

MATCH_PROMPT = """Rate how well this resume matches this job listing.

Job Title: {title}
Job Description snippet: {description}
Resume skills: {skills}
Resume experience: {experience}

Return JSON:
{{
  "match_score": <0-100>,
  "matched_skills": [],
  "missing_skills": [],
  "verdict": "<Strong Match|Good Match|Partial Match|Weak Match>"
}}"""


# ── Playwright scrape via subprocess (avoids Windows asyncio event loop conflict) ─
def _scrape_via_subprocess(urls_with_source: list[tuple[str, str]]) -> list[dict]:
    proc = subprocess.run(
        [sys.executable, str(WORKER_PATH), json.dumps(urls_with_source)],
        capture_output=True, text=True, timeout=180,
    )
    if proc.stderr:
        print(proc.stderr, end="")
    if proc.returncode == 0 and proc.stdout.strip():
        return json.loads(proc.stdout)
    print(f"[job_search] worker failed (exit {proc.returncode}): {proc.stderr[-300:]}")
    return []


async def _scrape_pages(urls_with_source: list[tuple[str, str]]) -> list[dict]:
    return await asyncio.to_thread(_scrape_via_subprocess, urls_with_source)


# ── LinkedIn search links (scraping blocked without login) ────────────────────
def _linkedin_leads(keywords: list[str], location: str) -> list[dict]:
    leads = []
    for kw in keywords:
        kw_enc  = kw.replace(" ", "%20")
        loc_enc = location.replace(" ", "%20")
        leads.append({
            "title":   f"LinkedIn Jobs — {kw}",
            "url":     f"https://www.linkedin.com/jobs/search/?keywords={kw_enc}&location={loc_enc}&f_TPR=r604800",
            "snippet": f"Click to browse LinkedIn for '{kw}' jobs in {location} (last 7 days)",
            "source":  "LinkedIn",
            "company": "",
        })
    return leads


# ── Keyword builder ───────────────────────────────────────────────────────────
def _flatten_skills(skills) -> list[str]:
    """Accept skills as list OR dict-of-lists and return a flat list."""
    if isinstance(skills, list):
        return [s for s in skills if isinstance(s, str)]
    if isinstance(skills, dict):
        out = []
        for v in skills.values():
            if isinstance(v, list):
                out.extend(s for s in v if isinstance(s, str))
        return out
    return []


def _build_keywords(parsed_resume: dict, target_role: str) -> list[str]:
    flat = _flatten_skills(parsed_resume.get("skills", {}))
    role = target_role or (parsed_resume.get("experience", [{}])[0].get("title", "") if parsed_resume.get("experience") else "Professional")

    # Build 3 search keyword strings from progressively fewer skills
    seen, keywords = set(), []
    for n in [3, 2, 0]:
        kw = f"{role} {' '.join(flat[:n])}".strip() if n else role
        if kw not in seen:
            seen.add(kw)
            keywords.append(kw)
    return keywords[:3]


def _naukri_url(keyword: str, location: str) -> str:
    slug = keyword.lower().replace(" ", "-")
    loc  = location.lower().replace(" ", "-")
    if loc in ("india", ""):
        return f"https://www.naukri.com/{slug}-jobs?experience=3"
    return f"https://www.naukri.com/{slug}-jobs-in-{loc}?experience=3"


def _indeed_url(keyword: str, location: str) -> str:
    kw  = keyword.replace(" ", "+")
    loc = location.replace(" ", "+") or "India"
    return f"https://in.indeed.com/jobs?q={kw}&l={loc}&fromage=14&sort=date"


# ── Main search ───────────────────────────────────────────────────────────────
async def search_jobs(parsed_resume: dict, target_role: str, location: str) -> list[dict]:
    keywords = _build_keywords(parsed_resume, target_role)
    loc      = location or "India"

    pages_to_scrape = []
    for kw in keywords[:2]:                         # 2 Naukri + 1 Indeed
        pages_to_scrape.append((_naukri_url(kw, loc), "Naukri"))
    pages_to_scrape.append((_indeed_url(keywords[0], loc), "Indeed"))

    scraped  = await _scrape_pages(pages_to_scrape)
    linkedin = _linkedin_leads(keywords, loc)

    raw = scraped + linkedin

    # Deduplicate
    seen, unique = set(), []
    for r in raw:
        url = r.get("url", "")
        if url and url not in seen:
            seen.add(url)
            unique.append(r)

    print(f"[job_search] {len(unique)} unique leads — scoring now")
    if not unique:
        return []

    scored = await _score_leads(unique, parsed_resume)
    scored.sort(key=lambda x: x.get("match_score", 0), reverse=True)
    return scored[:25]


# ── Scoring ───────────────────────────────────────────────────────────────────
async def _score_leads(leads: list[dict], parsed_resume: dict) -> list[dict]:
    skills_str = ", ".join(_flatten_skills(parsed_resume.get("skills", {}))[:20])

    exp     = parsed_resume.get("experience", [])
    exp_str = " | ".join(
        f"{e.get('title', '')} at {e.get('company', '')}" for e in exp[:2]
    )

    scored = []
    for lead in leads:
        try:
            result = await chat(
                prompt=MATCH_PROMPT.format(
                    title=lead["title"],
                    description=lead["snippet"][:400],
                    skills=skills_str,
                    experience=exp_str,
                ),
                model="fast",
                system=SYSTEM,
                json_mode=True,
            )
            data = json.loads(result)
            lead.update(data)
        except Exception as e:
            print(f"[scoring] {e}")
            lead["match_score"] = 50
            lead["verdict"]     = "Unknown"
        scored.append(lead)
    return scored
