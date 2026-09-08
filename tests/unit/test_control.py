"""Driving the browser one action at a time.

Two things here are worth holding down hard. An instruction arriving over HTTP
aims at a real browser, so anything unexpected has to be refused rather than
reinterpreted. And the login/payment gate decides when a person is called in
and when automation stops for good, so both its false positives and its false
negatives matter.
"""

import pytest

from travel_planner.tools.mcp import control
from travel_planner.tools.mcp.control import Action, ControlError

SNAPSHOT = """### Page
- Page URL: https://en.wikivoyage.org/wiki/Jaipur
- Page Title: Jaipur - Travel guide at Wikivoyage
### Snapshot
```yaml
- generic [active] [ref=e1]:
  - link "Jump to content" [ref=e3] [cursor=pointer]:
  - banner [ref=e5]:
    - button "Main menu" [ref=e9] [cursor=pointer]
    - searchbox "Search Wikivoyage" [ref=e24]
    - button "Search" [ref=e26]
    - link "Log in" [ref=e37] [cursor=pointer]:
  - generic [ref=e39]:
    - paragraph [ref=e47]:
    - combobox "Language" [ref=e51]
```
"""


# --- parsing an instruction -----------------------------------------------------


def test_a_known_action_parses():
    a = Action.parse({"kind": "click", "ref": "e24", "label": "Search"})
    assert a.kind == "click" and a.ref == "e24"


def test_the_action_key_may_be_called_action():
    assert Action.parse({"action": "back"}).kind == "back"


def test_an_unknown_action_is_refused():
    with pytest.raises(ControlError, match="unknown action"):
        Action.parse({"kind": "download_everything"})


def test_an_unknown_key_is_refused_rather_than_ignored():
    """A typo aimed at a live browser should be an error the caller sees, not
    an instruction quietly reshaped into something else."""
    with pytest.raises(ControlError, match="unexpected keys"):
        Action.parse({"kind": "click", "reff": "e24"})


def test_an_action_needs_a_kind():
    with pytest.raises(ControlError, match="needs a 'kind'"):
        Action.parse({"ref": "e24"})


def test_an_action_must_be_an_object():
    with pytest.raises(ControlError, match="must be an object"):
        Action.parse("click everything")


# --- reading the page -----------------------------------------------------------


def test_url_and_title_come_off_the_snapshot_header():
    assert control.page_url(SNAPSHOT) == "https://en.wikivoyage.org/wiki/Jaipur"
    assert control.page_title(SNAPSHOT).startswith("Jaipur")


def test_interactive_elements_are_the_ones_worth_clicking():
    els = control.interactive_elements(SNAPSHOT)
    by_ref = {e["ref"]: e for e in els}
    assert by_ref["e24"] == {"ref": "e24", "role": "searchbox", "name": "Search Wikivoyage"}
    assert by_ref["e51"]["role"] == "combobox"
    # The tree is mostly generic containers; listing them would bury the rest.
    assert not any(e["role"] in ("generic", "banner", "paragraph") for e in els)


def test_interactive_elements_are_capped():
    assert len(control.interactive_elements(SNAPSHOT, limit=2)) == 2


def test_elements_survive_a_snapshot_with_no_yaml_fence():
    assert control.interactive_elements('- button "Go" [ref=e1]') == [
        {"ref": "e1", "role": "button", "name": "Go"}
    ]


# --- when a person is needed ----------------------------------------------------


def test_a_page_with_a_password_field_is_a_login():
    assert control.classify_gate({"password": True, "path": "/w/index.php"}) == "login"


def test_an_otp_field_is_a_login():
    assert control.classify_gate({"otp": True, "path": "/verify"}) == "login"


def test_an_auth_path_is_a_login():
    assert control.classify_gate({"path": "/account/login"}) == "login"


def test_an_ordinary_article_needs_nobody():
    """The first version of this matched "log in" in the accessibility tree and
    flagged every Wikipedia-family article, because they all carry a Log in
    link in the header. A link that says log in is not a login page."""
    assert control.classify_gate({"path": "/wiki/jaipur", "password": False}) is None


def test_a_card_field_is_a_payment():
    assert control.classify_gate({"card": True, "path": "/checkout"}) == "payment"


def test_a_upi_field_is_a_payment():
    assert control.classify_gate({"upi": True, "path": "/pay"}) == "payment"


def test_payment_outranks_login():
    """A checkout page usually has both. Getting this order wrong would hand a
    payment page back to the automation after the person signed in."""
    assert control.classify_gate({"password": True, "card": True, "path": "/x"}) == "payment"


def test_pay_button_text_counts_even_without_a_field():
    assert control.classify_gate({"payText": True, "path": "/review"}) == "payment"


def test_an_empty_signal_set_needs_nobody():
    assert control.classify_gate({}) is None


# --- the action log -------------------------------------------------------------


def test_typed_text_never_reaches_the_log():
    """Someone taking over a login types into this. The log is streamed to the
    client, written to the run's events and visible in screenshots."""
    line = control._describe(Action(kind="type", text="hunter2", label="Password"))
    assert "hunter2" not in line
    assert "7 characters" in line and "Password" in line


def test_type_at_is_redacted_too():
    assert "s3cret" not in control._describe(Action(kind="type_at", text="s3cret"))


def test_navigation_logs_the_url():
    assert control._describe(Action(kind="navigate", url="https://x.test/a")) == "https://x.test/a"


def test_a_coordinate_click_logs_where():
    assert control._describe(Action(kind="click_at", x=12, y=34)) == "at (12, 34)"


# --- result parsing -------------------------------------------------------------


def test_evaluate_results_are_unwrapped():
    reply = '### Result\n{"ok": true, "y": 500}\n### Ran Playwright code\n```js\n...\n```'
    assert control._result_json(reply) == {"ok": True, "y": 500}


def test_a_non_json_result_still_returns_something_usable():
    assert control._result_json("### Result\nnavigated\n### Ran")["ok"] is True
