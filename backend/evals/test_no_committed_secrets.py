"""No tracked file may contain a real-looking credential.

This exists because of a live near-miss: a real provider API key was pasted
into backend/.env.example - the tracked template - instead of backend/.env,
the gitignored file. It never reached a commit, but only because it was
caught by eye. `.env.example` sits right next to `.env`, is named to be
edited, and is the exact file a person reaches for. Prose in the template
did not prevent it. This test does.

Scope is git-tracked files only. backend/.env, raw extracts and built
catalogs are gitignored and deliberately not scanned - the point is to guard
what can actually be committed.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent

# High-signal provider key shapes. Deliberately specific rather than a generic
# entropy heuristic: a guard that cries wolf gets deleted.
_SECRET_PATTERNS = (
    (r"AIza[0-9A-Za-z_\-]{30,}", "Google API key"),
    (r"AQ\.[0-9A-Za-z_\-]{25,}", "Google OAuth/short-lived token"),
    (r"sk-[0-9A-Za-z]{20,}", "OpenAI-style secret key"),
    (r"sk-ant-[0-9A-Za-z\-_]{20,}", "Anthropic key"),
    (r"gsk_[0-9A-Za-z]{20,}", "Groq key"),
    (r"ghp_[0-9A-Za-z]{20,}", "GitHub personal access token"),
    (r"xox[baprs]-[0-9A-Za-z\-]{20,}", "Slack token"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "private key block"),
)

_COMPILED = [(re.compile(pattern), label) for pattern, label in _SECRET_PATTERNS]

# This file necessarily contains the patterns it searches for.
_SELF = "backend/evals/test_no_committed_secrets.py"

_BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico", ".pdf", ".zip",
    ".woff", ".woff2", ".ttf", ".otf", ".mp4", ".parquet",
}


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def test_no_tracked_file_contains_a_real_looking_secret() -> None:
    offenders: list[str] = []
    scanned = 0

    for rel in _tracked_files():
        if rel == _SELF or Path(rel).suffix.lower() in _BINARY_SUFFIXES:
            continue
        path = REPO_ROOT / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
        scanned += 1
        for compiled, label in _COMPILED:
            match = compiled.search(text)
            if match:
                # Report the location and kind, never the value itself.
                offenders.append(f"{rel}: looks like a {label}")

    assert offenders == [], (
        "a real-looking credential is present in a git-TRACKED file. Move it to "
        "an ignored file (backend/.env), then ROTATE it - anything written to a "
        "tracked file must be treated as compromised:\n  " + "\n  ".join(offenders)
    )
    # Anti-vacuity: a scan of zero files passes forever.
    assert scanned > 50, f"expected to scan the repo, only read {scanned} files"


def test_the_env_template_holds_only_placeholders() -> None:
    """The specific file that got it wrong, asserted directly."""
    template = REPO_ROOT / "backend" / ".env.example"
    assert template.exists(), "backend/.env.example is the documented setup path"
    text = template.read_text(encoding="utf-8")

    for compiled, label in _COMPILED:
        # Reduce to a bool BEFORE asserting: pytest rewrites assertions and
        # will print the introspected operand, so `assert not re.search(...)`
        # would dump the matched secret straight into the failure output and
        # any CI log. Found this by actually running the guard against a
        # planted key. The bool carries the signal without the value.
        found = compiled.search(text) is not None
        assert not found, (
            f"backend/.env.example contains something shaped like a {label}. "
            "It is TRACKED by git - the real key belongs in backend/.env, which "
            "is ignored. Rotate whatever was pasted here."
        )

    # Anti-vacuity: prove the assertions above ran against the real template,
    # not an empty or unrelated file.
    assert "TRIPWISE_LLM_API_KEY" in text


def test_the_real_env_file_is_ignored_if_it_exists() -> None:
    """backend/.env is where the secret goes; it must never be trackable."""
    result = subprocess.run(
        ["git", "check-ignore", "-q", "backend/.env"],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    assert result.returncode == 0, (
        "backend/.env is NOT gitignored - a real key stored there could be "
        "committed. Restore the .env rules in the root .gitignore."
    )
