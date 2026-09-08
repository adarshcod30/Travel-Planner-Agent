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
    # Unnamed containers are still dropped: there is nothing a model could say
    # about "generic [ref=e39]" that would help it decide anything.
    assert not any(e["name"] == "" and e["role"] == "generic" for e in els)


GOIBIBO = """### Snapshot
```yaml
- link "Flights" [ref=e12]
- link "Hotels" [ref=e17]
- link "Hotels in Delhi" [ref=e403]
- generic [ref=e72]: Where to
- generic [ref=e77]: Check-in
- generic [ref=e83]: Check-out
- generic [ref=e91]: SEARCH
- generic [ref=e400]: Get Up to 15% OFF on Travel Bookings and more besides
- paragraph [ref=e133]: Some marketing copy
```
"""


def test_a_search_widget_built_from_divs_is_still_offered():
    """goibibo's "Where to" field is not an input — it renders as
    `generic [ref=e72]: Where to`, and so do its dates and its SEARCH button.
    Excluding generics made the one thing that page exists for invisible, and a
    browsing loop given that page could only click the nav bar over and over."""
    names = {e["name"] for e in control.interactive_elements(GOIBIBO)}
    assert {"Where to", "Check-in", "Check-out", "SEARCH"} <= names


def test_the_search_widget_outranks_the_nav_bar():
    """A page's first forty elements are routinely a nav bar, so in document
    order the useful half never survives truncation."""
    top = [e["name"] for e in control.interactive_elements(GOIBIBO, limit=4)]
    assert "Where to" in top and "SEARCH" in top
    assert "Flights" not in top


def test_long_marketing_text_is_not_mistaken_for_a_control():
    """A control's label is short. A paragraph is not a button."""
    names = {e["name"] for e in control.interactive_elements(GOIBIBO)}
    assert not any(n.startswith("Get Up to 15% OFF") for n in names)


def test_a_named_link_still_appears_just_lower_down():
    names = [e["name"] for e in control.interactive_elements(GOIBIBO, limit=40)]
    assert "Flights" in names
    assert names.index("Where to") < names.index("Flights")


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


# --- login walls that are not password fields -----------------------------------


def test_a_mobile_number_login_modal_is_a_login():
    """Indian booking sites sign you in by mobile number, not a password. Asking
    only "is there a password field" missed the single most common login wall on
    every site this planner actually uses — goibibo throws a Login/Signup panel
    with a +91 box over its listing and the gate saw nothing."""
    assert (
        control.classify_gate(
            {"phone": True, "credentialInModal": True, "path": "/hotels/hotels-in-agra-ct/"}
        )
        == "login"
    )


def test_a_sign_in_widget_in_the_header_is_not_a_login_wall():
    """Every travel site parks one on every page. Treating it as a wall stopped
    a run on the flight search and reported it had reached a sign-in."""
    assert control.classify_gate({"phone": True, "path": "/flights/", "inputCount": 63}) is None


def test_a_page_with_almost_nothing_but_a_credential_field_is_a_login():
    assert control.classify_gate({"password": True, "path": "/x", "inputCount": 2}) == "login"


def test_a_payment_page_still_outranks_a_phone_login():
    assert control.classify_gate({"phone": True, "card": True, "path": "/x"}) == "payment"


# --- cards built out of divs ----------------------------------------------------

CARD = """### Snapshot
```yaml
- generic [ref=e629] [cursor=pointer]:
  - list [ref=e633]:
    - generic [ref=e639]: View All
  - generic [ref=e641]:
    - generic [ref=e647]: "4"
    - generic [ref=e651]: Lemon Tree Hotel Agra
    - generic [ref=e655]: 11.3 km drive to Taj Mahal
- checkbox "Book @ ₹0" [ref=e194]
```
"""


def test_a_clickable_card_is_named_from_its_contents():
    """A result card is a clickable div wrapping a dozen unnamed divs — the
    hotel's name is a descendant and the card itself has no accessible name.
    Dropping unnamed elements dropped every hotel on the page and left the agent
    choosing between filters, which is how it concluded that a filter called
    "Book @ ₹0" was a cheap hotel."""
    by_ref = {e["ref"]: e for e in control.interactive_elements(CARD)}
    assert "e629" in by_ref, "the card itself must be offered, since it is what you click"
    assert "Lemon Tree Hotel Agra" in by_ref["e629"]["name"]


def test_card_furniture_is_not_mistaken_for_a_name():
    """The first text nodes in a card are its carousel arrows and rating badge,
    so taking them in document order labelled every hotel "View All · 4"."""
    name = {e["ref"]: e for e in control.interactive_elements(CARD)}["e629"]["name"]
    assert "View All" not in name
    assert name.strip() != "4"


def test_cursor_pointer_is_found_after_the_ref_too():
    """It sits on either side of the ref depending on what else the node
    carries. Reading only the attributes before it made every clickable card on
    a listing page read as unclickable."""
    line = (
        "- generic [ref=e900] [cursor=pointer]:\n  - generic [ref=e901]: Holiday Inn Agra MG Road"
    )
    assert any(e["ref"] == "e900" for e in control.interactive_elements(line))


def test_a_credit_card_advert_is_not_a_payment_page():
    """Every Indian travel site markets a co-branded credit card, and those
    pages are thick with "card number", "CVV" and "net banking". A run stopped
    on makemytrip.com/cards/makemytrip-icici-bank-credit-card and reported it
    had reached the payment page."""
    assert control.classify_gate({"path": "/cards/mmt-icici-credit-card", "payText": True}) is None


def test_a_real_card_field_stops_it_wherever_it_appears():
    """Checked before the marketing exemption, deliberately. Getting that order
    wrong would let the exemption carry a genuine card form through with it."""
    assert control.classify_gate({"path": "/offers/", "card": True}) == "payment"
    assert control.classify_gate({"path": "/cards/x", "upi": True}) == "payment"


def test_payment_words_alone_are_not_enough():
    """A listing page that mentions net banking in a bank offer is not a
    checkout."""
    assert control.classify_gate({"path": "/hotels/hotels-in-agra-ct/", "payText": True}) is None


def test_a_booking_path_is_a_payment_page():
    assert control.classify_gate({"path": "/hotels/nhotel-booking/"}) == "payment"
