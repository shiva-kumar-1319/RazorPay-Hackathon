import sys
import os

os.environ["PYTHONUNBUFFERED"] = "1"
sys.path.insert(0, os.path.abspath("."))
sys.path.insert(0, os.path.abspath(".venv/Lib/site-packages"))

import pytest

print("Running full test suite...")
sys.stdout.flush()
exit_code = pytest.main(["tests", "-v", "--tb=short"])
print(f"\nPytest finished with exit code {exit_code}")
sys.stdout.flush()
sys.exit(exit_code)
