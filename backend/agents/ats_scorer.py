import json
from utils.ollama_client import chat

SYSTEM = """You are an expert ATS (Applicant Tracking System) analyst and resume coach.
Analyse resumes deeply and return ONLY valid JSON. No markdown, no explanation."""

PROMPT = """Perform a detailed ATS analysis on this resume{role_context}.

Return a JSON object with this exact structure:
{{
  "score": <0-100 integer>,
  "grade": "<EXCELLENT|GOOD|NEEDS IMPROVEMENT>",
  "summary": "<2-sentence overall assessment>",
  "sections": {{
    "contact": {{"score": <0-10>, "issues": []}},
    "summary": {{"score": <0-10>, "issues": []}},
    "experience": {{"score": <0-25>, "issues": []}},
    "skills": {{"score": <0-20>, "issues": []}},
    "keywords": {{"score": <0-20>, "issues": []}},
    "impact": {{"score": <0-15>, "issues": []}}
  }},
  "fixes": [
    {{
      "id": "<unique_id>",
      "section": "<section name>",
      "severity": "<high|medium|low>",
      "issue": "<what is wrong>",
      "original": "<exact text from resume or empty string>",
      "suggestion": "<exact replacement text>",
      "reason": "<why this fix improves ATS score>"
    }}
  ],
  "missing_keywords": [],
  "strengths": []
}}

Resume:
{resume_text}"""


async def score_resume(resume_text: str, target_role: str = "") -> dict:
    role_context = f" for a {target_role} role" if target_role else " based on the candidate's own field and background"
    result = await chat(
        prompt=PROMPT.format(resume_text=resume_text, role_context=role_context),
        model="smart",
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
        return {"score": 0, "fixes": [], "error": "Parsing failed"}
