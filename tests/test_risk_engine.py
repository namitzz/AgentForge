from agentforge.risk_engine import RiskEngine, RiskLevel, assess_risk


def test_readme_typo_is_low_risk():
    report = assess_risk("Fix typo in README", ["README.md"])
    assert report.risk_level == RiskLevel.LOW
    assert report.review_required is False
    assert report.human_approval_required is False
    assert report.score < 40


def test_refactor_is_medium_risk():
    report = assess_risk(
        "Refactor the user profile component",
        ["src/components/UserProfile.tsx", "src/services/userService.ts"],
    )
    assert report.risk_level == RiskLevel.MEDIUM
    assert report.review_required is True
    assert report.human_approval_required is False
    assert 40 <= report.score < 70


def test_auth_change_is_high_risk():
    report = assess_risk(
        "Add password reset to login flow",
        ["src/auth/login.py", "src/auth/password_reset.py"],
    )
    assert report.risk_level == RiskLevel.HIGH
    assert report.review_required is True
    assert report.human_approval_required is True
    assert report.score >= 70


def test_db_migration_is_high_risk():
    report = assess_risk(
        "Add migration for users table to drop legacy column",
        ["migrations/0042_drop_legacy.sql"],
    )
    assert report.risk_level == RiskLevel.HIGH
    assert any("migrations" in r or "sensitive" in r.lower() for r in report.reasons)


def test_empty_task_defaults_to_medium_for_safety():
    report = assess_risk("", [])
    # Empty task should never be classified LOW — we don't know what it is.
    assert report.risk_level in (RiskLevel.MEDIUM, RiskLevel.HIGH)


def test_score_is_capped_at_100():
    report = assess_risk(
        "auth password token secret production deploy migration schema database payment billing",
        ["auth/login.py", "migrations/x.sql", ".env", "billing/charge.py"],
    )
    assert report.score <= 100


def test_low_keywords_reduce_score():
    plain = assess_risk("change handler logic", [])
    docs = assess_risk("update docstring and readme comment", [])
    assert docs.score < plain.score


def test_to_dict_has_required_fields():
    d = assess_risk("add auth login", ["auth/login.py"]).to_dict()
    for key in (
        "risk_level",
        "score",
        "reasons",
        "recommended_workflow",
        "review_required",
        "tests_required",
        "human_approval_required",
    ):
        assert key in d


def test_tests_required_flag_tracks_level():
    low = assess_risk("Fix typo in README", ["README.md"])
    med = assess_risk("Refactor the user profile component", ["src/components/UserProfile.tsx"])
    high = assess_risk("Add password reset to login flow", ["auth/login.py"])
    assert low.tests_required is False
    assert med.tests_required is True
    assert high.tests_required is True


def test_human_summary_includes_level_and_score():
    report = assess_risk("Fix typo in README", ["README.md"])
    text = "\n".join(report.human_summary())
    assert "Level: LOW" in text
    assert "Score:" in text
    assert "Recommended workflow:" in text


def test_high_task_not_downgraded_by_unrelated_readme_in_context():
    # If the task mentions auth/login, editing README on top must not
    # downgrade the assessment.
    report = assess_risk(
        "Add password reset to login flow",
        ["README.md", "USAGE.md", "src/utils.py"],
    )
    assert report.risk_level == RiskLevel.HIGH


def test_high_risk_recommends_human_approval_in_workflow():
    report = assess_risk("Add password reset to login flow", ["auth/login.py"])
    text = "\n".join(report.recommended_workflow)
    assert "Human approval" in text
    assert "Claude diff review required" in text
