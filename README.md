# cdd-context

Generate and maintain a `PROJECT_CONTEXT.md` file that gives Claude (or any LLM) immediate orientation on a codebase.

**Status:** v0.3.0 (draft) | Built with [CDD](https://github.com/thegdyne/cdd) spec 1.1.5

## Problem

When working with Claude across multiple sessions, you repeatedly share the same files. Claude can't remember what it saw yesterday. The friction isn't the mechanics of sending a file—it's the repetition and the feeling that Claude should already know this.

## Solution

A local tool that scans your codebase, generates summaries of each file, and assembles them into a single context document. Paste once at session start, Claude is oriented. File details come on-demand.

## Installation

```bash
pip install cdd-context
```

## Usage

```bash
# Generate PROJECT_CONTEXT.md
cdd-context build

# Generate and copy to clipboard
cdd-context build --clip

# Show what would be summarized (no API calls)
cdd-context build --dry-run

# Check cache state
cdd-context status

# Watch for changes and rebuild
cdd-context watch

# Clear cache (keeps PROJECT_CONTEXT.md)
cdd-context clear-cache
```

## How It Works

1. **Scanner** walks your directory tree, respects `.gitignore` and `.contextignore`
2. **Summarizer** generates concise summaries via LLM (Claude Haiku by default)
3. **Cache** stores summaries keyed by file hash + prompt hash + backend
4. **Generator** assembles everything into a structured markdown file

Only changed files are re-summarized. Typical projects stay under 8k tokens.

## Output Example

```markdown
# Project Context: my-project

> Files: 47 | Cache: 42/47 hits | Tokens: ~6200 | Mode: git

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

## Other Files

| File | Role | Summary |
|------|------|---------|
| src/generators/crystalline.py | library | Ice structure generator... |
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
```

## Requirements

- Python 3.10+
- `ANTHROPIC_API_KEY` environment variable (for summarization)

## Development

This project is built using [Contract-Driven Development](https://github.com/thegdyne/cdd).

```bash
# Run tests
python tests/test_scanner.py

# Lint contracts (requires cdd-tooling)
cdd lint contracts/
```

## Components

| Component | Status | Description |
|-----------|--------|-------------|
| scanner | ✓ implemented | Directory walking, git/contextignore filtering |
| cache | ✓ implemented | Content-addressed summary storage |
| summarizer | ✓ implemented | Heuristic file summarization (LLM integration planned) |
| generator | ✓ implemented | PROJECT_CONTEXT.md assembly |
| cli | ✓ implemented | Command-line interface |

## License

MIT
