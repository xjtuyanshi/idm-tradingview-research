"""Publication guardrails for the clean public IDM handoff."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = json.loads((ROOT / "release-manifest.json").read_text(encoding="utf-8"))


def test_frozen_pine_matches_release_manifest() -> None:
    pine = ROOT / MANIFEST["pine_file"]
    assert pine.exists()
    assert sha256(pine.read_bytes()).hexdigest() == MANIFEST["pine_sha256"]


def test_readme_leads_with_negative_expectancy_status() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for disclosure in ("Profit Factor **0.638**", "not calibrated", "-$175.41"):
        assert disclosure in readme


def test_handoff_prompt_requires_audit_before_editing() -> None:
    prompt = (ROOT / "docs" / "CLAUDE_FABLE_START_PROMPT.md").read_text(
        encoding="utf-8"
    )
    assert "Your first task is an audit only" in prompt
    assert "Stop after the audit" in prompt
    assert "Advisory never places an order" in prompt


def test_private_artifact_types_are_not_redistributed() -> None:
    excluded_dirs = {".git", ".venv", ".pytest_cache", "__pycache__"}
    forbidden_suffixes = {".csv", ".png", ".jpg", ".jpeg", ".webp", ".zip"}
    artifacts = [
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and not any(part in excluded_dirs for part in path.parts)
        and path.suffix.lower() in forbidden_suffixes
    ]
    assert artifacts == []


def test_public_text_has_no_local_or_private_conversation_routes() -> None:
    excluded_dirs = {".git", ".venv", ".pytest_cache", "__pycache__"}
    forbidden = (
        "/" + "Users" + "/",
        "discord.com" + "/channels/",
        "chatgpt-" + "conversation://",
        "git.chatgpt-" + "team.site",
    )
    leaks: list[tuple[Path, str]] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in excluded_dirs for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for token in forbidden:
            if token in text:
                leaks.append((path.relative_to(ROOT), token))
    assert leaks == []
