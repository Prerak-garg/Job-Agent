# Job Agent

An AI-powered job search assistant that automates resume optimization and referral discovery. Upload your resume (PDF/DOCX), get ATS-optimized rewrites via local LLMs, find LinkedIn recruiters and employees at target companies, and track your job applications — all running locally with no API keys required.

---

## Prerequisites

Make sure you have the following installed before getting started:

### 1. Python 3.10+
Download from: https://python.org/downloads

### 2. Node.js 18+
Download from: https://nodejs.org

### 3. Ollama (Local LLM Runner)
Ollama runs the AI models locally on your machine — no API keys or internet connection needed for inference.

Download from: https://ollama.com/download

After installing, pull the required models:
```bash
ollama pull llama3.2:3b
ollama pull qwen2.5:7b
```

Make sure Ollama is running before starting the app:
```bash
ollama serve
```

### 4. Playwright Browsers
Used for web automation. After installing Python dependencies, run:
```bash
playwright install
```

---

## Setup & Run

### Backend

```bash
cd backend
pip install -r requirements.txt
playwright install
uvicorn main:app --reload
```

The backend will start at `http://localhost:8000`

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend will start at `http://localhost:3000`

---

## Features

- **Resume Optimizer** — Upload your resume and get ATS-friendly rewrites powered by local LLMs
- **Referral Finder** — Discover LinkedIn recruiters and employees at target companies
- **Application Tracker** — Keep track of jobs you've applied to

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js, TypeScript, Tailwind CSS |
| Backend | FastAPI, Python |
| AI Models | Ollama (llama3.2:3b, qwen2.5:7b) |
| Database | TinyDB |
| Search | DuckDuckGo Search API |
| Resume Parsing | PyPDF2, python-docx |
