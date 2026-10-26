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

# Same for AI (Phase 5): the .env may switch real model calls on. Tests must never call a model,
# so AI is pinned off here. Tests that need it on use monkeypatch and a fake ai_client._post.
os.environ["AI_PROVIDER"] = ""
os.environ["AI_ENABLED"] = ""
os.environ["AI_MODELS"] = ""
os.environ["AI_CLAIMANT_CHAT"] = ""
os.environ["OPENROUTER_API_KEY"] = ""

# The browser tests sign a session cookie with SESSION_SECRET_KEY, and the live server they start
# inherits it. Pin a test-only value so the suite never depends on the developer's .env (CI has
# none) and never uses the real key.
os.environ["SESSION_SECRET_KEY"] = "test-only-session-key-not-a-secret"
