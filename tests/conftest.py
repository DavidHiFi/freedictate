import os
import sys
import tempfile
from pathlib import Path

# Every test runs against a scratch profile, never the real settings.
os.environ.setdefault("FREEDICTATE_HOME", tempfile.mkdtemp(prefix="fd-test-"))
# Qt tests build real windows. Offscreen keeps them off the shared desktop, where
# a visible window steals focus from whoever is using the PC.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
