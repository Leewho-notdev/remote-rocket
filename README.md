# 🚀 Remote Rocket

Personal self-hosted remote job aggregator for performance marketing, paid search, and SEM roles.

## Quick Start

```bash
cp .env.example .env
# Add your ANTHROPIC_API_KEY to .env

docker compose up -d
```

Then open `http://localhost:8501` (or your VPS IP).

## Configuration

- **Keywords & search terms:** `config/keywords.yml`
- **Target company career pages:** `config/companies.yml`
- **Scrape interval, salary threshold, API keys:** `.env`

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for full technical design.
