from agentforge.task_classifier import TaskType, classify


def test_bug_fix_skips_planner():
    c = classify("fix the off-by-one in pagination")
    assert c.task_type == TaskType.BUG_FIX
    assert c.routing.planner is None
    assert c.routing.implementer == "codex"


def test_security_forces_review():
    c = classify("patch the auth bypass vulnerability")
    assert c.task_type == TaskType.SECURITY
    assert c.routing.require_review is True


def test_docs_skips_reviewer():
    c = classify("update the README with install instructions")
    assert c.task_type == TaskType.DOCS
    assert c.routing.reviewer is None


def test_tests_route_skips_planner_and_reviewer():
    c = classify("write unit tests for the markdown parser")
    assert c.task_type == TaskType.TESTS
    assert c.routing.planner is None
    assert c.routing.reviewer is None


def test_unknown_defaults_to_full_pipeline():
    c = classify("xyzzy")
    assert c.task_type == TaskType.UNKNOWN
    assert c.routing.planner == "claude"
    assert c.routing.require_review is True


def test_empty_task_is_unknown_zero_confidence():
    c = classify("")
    assert c.task_type == TaskType.UNKNOWN
    assert c.confidence == 0.0
