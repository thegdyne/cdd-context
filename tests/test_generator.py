"""
Test runner for generator contract.
Validates implementation against contracts/generator.yaml assertions.
"""

import sys
from pathlib import Path

# Add package to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from cdd_context.generator import generate


def assert_eq(actual, expected, context: str):
    if actual != expected:
        raise AssertionError(f"{context}: expected {expected!r}, got {actual!r}")


def assert_contains(container, item, context: str):
    if item not in container:
        raise AssertionError(f"{context}: {item!r} not in container")


def assert_has_keys(obj, keys, context: str):
    missing = [k for k in keys if k not in obj]
    if missing:
        raise AssertionError(f"{context}: missing keys {missing}")


# Test fixtures
SAMPLE_FILES = [
    {
        "path": "src/main.py",
        "source_hash": "abc123",
        "summary": {"summary": "Main entry point", "role": "entrypoint"}
    },
    {
        "path": "src/utils.py",
        "source_hash": "def456",
        "summary": {"summary": "Utility functions", "role": "library"}
    },
    {
        "path": "README.md",
        "source_hash": "ghi789",
        "summary": {"summary": "Project readme", "role": "docs"}
    },
]

# Large files to trigger budget warning
LARGE_FILES = [
    {
        "path": f"src/package{i // 50}/module_{i}.py",
        "source_hash": f"hash{i}",
        "summary": {"summary": "A very long summary text that will contribute many tokens " * 3, "role": "library"}
    }
    for i in range(400)
]


def test_T001_output_contains_directory_structure():
    """T001: Output should contain directory structure section."""
    result = generate(
        files=[{
            "path": "src/main.py",
            "summary": {"summary": "Main entry", "role": "entrypoint"}
        }],
        ignore_mode="git"
    )
    assert_contains(result["content"], "## Directory Structure", "T001")
    print("✓ T001 output_contains_directory_structure")


def test_T002_output_contains_key_files():
    """T002: Output should contain key files section."""
    result = generate(
        files=[{
            "path": "README.md",
            "summary": {"summary": "Project readme", "role": "docs"}
        }],
        ignore_mode="git"
    )
    assert_contains(result["content"], "## Key Files", "T002")
    print("✓ T002 output_contains_key_files")


def test_T003_warns_on_large_output():
    """T003: Should warn when output exceeds token budget."""
    result = generate(files=LARGE_FILES, ignore_mode="git")
    assert_contains(result["warnings"], "token_budget_exceeded", "T003")
    print("✓ T003 warns_on_large_output")


def test_T004_output_deterministic():
    """T004: Same input should produce same output."""
    first = generate(files=SAMPLE_FILES, ignore_mode="git")
    second = generate(files=SAMPLE_FILES, ignore_mode="git")
    assert_eq(first["content"], second["content"], "T004")
    print("✓ T004 output_deterministic")


def test_T005_returns_structured_output():
    """T005: Should return all required fields."""
    result = generate(
        files=[{
            "path": "test.py",
            "summary": {"summary": "Test", "role": "test"}
        }],
        ignore_mode="git"
    )
    assert_has_keys(result, ["content", "warnings", "approx_tokens", "scan_hash"], "T005")
    print("✓ T005 returns_structured_output")


def test_scan_hash_differs_by_ignore_mode():
    """R003: scan_hash should differ by ignore_mode."""
    git_result = generate(files=SAMPLE_FILES, ignore_mode="git")
    best_effort_result = generate(files=SAMPLE_FILES, ignore_mode="best_effort")
    
    if git_result["scan_hash"] == best_effort_result["scan_hash"]:
        raise AssertionError("scan_hash should differ by ignore_mode")
    print("✓ R003 scan_hash_differs_by_ignore_mode")


def test_tree_structure():
    """R001: Tree should show directory hierarchy."""
    result = generate(
        files=[
            {"path": "src/main.py", "summary": {"summary": "Main", "role": "entrypoint"}},
            {"path": "src/utils/helpers.py", "summary": {"summary": "Helpers", "role": "library"}},
            {"path": "tests/test_main.py", "summary": {"summary": "Tests", "role": "test"}},
        ],
        ignore_mode="git"
    )
    # Should contain tree markers
    assert_contains(result["content"], "src/", "tree structure")
    print("✓ R001 tree_structure")


def test_entrypoint_in_key_files():
    """R001: Entrypoints should be in key files."""
    result = generate(
        files=[
            {"path": "main.py", "summary": {"summary": "Main entry", "role": "entrypoint"}},
            {"path": "lib.py", "summary": {"summary": "Library", "role": "library"}},
        ],
        ignore_mode="git"
    )
    # main.py should be in Key Files section, not Other Files
    assert_contains(result["content"], "### main.py", "entrypoint in key files")
    print("✓ R001 entrypoint_in_key_files")


def main():
    print("=" * 60)
    print("Generator Contract Tests")
    print("=" * 60)
    
    tests = [
        test_T001_output_contains_directory_structure,
        test_T002_output_contains_key_files,
        test_T003_warns_on_large_output,
        test_T004_output_deterministic,
        test_T005_returns_structured_output,
        test_scan_hash_differs_by_ignore_mode,
        test_tree_structure,
        test_entrypoint_in_key_files,
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
