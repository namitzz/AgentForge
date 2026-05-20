from pathlib import Path

from agentforge.agents.local_agent import LocalAgent
from agentforge.context_builder import build_context, select_relevant_files
from agentforge.tools.file_scanner import scan_repo


def test_ranks_files_by_task_token_overlap(sample_repo, base_config):
    summary = scan_repo(sample_repo, base_config)
    selected = select_relevant_files(summary, "fix pagination off-by-one", base_config)
    # pagination.py should rank above unrelated files.
    assert "src/pagination.py" in selected
    assert selected.index("src/pagination.py") == 0


def test_respects_max_files_sent(sample_repo, base_config):
    base_config.max_files_sent = 2
    summary = scan_repo(sample_repo, base_config)
    selected = select_relevant_files(summary, "fix pagination", base_config)
    assert len(selected) <= 2


def test_total_chars_cap_enforced(sample_repo, base_config):
    base_config.max_total_chars = 50  # ridiculously small
    summary = scan_repo(sample_repo, base_config)
    local = LocalAgent(config=base_config, cwd=sample_repo)
    ctx = build_context(local, summary, "fix pagination", base_config)
    assert ctx.total_chars <= 50 + 100  # allow truncation marker overhead
    assert ctx.truncated is True


def test_per_file_cap_enforced(sample_repo, base_config):
    base_config.max_chars_per_file = 10
    summary = scan_repo(sample_repo, base_config)
    local = LocalAgent(config=base_config, cwd=sample_repo)
    ctx = build_context(local, summary, "fix pagination", base_config)
    for _, content in ctx.selected_files:
        assert "[truncated" in content or len(content) <= 10
