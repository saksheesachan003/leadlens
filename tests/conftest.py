import os
import sys
import tempfile

# Use a throwaway database for every test run.
os.environ["LEADLENS_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
