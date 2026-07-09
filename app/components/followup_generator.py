"""
app/components/followup_generator.py

Follow-up email generation for the Applications pipeline.

Two responsibilities:
  1. Find and verify a contact email for a job using Hunter.io
     (domain search → email verifier — only surfaces addresses that pass).
  2. Draft a follow-up email via Claude using job + resume context.

Requires HUNTER_API_KEY in the environment. If the key is missing or Hunter
returns no verified result, email discovery is skipped gracefully.
"""

import json
import logging
import os
import re

import anthropic
import requests
import yaml

log = logging.getLogger("remote-rocket.followup")

HUNTER_API_KEY  = os.getenv("HUNTER_API_KEY", "")
FOLLOWUP_MODEL  = os.getenv("FOLLOWUP_MODEL", "claude-haiku-4-5-20251001")
HUNTER_DOMAIN   = "https://api.hunter.io/v2"

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _prompt_path() -> str:
    candidates = [
        "/app/prompts/tailoring_prompts.yml",
        os.path.join(os.path.dirname(__file__), "..", "..", "prompts", "tailoring_prompts.yml"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    raise FileNotFoundError("tailoring_prompts.yml not found.")


def _load_prompts() -> dict:
    with open(_prompt_path()) as f:
        return yaml.safe_load(f)


# ── Domain extraction ──────────────────────────────────────────────────────────

def _extract_domain(job: dict) -> str | None:
    """
    Pull a company domain from the job URL, falling back to a Hunter
    company-to-domain lookup if only a name is available.
    """
    url = job.get("url") or ""
    if url:
        match = re.search(r"https?://(?:www\.)?([^/]+)", url)
        if match:
            host = match.group(1).lower()
            # Skip job board domains — they aren't the company.
            boards = {
                # Job boards
                "linkedin.com", "indeed.com", "glassdoor.com", "ziprecruiter.com",
                "monster.com", "careerbuilder.com", "adzuna.com", "simplyhired.com",
                "dice.com", "builtin.com",
                # ATS platforms
                "lever.co", "greenhouse.io", "ashbyhq.com", "workday.com",
                "myworkdayjobs.com", "icims.com", "taleo.net", "smartrecruiters.com",
                "jobvite.com", "breezy.hr", "recruitee.com", "bamboohr.com",
                "jazz.co", "applytojob.com", "workable.com", "pinpointhq.com",
                "rippling.com", "gusto.com", "hire.withgoogle.com",
            }
            if not any(host.endswith(b) for b in boards):
                return host

    # Fall back to Hunter's company-name lookup.
    company = (job.get("company") or "").strip()
    if company and HUNTER_API_KEY:
        try:
            r = requests.get(
                f"{HUNTER_DOMAIN}/domain-search",
                params={"company": company, "api_key": HUNTER_API_KEY},
                timeout=8,
            )
            data = r.json().get("data", {})
            return data.get("domain")
        except Exception as e:
            log.warning(f"Hunter company lookup failed: {e}")

    return None


# ── Email discovery + verification ────────────────────────────────────────────

def find_verified_email(job: dict, contact_name: str = "") -> dict:
    """
    Try to find a verified contact email for the job.

    Returns:
        {
            "email":    str or None,      # verified address, or None
            "name":     str or None,      # associated name if found
            "status":   "verified" | "unverifiable" | "no_key" | "not_found",
            "source":   str,              # human-readable explanation
        }
    """
    if not HUNTER_API_KEY:
        return {"email": None, "name": None,
                "status": "no_key", "source": "HUNTER_API_KEY not configured."}

    domain = _extract_domain(job)
    if not domain:
        return {"email": None, "name": None,
                "status": "not_found", "source": "Could not determine company domain."}

    # Step 1: domain search — get candidate emails.
    try:
        params = {"domain": domain, "api_key": HUNTER_API_KEY, "limit": 10}
        if contact_name.strip():
            params["type"] = "personal"
        r = requests.get(f"{HUNTER_DOMAIN}/domain-search", params=params, timeout=10)
        r.raise_for_status()
        emails = r.json().get("data", {}).get("emails", [])
    except Exception as e:
        log.warning(f"Hunter domain search failed for {domain}: {e}")
        return {"email": None, "name": None,
                "status": "unverifiable", "source": f"Hunter search error: {e}"}

    if not emails:
        return {"email": None, "name": None,
                "status": "not_found",
                "source": f"No emails found on Hunter for {domain}."}

    # Prefer HR/recruiting-type addresses; fall back to highest-confidence.
    recruiting_keywords = {"hr", "recruit", "hiring", "talent", "people", "careers",
                           "jobs", "staffing"}

    def _score(e: dict) -> tuple:
        addr = (e.get("value") or "").lower()
        local = addr.split("@")[0]
        is_recruiting = any(k in local for k in recruiting_keywords)
        confidence = e.get("confidence") or 0
        return (is_recruiting, confidence)

    emails_sorted = sorted(emails, key=_score, reverse=True)
    candidate = emails_sorted[0]
    email_addr = candidate.get("value")
    email_name = " ".join(filter(None, [candidate.get("first_name"), candidate.get("last_name")])) or None

    if not email_addr:
        return {"email": None, "name": None,
                "status": "not_found", "source": "Hunter returned no usable address."}

    # Step 2: verify the best candidate.
    try:
        vr = requests.get(
            f"{HUNTER_DOMAIN}/email-verifier",
            params={"email": email_addr, "api_key": HUNTER_API_KEY},
            timeout=15,
        )
        vr.raise_for_status()
        vdata = vr.json().get("data", {})
        vstatus = vdata.get("status")  # "valid", "invalid", "accept_all", "unknown"
    except Exception as e:
        log.warning(f"Hunter verifier failed for {email_addr}: {e}")
        return {"email": None, "name": email_name,
                "status": "unverifiable", "source": f"Verification error: {e}"}

    if vstatus == "valid":
        return {
            "email":  email_addr,
            "name":   email_name,
            "status": "verified",
            "source": f"Verified via Hunter.io ({domain})",
        }
    else:
        log.info(f"Hunter verification status for {email_addr}: {vstatus} — not surfacing.")
        return {
            "email":  None,
            "name":   email_name,
            "status": "unverifiable",
            "source": f"No verified email found for {domain} (Hunter status: {vstatus}).",
        }


# ── Email drafting ─────────────────────────────────────────────────────────────

def draft_followup_email(job: dict, sender_name: str, contact_name: str = "",
                         applied_date: str = "", resume_summary: str = "",
                         previous_followups: list = None) -> str:
    """
    Draft a follow-up email using Claude.

    `previous_followups` is a list of dicts from get_followups() — passed so
    Claude can write a conscious progression rather than repeating itself.
    Returns the email body as a plain string (no subject line).
    """
    followup_num = len(previous_followups or []) + 1

    history_block = ""
    if previous_followups:
        lines = []
        for f in previous_followups:
            date_str = (f.get("created_at") or "")[:10]
            lines.append(f"Follow-up #{f['followup_num']} (sent {date_str}):\n{f['draft_text']}")
        history_block = "\n\n---\n".join(lines)

    prompts = _load_prompts()
    system  = prompts.get("followup_system", "")
    prompt  = prompts.get("followup_draft", "").format(
        job_title      = job.get("title") or "(untitled)",
        job_company    = job.get("company") or "(unknown company)",
        sender_name    = sender_name or "the candidate",
        contact_name   = contact_name or "Hiring Team",
        applied_date   = applied_date or "recently",
        resume_summary = resume_summary or "",
        followup_num   = followup_num,
        history_block  = history_block or "None — this is the first follow-up.",
    )

    try:
        msg = _get_client().messages.create(
            model      = FOLLOWUP_MODEL,
            max_tokens = 600,
            system     = system,
            messages   = [{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        # Hard strip any dashes that slipped through — em, en, figure, hyphen-minus.
        text = re.sub(r"—|–|‒|‐", ", ", text)  # em/en/figure/hyphen → comma
        return text
    except Exception as e:
        log.error(f"Follow-up draft failed: {e}")
        raise RuntimeError(f"Could not draft email: {e}")


def followup_subject(job: dict) -> str:
    title   = job.get("title") or "the role"
    company = job.get("company") or ""
    return f"Following up on my application for {title}" + (f" at {company}" if company else "")
