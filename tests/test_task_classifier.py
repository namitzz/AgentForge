"""Tests for the upgraded task classifier.

Covers backward-compat with the previous tests, plus:
  - ambiguous prompts get lower confidence
  - multi-intent prompts surface secondary_intents
  - false positives from naive substring matching are gone
  - security / auth variants all route to SECURITY
  - confidence scales with signal strength
  - routing expectations including the DOCS implementer fix
"""

from __future__ import annotations

from agentforge.task_classifier import TaskType, classify


# ---------------------------------------------------------------------------
# Backward-compat: every assertion that the previous tests made.
# ---------------------------------------------------------------------------

def test_bug_fix_skips_planner():
    c = classify("fix the off-by-one in pagination")
    assert c.task_type == TaskType.BUG_FIX
    assert c.routing.planner is None
    assert c.routing.implementer == "claude"


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


# ---------------------------------------------------------------------------
# Security / auth variants.
# ---------------------------------------------------------------------------

def test_security_variant_authentication():
    c = classify("review the authentication flow for token leaks")
    assert c.task_type == TaskType.SECURITY
    assert c.routing.require_review is True


def test_security_variant_authorization():
    c = classify("add authorization checks to the admin panel")
    assert c.task_type == TaskType.SECURITY


def test_security_variant_authn_authz():
    c = classify("audit authn and authz layers")
    assert c.task_type == TaskType.SECURITY


def test_security_variant_jwt():
    c = classify("rotate the JWT signing key in the API layer")
    assert c.task_type == TaskType.SECURITY


def test_security_variant_sql_injection():
    c = classify("guard the search endpoint against sql injection")
    assert c.task_type == TaskType.SECURITY


def test_fix_on_auth_surface_wins_over_plain_bug():
    """A "fix" on an auth-surface (login) should land as SECURITY, not BUG_FIX."""
    c = classify("fix the broken login redirect for SSO users")
    assert c.task_type == TaskType.SECURITY


# ---------------------------------------------------------------------------
# False-positive prevention. These would have hit on the old substring-first
# matcher and surface incorrectly.
# ---------------------------------------------------------------------------

def test_substring_test_does_not_match_biggest():
    """'biggest' contains the letters t-e-s-t but is not the word 'test'."""
    c = classify("biggest improvements to the search ranking algorithm")
    assert c.task_type != TaskType.TESTS
    assert "test" not in c.keywords_matched


def test_substring_api_does_not_match_rapid():
    """'rapid' contains 'api'."""
    c = classify("explore rapid prototyping options for the dashboard")
    assert "api" not in c.keywords_matched
    assert "endpoint" not in c.keywords_matched


def test_substring_doc_does_not_match_document_inside_code():
    """'document.getElementById' must not classify as DOCS."""
    c = classify("rename the variable in document.getElementById call sites")
    # 'document' is not the word 'doc' (no word boundary inside).
    assert c.task_type != TaskType.DOCS


def test_substring_fix_does_not_match_prefix_inside_other_words():
    """'prefix' / 'suffix' / 'matrix' all contain 'fix' as a substring."""
    c = classify("rename the prefix variable")
    # Should not classify as BUG_FIX.
    assert c.task_type != TaskType.BUG_FIX


# ---------------------------------------------------------------------------
# Stem-aware matching: verbs in their natural English forms.
# ---------------------------------------------------------------------------

def test_stem_fixing_classifies_as_bug_fix():
    c = classify("fixing the off-by-one in pagination")
    assert c.task_type == TaskType.BUG_FIX


def test_stem_fixed_classifies_as_bug_fix():
    c = classify("fixed the off-by-one in pagination")
    assert c.task_type == TaskType.BUG_FIX


def test_stem_refactored_is_refactor():
    c = classify("refactored the storage layer")
    assert c.task_type == TaskType.REFACTOR


# ---------------------------------------------------------------------------
# Multi-intent detection.
# ---------------------------------------------------------------------------

def test_bug_and_tests_surfaces_tests_as_secondary():
    c = classify("fix the off-by-one bug in pagination and add tests for it")
    assert c.task_type == TaskType.BUG_FIX
    assert TaskType.TESTS in c.secondary_intents


def test_refactor_and_tests_captures_both_intents():
    """Either ordering is defensible — what matters is that BOTH show up."""
    c = classify("refactor the storage layer and add unit tests for it")
    primary_plus_secondary = {c.task_type, *c.secondary_intents}
    assert TaskType.REFACTOR in primary_plus_secondary
    assert TaskType.TESTS in primary_plus_secondary


def test_secondary_intents_threshold_skips_weak_signals():
    """A single weak / medium feature in another type shouldn't become a
    secondary intent — that would be noise."""
    c = classify("refactor the storage layer")
    # FEATURE has no real signal here; ensure it's not surfaced.
    assert TaskType.FEATURE not in c.secondary_intents


def test_multi_intent_appears_in_to_dict():
    d = classify("fix bug and add tests").to_dict()
    assert "secondary_intents" in d
    assert isinstance(d["secondary_intents"], list)


# ---------------------------------------------------------------------------
# Confidence behaviour.
# ---------------------------------------------------------------------------

def test_strong_match_yields_high_confidence():
    c = classify("fix bug in pagination off-by-one")
    assert c.confidence >= 0.7


def test_weak_lone_signal_yields_modest_confidence():
    c = classify("there's an issue somewhere")
    assert c.confidence <= 0.45


def test_clear_signal_beats_ambiguous_signal_in_confidence():
    c_clear = classify("write unit tests for the markdown parser")
    c_ambig = classify("change something")
    assert c_clear.confidence > c_ambig.confidence


def test_no_match_falls_back_to_low_confidence_unknown():
    c = classify("change something")
    assert c.task_type == TaskType.UNKNOWN
    # The fallback is intentionally low so consumers can ask a human.
    assert c.confidence <= 0.5


def test_confidence_is_deterministic_across_runs():
    a = classify("fix the off-by-one bug")
    b = classify("fix the off-by-one bug")
    assert a.confidence == b.confidence
    assert a.task_type == b.task_type
    assert a.keywords_matched == b.keywords_matched


# ---------------------------------------------------------------------------
# Routing expectations.
# ---------------------------------------------------------------------------

def test_docs_routing_uses_implementer_default_not_planner_default():
    """Conceptual fix: docs are still 'changes', so the agent that writes
    changes is the natural choice. Previously docs routed prose work to
    planner_default which coupled it to the planning configuration."""
    c = classify(
        "update the README",
        defaults=("planner-agent", "impl-agent", "reviewer-agent"),
    )
    assert c.routing.implementer == "impl-agent"


def test_security_routing_runs_full_pipeline():
    c = classify("patch the auth bypass vulnerability")
    assert c.routing.planner is not None
    assert c.routing.implementer is not None
    assert c.routing.reviewer is not None
    assert c.routing.require_review is True


def test_unknown_routing_is_safety_conservative():
    """If we don't know what the task is, we plan + implement + review."""
    c = classify("xyzzy")
    assert c.routing.planner is not None
    assert c.routing.implementer is not None
    assert c.routing.reviewer is not None
    assert c.routing.require_review is True


def test_typo_in_test_file_is_docs_not_tests():
    """'fix typo' is a strong DOCS signal; 'test' is a medium TESTS one.
    DOCS should win on score."""
    c = classify("fix typo in test file comment")
    assert c.task_type == TaskType.DOCS


def test_keywords_matched_is_explainable():
    """Every fired feature must appear in keywords_matched so the
    routing decision is auditable."""
    c = classify("fix the off-by-one in pagination")
    assert c.keywords_matched, "no features matched — explainability broken"
    # 'off-by-one' was a strong feature; should be in the matched list.
    assert any("off-by-one" in label for label in c.keywords_matched)
