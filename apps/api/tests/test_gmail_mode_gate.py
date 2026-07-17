"""The demo backend must never import Gmail code.

Verified by spawning a subprocess with WINNOW_MODE=demo and attempting
``import winnow_api.gmail``. Subprocess is the honest test — an
in-process test would be polluted by the parent's already-imported
modules and the ``@lru_cache`` on ``get_settings``.

If this test ever passes silently in the failure direction (e.g. the
import-time gate is deleted or misplaced), a demo deployment could
gain the ability to touch Gmail. That is why the gate lives in
``winnow_api/gmail/__init__.py`` and this test is here.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


_PYTHON = sys.executable
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _run_import(module: str, env_overrides: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    # Clear the .env-loaded values so the subprocess sees exactly what
    # we set. pydantic-settings would otherwise pick up .env.
    for k in list(env):
        if k.startswith("WINNOW_"):
            env.pop(k, None)
    env.update(env_overrides)
    # PYTHONPATH so the subprocess finds our workspace without an install step.
    env["PYTHONPATH"] = str(_REPO_ROOT / "apps" / "api") + os.pathsep + str(
        _REPO_ROOT / "packages" / "seed-data"
    )
    return subprocess.run(
        [_PYTHON, "-c", f"import {module}"],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )


def test_gmail_import_fails_in_demo_mode():
    result = _run_import(
        "winnow_api.gmail",
        {
            "WINNOW_MODE": "demo",
            "WINNOW_DATABASE_URL": "postgresql+psycopg://unused/x",
            "WINNOW_IP_HASH_SALT": "salt",
        },
    )
    assert result.returncode != 0
    assert "real-mode only" in result.stderr
    assert "WINNOW_MODE=demo" in result.stderr


def test_gmail_import_succeeds_in_real_mode():
    """Symmetric check — the guard doesn't spuriously fire in real mode.

    Uses a dummy DATABASE_URL because no connection is made at import
    time; only the Settings construction path is exercised.
    """
    result = _run_import(
        "winnow_api.gmail",
        {
            "WINNOW_MODE": "real",
            "WINNOW_DATABASE_URL": "postgresql+psycopg://unused/x",
            "WINNOW_ENCRYPTION_KEY": "x" * 44,
            "WINNOW_LLM_API_KEY": "sk-test",
        },
    )
    assert result.returncode == 0, result.stderr
