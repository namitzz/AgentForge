from agentforge.policy import Policy, PolicyEngine


def test_blocks_listed_files(base_config):
    engine = PolicyEngine.from_config_list(base_config.policies)
    kept, blocked = engine.filter_blocked(
        ["src/app.py", ".env", "credentials.json", "lib/secrets.yaml"]
    )
    assert "src/app.py" in kept
    assert ".env" not in kept
    assert "credentials.json" not in kept
    assert "lib/secrets.yaml" not in kept
    assert {h.path for h in blocked} == {".env", "credentials.json", "lib/secrets.yaml"}


def test_auth_match_requires_review(base_config):
    engine = PolicyEngine.from_config_list(base_config.policies)
    report = engine.evaluate(["src/auth.py", "src/utils.py"])
    assert report.require_review is True
    assert report.require_tests is True
    assert "Auth changes require review" in report.triggering_policies


def test_migrations_require_human_approval(base_config):
    engine = PolicyEngine.from_config_list(base_config.policies)
    report = engine.evaluate(["migrations/001_init.sql"])
    assert report.require_human_approval is True


def test_no_match_means_no_escalation(base_config):
    engine = PolicyEngine.from_config_list(base_config.policies)
    report = engine.evaluate(["src/utils.py", "README.md"])
    assert report.require_review is False
    assert report.require_tests is False
    assert report.require_human_approval is False


def test_human_summary_text(base_config):
    engine = PolicyEngine.from_config_list(base_config.policies)
    report = engine.evaluate(["src/auth.py", ".env"])
    summary = "\n".join(report.human_summary())
    assert "Review required: yes" in summary
    assert "Blocked" in summary


def test_glob_patterns_match_at_depth():
    engine = PolicyEngine([Policy(name="p", block=["**/secrets*"])])
    _, blocked = engine.filter_blocked(["a/b/secrets.yaml", "ok.py"])
    assert [h.path for h in blocked] == ["a/b/secrets.yaml"]
