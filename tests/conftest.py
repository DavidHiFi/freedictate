import os
import sys
import tempfile
from pathlib import Path

# Every test runs against a scratch profile, never the real settings.
os.environ.setdefault("FREEDICTATE_HOME", tempfile.mkdtemp(prefix="fd-test-"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
