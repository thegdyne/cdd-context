"""
Cache: Stores file hashes and summaries with content-addressed invalidation.

Contract: cache v1.0.0
"""

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


@dataclass
class CacheKey:
    """Cache key components for invalidation."""
    source_hash: str
    prompt_hash: str
    backend_id: str
    tool_version: str


@dataclass
class CacheEntry:
    """Stored cache entry."""
    path: str
    source_hash: str
    prompt_hash: str
    backend_id: str
    tool_version: str
    summary: dict
    timestamp: str
    approx_tokens: int = 0
    
    def matches(self, key: CacheKey) -> tuple[bool, Optional[str]]:
        """Check if entry matches key. Returns (matches, staleness_reason)."""
        if self.source_hash != key.source_hash:
            return False, "source_changed"
        if self.prompt_hash != key.prompt_hash:
            return False, "prompt_changed"
        if self.backend_id != key.backend_id:
            return False, "backend_changed"
        if self.tool_version != key.tool_version:
            return False, "tool_changed"
        return True, None


@dataclass
class CacheResult:
    """Result from cache lookup."""
    cache_hit: bool
    summary: Optional[dict] = None
    staleness_reason: Optional[str] = None
    is_stale: bool = False


@dataclass
class CacheStats:
    """Cache statistics."""
    hits: int = 0
    misses: int = 0
    tokens_saved: int = 0


class Cache:
    """
    Content-addressed cache for file summaries.
    
    Storage layout:
        .context-cache/
            {path_hash}.json  # One file per source path
    """
    
    def __init__(self, cache_dir: Optional[Path] = None):
        """
        Initialize cache.
        
        Args:
            cache_dir: Directory for cache files. Defaults to .context-cache/
        """
        self.cache_dir = cache_dir or Path(".context-cache")
        self.stats = CacheStats()
    
    def _path_hash(self, path: str) -> str:
        """Generate hash for file path (used as cache filename)."""
        return hashlib.sha256(path.encode("utf-8")).hexdigest()[:16]
    
    def _cache_file(self, path: str) -> Path:
        """Get cache file path for a source file."""
        return self.cache_dir / f"{self._path_hash(path)}.json"
    
    def _load_entry(self, path: str) -> Optional[CacheEntry]:
        """Load cache entry for path, if exists."""
        cache_file = self._cache_file(path)
        if not cache_file.exists():
            return None
        
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return CacheEntry(**data)
        except (json.JSONDecodeError, TypeError, KeyError):
            # Corrupted cache file, treat as miss
            return None
    
    def _save_entry(self, entry: CacheEntry) -> None:
        """Save cache entry atomically."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = self._cache_file(entry.path)
        
        # Atomic write: write to temp, then rename
        fd, temp_path = tempfile.mkstemp(
            dir=self.cache_dir,
            prefix=".tmp_",
            suffix=".json"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(asdict(entry), f, indent=2)
            os.replace(temp_path, cache_file)
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise
    
    def check_status(
        self,
        path: str,
        source_hash: str,
        prompt_hash: str,
        backend_id: str,
        tool_version: str,
    ) -> dict:
        """
        Check cache status without retrieving or creating entry.
        
        Returns dict with is_stale and staleness_reason.
        """
        key = CacheKey(source_hash, prompt_hash, backend_id, tool_version)
        entry = self._load_entry(path)
        
        if entry is None:
            return {
                "is_stale": True,
                "staleness_reason": "not_cached",
            }
        
        matches, reason = entry.matches(key)
        return {
            "is_stale": not matches,
            "staleness_reason": reason,
        }
    
    def get(
        self,
        path: str,
        source_hash: str,
        prompt_hash: str,
        backend_id: str,
        tool_version: str,
    ) -> CacheResult:
        """
        Get cached summary if valid.
        
        Returns CacheResult with cache_hit=True if found and valid,
        otherwise cache_hit=False with staleness_reason.
        """
        key = CacheKey(source_hash, prompt_hash, backend_id, tool_version)
        entry = self._load_entry(path)
        
        if entry is None:
            self.stats.misses += 1
            return CacheResult(
                cache_hit=False,
                is_stale=True,
                staleness_reason="not_cached",
            )
        
        matches, reason = entry.matches(key)
        
        if matches:
            self.stats.hits += 1
            self.stats.tokens_saved += entry.approx_tokens
            return CacheResult(
                cache_hit=True,
                summary=entry.summary,
                is_stale=False,
            )
        else:
            self.stats.misses += 1
            return CacheResult(
                cache_hit=False,
                is_stale=True,
                staleness_reason=reason,
            )
    
    def put(
        self,
        path: str,
        source_hash: str,
        prompt_hash: str,
        backend_id: str,
        tool_version: str,
        summary: dict,
        approx_tokens: int = 0,
    ) -> None:
        """
        Store summary in cache.
        """
        entry = CacheEntry(
            path=path,
            source_hash=source_hash,
            prompt_hash=prompt_hash,
            backend_id=backend_id,
            tool_version=tool_version,
            summary=summary,
            timestamp=datetime.now(timezone.utc).isoformat(),
            approx_tokens=approx_tokens,
        )
        self._save_entry(entry)
    
    def get_or_create(
        self,
        path: str,
        source_hash: str,
        prompt_hash: str,
        backend_id: str,
        tool_version: str,
        summary: Optional[dict] = None,
    ) -> dict:
        """
        Get cached summary or store new one.
        
        This is the main interface for the test harness.
        If summary is provided and cache misses, it stores the summary.
        
        Returns dict with cache_hit, summary, and staleness_reason.
        """
        result = self.get(path, source_hash, prompt_hash, backend_id, tool_version)
        
        if result.cache_hit:
            return {
                "cache_hit": True,
                "summary": result.summary,
                "staleness_reason": None,
            }
        
        # Cache miss
        if summary is not None:
            # Store the provided summary
            approx_tokens = len(str(summary)) // 4
            self.put(
                path, source_hash, prompt_hash, backend_id, tool_version,
                summary, approx_tokens
            )
            return {
                "cache_hit": False,
                "summary": summary,
                "staleness_reason": result.staleness_reason,
            }
        
        # No summary provided, just report miss
        return {
            "cache_hit": False,
            "summary": None,
            "staleness_reason": result.staleness_reason,
        }
    
    def clear(self) -> int:
        """
        Clear all cache entries.
        
        Returns number of entries cleared.
        """
        if not self.cache_dir.exists():
            return 0
        
        count = 0
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                cache_file.unlink()
                count += 1
            except OSError:
                pass
        
        return count
    
    def get_stats(self) -> dict:
        """Get cache statistics."""
        return {
            "hits": self.stats.hits,
            "misses": self.stats.misses,
            "tokens_saved": self.stats.tokens_saved,
            "hit_rate": (
                self.stats.hits / (self.stats.hits + self.stats.misses)
                if (self.stats.hits + self.stats.misses) > 0
                else 0.0
            ),
        }


def hash_file(path: Path) -> str:
    """Compute SHA256 hash of file contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_prompt(prompt: str) -> str:
    """Compute hash of prompt string."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


# --- Build Manifest (for --changes) ---

MANIFEST_SCHEMA_VERSION = 1
MANIFEST_FILENAME = "last_build.json"


@dataclass
class BuildManifest:
    """Persisted state from last successful build."""
    schema_version: int
    tool_version: str
    ignore_mode: str
    scan_hash: str
    files: list[dict]  # [{path, source_hash}, ...]
    
    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "tool_version": self.tool_version,
            "ignore_mode": self.ignore_mode,
            "scan_hash": self.scan_hash,
            "files": self.files,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "BuildManifest":
        return cls(
            schema_version=data.get("schema_version", 1),
            tool_version=data.get("tool_version", ""),
            ignore_mode=data.get("ignore_mode", ""),
            scan_hash=data.get("scan_hash", ""),
            files=data.get("files", []),
        )
    
    def file_hashes(self) -> dict[str, str]:
        """Return {path: source_hash} mapping."""
        return {f["path"]: f["source_hash"] for f in self.files}


@dataclass
class ChangeSet:
    """Diff between two builds."""
    prev_scan_hash: str
    cur_scan_hash: str
    ignore_mode: str
    added: list[str]
    modified: list[str]
    deleted: list[str]
    renamed: list[tuple[str, str]]  # [(old_path, new_path), ...]
    
    def is_empty(self) -> bool:
        return not (self.added or self.modified or self.deleted or self.renamed)


def save_manifest(
    cache_dir: Path,
    tool_version: str,
    ignore_mode: str,
    scan_hash: str,
    files: list[dict],
) -> None:
    """Save build manifest after successful build."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = cache_dir / MANIFEST_FILENAME
    
    # Sort files by path for determinism
    sorted_files = sorted(files, key=lambda f: f["path"])
    
    manifest = BuildManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        tool_version=tool_version,
        ignore_mode=ignore_mode,
        scan_hash=scan_hash,
        files=sorted_files,
    )
    
    # Atomic write
    fd, temp_path = tempfile.mkstemp(dir=cache_dir, prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(manifest.to_dict(), f, indent=2)
        os.replace(temp_path, manifest_path)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def load_manifest(cache_dir: Path) -> Optional[BuildManifest]:
    """Load previous build manifest, if exists."""
    manifest_path = cache_dir / MANIFEST_FILENAME
    if not manifest_path.exists():
        return None
    
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return BuildManifest.from_dict(data)
    except (json.JSONDecodeError, KeyError):
        return None


def compute_changes(
    prev: BuildManifest,
    cur_files: list[dict],
    cur_scan_hash: str,
    cur_ignore_mode: str,
) -> ChangeSet:
    """
    Compute diff between previous manifest and current scan.
    
    Args:
        prev: Previous build manifest
        cur_files: Current [{path, source_hash}, ...]
        cur_scan_hash: Current scan hash
        cur_ignore_mode: Current ignore mode
    
    Returns:
        ChangeSet with added/modified/deleted/renamed
    """
    prev_hashes = prev.file_hashes()
    cur_hashes = {f["path"]: f["source_hash"] for f in cur_files}
    
    prev_paths = set(prev_hashes.keys())
    cur_paths = set(cur_hashes.keys())
    
    # Basic diff
    added_paths = cur_paths - prev_paths
    deleted_paths = prev_paths - cur_paths
    common_paths = prev_paths & cur_paths
    
    modified = sorted([
        p for p in common_paths
        if prev_hashes[p] != cur_hashes[p]
    ])
    
    # Rename detection: match deleted hash to added hash
    renamed = []
    deleted_by_hash = {prev_hashes[p]: p for p in deleted_paths}
    
    matched_added = set()
    matched_deleted = set()
    
    for added_path in sorted(added_paths):
        added_hash = cur_hashes[added_path]
        if added_hash in deleted_by_hash:
            old_path = deleted_by_hash[added_hash]
            if old_path not in matched_deleted:
                renamed.append((old_path, added_path))
                matched_added.add(added_path)
                matched_deleted.add(old_path)
    
    # Remove matched from added/deleted
    added = sorted(added_paths - matched_added)
    deleted = sorted(deleted_paths - matched_deleted)
    
    return ChangeSet(
        prev_scan_hash=prev.scan_hash,
        cur_scan_hash=cur_scan_hash,
        ignore_mode=cur_ignore_mode,
        added=added,
        modified=modified,
        deleted=deleted,
        renamed=renamed,
    )
