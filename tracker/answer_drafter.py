import json
from pathlib import Path
from typing import Dict, List, Optional

from tracker.config import setup_logging
from tracker.database import get_job_descriptions, get_tracked_jobs
from tracker.fit_scorer import load_resume
from tracker.normalizer import normalize_url
from tracker.salary_estimator import _load_api_key

logger = setup_logging()

# Drafts answers to an application's open-ended questions ("Why us?", "Describe a
# project...") in the candidate's voice, for the Chrome extension's answer panel.
MODEL = "claude-opus-5-5"
# What the candidate has actually done, beyond the resume. Personal, so it lives
# outside the repository; answers may only use facts from here, the resume or the note.
FACTS_FILE = Path.home() / ".config" / "jobtracker" / "answer_facts.md"
MAX_PAGE_CHARS = 8000

STYLE = """You draft answers to the open-ended questions on a job application, written as the candidate in the first person. They paste your answers in as their own, so write the way a thoughtful person writes, not like marketing copy.

Truthfulness comes first:
- Use only facts from <resume>, <facts>, and the candidate's note for that question. Never invent tools, architectures, numbers, user counts, metrics, results or experiences. If an answer needs a detail you don't have, write around it, or leave a short gap like [add: what the model's accuracy was] for the candidate to fill in.
- The <facts> file lists things that are NOT true about some projects. Never say those.
- Refer to other people by role ("my manager", "the CTO") and never give them a he/she you weren't told.
- When a note is given ("say it was...", "talk about..."), it is the substance of the answer. Follow it exactly and don't swap in a different example.

Length and form:
- Default to one or two sentences. Go longer only when the question asks for it (e.g. "200-400 words", "in 2-3 paragraphs") or the note does.
- Stay well under any character limit you're given (count characters, spaces included). Word limits too.
- Plain sentences and paragraphs. No bullet points, headings, bold or emojis unless the question asks for a list (e.g. "list your skills"); then give a plain comma-separated line.
- Always write in English.

Voice:
- Questions about the person ("Why do you want to work here?", "Why are you a good fit?", "What motivates you?", "Tell us about yourself") are about mindset, interests and what they can do with their Master's training. Don't turn these into a tour of their projects or a list of tools.
- "Why this company" answers should name something specific and true about the company from the job description, not generic praise.
- Vary wording between answers; never reuse an opening across questions.
- Never use these phrases or close variants: "autonomous AI pipelines", "automated data workflows", "real-time visual outputs", "end-to-end product lifecycle", "low-latency, production-grade systems", "solving complex infrastructure challenges", "high-velocity engineering", "my background in [project]", "perfectly aligns", "I am eager to leverage", "passionate about leveraging", "the intersection of", "cutting-edge", "seamless".
- Don't overclaim seniority. This is a new grad with internships, an AI Master's and real shipped projects.

Give one answer per question, in the order given."""


def _load_facts() -> str:
    try:
        return FACTS_FILE.read_text().strip()
    except OSError:
        return ""


def _find_job(urls: List[str]) -> Optional[Dict]:
    """The tracked job one of these page URLs belongs to, if any."""
    wanted = set()
    for url in urls:
        if url and url.startswith("http"):
            try:
                wanted.add(normalize_url(url))
            except Exception:
                pass
    if not wanted:
        return None
    for job in get_tracked_jobs().values():
        links = {job["normalized_url"]}
        for link in (job.get("original_url"), job.get("apply_url")):
            if link:
                links.add(normalize_url(link))
        if links & wanted:
            return job
    return None


def draft_answers(urls: List[str], page_title: str, page_text: str, questions: List[Dict]) -> Dict:
    """
    questions: [{"label", "max_length" (int or None), "note" (optional), "previous" (optional)}].
    Returns {"answers": [str, ...], "job": "Company - Title" or ""} or {"error": "..."}.
    """
    resume, _, _ = load_resume()
    key = _load_api_key()
    if not resume:
        return {"error": "No resume found (looked for NwachukwuOfomaResume in Downloads, Documents and Desktop)."}
    if not key:
        return {"error": "No Anthropic API key set up."}
    if not questions:
        return {"error": "No questions to answer."}
    import anthropic

    job = _find_job(urls)
    description = ""
    if job:
        description = get_job_descriptions([job["normalized_url"]]).get(job["normalized_url"], "")
    if job:
        about_job = f"Company: {job['company']}\nRole: {job['title']}"
    else:
        about_job = f"Page title: {page_title or 'unknown'} (work out the company and role from the page)"
    context = description or (page_text or "")[:MAX_PAGE_CHARS]

    lines = []
    for i, q in enumerate(questions, 1):
        lines.append(f"Question {i}: {q['label']}")
        if q.get("max_length"):
            lines.append(f"Character limit: {q['max_length']}")
        if q.get("note"):
            lines.append(f"Candidate's note: {q['note']}")
        if q.get("previous"):
            lines.append(f"The candidate didn't like this draft, so write a clearly different one: {q['previous']}")
        lines.append("")
    user = (
        f"<job>\n{about_job}\n\n{context or '(no description available)'}\n</job>\n\n"
        + "\n".join(lines)
    )
    system = [
        {"type": "text", "text": STYLE},
        # Stable across every request, so it's cached; the job and questions come after
        {"type": "text", "text": f"<resume>\n{resume}\n</resume>\n\n<facts>\n{_load_facts()}\n</facts>",
         "cache_control": {"type": "ephemeral"}},
    ]
    schema = {
        "type": "object",
        "properties": {"answers": {"type": "array", "items": {"type": "string"}}},
        "required": ["answers"],
        "additionalProperties": False,
    }
    client = anthropic.Anthropic(api_key=key, max_retries=3)
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
            system=system,
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.APIStatusError as e:
        logger.warning(f"Answer drafting failed: {e}")
        return {"error": f"Claude API error ({e.status_code})."}
    except anthropic.APIConnectionError:
        return {"error": "Couldn't reach the Claude API."}
    if response.stop_reason == "refusal":
        return {"error": "Claude declined to draft these answers."}
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        answers = json.loads(text)["answers"]
    except (json.JSONDecodeError, KeyError):
        return {"error": "Got an unreadable reply; try again."}
    answers = (answers + [""] * len(questions))[:len(questions)]
    return {"answers": answers, "job": f"{job['company']} - {job['title']}" if job else ""}
