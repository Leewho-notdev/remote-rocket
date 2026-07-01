"""
app/components/resume_generator.py
Phase 2: Claude-powered resume tailoring + cover letter generation.

Given the master resume text and a job listing, produces a tailored resume and
a matching cover letter in one call. Optional `notes` steer a regeneration
(e.g. "emphasize more ROAS and Performance Max wins").

Prompts live in prompts/tailoring_prompts.yml so wording can be tuned without
touching code. Model defaults to Sonnet — quality matters for a document the
user actually sends to employers.
"""

import functools
import json
import logging
import os
import re

import anthropic
import yaml
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

log = logging.getLogger("remote-rocket.resume")

# Sonnet for tailoring (the document you send); cheap Haiku for the one-time
# structuring pass on upload. Both overridable via env.
MODEL = os.getenv("RESUME_MODEL", "claude-sonnet-4-6")
STRUCTURE_MODEL = os.getenv("STRUCTURE_MODEL", "claude-haiku-4-5-20251001")

MAX_JOB_CHARS = 8000
MAX_RESUME_CHARS = 14000

RESUME_MARK = "===TAILORED_RESUME==="
COVER_MARK = "===COVER_LETTER==="

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    return _client


@functools.lru_cache(maxsize=1)
def _prompt_path() -> str:
    """Locate tailoring_prompts.yml — container path first, then local dev."""
    candidates = [
        "/app/prompts/tailoring_prompts.yml",
        os.path.join(os.path.dirname(__file__), "..", "..", "prompts", "tailoring_prompts.yml"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    raise FileNotFoundError(
        "tailoring_prompts.yml not found (looked in /app/prompts and ../prompts)."
    )


def _load_prompts() -> dict:
    """Read prompts fresh each call so edits to the YAML take effect immediately."""
    with open(_prompt_path()) as f:
        return yaml.safe_load(f)


@retry(
    retry=retry_if_exception_type((anthropic.RateLimitError, anthropic.APIConnectionError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=4, max=30),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)
def _call_claude(system: str, prompt: str, model: str = MODEL, max_tokens: int = 4096) -> anthropic.types.Message:
    return _get_client().messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )


# ── One-time structuring pass (on upload) ──────────────────────────────────────

def structure_resume(raw_text: str) -> str | None:
    """
    Run a lightweight Claude (Haiku) pass to structure raw resume text into
    clean sections. Returns a JSON string, or None if structuring fails —
    callers fall back to the raw text, so this never blocks saving a resume.
    """
    if not (raw_text or "").strip():
        return None

    prompts = _load_prompts()
    prompt = prompts["structure"].format(resume_text=raw_text[:MAX_RESUME_CHARS])

    try:
        message = _call_claude(prompts["structure_system"], prompt,
                               model=STRUCTURE_MODEL, max_tokens=3000)
    except Exception as e:  # noqa: BLE001 — structuring is best-effort
        log.warning(f"Resume structuring failed (falling back to raw text): {e}")
        return None

    data = _parse_json(message.content[0].text)
    if data is None:
        log.warning("Resume structuring returned unparseable JSON; using raw text.")
        return None
    return json.dumps(data)


def structured_to_markdown(structured: dict) -> str:
    """Render structured resume JSON to clean markdown (preview + tailoring input)."""
    if not structured:
        return ""
    parts = []
    if structured.get("name"):
        parts.append(f"# {structured['name']}")

    contact = structured.get("contact") or {}
    bits = [contact.get("email"), contact.get("phone"), contact.get("location")]
    bits += list(contact.get("links") or [])
    bits = [b for b in bits if b]
    if bits:
        parts.append(" · ".join(bits))

    if structured.get("summary"):
        parts.append(f"\n## Summary\n{structured['summary']}")

    skills = structured.get("skills") or []
    if skills:
        parts.append("\n## Skills\n" + ", ".join(skills))

    experience = structured.get("experience") or []
    if experience:
        parts.append("\n## Experience")
        for role in experience:
            header = " — ".join(x for x in [role.get("title"), role.get("company")] if x)
            if role.get("dates"):
                header += f"  ({role['dates']})"
            if header:
                parts.append(f"\n### {header}")
            for bullet in (role.get("bullets") or []):
                parts.append(f"- {bullet}")

    education = structured.get("education") or []
    if education:
        parts.append("\n## Education")
        for ed in education:
            line = ", ".join(x for x in [ed.get("degree"), ed.get("institution")] if x)
            if ed.get("dates"):
                line += f" ({ed['dates']})"
            if line:
                parts.append(f"- {line}")

    certs = structured.get("certifications") or []
    if certs:
        parts.append("\n## Certifications")
        for c in certs:
            parts.append(f"- {c}")

    return "\n".join(parts).strip()


def resume_text_for_tailoring(master: dict) -> str:
    """
    Best resume text to feed the tailoring step: prefer the clean structured
    render, fall back to raw text if structuring wasn't available.
    """
    sj = master.get("structured_json")
    if sj:
        try:
            md = structured_to_markdown(json.loads(sj))
            if md.strip():
                return md
        except (json.JSONDecodeError, TypeError):
            pass
    return master.get("raw_text") or ""


def _parse_json(raw_text: str) -> dict | None:
    """Parse a JSON object from a model response, tolerating code fences."""
    text = _strip_fences(raw_text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                return None
    return None


def generate_tailored(job: dict, resume_text: str, notes: str = "") -> dict:
    """
    Generate a tailored resume + cover letter for a job.

    `job` needs title, company, and a description (description_clean/raw).
    `resume_text` is the master resume text. `notes` optionally steers the tone
    / emphasis for a regeneration.

    Returns {"tailored_resume": str, "cover_letter": str}.
    Raises RuntimeError with a user-friendly message on failure.
    """
    description = (
        job.get("description_clean")
        or job.get("description_raw")
        or ""
    ).strip()

    if not (resume_text or "").strip():
        raise RuntimeError("No master resume set up yet.")
    if not description:
        raise RuntimeError("This job has no description to tailor against.")

    prompts = _load_prompts()
    notes_block = ""
    if notes.strip():
        notes_block = prompts["notes_template"].format(notes=notes.strip())

    user_prompt = prompts["tailor"].format(
        notes_block=notes_block,
        resume_mark=RESUME_MARK,
        cover_mark=COVER_MARK,
        job_title=job.get("title", "") or "(untitled)",
        job_company=job.get("company", "") or "(unknown company)",
        job_description=description[:MAX_JOB_CHARS],
        resume_text=resume_text[:MAX_RESUME_CHARS],
    )

    try:
        message = _call_claude(prompts["system"], user_prompt)
    except anthropic.AuthenticationError:
        raise RuntimeError(
            "Claude authentication failed. Check ANTHROPIC_API_KEY in your .env."
        )
    except Exception as e:  # noqa: BLE001 — surface a clean message to the UI
        log.error(f"Resume generation failed: {e}")
        raise RuntimeError(f"Generation failed: {e}")

    raw = message.content[0].text
    usage = message.usage
    log.info(
        f"Resume tailoring tokens — in: {usage.input_tokens}, out: {usage.output_tokens} "
        f"| '{job.get('title')}' @ {job.get('company')}"
    )

    parsed = _parse_sections(raw)
    if not parsed["tailored_resume"]:
        log.warning("Delimiters missing in response; returning raw text as resume.")
        parsed["tailored_resume"] = raw.strip()

    return parsed


def _parse_sections(raw: str) -> dict:
    """Split the model output on the resume/cover-letter delimiters."""
    text = raw.strip()
    resume_text = ""
    cover_text = ""

    if RESUME_MARK in text:
        after = text.split(RESUME_MARK, 1)[1]
        if COVER_MARK in after:
            resume_part, cover_part = after.split(COVER_MARK, 1)
            resume_text = resume_part.strip()
            cover_text = cover_part.strip()
        else:
            resume_text = after.strip()
    elif COVER_MARK in text:
        cover_text = text.split(COVER_MARK, 1)[1].strip()

    return {
        "tailored_resume": _strip_fences(resume_text),
        "cover_letter": _strip_fences(cover_text),
    }


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:markdown|md)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()
