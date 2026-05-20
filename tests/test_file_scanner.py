from agentforge.tools.file_scanner import read_file_capped, scan_repo


def test_ignores_node_modules(sample_repo, base_config):
    summary = scan_repo(sample_repo, base_config)
    paths = {f.path for f in summary.files}
    assert not any(p.startswith("node_modules/") for p in paths)


def test_filters_secret_files(sample_repo, base_config):
    summary = scan_repo(sample_repo, base_config)
    paths = {f.path for f in summary.files}
    assert ".env" not in paths
    assert "credentials.json" not in paths


def test_skips_binaries(sample_repo, base_config):
    summary = scan_repo(sample_repo, base_config)
    paths = {f.path for f in summary.files}
    # image.png has a non-text extension and NUL bytes; should be excluded.
    assert "image.png" not in paths


def test_marks_risky_files(sample_repo, base_config):
    summary = scan_repo(sample_repo, base_config)
    risky_paths = {f.path for f in summary.files if f.is_risky}
    assert any("auth" in p for p in risky_paths)
    assert any(p.startswith("migrations/") for p in risky_paths)


def test_read_file_capped_truncates(tmp_path):
    p = tmp_path / "big.py"
    p.write_text("x" * 5000, encoding="utf-8")
    text = read_file_capped(p, max_chars=1000)
    assert len(text) >= 1000
    assert "[truncated" in text


def test_read_file_capped_handles_missing(tmp_path):
    assert read_file_capped(tmp_path / "nope.py", max_chars=100) == ""
