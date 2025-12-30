"""
Scanner: Walks directory tree, determines file set using git when available.

Contract: scanner v1.0.0
"""

import fnmatch
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ScanResult:
    """Output schema for scan()."""
    files: list[str] = field(default_factory=list)
    ignore_mode: str = "best_effort"
    warnings: list[str] = field(default_factory=list)
    priority_paths: list[str] = field(default_factory=list)


# Priority filename patterns (R004)
PRIORITY_PATTERNS = [
    r"^README",
    r"^CLAUDE\.md$",
    r"^package\.json$",
    r"^Cargo\.toml$",
    r"^go\.mod$",
    r"^pyproject\.toml$",
    r"^setup\.py$",
    r"^main\.(py|js|ts|go|rs|scala)$",
    r"^app\.(py|js|ts)$",
    r"^index\.(py|js|ts)$",
    r"^__main__\.py$",
    r"^config\.(yaml|yml|json|toml)$",
    r"^settings\.(py|yaml|yml|json)$",
    r"^Makefile$",
    r"^Dockerfile$",
]


def _load_ignore_patterns(root: Path) -> list[str]:
    """Load ignore patterns from .contextignore.default and .contextignore."""
    patterns = []
    
    # Load default patterns (shipped with tool)
    default_file = Path(__file__).parent / ".contextignore.default"
    if default_file.exists():
        patterns.extend(_parse_ignore_file(default_file))
    
    # Load project-specific patterns (user file)
    project_file = root / ".contextignore"
    if project_file.exists():
        patterns.extend(_parse_ignore_file(project_file))
    
    return patterns


def _parse_ignore_file(path: Path) -> list[str]:
    """Parse a gitignore-style file into patterns."""
    patterns = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue
            patterns.append(line)
    return patterns


def _matches_pattern(path: str, pattern: str) -> bool:
    """Check if path matches a gitignore-style pattern.
    
    Patterns:
    - * matches anything except /
    - ** matches zero or more directories
    - / prefix anchors to root
    - Trailing / matches directories only (we treat all as files here)
    """
    # Normalize path to posix style
    path = path.replace("\\", "/")
    
    # Handle directory-only patterns (trailing /)
    if pattern.endswith("/"):
        pattern = pattern[:-1]
        # Match if path starts with this directory
        if path == pattern or path.startswith(pattern + "/"):
            return True
        # Also match if any path component equals the pattern
        parts = path.split("/")
        return pattern in parts
    
    # Handle root-anchored patterns
    anchored = pattern.startswith("/")
    if anchored:
        pattern = pattern[1:]
    
    # Convert gitignore pattern to regex
    regex_pattern = _pattern_to_regex(pattern)
    
    if anchored:
        # Must match from start
        return bool(re.match(regex_pattern + "$", path))
    else:
        # Can match anywhere in path
        # Try matching the full path
        if re.match(regex_pattern + "$", path):
            return True
        # Try matching just the filename
        filename = path.split("/")[-1]
        if re.match(regex_pattern + "$", filename):
            return True
        # Try matching path suffixes
        parts = path.split("/")
        for i in range(len(parts)):
            suffix = "/".join(parts[i:])
            if re.match(regex_pattern + "$", suffix):
                return True
        return False


def _pattern_to_regex(pattern: str) -> str:
    """Convert a gitignore pattern to a regex pattern."""
    result = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == "*":
            if i + 1 < len(pattern) and pattern[i + 1] == "*":
                # ** matches anything including /
                if i + 2 < len(pattern) and pattern[i + 2] == "/":
                    result.append("(?:.*/)?")
                    i += 3
                    continue
                else:
                    result.append(".*")
                    i += 2
                    continue
            else:
                # * matches anything except /
                result.append("[^/]*")
        elif c == "?":
            result.append("[^/]")
        elif c == ".":
            result.append(r"\.")
        elif c in "[]":
            result.append(c)
        elif c == "\\":
            if i + 1 < len(pattern):
                result.append(re.escape(pattern[i + 1]))
                i += 1
            else:
                result.append(r"\\")
        else:
            result.append(re.escape(c))
        i += 1
    return "".join(result)


def _should_ignore(path: str, patterns: list[str]) -> bool:
    """Check if path should be ignored based on patterns.
    
    Supports negation patterns (!) - later patterns override earlier ones.
    """
    ignored = False
    for pattern in patterns:
        if pattern.startswith("!"):
            # Negation pattern
            if _matches_pattern(path, pattern[1:]):
                ignored = False
        else:
            if _matches_pattern(path, pattern):
                ignored = True
    return ignored


def _is_priority_file(filename: str) -> bool:
    """Check if filename matches priority patterns (R004)."""
    for pattern in PRIORITY_PATTERNS:
        if re.match(pattern, filename, re.IGNORECASE):
            return True
    return False


def _git_available() -> bool:
    """Check if git is available on PATH."""
    return shutil.which("git") is not None


def _in_git_worktree(root: Path) -> bool:
    """Check if root is the root of a git worktree (not just inside one)."""
    # Check if .git exists at root (either directory or file for worktrees)
    git_path = root / ".git"
    if not git_path.exists():
        return False
    
    # Verify git agrees this is a valid repo
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return False
        
        # Check that the toplevel matches our root
        toplevel = Path(result.stdout.strip()).resolve()
        return toplevel == root.resolve()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def _get_submodule_paths(root: Path) -> set[str]:
    """Get paths that are submodules (R005)."""
    submodules = set()
    
    # Check .gitmodules file
    gitmodules = root / ".gitmodules"
    if gitmodules.exists():
        try:
            content = gitmodules.read_text(encoding="utf-8")
            for match in re.finditer(r'path\s*=\s*(.+)', content):
                path = match.group(1).strip()
                submodules.add(path)
        except Exception:
            pass
    
    return submodules


def _is_submodule_dir(path: Path) -> bool:
    """Check if directory is a submodule (has .git file with gitdir pointer)."""
    git_path = path / ".git"
    if git_path.is_file():
        try:
            content = git_path.read_text(encoding="utf-8")
            return content.strip().startswith("gitdir:")
        except Exception:
            pass
    return False


def _scan_with_git(root: Path) -> list[str]:
    """Get file list using git ls-files."""
    try:
        result = subprocess.run(
            [
                "git", "-c", "core.quotepath=false",
                "ls-files", "-z",
                "--cached", "--others", "--exclude-standard"
            ],
            cwd=root,
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            return []
        
        # Parse null-separated output
        files = []
        for path in result.stdout.split(b"\x00"):
            if path:
                # Decode path (git outputs UTF-8)
                try:
                    decoded = path.decode("utf-8")
                except UnicodeDecodeError:
                    decoded = path.decode("utf-8", errors="replace")
                # Normalize to posix style
                decoded = decoded.replace("\\", "/")
                files.append(decoded)
        
        return files
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return []


def _scan_directory(root: Path, patterns: list[str], submodules: set[str]) -> list[str]:
    """Walk directory tree with ignore pattern filtering."""
    files = []
    root_path = root.resolve()
    
    for dirpath, dirnames, filenames in os.walk(root):
        # Convert to relative posix path
        rel_dir = Path(dirpath).resolve().relative_to(root_path)
        rel_dir_str = str(rel_dir).replace("\\", "/")
        if rel_dir_str == ".":
            rel_dir_str = ""
        
        # Filter out ignored directories (modify in place to prevent descent)
        dirnames[:] = [
            d for d in dirnames
            if not _should_ignore(
                f"{rel_dir_str}/{d}" if rel_dir_str else d,
                patterns
            )
            and not d.startswith(".")  # Skip hidden directories
            and d not in submodules  # Skip submodules (R005)
            and not _is_submodule_dir(Path(dirpath) / d)
        ]
        
        # Process files
        for filename in filenames:
            if filename.startswith("."):
                continue
            
            rel_path = f"{rel_dir_str}/{filename}" if rel_dir_str else filename
            
            if not _should_ignore(rel_path, patterns):
                files.append(rel_path)
    
    return sorted(files)


def scan(
    root: str,
    mock_git_missing: bool = False,
) -> dict:
    """
    Scan directory for files to summarize.
    
    Args:
        root: Path to project root directory
        mock_git_missing: If True, pretend git is not available (for testing)
    
    Returns:
        ScanResult as dict with keys: files, ignore_mode, warnings, priority_paths
    """
    root_path = Path(root).resolve()
    
    if not root_path.exists():
        return ScanResult(
            warnings=[f"Root directory does not exist: {root}"]
        ).__dict__
    
    if not root_path.is_dir():
        return ScanResult(
            warnings=[f"Root is not a directory: {root}"]
        ).__dict__
    
    result = ScanResult()
    patterns = _load_ignore_patterns(root_path)
    submodules = _get_submodule_paths(root_path)
    
    # Determine scan mode (R002)
    git_on_path = _git_available() and not mock_git_missing
    in_worktree = git_on_path and _in_git_worktree(root_path)
    
    if not git_on_path:
        result.warnings.append("git not found; using best-effort ignore matching")
    
    if git_on_path and in_worktree:
        # Case A: git available, inside worktree
        result.ignore_mode = "git"
        files = _scan_with_git(root_path)
        
        # Apply .contextignore as additive filter (R003)
        files = [f for f in files if not _should_ignore(f, patterns)]
        result.files = sorted(files)
    else:
        # Case B/C: best-effort mode
        result.ignore_mode = "best_effort"
        result.files = _scan_directory(root_path, patterns, submodules)
    
    # Identify priority paths (R004)
    for file_path in result.files:
        filename = file_path.split("/")[-1]
        if _is_priority_file(filename):
            result.priority_paths.append(file_path)
    
    return result.__dict__


if __name__ == "__main__":
    import json
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python scanner.py <root_path>", file=sys.stderr)
        sys.exit(1)
    
    result = scan(sys.argv[1])
    print(json.dumps(result, indent=2))
