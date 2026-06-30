"""
config_validator.py
Validates keywords.yml and companies.yml on startup.
If either file is missing or malformed, the scraper exits immediately
with a clear error message rather than failing silently mid-run.
"""

import sys
import logging
import yaml

log = logging.getLogger("remote-rocket.config")

KEYWORDS_PATH  = "/app/config/keywords.yml"
COMPANIES_PATH = "/app/config/companies.yml"

# Required top-level keys in keywords.yml
REQUIRED_KEYWORD_KEYS = ["search_terms", "title_boost_keywords", "title_exclusions"]

# Required keys on each entry in companies.yml
REQUIRED_COMPANY_KEYS = ["name", "careers_url"]


def _load_yaml(path: str) -> dict | list:
    """Load a YAML file. Exit with a clear message if it can't be read."""
    try:
        with open(path) as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        log.error(f"Config file not found: {path}")
        log.error("Make sure the config/ directory is mounted correctly in docker-compose.yml")
        sys.exit(1)
    except yaml.YAMLError as e:
        log.error(f"YAML syntax error in {path}: {e}")
        log.error("Use a YAML validator (e.g. yamllint.com) to check your formatting.")
        sys.exit(1)


def load_keywords() -> dict:
    """Load and validate keywords.yml. Returns the config dict."""
    config = _load_yaml(KEYWORDS_PATH)

    if not isinstance(config, dict):
        log.error(f"keywords.yml must be a YAML mapping (dictionary), got: {type(config).__name__}")
        sys.exit(1)

    for key in REQUIRED_KEYWORD_KEYS:
        if key not in config:
            log.error(f"keywords.yml is missing required key: '{key}'")
            log.error(f"Required keys: {REQUIRED_KEYWORD_KEYS}")
            sys.exit(1)
        if not isinstance(config[key], list):
            log.error(f"keywords.yml: '{key}' must be a list, got: {type(config[key]).__name__}")
            sys.exit(1)

    if not config["search_terms"]:
        log.error("keywords.yml: 'search_terms' list is empty. Add at least one search term.")
        sys.exit(1)

    log.info(f"keywords.yml OK — {len(config['search_terms'])} search terms, "
             f"{len(config['title_exclusions'])} exclusions")
    return config


def load_companies() -> list[dict]:
    """Load and validate companies.yml. Returns the list of company dicts."""
    raw = _load_yaml(COMPANIES_PATH)

    if not isinstance(raw, dict) or "companies" not in raw:
        log.error("companies.yml must have a top-level 'companies:' key containing a list.")
        sys.exit(1)

    companies = raw["companies"]

    if not isinstance(companies, list) or len(companies) == 0:
        log.error("companies.yml: 'companies' must be a non-empty list.")
        sys.exit(1)

    for i, company in enumerate(companies):
        if not isinstance(company, dict):
            log.error(f"companies.yml: entry #{i + 1} is not a valid mapping (dictionary).")
            sys.exit(1)
        for key in REQUIRED_COMPANY_KEYS:
            if key not in company or not company[key]:
                log.error(f"companies.yml: entry #{i + 1} ('{company.get('name', '?')}') "
                          f"is missing required key: '{key}'")
                sys.exit(1)

    high_priority = sum(1 for c in companies if c.get("high_priority", False))
    log.info(f"companies.yml OK — {len(companies)} companies "
             f"({high_priority} high-priority, {len(companies) - high_priority} standard)")
    return companies
