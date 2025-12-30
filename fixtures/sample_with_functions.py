"""Sample module with functions."""

import os
import sys
from pathlib import Path

def public_function():
    """A public function."""
    pass

def another_public():
    """Another public function."""
    pass

class MyClass:
    """A public class."""
    pass

def _private_helper():
    """Private helper."""
    pass

if __name__ == "__main__":
    public_function()
