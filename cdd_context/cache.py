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
