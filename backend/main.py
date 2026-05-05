import asyncio
import sys
import json
import shutil
import uuid

# Playwright requires ProactorEventLoop on Windows to spawn subprocesses
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
from pathlib import Path
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from utils.resume_io import extract_text
from agents.resume_parser import parse_resume
from agents.ats_scorer import score_resume
from agents.resume_fixer import apply_all_fixes, save_fixed_docx
from agents.job_search import search_jobs
from agents.referral_finder import find_referrals_for_leads
from agents.application_agent import apply_to_job, generate_cover_letter
from db.tracker import save_leads, get_leads, save_profile, get_profile, already_applied

app = FastAPI(title="Job Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOADS_DIR = Path("uploads")
OUTPUTS_DIR = Path("outputs")
UPLOADS_DIR.mkdir(exist_ok=True)
OUTPUTS_DIR.mkdir(exist_ok=True)

# ── In-memory session state ───────────────────────────────────────────────────
session: dict = {}


# ── Models ────────────────────────────────────────────────────────────────────
class FixRequest(BaseModel):
    approved_fix_ids: list[str]

class PreferencesRequest(BaseModel):
    target_role: str = ""
    location: str = "India"
    cover_letter_style: str = "per_job"  # per_job | generic | none
    apply_mode: str = "individual"        # individual | batch

class UserProfile(BaseModel):
    address: str = ""
    city: str = ""
    date_of_birth: str = ""
    gender: str = ""
    notice_period: str = ""
    current_ctc: str = ""
    expected_ctc: str = ""
    total_experience: str = ""
    work_authorization: str = ""

class ApplyRequest(BaseModel):
    approved_lead_urls: list[str]
    apply_mode: str = "individual"
    cover_letter_style: str = "per_job"


# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/api/resume/upload")
async def upload_resume(file: UploadFile = File(...)):
    ext = Path(file.filename).suffix.lower()
    if ext not in [".pdf", ".docx"]:
        raise HTTPException(400, "Only PDF and DOCX files are supported")

    file_id = str(uuid.uuid4())
    save_path = UPLOADS_DIR / f"{file_id}{ext}"
    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    resume_text = extract_text(str(save_path))
    parsed      = await parse_resume(resume_text)

    session["file_id"]     = file_id
    session["file_path"]   = str(save_path)
    session["resume_text"] = resume_text
    session["parsed"]      = parsed

    return {"file_id": file_id, "parsed": parsed}


@app.get("/api/resume/ats")
async def get_ats_score():
    if "resume_text" not in session:
        raise HTTPException(400, "No resume uploaded")
    target = session.get("preferences", {}).get("target_role", "")
    report = await score_resume(session["resume_text"], target)
    session["ats_report"] = report
    return report


@app.post("/api/resume/fix")
async def fix_resume(req: FixRequest):
    if "ats_report" not in session:
        raise HTTPException(400, "Run ATS score first")

    all_fixes      = session["ats_report"].get("fixes", [])
    approved_fixes = [f for f in all_fixes if f["id"] in req.approved_fix_ids]

    fixed_text = await apply_all_fixes(session["resume_text"], approved_fixes)
    session["fixed_text"] = fixed_text

    output_path = str(OUTPUTS_DIR / f"{session['file_id']}_fixed.docx")
    save_fixed_docx(session["file_path"], fixed_text, output_path)
    session["fixed_path"] = output_path

    return {"message": f"Applied {len(approved_fixes)} fixes", "download_ready": True}


@app.get("/api/resume/download-fixed")
async def download_fixed():
    path = session.get("fixed_path")
    if not path or not Path(path).exists():
        raise HTTPException(404, "Fixed resume not found")
    return FileResponse(path, filename="Resume_Updated.docx")


@app.post("/api/preferences")
async def set_preferences(prefs: PreferencesRequest):
    session["preferences"] = prefs.dict()
    return {"message": "Preferences saved"}


@app.post("/api/profile")
async def save_user_profile(profile: UserProfile):
    save_profile(profile.dict())
    session["profile"] = profile.dict()
    return {"message": "Profile saved"}


@app.get("/api/jobs/search")
async def search_for_jobs():
    if "parsed" not in session:
        raise HTTPException(400, "No resume uploaded")

    prefs    = session.get("preferences", {})
    leads    = await search_jobs(session["parsed"], prefs.get("target_role", ""), prefs.get("location", "India"))
    leads    = await find_referrals_for_leads(leads)
    save_leads(leads)
    session["leads"] = leads
    return {"leads": leads}


@app.get("/api/jobs/leads")
async def get_job_leads():
    return {"leads": get_leads()}


@app.post("/api/jobs/apply")
async def apply_to_jobs(req: ApplyRequest):
    parsed  = session.get("parsed", {})
    profile = session.get("profile") or get_profile()
    leads   = session.get("leads", get_leads())
    prefs   = session.get("preferences", {})

    approved = [l for l in leads if l["url"] in req.approved_lead_urls]
    resume_path = session.get("fixed_path") or session.get("file_path", "")

    cover_letter_cache: dict[str, str] = {}

    async def run_apply():
        results = []
        for job in approved:
            url = job["url"]
            # LinkedIn search pages can't be auto-applied
            if "linkedin.com/jobs/search" in url:
                r = {"url": url, "title": job.get("title", ""), "status": "manual_action",
                     "reason": "LinkedIn search page — open manually to apply"}
                yield json.dumps(r) + "\n"
                continue

            if already_applied(url):
                yield json.dumps({"url": url, "title": job.get("title",""), "status": "skipped", "reason": "Already applied"}) + "\n"
                continue

            style = req.cover_letter_style
            if style != "none":
                cache_key = "generic" if style == "generic" else url
                if cache_key not in cover_letter_cache:
                    cover_letter_cache[cache_key] = await generate_cover_letter(job, parsed, style)
                cover_letter = cover_letter_cache[cache_key]
            else:
                cover_letter = ""

            result = await apply_to_job(
                job=job,
                parsed_resume=parsed,
                user_profile=profile,
                cover_letter=cover_letter,
                resume_path=resume_path,
            )
            yield json.dumps(result) + "\n"

    return StreamingResponse(run_apply(), media_type="application/x-ndjson")


@app.get("/api/health")
async def health():
    return {"status": "ok"}
