# AI Podcast Monitor

## Overview
Monitor YouTube AI/tech podcast channels, extract transcripts, analyze with Claude, push insights to Notion.

## Architecture
- Python scripts in `scripts/` handle data fetching (RSS + transcripts)
- Claude Code skill at `.claude/skills/podcast/SKILL.md` orchestrates the workflow
- State tracked in `data/processed.json` (gitignored)
- Notion database "AI Podcast Insights" stores all analysis

## Running
- User invokes `/podcast` to trigger the full workflow
- Python 3.9+ required with packages in requirements.txt
- No API keys needed (YouTube RSS + youtube-transcript-api are both free)

## Conventions
- All Python scripts output JSON to stdout, errors/warnings to stderr
- Scripts use absolute paths relative to PROJECT_ROOT
- Each script is independently runnable for debugging
