"""
CLI: Command-line interface for cdd-context.

Contract: cli v1.0.0
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .cache import (
    Cache, hash_file, hash_prompt,
    save_manifest, load_manifest, compute_changes, ChangeSet,
)
from .generator import generate
from .scanner import scan
from .summarizer import summarize_file, get_prompt_hash, get_backend_id, get_tool_version


def find_project_root(start: Optional[Path] = None) -> Path:
    """Find project root via git or use cwd."""
    start = start or Path.cwd()
    
    # Try git
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    
    return start.resolve()


def cmd_build(args) -> int:
    """Build PROJECT_CONTEXT.md."""
    root = Path(args.root) if args.root else find_project_root()
    root = root.resolve()
    
    if not root.exists():
        print(f"Error: Root directory does not exist: {root}", file=sys.stderr)
        return 1
    
    # Initialize cache
    cache_dir = root / ".context-cache"
    cache = Cache(cache_dir=cache_dir)
    
    # Handle --changes mode
    changes_mode = getattr(args, 'changes', None)
    if changes_mode:
        return cmd_build_changes(args, root, cache, changes_mode)
    
    print(f"Scanning {root}...")
    
    # Scan
    scan_result = scan(str(root))
    files = scan_result["files"]
    ignore_mode = scan_result["ignore_mode"]
    priority_paths = scan_result.get("priority_paths", [])
    
    if scan_result.get("warnings"):
        for warning in scan_result["warnings"]:
            print(f"  Warning: {warning}")
    
    print(f"  Found {len(files)} files (mode: {ignore_mode})")
    
    if args.dry_run:
        print("\n[Dry run] Would summarize:")
        for f in files[:20]:
            print(f"  {f}")
        if len(files) > 20:
            print(f"  ... and {len(files) - 20} more")
        return 0
    
    # Summarize files
    print("Summarizing files...")
    summaries = []
    cache_hits = 0
    
    prompt_hash = get_prompt_hash()
    backend_id = get_backend_id()
    tool_version = get_tool_version()
    
    for i, file_path in enumerate(files):
        full_path = root / file_path
        
        if not full_path.exists():
            continue
        
        # Compute source hash
        try:
            source_hash = hash_file(full_path)
        except Exception:
            continue
        
        # Check cache
        cache_result = cache.get(
            path=file_path,
            source_hash=source_hash,
            prompt_hash=prompt_hash,
            backend_id=backend_id,
            tool_version=tool_version,
        )
        
        if cache_result.cache_hit:
            summary = cache_result.summary
            cache_hits += 1
        else:
            # Generate summary (heuristic only for now)
            summary = summarize_file(str(full_path), use_llm=False)
            
            # Store in cache
            cache.put(
                path=file_path,
                source_hash=source_hash,
                prompt_hash=prompt_hash,
                backend_id=backend_id,
                tool_version=tool_version,
                summary=summary,
            )
        
        summaries.append({
            "path": file_path,
            "source_hash": source_hash,
            "summary": summary,
        })
        
        # Progress
        if (i + 1) % 50 == 0:
            print(f"  Processed {i + 1}/{len(files)} files...")
    
    print(f"  Cache: {cache_hits}/{len(summaries)} hits")
    
    # Generate context
    print("Generating context...")
    project_name = root.name
    
    # Compute scan_hash for manifest
    from .generator import _compute_scan_hash, FileSummary
    file_summaries = [
        FileSummary(path=s["path"], source_hash=s["source_hash"], summary=s["summary"])
        for s in summaries
    ]
    scan_hash = _compute_scan_hash(file_summaries, ignore_mode)
    
    result = generate(
        files=summaries,
        ignore_mode=ignore_mode,
        cache_hits=cache_hits,
        cache_total=len(summaries),
        priority_paths=priority_paths,
        project_name=project_name,
    )
    
    if result["warnings"]:
        for warning in result["warnings"]:
            print(f"  Warning: {warning}")
    
    print(f"  Tokens: ~{result['approx_tokens']}")
    
    # Write output
    output_path = root / "PROJECT_CONTEXT.md"
    output_path.write_text(result["content"], encoding="utf-8")
    print(f"\nWrote {output_path}")
    
    # Save manifest for --changes
    save_manifest(
        cache_dir=cache_dir,
        tool_version=tool_version,
        ignore_mode=ignore_mode,
        scan_hash=scan_hash,
        files=[{"path": s["path"], "source_hash": s["source_hash"]} for s in summaries],
    )
    
    # Clipboard
    if args.clip:
        if copy_to_clipboard(result["content"]):
            print("Copied to clipboard")
        else:
            print("Warning: Could not copy to clipboard")
    
    return 0


def cmd_build_changes(args, root: Path, cache: Cache, changes_mode: str) -> int:
    """Build changes output (delta since last build)."""
    cache_dir = root / ".context-cache"
    
    # Load previous manifest
    prev_manifest = load_manifest(cache_dir)
    if prev_manifest is None:
        print("No previous build snapshot found; run 'cdd-context build' first.", file=sys.stderr)
        return 2
    
    # Scan current state
    scan_result = scan(str(root))
    files = scan_result["files"]
    ignore_mode = scan_result["ignore_mode"]
    
    # Check ignore_mode mismatch
    if prev_manifest.ignore_mode != ignore_mode:
        print(
            f"Baseline built with ignore_mode={prev_manifest.ignore_mode}, "
            f"current run is {ignore_mode}; run full build to reset baseline.",
            file=sys.stderr
        )
        return 2
    
    # Hash current files
    tool_version = get_tool_version()
    prompt_hash = get_prompt_hash()
    backend_id = get_backend_id()
    
    cur_files = []
    for file_path in files:
        full_path = root / file_path
        if not full_path.exists():
            continue
        try:
            source_hash = hash_file(full_path)
            cur_files.append({"path": file_path, "source_hash": source_hash})
        except Exception:
            continue
    
    # Compute scan_hash
    from .generator import _compute_scan_hash, FileSummary
    file_summaries = [FileSummary(path=f["path"], source_hash=f["source_hash"]) for f in cur_files]
    cur_scan_hash = _compute_scan_hash(file_summaries, ignore_mode)
    
    # Compute changes
    changes = compute_changes(prev_manifest, cur_files, cur_scan_hash, ignore_mode)
    
    if changes.is_empty():
        print("No changes since last build.")
        return 0
    
    # Generate output based on mode
    project_name = root.name
    
    if changes_mode == "list":
        output = format_changes_list(project_name, changes)
    elif changes_mode == "summaries":
        output = format_changes_summaries(
            project_name, changes, root, cache,
            prompt_hash, backend_id, tool_version
        )
    else:  # both
        output = format_changes_both(
            project_name, changes, root, cache,
            prompt_hash, backend_id, tool_version
        )
    
    # Output
    print(output)
    
    if args.clip:
        if copy_to_clipboard(output):
            print("\nCopied to clipboard")
        else:
            print("\nWarning: Could not copy to clipboard")
    
    return 0


def format_changes_list(project_name: str, changes: ChangeSet) -> str:
    """Format changes as list only."""
    lines = [
        f"# Project Changes: {project_name}",
        "",
        f"> Since scan: {changes.prev_scan_hash} → {changes.cur_scan_hash} | Mode: {changes.ignore_mode}",
        "",
    ]
    
    if changes.modified:
        lines.append("## Modified")
        for path in changes.modified:
            lines.append(f"- {path}")
        lines.append("")
    
    if changes.added:
        lines.append("## Added")
        for path in changes.added:
            lines.append(f"- {path}")
        lines.append("")
    
    if changes.deleted:
        lines.append("## Deleted")
        for path in changes.deleted:
            lines.append(f"- {path}")
        lines.append("")
    
    if changes.renamed:
        lines.append("## Renamed")
        for old_path, new_path in changes.renamed:
            lines.append(f"- {old_path} → {new_path}")
        lines.append("")
    
    return "\n".join(lines)


def format_changes_both(
    project_name: str,
    changes: ChangeSet,
    root: Path,
    cache: Cache,
    prompt_hash: str,
    backend_id: str,
    tool_version: str,
) -> str:
    """Format changes with list header then summaries."""
    lines = [
        f"# Project Changes: {project_name}",
        "",
        f"> Since scan: {changes.prev_scan_hash} → {changes.cur_scan_hash} | Mode: {changes.ignore_mode}",
        "",
    ]
    
    # Summary line
    parts = []
    if changes.modified:
        parts.append(f"{len(changes.modified)} modified")
    if changes.added:
        parts.append(f"{len(changes.added)} added")
    if changes.deleted:
        parts.append(f"{len(changes.deleted)} deleted")
    if changes.renamed:
        parts.append(f"{len(changes.renamed)} renamed")
    
    lines.append(f"**Changes:** {', '.join(parts)}")
    lines.append("")
    
    def get_summary(file_path: str) -> dict:
        full_path = root / file_path
        try:
            source_hash = hash_file(full_path)
        except Exception:
            return {"summary": f"Could not read: {file_path}"}
        
        cache_result = cache.get(
            path=file_path,
            source_hash=source_hash,
            prompt_hash=prompt_hash,
            backend_id=backend_id,
            tool_version=tool_version,
        )
        
        if cache_result.cache_hit:
            return cache_result.summary
        
        summary = summarize_file(str(full_path), use_llm=False)
        cache.put(file_path, source_hash, prompt_hash, backend_id, tool_version, summary)
        return summary
    
    def format_file_summary(path: str, summary: dict) -> list[str]:
        result = [f"### {path}"]
        role = summary.get("role", "unknown")
        result.append(f"**Role:** {role}")
        result.append("")
        result.append(summary.get("summary", ""))
        
        public_symbols = summary.get("public_symbols", [])
        if public_symbols:
            result.append("")
            result.append(f"**Provides:** {', '.join(public_symbols[:10])}")
        
        import_deps = summary.get("import_deps", [])
        if import_deps:
            result.append(f"**Consumes:** {', '.join(import_deps[:10])}")
        
        result.append("")
        return result
    
    if changes.modified:
        lines.append("## Modified")
        lines.append("")
        for path in changes.modified:
            summary = get_summary(path)
            lines.extend(format_file_summary(path, summary))
    
    if changes.added:
        lines.append("## Added")
        lines.append("")
        for path in changes.added:
            summary = get_summary(path)
            lines.extend(format_file_summary(path, summary))
    
    if changes.renamed:
        lines.append("## Renamed")
        lines.append("")
        for old_path, new_path in changes.renamed:
            lines.append(f"*{old_path} → {new_path}*")
            lines.append("")
            summary = get_summary(new_path)
            lines.extend(format_file_summary(new_path, summary))
    
    if changes.deleted:
        lines.append("## Deleted")
        lines.append("")
        for path in changes.deleted:
            lines.append(f"- {path}")
        lines.append("")
    
    return "\n".join(lines)


def format_changes_summaries(
    project_name: str,
    changes: ChangeSet,
    root: Path,
    cache: Cache,
    prompt_hash: str,
    backend_id: str,
    tool_version: str,
) -> str:
    """Format changes with summaries for added/modified files."""
    lines = [
        f"# Project Changes: {project_name}",
        "",
        f"> Since scan: {changes.prev_scan_hash} → {changes.cur_scan_hash} | Mode: {changes.ignore_mode}",
        "",
    ]
    
    def get_summary(file_path: str) -> dict:
        full_path = root / file_path
        try:
            source_hash = hash_file(full_path)
        except Exception:
            return {"summary": f"Could not read: {file_path}"}
        
        # Check cache
        cache_result = cache.get(
            path=file_path,
            source_hash=source_hash,
            prompt_hash=prompt_hash,
            backend_id=backend_id,
            tool_version=tool_version,
        )
        
        if cache_result.cache_hit:
            return cache_result.summary
        
        # Generate summary
        summary = summarize_file(str(full_path), use_llm=False)
        cache.put(file_path, source_hash, prompt_hash, backend_id, tool_version, summary)
        return summary
    
    def format_file_summary(path: str, summary: dict) -> list[str]:
        result = [f"### {path}"]
        role = summary.get("role", "unknown")
        result.append(f"**Role:** {role}")
        result.append("")
        result.append(summary.get("summary", ""))
        
        public_symbols = summary.get("public_symbols", [])
        if public_symbols:
            result.append("")
            result.append(f"**Provides:** {', '.join(public_symbols[:10])}")
        
        import_deps = summary.get("import_deps", [])
        if import_deps:
            result.append(f"**Consumes:** {', '.join(import_deps[:10])}")
        
        result.append("")
        return result
    
    if changes.modified:
        lines.append("## Modified")
        lines.append("")
        for path in changes.modified:
            summary = get_summary(path)
            lines.extend(format_file_summary(path, summary))
    
    if changes.added:
        lines.append("## Added")
        lines.append("")
        for path in changes.added:
            summary = get_summary(path)
            lines.extend(format_file_summary(path, summary))
    
    if changes.renamed:
        lines.append("## Renamed")
        lines.append("")
        for old_path, new_path in changes.renamed:
            summary = get_summary(new_path)
            lines.append(f"### {old_path} → {new_path}")
            lines.extend(format_file_summary(new_path, summary)[1:])  # Skip duplicate header
    
    if changes.deleted:
        lines.append("## Deleted")
        lines.append("")
        for path in changes.deleted:
            lines.append(f"- {path}")
        lines.append("")
    
    return "\n".join(lines)


def cmd_status(args) -> int:
    """Show cache status."""
    root = Path(args.root) if args.root else find_project_root()
    root = root.resolve()
    
    cache_dir = root / ".context-cache"
    
    if not cache_dir.exists():
        print("No cache found.")
        return 0
    
    # Count cache entries
    entries = list(cache_dir.glob("*.json"))
    print(f"Cache directory: {cache_dir}")
    print(f"Cache entries: {len(entries)}")
    
    # Check for PROJECT_CONTEXT.md
    context_file = root / "PROJECT_CONTEXT.md"
    if context_file.exists():
        stat = context_file.stat()
        print(f"Context file: {context_file} ({stat.st_size} bytes)")
    else:
        print("Context file: not found")
    
    return 0


def cmd_clear_cache(args) -> int:
    """Clear cache directory."""
    root = Path(args.root) if args.root else find_project_root()
    root = root.resolve()
    
    cache_dir = root / ".context-cache"
    
    if not cache_dir.exists():
        print("No cache to clear.")
        return 0
    
    shutil.rmtree(cache_dir)
    print(f"Cleared {cache_dir}")
    
    return 0


def cmd_watch(args) -> int:
    """Watch for changes and rebuild."""
    print("Watch mode not yet implemented.")
    print("Use: cdd-context build")
    return 1


def copy_to_clipboard(text: str) -> bool:
    """Copy text to clipboard. Returns True on success."""
    # macOS
    if shutil.which("pbcopy"):
        try:
            subprocess.run(["pbcopy"], input=text.encode(), check=True)
            return True
        except subprocess.SubprocessError:
            pass
    
    # Linux - xclip
    if shutil.which("xclip"):
        try:
            subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=text.encode(),
                check=True
            )
            return True
        except subprocess.SubprocessError:
            pass
    
    # Linux - xsel
    if shutil.which("xsel"):
        try:
            subprocess.run(
                ["xsel", "--clipboard", "--input"],
                input=text.encode(),
                check=True
            )
            return True
        except subprocess.SubprocessError:
            pass
    
    # Windows
    if shutil.which("clip"):
        try:
            subprocess.run(["clip"], input=text.encode(), check=True)
            return True
        except subprocess.SubprocessError:
            pass
    
    return False


def main(argv: Optional[list[str]] = None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="cdd-context",
        description="Generate LLM context files for codebases",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"cdd-context {get_tool_version()}",
    )
    
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # build
    build_parser = subparsers.add_parser("build", help="Generate PROJECT_CONTEXT.md")
    build_parser.add_argument("--root", help="Project root directory")
    build_parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    build_parser.add_argument("--clip", action="store_true", help="Copy to clipboard")
    build_parser.add_argument("--format", choices=["md", "json"], default="md", help="Output format")
    build_parser.add_argument(
        "--changes",
        nargs="?",
        const="both",
        choices=["list", "summaries", "both"],
        help="Show changes since last build (list, summaries, or both)"
    )
    build_parser.set_defaults(func=cmd_build)
    
    # status
    status_parser = subparsers.add_parser("status", help="Show cache status")
    status_parser.add_argument("--root", help="Project root directory")
    status_parser.set_defaults(func=cmd_status)
    
    # clear-cache
    clear_parser = subparsers.add_parser("clear-cache", help="Clear cache")
    clear_parser.add_argument("--root", help="Project root directory")
    clear_parser.set_defaults(func=cmd_clear_cache)
    
    # watch
    watch_parser = subparsers.add_parser("watch", help="Watch for changes")
    watch_parser.add_argument("--root", help="Project root directory")
    watch_parser.set_defaults(func=cmd_watch)
    
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
