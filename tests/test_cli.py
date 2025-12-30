"""
Test runner for CLI contract.
Validates implementation against contracts/cli.yaml assertions.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

# Add package to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from cdd_context.cli import main


def assert_eq(actual, expected, context: str):
    if actual != expected:
        raise AssertionError(f"{context}: expected {expected!r}, got {actual!r}")


def assert_file_exists(path: Path, context: str):
    if not path.exists():
        raise AssertionError(f"{context}: file does not exist: {path}")


def assert_file_not_exists(path: Path, context: str):
    if path.exists():
        raise AssertionError(f"{context}: file should not exist: {path}")


def test_T001_build_creates_file():
    """T001: build command should create PROJECT_CONTEXT.md."""
    # Use a temp copy of fixture
    with tempfile.TemporaryDirectory() as tmpdir:
        fixture_src = Path("fixtures/non_git_project_with_contextignore")
        fixture_dst = Path(tmpdir) / "project"
        shutil.copytree(fixture_src, fixture_dst)
        
        # Run build
        exit_code = main(["build", "--root", str(fixture_dst)])
        assert_eq(exit_code, 0, "T001 exit code")
        
        # Check file exists
        output = fixture_dst / "PROJECT_CONTEXT.md"
        assert_file_exists(output, "T001")
    
    print("✓ T001 build_creates_file")


def test_T002_dry_run_no_file():
    """T002: dry-run should not create file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fixture_src = Path("fixtures/non_git_project_with_contextignore")
        fixture_dst = Path(tmpdir) / "project"
        shutil.copytree(fixture_src, fixture_dst)
        
        # Run dry-run
        exit_code = main(["build", "--dry-run", "--root", str(fixture_dst)])
        assert_eq(exit_code, 0, "T002 exit code")
        
        # File should not exist
        output = fixture_dst / "PROJECT_CONTEXT.md"
        assert_file_not_exists(output, "T002")
    
    print("✓ T002 dry_run_no_file")


def test_T003_clear_cache():
    """T003: clear-cache should remove cache but not context file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fixture_src = Path("fixtures/non_git_project_with_contextignore")
        fixture_dst = Path(tmpdir) / "project"
        shutil.copytree(fixture_src, fixture_dst)
        
        # Build first to create cache
        main(["build", "--root", str(fixture_dst)])
        
        cache_dir = fixture_dst / ".context-cache"
        context_file = fixture_dst / "PROJECT_CONTEXT.md"
        
        assert_file_exists(cache_dir, "T003 cache created")
        assert_file_exists(context_file, "T003 context created")
        
        # Clear cache
        exit_code = main(["clear-cache", "--root", str(fixture_dst)])
        assert_eq(exit_code, 0, "T003 exit code")
        
        # Cache should be gone, context should remain
        assert_file_not_exists(cache_dir, "T003 cache cleared")
        assert_file_exists(context_file, "T003 context preserved")
    
    print("✓ T003 clear_cache")


def test_status_command():
    """R002: status should show cache info."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fixture_src = Path("fixtures/non_git_project_with_contextignore")
        fixture_dst = Path(tmpdir) / "project"
        shutil.copytree(fixture_src, fixture_dst)
        
        # Status before build
        exit_code = main(["status", "--root", str(fixture_dst)])
        assert_eq(exit_code, 0, "R002 status before build")
        
        # Build
        main(["build", "--root", str(fixture_dst)])
        
        # Status after build
        exit_code = main(["status", "--root", str(fixture_dst)])
        assert_eq(exit_code, 0, "R002 status after build")
    
    print("✓ R002 status_command")


def test_changes_no_baseline():
    """R009: --changes should fail if no baseline exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fixture_src = Path("fixtures/non_git_project_with_contextignore")
        fixture_dst = Path(tmpdir) / "project"
        shutil.copytree(fixture_src, fixture_dst)
        
        # Try --changes without prior build
        exit_code = main(["build", "--changes", "--root", str(fixture_dst)])
        assert_eq(exit_code, 2, "R009 no baseline")
    
    print("✓ R009 changes_no_baseline")


def test_changes_no_changes():
    """R009: --changes should report no changes when nothing changed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fixture_src = Path("fixtures/non_git_project_with_contextignore")
        fixture_dst = Path(tmpdir) / "project"
        shutil.copytree(fixture_src, fixture_dst)
        
        # Build first
        main(["build", "--root", str(fixture_dst)])
        
        # Check changes - should be empty
        exit_code = main(["build", "--changes", "--root", str(fixture_dst)])
        assert_eq(exit_code, 0, "R009 no changes")
    
    print("✓ R009 changes_no_changes")


def test_changes_detects_modification():
    """R009: --changes should detect modified files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fixture_src = Path("fixtures/non_git_project_with_contextignore")
        fixture_dst = Path(tmpdir) / "project"
        shutil.copytree(fixture_src, fixture_dst)
        
        # Build first
        main(["build", "--root", str(fixture_dst)])
        
        # Modify a file
        main_py = fixture_dst / "main.py"
        main_py.write_text(main_py.read_text() + "\n# modified\n")
        
        # Check changes - should detect modification
        exit_code = main(["build", "--changes=list", "--root", str(fixture_dst)])
        assert_eq(exit_code, 0, "R009 detects modification")
    
    print("✓ R009 changes_detects_modification")


def main_tests():
    print("=" * 60)
    print("CLI Contract Tests")
    print("=" * 60)
    
    tests = [
        test_T001_build_creates_file,
        test_T002_dry_run_no_file,
        test_T003_clear_cache,
        test_status_command,
        test_changes_no_baseline,
        test_changes_no_changes,
        test_changes_detects_modification,
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
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main_tests())
