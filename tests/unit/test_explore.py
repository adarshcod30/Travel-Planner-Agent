"""Searching the open web and following what comes back.

Everything here is the part that runs without a browser: which links are worth
opening, and how a result is addressed. The addressing is the interesting half
— Google publishes no destination URLs at all, so a result can only be reached
by clicking it.
"""

from travel_planner.tools.mcp import explore

QUERY = "things to do in Agra in November"


def _link(href="", text="", ref=""):
    return {"href": href, "text": text, "ref": ref}


def test_a_result_needs_a_href_or_a_ref():
    assert explore.rank_results([_link(text="Things to do in Agra in November")], QUERY) == []


def test_a_ref_alone_is_enough():
    """Google gives nothing else."""
    (got,) = explore.rank_results([_link(text="Agra in November: what to see", ref="e9")], QUERY)
    assert got["ref"] == "e9"


def test_a_redirect_wrapper_is_not_judged_by_the_engines_host():
    """`google.com/goto?url=<token>` is a result, not a Google page. Judging it
    by that host discarded every real result Google returned, because
    google.com is on the skip list."""
    (got,) = explore.rank_results(
        [_link("https://www.google.com/goto?url=CAESag", "Agra in November guide", "e4")], QUERY
    )
    assert got["host"] == "(unknown until opened)"
    assert got["url"] == "", "there is no URL to navigate to; it has to be clicked"


def test_social_and_hostile_hosts_are_skipped():
    for host in ("facebook.com", "pinterest.com", "tripadvisor.in", "www.google.com"):
        assert (
            explore.rank_results([_link(f"https://{host}/x", "Agra in November things")], QUERY)
            == []
        )


def test_official_sources_outrank_the_rest():
    ranked = explore.rank_results(
        [
            _link("https://randomblog.example/x", "Agra in November things to do"),
            _link("https://uptourism.gov.in/agra", "Agra in November"),
        ],
        QUERY,
    )
    assert ranked[0]["host"].endswith("gov.in")


def test_a_title_unrelated_to_the_query_is_dropped():
    assert explore.rank_results([_link("https://x.test/a", "Cheap flights to Dubai")], QUERY) == []


def test_one_page_per_host():
    """Ten links into one site are one source; the other nine crowd out
    everything else."""
    same = [_link(f"https://holidify.com/agra/{i}", f"Agra things to do {i}") for i in range(5)]
    assert len(explore.rank_results(same, QUERY)) == 1


def test_very_short_link_text_is_ignored():
    assert explore.rank_results([_link("https://x.test/a", "Agra")], QUERY) == []


# --- joining the DOM to the accessibility tree ----------------------------------


def test_refs_are_matched_to_dom_links_by_text():
    """The DOM has hrefs and knows what a result is; the tree has the refs a
    click needs. Text is the only thing both carry."""
    merged = explore._with_refs(
        [_link("https://www.google.com/goto?url=X", "Agra in  November — a guide")],
        [_link(text="Agra in November - a guide", ref="e12")],
    )
    # Whitespace and punctuation differ between the two renderings, so the key
    # is deliberately loose.
    assert merged[0]["href"].endswith("X")


def test_the_dom_decides_what_counts_as_a_result():
    """The tree cannot tell a result from the engine's own "related searches",
    and those echo the query word for word — merged in, they outscored every
    real answer and the pages opened were always another Google search."""
    merged = explore._with_refs(
        [_link("https://x.test/real", "A real result about Agra", "")],
        [_link(text="things to do in Agra in November", ref="e1")],
    )
    assert len(merged) == 1
    assert merged[0]["text"] == "A real result about Agra"


def test_the_tree_is_used_when_the_dom_gives_nothing():
    merged = explore._with_refs([], [_link(text="Agra in November", ref="e1")])
    assert merged[0]["ref"] == "e1"


# --- redirect unwrapping --------------------------------------------------------


def test_duckduckgo_redirects_are_unwrapped():
    """It hands out its own domain rather than the destination, so ranking by
    host would score every result identically."""
    wrapped = "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fwikivoyage.org%2Fwiki%2FAgra&rut=x"
    assert explore._unwrap(wrapped) == "https://wikivoyage.org/wiki/Agra"


def test_an_ordinary_url_is_left_alone():
    assert explore._unwrap("https://x.test/a?b=1") == "https://x.test/a?b=1"


# --- tabs -----------------------------------------------------------------------


def test_tabs_are_counted_from_a_listing():
    """A result opens with target=_blank, so the click lands in a new tab while
    the tab being read stays on the results page — which made every click come
    back as about:blank until this was noticed."""
    listing = "### Result\n- 0: (current) [Search](https://google.com/search?q=x)\n- 1: [Agra](https://x.test/)"
    assert explore._tab_count(listing) == 2
    assert explore._tab_count("### Result\n- 0: (current) [Search](https://g/)") == 1


def test_no_tabs_listed_is_zero_not_an_error():
    assert explore._tab_count("") == 0


# --- notes ----------------------------------------------------------------------


def test_a_search_that_read_nothing_produces_no_note():
    assert explore.summarise({"query": QUERY, "pages": []}) is None


def test_the_note_names_the_pages_it_read():
    note = explore.summarise(
        {
            "query": QUERY,
            "pages": [
                {"title": "Agra in November", "host": "uptourism.gov.in", "excerpt": "Mild."}
            ],
        }
    )
    assert "uptourism.gov.in" in note and "Mild." in note
    assert QUERY in note
