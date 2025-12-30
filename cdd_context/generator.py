"""
Generator: Assembles PROJECT_CONTEXT.md from file summaries.

Contract: generator v1.0.0
"""

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# Constants
TOKEN_BUDGET = 8000
KEY_FILE_THRESHOLD = 5

# Priority filename patterns for key files
KEY_FILE_PATTERNS = [
    "readme", "claude.md", "package.json", "cargo.toml",
    "go.mod", "pyproject.toml"
]


@dataclass 
class FileSummary:
    """Summary data for a single file."""
    path: str
    source_hash: str = ""
    summary: dict = field(default_factory=dict)
    
    @property
    def role(self) -> str:
        return self.summary.get("role", "unknown")
    
    @property
    def summary_text(self) -> str:
        return self.summary.get("summary", "")
    
    @property
    def public_symbols(self) -> list:
        return self.summary.get("public_symbols", [])
    
    @property
    def import_deps(self) -> list:
        return self.summary.get("import_deps", [])
    
    @property
    def entrypoints(self) -> list:
        return self.summary.get("entrypoints", [])


@dataclass
class GeneratorResult:
    """Output from generate()."""
    content: str = ""
    warnings: list[str] = field(default_factory=list)
    approx_tokens: int = 0
    scan_hash: str = ""


def _compute_priority_score(file: FileSummary, priority_paths: list[str]) -> int:
    """Compute priority score for key file selection."""
    score = 0
    filename = Path(file.path).name.lower()
    
    # +10 if entrypoint
    if file.role == "entrypoint":
        score += 10
    
    # +5 if config
    if file.role == "config":
        score += 5
    
    # +3 if docs (README etc should be key files)
    if file.role == "docs":
        score += 3
    
    # +3 if matches key file patterns
    for pattern in KEY_FILE_PATTERNS:
        if pattern in filename:
            score += 3
            break
    
    # +2 if in priority_paths
    if file.path in priority_paths:
        score += 2
    
    # +1 if has high-confidence entrypoints
    for ep in file.entrypoints:
        if ep.get("confidence", 0) > 0.8:
            score += 1
            break
    
    return score


def _compute_scan_hash(files: list[FileSummary], ignore_mode: str) -> str:
    """Compute hash of scanned files for change detection."""
    items = sorted([
        (ignore_mode, f.path, f.source_hash)
        for f in files
    ])
    content = json.dumps(items, sort_keys=True)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _build_tree(paths: list[str]) -> str:
    """Build directory tree visualization."""
    if not paths:
        return ""
    
    # Build tree structure
    tree = {}
    for path in sorted(paths):
        parts = path.split("/")
        current = tree
        for part in parts:
            if part not in current:
                current[part] = {}
            current = current[part]
    
    # Render tree
    lines = []
    
    def render(node: dict, prefix: str = "", is_last: bool = True, is_root: bool = True):
        items = sorted(node.items())
        for i, (name, children) in enumerate(items):
            is_last_item = (i == len(items) - 1)
            
            if is_root:
                lines.append(name + "/")
                render(children, "", is_last_item, False)
            else:
                connector = "└── " if is_last_item else "├── "
                suffix = "/" if children else ""
                lines.append(prefix + connector + name + suffix)
                
                if children:
                    extension = "    " if is_last_item else "│   "
                    render(children, prefix + extension, is_last_item, False)
    
    render(tree)
    return "\n".join(lines)


def _build_key_file_section(file: FileSummary) -> str:
    """Build markdown section for a key file."""
    lines = [
        f"### {file.path}",
        f"**Role:** {file.role}",
        "",
        file.summary_text,
    ]
    
    if file.public_symbols:
        lines.append("")
        lines.append(f"**Provides:** {', '.join(file.public_symbols[:10])}")
    
    if file.import_deps:
        lines.append(f"**Consumes:** {', '.join(file.import_deps[:10])}")
    
    if file.entrypoints:
        ep = file.entrypoints[0]
        lines.append(f"**Entry:** `{ep.get('evidence', '')}` (line {ep.get('lineno', '?')})")
    
    return "\n".join(lines)


def generate(
    files: list[dict],
    ignore_mode: str = "git",
    cache_hits: int = 0,
    cache_total: Optional[int] = None,
    priority_paths: Optional[list[str]] = None,
    project_name: Optional[str] = None,
) -> dict:
    """
    Generate PROJECT_CONTEXT.md content.
    
    Args:
        files: List of {path, source_hash, summary} dicts
        ignore_mode: "git" or "best_effort"
        cache_hits: Number of cache hits
        cache_total: Total files processed
        priority_paths: Paths flagged by scanner heuristics
        project_name: Project name for header
    
    Returns:
        Dict with content, warnings, approx_tokens, scan_hash
    """
    result = GeneratorResult()
    priority_paths = priority_paths or []
    
    # Convert to FileSummary objects
    file_summaries = [
        FileSummary(
            path=f["path"],
            source_hash=f.get("source_hash", ""),
            summary=f.get("summary", {}),
        )
        for f in files
    ]
    
    # Compute scan hash
    result.scan_hash = _compute_scan_hash(file_summaries, ignore_mode)
    
    # Compute priority scores and classify
    scored_files = [
        (f, _compute_priority_score(f, priority_paths))
        for f in file_summaries
    ]
    
    # Key files: score >= threshold, sorted by score desc then path
    key_files = sorted(
        [(f, s) for f, s in scored_files if s >= KEY_FILE_THRESHOLD],
        key=lambda x: (-x[1], x[0].path)
    )
    key_file_set = {f.path for f, _ in key_files}
    
    # Other files: remaining, sorted by path
    other_files = sorted(
        [f for f, s in scored_files if f.path not in key_file_set],
        key=lambda f: f.path
    )
    
    # Build content
    sections = []
    
    # Header
    name = project_name or "Project"
    cache_total = cache_total if cache_total is not None else len(files)
    hit_rate = f"{cache_hits}/{cache_total}" if cache_total > 0 else "0/0"
    
    sections.append(f"# Project Context: {name}")
    sections.append("")
    sections.append(f"> Files: {len(files)} | Cache: {hit_rate} hits | Mode: {ignore_mode} | Hash: {result.scan_hash}")
    sections.append("")
    
    # Directory structure
    sections.append("## Directory Structure")
    sections.append("")
    sections.append("```")
    sections.append(_build_tree([f.path for f in file_summaries]))
    sections.append("```")
    sections.append("")
    
    # Key files
    if key_files:
        sections.append("## Key Files")
        sections.append("")
        for f, _ in key_files:
            sections.append(_build_key_file_section(f))
            sections.append("")
    
    # Other files table
    if other_files:
        sections.append("## Other Files")
        sections.append("")
        sections.append("| File | Role | Summary |")
        sections.append("|------|------|---------|")
        for f in other_files:
            # Truncate summary for table
            summary = f.summary_text[:60]
            if len(f.summary_text) > 60:
                summary += "..."
            sections.append(f"| {f.path} | {f.role} | {summary} |")
        sections.append("")
    
    # Join content
    result.content = "\n".join(sections)
    
    # Token estimation
    result.approx_tokens = math.ceil(len(result.content) / 4)
    
    # Warnings
    if result.approx_tokens > TOKEN_BUDGET:
        result.warnings.append("token_budget_exceeded")
    
    return {
        "content": result.content,
        "warnings": result.warnings,
        "approx_tokens": result.approx_tokens,
        "scan_hash": result.scan_hash,
    }


def generate_json(
    files: list[dict],
    ignore_mode: str = "git",
    cache_hits: int = 0,
    cache_total: Optional[int] = None,
    priority_paths: Optional[list[str]] = None,
) -> dict:
    """Generate JSON format output."""
    file_summaries = [
        FileSummary(
            path=f["path"],
            source_hash=f.get("source_hash", ""),
            summary=f.get("summary", {}),
        )
        for f in files
    ]
    
    scan_hash = _compute_scan_hash(file_summaries, ignore_mode)
    priority_paths = priority_paths or []
    cache_total = cache_total if cache_total is not None else len(files)
    
    # Classify files
    scored_files = [
        (f, _compute_priority_score(f, priority_paths))
        for f in file_summaries
    ]
    
    key_files = sorted(
        [(f, s) for f, s in scored_files if s >= KEY_FILE_THRESHOLD],
        key=lambda x: (-x[1], x[0].path)
    )
    key_file_set = {f.path for f, _ in key_files}
    
    other_files = sorted(
        [f for f, s in scored_files if f.path not in key_file_set],
        key=lambda f: f.path
    )
    
    return {
        "metadata": {
            "files": len(files),
            "cache_hits": cache_hits,
            "ignore_mode": ignore_mode,
            "scan_hash": scan_hash,
        },
        "tree": _build_tree([f.path for f in file_summaries]),
        "key_files": [
            {
                "path": f.path,
                "role": f.role,
                "summary": f.summary_text,
                "public_symbols": f.public_symbols,
                "import_deps": f.import_deps,
                "entrypoints": f.entrypoints,
            }
            for f, _ in key_files
        ],
        "other_files": [
            {
                "path": f.path,
                "role": f.role,
                "summary": f.summary_text,
            }
            for f in other_files
        ],
    }
