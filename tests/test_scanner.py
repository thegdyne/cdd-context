"""
Test runner for scanner contract.
Validates implementation against contracts/scanner.yaml assertions.
"""

import json
import sys
from pathlib import Path

# Add package to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from cdd_context.scanner import scan


def assert_eq(actual, expected, context: str):
    if actual != expected:
        raise AssertionError(f"{context}: expected {expected!r}, got {actual!r}")


def assert_contains(container, item, context: str):
    if item not in container:
        raise AssertionError(f"{context}: {item!r} not in {container!r}")


def assert_not_contains(container, item, context: str):
    if item in container:
        raise AssertionError(f"{context}: {item!r} unexpectedly in {container!r}")


def test_T001_scan_respects_gitignore():
    """T001: Git repo should exclude files in .gitignore"""
    result = scan("fixtures/project_with_gitignore")
    assert_not_contains(result["files"], "ignored_file.txt", "T001")
    assert_eq(result["ignore_mode"], "git", "T001")
    print("✓ T001 scan_respects_gitignore")


def test_T002_scan_excludes_secrets():
    """T002: Should exclude .env files"""
    result = scan("fixtures/project_with_env")
    assert_not_contains(result["files"], ".env", "T002")
    print("✓ T002 scan_excludes_secrets")


def test_T003_scan_sets_ignore_mode_git():
    """T003: Git repo should report ignore_mode: git"""
    result = scan("fixtures/project_with_gitignore")
    assert_eq(result["ignore_mode"], "git", "T003")
    print("✓ T003 scan_sets_ignore_mode_git")


def test_T004_scan_sets_ignore_mode_best_effort():
    """T004: Non-git project should report ignore_mode: best_effort"""
    result = scan("fixtures/non_git_project_with_contextignore")
    assert_eq(result["ignore_mode"], "best_effort", "T004")
    print("✓ T004 scan_sets_ignore_mode_best_effort")


def test_T005_scan_handles_gitignore_negation():
    """T005: Git repo with negation should include negated file"""
    result = scan("fixtures/project_with_gitignore_negation")
    assert_contains(result["files"], "important.env", "T005")
    print("✓ T005 scan_handles_gitignore_negation")


def test_T006_scan_warns_when_git_missing():
    """T006: Should warn and use best_effort when git missing"""
    result = scan("fixtures/project_with_gitignore", mock_git_missing=True)
    assert_eq(result["ignore_mode"], "best_effort", "T006")
    # Check warnings contains substring
    found = any("git not found" in w for w in result["warnings"])
    if not found:
        raise AssertionError(f"T006: 'git not found' not in warnings: {result['warnings']}")
    print("✓ T006 scan_warns_when_git_missing")


def test_T007_scan_handles_contextignore_negation_best_effort():
    """T007: Non-git with .contextignore negation should include negated file"""
    result = scan("fixtures/non_git_project_with_contextignore_negation")
    assert_eq(result["ignore_mode"], "best_effort", "T007")
    assert_contains(result["files"], "negated_file.txt", "T007")
    print("✓ T007 scan_handles_contextignore_negation_best_effort")


def test_priority_paths_detection():
    """R004: Should identify key files heuristically"""
    result = scan("fixtures/project_with_env")
    assert_contains(result["priority_paths"], "app.py", "R004")
    print("✓ R004 priority_paths detection")


def main():
    print("=" * 60)
    print("Scanner Contract Tests")
    print("=" * 60)
    
    tests = [
        test_T001_scan_respects_gitignore,
        test_T002_scan_excludes_secrets,
        test_T003_scan_sets_ignore_mode_git,
        test_T004_scan_sets_ignore_mode_best_effort,
        test_T005_scan_handles_gitignore_negation,
        test_T006_scan_warns_when_git_missing,
        test_T007_scan_handles_contextignore_negation_best_effort,
        test_priority_paths_detection,
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
