"""
Test runner for cache contract.
Validates implementation against contracts/cache.yaml assertions.
"""

import shutil
import sys
import tempfile
from pathlib import Path

# Add package to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from cdd_context.cache import Cache


def assert_eq(actual, expected, context: str):
    if actual != expected:
        raise AssertionError(f"{context}: expected {expected!r}, got {actual!r}")


def assert_has_keys(obj, keys, context: str):
    missing = [k for k in keys if k not in obj]
    if missing:
        raise AssertionError(f"{context}: missing keys {missing} in {obj}")


class TestContext:
    """Manages temp directory for cache tests."""
    
    def __init__(self):
        self.temp_dir = None
        self.cache = None
    
    def __enter__(self):
        self.temp_dir = tempfile.mkdtemp()
        self.cache = Cache(cache_dir=Path(self.temp_dir) / ".context-cache")
        return self
    
    def __exit__(self, *args):
        if self.temp_dir:
            shutil.rmtree(self.temp_dir, ignore_errors=True)


def test_T001_cache_hit_on_unchanged():
    """T001: Cache should hit when all key components match."""
    with TestContext() as ctx:
        # First call - store
        first = ctx.cache.get_or_create(
            path="test.py",
            source_hash="abc123",
            prompt_hash="p1",
            backend_id="claude:haiku",
            tool_version="0.3.0",
            summary={"text": "Test summary"},
        )
        assert_eq(first["cache_hit"], False, "T001 first call")
        
        # Second call - should hit
        second = ctx.cache.get_or_create(
            path="test.py",
            source_hash="abc123",
            prompt_hash="p1",
            backend_id="claude:haiku",
            tool_version="0.3.0",
        )
        assert_eq(second["cache_hit"], True, "T001 second call")
    
    print("✓ T001 cache_hit_on_unchanged")


def test_T002_cache_miss_on_source_changed():
    """T002: Cache should miss when source_hash changes."""
    with TestContext() as ctx:
        # First call - store
        ctx.cache.get_or_create(
            path="test.py",
            source_hash="abc123",
            prompt_hash="p1",
            backend_id="claude:haiku",
            tool_version="0.3.0",
            summary={"text": "Test summary"},
        )
        
        # Second call - different source_hash
        second = ctx.cache.get_or_create(
            path="test.py",
            source_hash="def456",
            prompt_hash="p1",
            backend_id="claude:haiku",
            tool_version="0.3.0",
        )
        assert_eq(second["cache_hit"], False, "T002")
        assert_eq(second["staleness_reason"], "source_changed", "T002")
    
    print("✓ T002 cache_miss_on_source_changed")


def test_T003_cache_miss_on_prompt_change():
    """T003: Cache should miss when prompt_hash changes."""
    with TestContext() as ctx:
        # First call - store
        ctx.cache.get_or_create(
            path="test.py",
            source_hash="abc123",
            prompt_hash="p1",
            backend_id="claude:haiku",
            tool_version="0.3.0",
            summary={"text": "Test summary"},
        )
        
        # Second call - different prompt_hash
        second = ctx.cache.get_or_create(
            path="test.py",
            source_hash="abc123",
            prompt_hash="p2",
            backend_id="claude:haiku",
            tool_version="0.3.0",
        )
        assert_eq(second["cache_hit"], False, "T003")
        assert_eq(second["staleness_reason"], "prompt_changed", "T003")
    
    print("✓ T003 cache_miss_on_prompt_change")


def test_T004_cache_miss_on_backend_change():
    """T004: Cache should miss when backend_id changes."""
    with TestContext() as ctx:
        # First call - store
        ctx.cache.get_or_create(
            path="test.py",
            source_hash="abc123",
            prompt_hash="p1",
            backend_id="claude:haiku",
            tool_version="0.3.0",
            summary={"text": "Test summary"},
        )
        
        # Second call - different backend_id
        second = ctx.cache.get_or_create(
            path="test.py",
            source_hash="abc123",
            prompt_hash="p1",
            backend_id="claude:sonnet",
            tool_version="0.3.0",
        )
        assert_eq(second["cache_hit"], False, "T004")
        assert_eq(second["staleness_reason"], "backend_changed", "T004")
    
    print("✓ T004 cache_miss_on_backend_change")


def test_T005_cache_miss_on_tool_version_change():
    """T005: Cache should miss when tool_version changes."""
    with TestContext() as ctx:
        # First call - store
        ctx.cache.get_or_create(
            path="test.py",
            source_hash="abc123",
            prompt_hash="p1",
            backend_id="claude:haiku",
            tool_version="0.2.0",
            summary={"text": "Test summary"},
        )
        
        # Second call - different tool_version
        second = ctx.cache.get_or_create(
            path="test.py",
            source_hash="abc123",
            prompt_hash="p1",
            backend_id="claude:haiku",
            tool_version="0.3.0",
        )
        assert_eq(second["cache_hit"], False, "T005")
        assert_eq(second["staleness_reason"], "tool_changed", "T005")
    
    print("✓ T005 cache_miss_on_tool_version_change")


def test_T006_status_reports_staleness_reason():
    """T006: check_status should report staleness info."""
    with TestContext() as ctx:
        result = ctx.cache.check_status(
            path="test.py",
            source_hash="abc123",
            prompt_hash="p1",
            backend_id="claude:haiku",
            tool_version="0.3.0",
        )
        assert_has_keys(result, ["is_stale", "staleness_reason"], "T006")
    
    print("✓ T006 status_reports_staleness_reason")


def test_cache_stats():
    """R004: Cache should track statistics."""
    with TestContext() as ctx:
        # Miss
        ctx.cache.get_or_create(
            path="test.py",
            source_hash="abc123",
            prompt_hash="p1",
            backend_id="claude:haiku",
            tool_version="0.3.0",
            summary={"text": "Test summary"},
        )
        
        # Hit
        ctx.cache.get_or_create(
            path="test.py",
            source_hash="abc123",
            prompt_hash="p1",
            backend_id="claude:haiku",
            tool_version="0.3.0",
        )
        
        stats = ctx.cache.get_stats()
        assert_eq(stats["hits"], 1, "R004 hits")
        assert_eq(stats["misses"], 1, "R004 misses")
    
    print("✓ R004 cache_stats")


def test_atomic_write():
    """R006: Cache should use atomic writes."""
    with TestContext() as ctx:
        # Write entry
        ctx.cache.put(
            path="test.py",
            source_hash="abc123",
            prompt_hash="p1",
            backend_id="claude:haiku",
            tool_version="0.3.0",
            summary={"text": "Test summary"},
        )
        
        # Verify file exists and is valid JSON
        cache_files = list(ctx.cache.cache_dir.glob("*.json"))
        assert_eq(len(cache_files), 1, "R006 file count")
        
        # Verify no temp files left
        temp_files = list(ctx.cache.cache_dir.glob(".tmp_*"))
        assert_eq(len(temp_files), 0, "R006 no temp files")
    
    print("✓ R006 atomic_write")


def main():
    print("=" * 60)
    print("Cache Contract Tests")
    print("=" * 60)
    
    tests = [
        test_T001_cache_hit_on_unchanged,
        test_T002_cache_miss_on_source_changed,
        test_T003_cache_miss_on_prompt_change,
        test_T004_cache_miss_on_backend_change,
        test_T005_cache_miss_on_tool_version_change,
        test_T006_status_reports_staleness_reason,
        test_cache_stats,
        test_atomic_write,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"✗ {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {test.__name__}: unexpected error: {e}")
            failed += 1
    
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
