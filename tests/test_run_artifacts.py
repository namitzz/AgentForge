"""All canonical run artifacts must be present after every run."""

from __future__ import annotations

from pathlib import Path

from agentforge.logger import ARTIFACT_NAMES, RunLogger


def test_fill_missing_placeholders(tmp_path):
    logger = RunLogger(root=tmp_path)
    logger.save_task({"task": "hello"})
    filled = logger.fill_missing_placeholders(reason="dry-run preview")
    # task.json already existed, so it should not have been re-filled.
    assert "task.json" not in filled
    for name in ARTIFACT_NAMES:
        assert (logger.dir / name).exists(), f"missing artifact: {name}"


def test_placeholder_marker_is_distinguishable(tmp_path):
    import json

    logger = RunLogger(root=tmp_path)
    logger.fill_missing_placeholders(reason="early stop")
    review = json.loads((logger.dir / "review.json").read_text())
    assert review.get("placeholder") is True
    assert review.get("reason") == "early stop"


def test_real_artifact_overrides_placeholder(tmp_path):
    import json

    logger = RunLogger(root=tmp_path)
    logger.save_review({"status": "approved", "risk_level": "low", "issues": [], "summary": "ok"})
    logger.fill_missing_placeholders(reason="should not overwrite")
    review = json.loads((logger.dir / "review.json").read_text())
    assert review.get("placeholder") is None
    assert review["status"] == "approved"
