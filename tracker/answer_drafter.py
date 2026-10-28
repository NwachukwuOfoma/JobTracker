import base64
import json
import re
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from tracker.config import setup_logging
from tracker.database import get_job_descriptions, get_tracked_jobs, save_job_descriptions
from tracker.fit_scorer import find_latest_resume, load_resume
from tracker.job_details import fetch_description
from tracker.normalizer import load_page_links, tab_key
from tracker.salary_estimator import _load_api_key

logger = setup_logging()

# Drafts answers to an application's open-ended questions ("Why us?", "Describe a
# project...") in the candidate's voice, for the Chrome extension's answer panel.
# First drafts use Haiku (about 0.1 cents a page): given the job description it
# writes specific answers. Redo, used on a draft the candidate didn't like, uses
# Sonnet (2-3 cents), which writes tighter and less generic. Server-side refusal
# fallbacks aren't offered for Haiku, so a refusal is just reported.
MODEL = "claude-haiku-5-5"
REDRAFT_MODEL = "claude-sonnet-5-5"
# What the candidate has actually done, beyond the resume. Personal, so it lives
# outside the repository; answers may only use facts from here, the resume or the note.
FACTS_FILE = Path.home() / ".config" / "jobtracker" / "answer_facts.md"
MAX_PAGE_CHARS = 8000
# Answers the candidate approved (filled in or copied), one JSON object per line. Similar
# past answers are shown when drafting, so their stories and angles carry over.
HISTORY_FILE = Path.home() / ".config" / "jobtracker" / "answer_history.jsonl"
MAX_EXAMPLES = 40
STOPWORDS = set("a an and are as at be by can describe did do does for from has have how i in is it its me of on or our please share tell that the this to us was we were what when where which who why will with you your".split())

STYLE = """You draft answers to the open-ended questions on a job application, written as the candidate in the first person. They paste your answers in as their own, so write the way a thoughtful person writes, not like marketing copy.

Grounding:
- Build answers from <resume>, <facts>, and the candidate's note for that question. When an answer needs a detail you don't have, write a believable one that fits their actual background and experience, and the candidate will correct it if needed. Always give a complete, ready-to-paste answer: never leave gaps, placeholders or brackets.
- Keep filled-in details modest: no made-up precise metrics, percentages, user counts or tools they haven't used.
- The <facts> file lists things that are NOT true about some projects. Never say those.
- When a question asks for a link, use one from <facts> or the resume.
- Refer to other people by role ("my manager", "the CTO") and never give them a he/she you weren't told.
- When a note is given ("say it was...", "talk about..."), it is the substance of the answer. Follow it exactly and don't swap in a different example.

Length and form:
- Default to 1-3 sentences: one sentence when the question is simple, up to three only when it genuinely needs more. Go beyond three sentences only when the question explicitly sets a length (e.g. "in 2-3 sentences", "200-400 words", "in a paragraph", a character limit that invites more) or the note asks for it, and then match that expectation.
- Keep sentences tight, around 30 words or fewer; don't pack a whole paragraph into one long sentence.
- Three sentences is a hard maximum unless the question sets a length. A multi-part question still gets at most three: cover the parts briefly rather than adding sentences.
- Stay well under any character limit you're given (count characters, spaces included). Word limits too.
- Plain sentences and paragraphs. No bullet points, headings, bold or emojis unless the question asks for a list (e.g. "list your skills"); then give a plain comma-separated line.
- Always write in English.

Voice:
- Every sentence should carry something specific: a named project, a concrete decision they made, or a true detail from the job description. Cut sentences that would fit any candidate or any company ("I'd like to bring that ownership to a fast-moving team").
- Questions about the person ("Why do you want to work here?", "Why are you a good fit?", "What motivates you?", "Tell us about yourself") are about mindset, interests and what they can do with their Master's training. Don't turn these into a tour of their projects or a list of tools.
- "Why this company" answers should name something specific and true about the company from the job description, not generic praise.
- Vary wording between answers; never reuse an opening across questions.
- Never use these phrases or close variants: "autonomous AI pipelines", "automated data workflows", "real-time visual outputs", "end-to-end product lifecycle", "low-latency, production-grade systems", "solving complex infrastructure challenges", "high-velocity engineering", "my background in [project]", "perfectly aligns", "I am eager to leverage", "passionate about leveraging", "the intersection of", "cutting-edge", "seamless".
- Don't overclaim seniority. This is a new grad with internships, an AI Master's and real shipped projects.

Past answers:
- <past_answers> holds answers the candidate approved for earlier applications, with the note they gave. Most will be unrelated; for a question that asks for the same kind of story (even worded differently), reuse the same story, angle and details (the candidate signed off on them), rewritten for this company and question rather than copied word for word. A note on the current question always wins over a past answer.

Give one answer per question, in the order given."""


def _load_facts() -> str:
    try:
        return FACTS_FILE.read_text().strip()
    except OSError:
        return ""


def _words(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9+#]+", text.lower()) if w not in STOPWORDS and len(w) > 2}


def _load_history() -> List[Dict]:
    try:
        lines = HISTORY_FILE.read_text().splitlines()
    except OSError:
        return []
    history = []
    for line in lines:
        try:
            history.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return history


def _similar_examples(questions: List[Dict]) -> List[Dict]:
    """
    Past answers to show the model: those whose questions share the most words with
    these ones, topped up with the most recent. Word overlap misses rephrasings
    ("vague problem" vs "ambiguity"), so the model judges which are actually similar.
    """
    history = _load_history()
    scored = {}
    for q in questions:
        words = _words(q["label"])
        for i, past in enumerate(history):
            other = _words(past["question"])
            if words and other:
                scored[i] = max(scored.get(i, 0), len(words & other) / len(words | other))
    # Best matches first; among equals (and for the top-up), the newest first
    ranked = sorted(range(len(history)), key=lambda i: (scored.get(i, 0) >= 0.15, scored.get(i, 0), i), reverse=True)
    return [history[i] for i in ranked[:MAX_EXAMPLES]]


def save_answer(urls: List[str], question: str, note: str, answer: str) -> Dict:
    """Records an answer the candidate filled in or copied (the latest copy of each replaces older ones)."""
    if not question or not answer.strip():
        return {"saved": False}
    job = _find_job(urls)
    entry = {
        "question": question, "note": note, "answer": answer.strip(),
        "company": job["company"] if job else "", "date": date.today().isoformat(),
    }
    history = [h for h in _load_history() if not (h["question"] == question and h.get("company") == entry["company"])]
    history.append(entry)
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text("".join(json.dumps(h) + "\n" for h in history))
    return {"saved": True}


def _find_job(urls: List[str]) -> Optional[Dict]:
    """The tracked job one of these page URLs belongs to, if any: matched as loosely as
    the extension's job-tab count, including company pages a LinkedIn job led to."""
    links = load_page_links()
    wanted = set()
    for url in urls:
        if url and url.startswith("http"):
            try:
                key = tab_key(url)
                wanted.update({key, links.get(key, key)})
            except Exception:
                pass
    if not wanted:
        return None
    for job in get_tracked_jobs().values():
        keys = {tab_key(link) for link in (job["normalized_url"], job.get("original_url"), job.get("apply_url")) if link}
        if keys & wanted:
            return job
    return None


# A question that sets its own length ("in 2-3 sentences", "200 words", "a paragraph")
LENGTH_ASKED = re.compile(r"\b\d+\s*(?:[-–]|to)?\s*\d*\s*(?:words?|characters?|sentences?|paragraphs?)\b|\bparagraphs?\b|in detail|elaborate", re.I)


def _sentences(text: str) -> int:
    return len(re.findall(r"[.!?](?=\s|$)", text.strip()))


def draft_answers(urls: List[str], page_title: str, page_text: str, questions: List[Dict], retry_long: bool = True) -> Dict:
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
        # Never read yet (e.g. a job marked applied before it was scored): without it,
        # "Why us?" answers have only the application form to go on. Workable
        # rate-limits, so its jobs are left to the fit scorer's single request.
        if not description and "workable.com" not in job["normalized_url"]:
            description = fetch_description(job.get("original_url") or job["normalized_url"], attempts=1)
            if description:
                save_job_descriptions({job["normalized_url"]: description})
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
    past = ""
    examples = _similar_examples(questions)
    if examples:
        past = "<past_answers>\n" + "\n\n".join(
            f"Question: {e['question']}\n" + (f"Note: {e['note']}\n" if e.get("note") else "") + f"Approved answer: {e['answer']}"
            for e in examples
        ) + "\n</past_answers>\n\n"
    user = (
        f"<job>\n{about_job}\n\n{context or '(no description available)'}\n</job>\n\n"
        + past
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
        response = client.messages.create(
            model=REDRAFT_MODEL if any(q.get("previous") for q in questions) else MODEL,
            max_tokens=16000,
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
    # Drafts sometimes run past the three-sentence cap; shorten those once
    if retry_long:
        long = [i for i, (q, a) in enumerate(zip(questions, answers))
                if _sentences(a) > 3 and not LENGTH_ASKED.search(f"{q['label']} {q.get('note', '')}")]
        if long:
            shorter = draft_answers(urls, page_title, page_text, [
                {**questions[i], "previous": "", "note": f"{questions[i].get('note', '')} Rewrite this draft in at most three sentences, keeping its story: {answers[i]}".strip()}
                for i in long
            ], retry_long=False).get("answers", [])
            for i, answer in zip(long, shorter):
                if answer and _sentences(answer) < _sentences(answers[i]):
                    answers[i] = answer
    return {"answers": answers, "job": f"{job['company']} - {job['title']}" if job else ""}



# Standard answers for the rest of an application (contact details, eligibility,
# logistics, demographics) that the panel's "Fill rest" matches to form fields itself,
# without any API calls. Personal, so it lives outside the repository.
PROFILE_FILE = Path.home() / ".config" / "jobtracker" / "application_profile.json"


def load_profile() -> Dict:
    try:
        return {"profile": json.loads(PROFILE_FILE.read_text())}
    except (OSError, json.JSONDecodeError) as e:
        return {"error": f"Couldn't read {PROFILE_FILE}: {e}"}


def resume_for_upload() -> Dict:
    """The newest resume, base64-encoded for the extension to attach to an application."""
    path = find_latest_resume()
    if not path:
        return {"error": "No resume found (looked for NwachukwuOfomaResume in Downloads, Documents and Desktop)."}
    types = {".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
    return {"name": path.name, "type": types.get(path.suffix.lower(), "application/octet-stream"),
            "data": base64.b64encode(path.read_bytes()).decode()}
