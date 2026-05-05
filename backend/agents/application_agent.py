import asyncio
import json
import subprocess
import sys
from pathlib import Path
from utils.ollama_client import chat
from db.tracker import mark_applied, already_applied

WORKER_PATH = Path(__file__).parent.parent / "apply_worker.py"

COVER_LETTER_PROMPT = """Write a concise, professional cover letter for this job application.

Applicant: {name}
Role applying for: {title} at {company}
Key skills: {skills}
Recent experience: {experience}
Job description: {jd_snippet}
Style: {style}
Keep it under 250 words. Return only the cover letter text."""


# ── Cover letter (async, called before browser) ───────────────────────────────
async def generate_cover_letter(job: dict, parsed_resume: dict, style: str) -> str:
    if style == "none":
        return ""
    raw_skills = parsed_resume.get("skills", {})
    if isinstance(raw_skills, list):
        flat_skills = raw_skills
    else:
        flat_skills = []
        for v in raw_skills.values():
            if isinstance(v, list):
                flat_skills.extend(v)
    skills = ", ".join(flat_skills[:8])
    exp     = parsed_resume.get("experience", [])
    exp_str = f"{exp[0]['title']} at {exp[0]['company']}" if exp else ""
    company = job.get("company") or _extract_company(job.get("title", ""))
    return await chat(
        prompt=COVER_LETTER_PROMPT.format(
            name=parsed_resume.get("name", ""),
            title=job.get("title", ""),
            company=company,
            skills=skills,
            experience=exp_str,
            jd_snippet=job.get("snippet", "")[:400],
            style="tailored and specific" if style == "per_job" else "generic and professional",
        ),
        model="smart",
    )


# ── Subprocess call to apply_worker.py ────────────────────────────────────────
def _apply_via_subprocess(job: dict, parsed_resume: dict, user_profile: dict,
                          cover_letter: str, resume_path: str) -> dict:
    payload = json.dumps({
        "job": job,
        "parsed_resume": parsed_resume,
        "user_profile": user_profile,
        "cover_letter": cover_letter,
        "resume_path": resume_path,
    })
    proc = subprocess.run(
        [sys.executable, str(WORKER_PATH), payload],
        capture_output=True, text=True, timeout=300,
    )
    if proc.stderr:
        print(proc.stderr, end="")
    if proc.returncode == 0 and proc.stdout.strip():
        result = json.loads(proc.stdout)
        if result.get("status") == "applied":
            company = job.get("company") or _extract_company(job.get("title", ""))
            mark_applied(job.get("url", ""), job.get("title", ""), company)
        return result
    print(f"[apply_worker] failed (exit {proc.returncode}): {proc.stderr[-300:]}")
    return {"url": job.get("url", ""), "title": job.get("title", ""),
            "status": "error", "reason": "Worker process failed"}


# ── Public async entry point ──────────────────────────────────────────────────
async def apply_to_job(job: dict, parsed_resume: dict, user_profile: dict,
                       cover_letter: str, resume_path: str,
                       confirm_callback=None) -> dict:
    url = job.get("url", "")
    if already_applied(url):
        return {"status": "skipped", "reason": "Already applied", "url": url}

    return await asyncio.to_thread(
        _apply_via_subprocess, job, parsed_resume, user_profile, cover_letter, resume_path
    )


def _extract_company(title: str) -> str:
    parts = title.split(" at ")
    return parts[-1].strip() if len(parts) > 1 else ""
