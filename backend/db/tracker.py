from tinydb import TinyDB, Query
from pathlib import Path

DB_PATH = Path(__file__).parent / "jobs.json"
db = TinyDB(DB_PATH)
applied_table = db.table("applied")
leads_table   = db.table("leads")
profile_table = db.table("user_profile")

Job = Query()


def mark_applied(url: str, title: str, company: str):
    if not applied_table.search(Job.url == url):
        applied_table.insert({"url": url, "title": title, "company": company})


def already_applied(url: str) -> bool:
    return bool(applied_table.search(Job.url == url))


def save_leads(leads: list[dict]):
    leads_table.truncate()
    leads_table.insert_multiple(leads)


def get_leads() -> list[dict]:
    return leads_table.all()


def save_profile(profile: dict):
    profile_table.truncate()
    profile_table.insert(profile)


def get_profile() -> dict:
    rows = profile_table.all()
    return rows[0] if rows else {}
