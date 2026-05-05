import asyncio
from duckduckgo_search import DDGS


def _ddg_search(query: str, max_results: int = 5) -> list[dict]:
    try:
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))
    except Exception:
        return []


async def find_referrals(company: str, role: str) -> dict:
    recruiter_query  = f'site:linkedin.com/in "{company}" recruiter OR "talent acquisition" OR "HR"'
    employee_query   = f'site:linkedin.com/in "{company}" "{role}" OR "software engineer" OR "developer"'

    recruiter_raw, employee_raw = await asyncio.gather(
        asyncio.to_thread(_ddg_search, recruiter_query, 5),
        asyncio.to_thread(_ddg_search, employee_query,  5),
    )

    def parse_profiles(raw: list[dict]) -> list[dict]:
        profiles = []
        for r in raw:
            url = r.get("href", "")
            if "linkedin.com/in/" in url:
                profiles.append({
                    "name":    r.get("title", "").split(" | ")[0].strip(),
                    "url":     url,
                    "snippet": r.get("body", "")[:150],
                })
        return profiles

    return {
        "company":    company,
        "recruiters": parse_profiles(recruiter_raw),
        "employees":  parse_profiles(employee_raw),
    }


async def find_referrals_for_leads(leads: list[dict]) -> list[dict]:
    tasks = [
        find_referrals(
            lead.get("company") or _extract_company(lead.get("title", "")),
            "software engineer",
        )
        for lead in leads
    ]
    results = await asyncio.gather(*tasks)
    for lead, referral in zip(leads, results):
        lead["referrals"] = referral
    return leads


def _extract_company(title: str) -> str:
    parts = title.split(" at ")
    return parts[-1].strip() if len(parts) > 1 else title.split("-")[-1].strip()
