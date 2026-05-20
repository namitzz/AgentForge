from agentforge.prompts.review_prompt import build_review_prompt


def test_prompt_contains_only_diff_not_full_files():
    full_file = "def secret_thing():\n    return 'should-not-be-in-prompt'\n"
    diff = "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n"
    prompt = build_review_prompt(task="t", plan="p", diff=diff, test_result="ok")
    assert "diff --git" in prompt
    assert "should-not-be-in-prompt" not in prompt
    assert full_file not in prompt


def test_prompt_demands_json_output():
    prompt = build_review_prompt(task="t", plan="p", diff="", test_result="")
    assert '"status"' in prompt
    assert '"risk_level"' in prompt
    assert '"issues"' in prompt


def test_handles_empty_inputs():
    prompt = build_review_prompt(task="", plan="", diff="", test_result="")
    assert "(no diff)" in prompt
    assert "(no plan)" in prompt
