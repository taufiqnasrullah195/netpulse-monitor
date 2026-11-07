"""Entry point for the test suite — avoids inline python -c approval gate."""
import sys
import pytest

if __name__ == "__main__":
    sys.exit(pytest.main(["-v", "test_scanner.py", "test_monitor.py", "test_reporter.py"]))
