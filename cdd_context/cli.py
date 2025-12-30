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

from .cache import Cache, hash_file, hash_prompt
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
    
    # Initialize cache
    cache = Cache(cache_dir=root / ".context-cache")
    
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
    
    # Clipboard
    if args.clip:
        if copy_to_clipboard(result["content"]):
            print("Copied to clipboard")
        else:
            print("Warning: Could not copy to clipboard")
    
    return 0


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
