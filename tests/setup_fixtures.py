#!/usr/bin/env python3
"""
Setup script to initialize git fixtures before running tests.

Run this once after cloning the repo:
    python tests/setup_fixtures.py
"""

import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], cwd: Path) -> bool:
    """Run command and return success status."""
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERROR: {' '.join(cmd)}")
        print(f"  {result.stderr}")
        return False
    return True


def setup_git_fixture(path: Path, files_to_add: list[str], ignored_files: dict[str, str] = None):
    """Initialize a git repo and add specified files."""
    print(f"Setting up {path.name}...")
    
    # Initialize git repo
    if not run(["git", "init"], path):
        return False
    
    # Create any ignored files that should exist but not be tracked
    if ignored_files:
        for filename, content in ignored_files.items():
            (path / filename).write_text(content)
    
    # Add tracked files
    for f in files_to_add:
        if not run(["git", "add", f], path):
            return False
    
    # Commit
    if not run(
        ["git", "-c", "user.email=test@test.com", "-c", "user.name=Test", 
         "commit", "-m", "Initial commit"],
        path
    ):
        return False
    
    print(f"  ✓ {path.name} ready")
    return True


def main():
    fixtures_dir = Path(__file__).parent.parent / "fixtures"
    
    print("Setting up git fixtures...")
    print()
    
    success = True
    
    # project_with_gitignore: has ignored_file.txt that should exist but not be tracked
    success &= setup_git_fixture(
        fixtures_dir / "project_with_gitignore",
        files_to_add=[".gitignore", "tracked.py"],
        ignored_files={"ignored_file.txt": "This file should be ignored\n"}
    )
    
    # project_with_gitignore_negation: has secret.env that should exist but not be tracked
    success &= setup_git_fixture(
        fixtures_dir / "project_with_gitignore_negation",
        files_to_add=[".gitignore", "code.py", "important.env"],
        ignored_files={"secret.env": "SECRET=no\n"}
    )
    
    print()
    if success:
        print("All fixtures ready. You can now run tests:")
        print("  python tests/test_scanner.py")
    else:
        print("Some fixtures failed to set up.")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
