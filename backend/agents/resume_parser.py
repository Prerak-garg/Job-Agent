import json
from utils.ollama_client import chat

SYSTEM = """You are a resume parser. Extract structured data from the resume text and return ONLY valid JSON.
No explanation, no markdown, just the JSON object."""

PROMPT = """Parse this resume and return a JSON object with these exact keys:
{{
  "name": "",
  "email": "",
  "phone": "",
  "linkedin": "",
  "github": "",
  "summary": "",
  "experience": [{{"company": "", "title": "", "duration": "", "bullets": []}}],
  "projects": [{{"name": "", "stack": "", "bullets": []}}],
  "skills": [],
  "education": [{{"institution": "", "degree": "", "year": "", "score": ""}}],
  "certifications": [],
  "achievements": []
}}

"skills" must be a flat list of strings — include every skill, tool, domain area, competency, language, software, or technique mentioned. Do NOT use nested objects or categories.

Resume:
{resume_text}"""


async def parse_resume(resume_text: str) -> dict:
    result = await chat(
        prompt=PROMPT.format(resume_text=resume_text),
        model="fast",
        system=SYSTEM,
        json_mode=True,
    )
    try:
        return json.loads(result)
    except json.JSONDecodeError:
        import re
        match = re.search(r"\{.*\}", result, re.DOTALL)
        if match:
            return json.loads(match.group())
        return {}
