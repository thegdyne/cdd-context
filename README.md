# cdd-context

Generate and maintain a `PROJECT_CONTEXT.md` file that gives Claude (or any LLM) immediate orientation on a codebase.

**Status:** v0.3.0 (draft) | Built with [CDD](https://github.com/thegdyne/cdd) spec 1.1.5

## Problem

When working with Claude across multiple sessions, you repeatedly share the same files. Claude can't remember what it saw yesterday. The friction isn't the mechanics of sending a file—it's the repetition and the feeling that Claude should already know this.

## Solution

A local tool that scans your codebase, generates summaries of each file, and assembles them into a single context document. Paste once at session start, Claude is oriented. File details come on-demand.

## Quick Start

```bash
# Install from source
git clone https://github.com/thegdyne/cdd-context.git
cd cdd-context
pip install -e .

# Go to any project
cd ~/your-project

# Generate context
cdd-context build

# Output: PROJECT_CONTEXT.md created
```

## Workflow

**First session:**
```bash
cdd-context build --clip   # Generates + copies to clipboard
```
Paste into Claude. Claude now knows your project structure.

**Later sessions:**
```bash
cdd-context build --clip   # Only re-summarizes changed files (cache hits)
```

**Check what's cached:**
```bash
cdd-context status
# Cache entries: 47
# Context file: PROJECT_CONTEXT.md (6200 bytes)
```

**Something weird? Reset:**
```bash
cdd-context clear-cache
cdd-context build
```

## Commands

```bash
cdd-context build            # Generate PROJECT_CONTEXT.md
cdd-context build --clip     # Generate and copy to clipboard
cdd-context build --dry-run  # Show what would be summarized (no changes)
cdd-context status           # Show cache state
cdd-context clear-cache      # Clear cache (keeps PROJECT_CONTEXT.md)
cdd-context watch            # Watch for changes and rebuild (planned)
```

## How It Works

1. **Scanner** walks your directory tree, respects `.gitignore` and `.contextignore`
2. **Summarizer** generates concise summaries (heuristic-based, LLM integration planned)
3. **Cache** stores summaries keyed by file hash + prompt hash + backend
4. **Generator** assembles everything into a structured markdown file

Only changed files are re-summarized. Typical projects stay under 8k tokens.

## Output Example

```markdown
# Project Context: my-project

> Files: 47 | Cache: 42/47 hits | Mode: git | Hash: a1b2c3d4

## Directory Structure

my-project/
├── src/
│   ├── engine.py
│   └── generators/
├── tests/
└── README.md

## Key Files

### src/engine.py
**Role:** entrypoint

Main synthesis engine coordinating generators and MIDI input...

**Provides:** start_engine, stop_engine, process_midi
**Consumes:** os, sys, generators

## Other Files

| File | Role | Summary |
|------|------|---------|
| src/generators/crystalline.py | library | Ice structure generator... |
```

## What Gets Ignored

1. Everything in `.gitignore` (if in a git repo)
2. Plus `.contextignore` patterns you add
3. Plus built-in defaults:

```
.env, .env.*, *.pem, *.key, secrets.*
node_modules/, __pycache__/, .git/
*.log, *.pyc, .DS_Store
dist/, build/, *.egg-info/
```

## Configuration

Create `.contextignore` in your project root to exclude additional files:

```gitignore
# Secrets
.env
*.pem

# Large files
*.pdf
data/

# Noise
*.log
vendor/
```

## Requirements

- Python 3.10+

## Development

This project is built using [Contract-Driven Development](https://github.com/thegdyne/cdd).

```bash
# Setup after clone
python tests/setup_fixtures.py

# Run all tests
python tests/test_scanner.py
python tests/test_cache.py
python tests/test_summarizer.py
python tests/test_generator.py
python tests/test_cli.py
```

## Components

| Component | Status | Description |
|-----------|--------|-------------|
| scanner | ✓ implemented | Directory walking, git/contextignore filtering |
| cache | ✓ implemented | Content-addressed summary storage |
| summarizer | ✓ implemented | Heuristic file summarization (LLM integration planned) |
| generator | ✓ implemented | PROJECT_CONTEXT.md assembly |
| cli | ✓ implemented | Command-line interface |

## Roadmap

- [ ] LLM integration (Claude Haiku for better summaries)
- [ ] Watch mode (auto-rebuild on file changes)
- [ ] PyPI publish (`pip install cdd-context`)

## License

MIT
