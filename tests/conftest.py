"""
Test isolation. Every test run uses a throwaway data folder, never the project's data/
folder that a running dev server (and your local claims) live in.

This has to happen before anything imports storage.py, because storage reads
HARBORCLAIM_DATA_DIR once, at import. pytest loads this file first. The live uvicorn that
tests/test_ui.py starts inherits the environment, so the browser tests and the server they
drive share the same throwaway folder.
"""

import atexit
import os
import shutil
import tempfile

_data_dir = tempfile.mkdtemp(prefix="harborclaim-test-")
os.environ["HARBORCLAIM_DATA_DIR"] = _data_dir
atexit.register(shutil.rmtree, _data_dir, ignore_errors=True)

# app.py loads the developer's .env on import, and that file may switch real email on. Tests
# must never send real email, so pin these here; load_dotenv() does not override variables
# that are already set. Tests that need another value use monkeypatch.setenv.
os.environ["EMAIL_PROVIDER"] = "simulated"
os.environ["EMAIL_ENABLED"] = ""
os.environ["ADJUSTER_NOTIFY_EMAIL"] = ""
os.environ["APP_BASE_URL"] = ""
