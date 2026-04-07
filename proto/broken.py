"""Deliberately broken script for AutoDream E2E demo.

Running commands that interact with this script triggers real OS failures
that map to AutoDream FAILURE_PATTERNS.
"""

# This file intentionally does nothing useful.
# The tests in test_autodream_demo.py execute bash commands that would
# attempt to read or operate on paths derived from this script's location,
# triggering "no such file or directory", "file not found", and
# "command not found" errors.
