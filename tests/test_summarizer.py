"""
Test runner for summarizer contract.
Validates implementation against contracts/summarizer.yaml assertions.
"""

import sys
from pathlib import Path

# Add package to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from cdd_context.summarizer import summarize_file


def assert_eq(actual, expected, context: str):
    if actual != expected:
        raise AssertionError(f"{context}: expected {expected!r}, got {actual!r}")


def assert_has_keys(obj, keys, context: str):
    missing = [k for k in keys if k not in obj]
    if missing:
        raise AssertionError(f"{context}: missing keys {missing}")


def assert_gt(actual, expected, context: str):
    if not actual > expected:
        raise AssertionError(f"{context}: expected {actual} > {expected}")


def assert_in(item, container, context: str):
    if item not in container:
        raise AssertionError(f"{context}: {item!r} not in {container!r}")


def test_T001_summarize_returns_all_fields():
    """T001: Should return all required fields."""
    result = summarize_file(
        "fixtures/non_git_project_with_contextignore/main.py",
        use_llm=False
    )
    assert_has_keys(
        result,
        ["summary", "role", "public_symbols", "import_deps", "excluded", "is_binary"],
        "T001"
    )
    print("✓ T001 summarize_returns_all_fields")


def test_T002_binary_file_excluded():
    """T002: Binary files should be excluded."""
    result = summarize_file("fixtures/binary_file.bin", use_llm=False)
    assert_eq(result["excluded"], True, "T002 excluded")
    assert_eq(result["exclusion_reason"], "binary_file", "T002 reason")
    print("✓ T002 binary_file_excluded")


def test_T003_large_file_excluded():
    """T003: Large files should be excluded from LLM."""
    result = summarize_file("fixtures/large_file.py", use_llm=False)
    assert_eq(result["excluded"], True, "T003 excluded")
    assert_eq(result["exclusion_reason"], "file_too_large", "T003 reason")
    print("✓ T003 large_file_excluded")


def test_T004_private_key_excluded():
    """T004: Files with private keys should be excluded."""
    result = summarize_file("fixtures/file_with_private_key.py", use_llm=False)
    assert_eq(result["excluded"], True, "T004 excluded")
    assert_eq(result["exclusion_reason"], "private_key_block", "T004 reason")
    print("✓ T004 private_key_excluded")


def test_T005_heuristic_extracts_functions():
    """T005: Heuristic should extract public functions."""
    result = summarize_file("fixtures/sample_with_functions.py", use_llm=False)
    assert_gt(result["public_symbols_count"], 0, "T005")
    # Should find public_function, another_public, MyClass
    # But not _private_helper
    assert_in("public_function", result["public_symbols"], "T005 public_function")
    assert_in("MyClass", result["public_symbols"], "T005 MyClass")
    print("✓ T005 heuristic_extracts_functions")


def test_T006_role_classification():
    """T006: Should classify file role correctly."""
    result = summarize_file(
        "fixtures/non_git_project_with_contextignore/main.py",
        use_llm=False
    )
    valid_roles = ["entrypoint", "config", "library", "test", "docs", "asset", "unknown"]
    assert_in(result["role"], valid_roles, "T006")
    print("✓ T006 role_classification")


def test_heuristic_extracts_imports():
    """R003: Heuristic should extract imports."""
    result = summarize_file("fixtures/sample_with_functions.py", use_llm=False)
    assert_in("os", result["import_deps"], "R003 os import")
    assert_in("sys", result["import_deps"], "R003 sys import")
    assert_in("pathlib", result["import_deps"], "R003 pathlib import")
    print("✓ R003 heuristic_extracts_imports")


def test_entrypoint_detection():
    """R003: Should detect if __name__ == '__main__' entrypoints."""
    result = summarize_file("fixtures/sample_with_functions.py", use_llm=False)
    assert_gt(result["entrypoints_count"], 0, "entrypoint detection")
    assert_eq(result["entrypoints"][0]["evidence"], 'if __name__ == "__main__"', "evidence")
    print("✓ R003 entrypoint_detection")


def main():
    print("=" * 60)
    print("Summarizer Contract Tests")
    print("=" * 60)
    
    tests = [
        test_T001_summarize_returns_all_fields,
        test_T002_binary_file_excluded,
        test_T003_large_file_excluded,
        test_T004_private_key_excluded,
        test_T005_heuristic_extracts_functions,
        test_T006_role_classification,
        test_heuristic_extracts_imports,
        test_entrypoint_detection,
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
