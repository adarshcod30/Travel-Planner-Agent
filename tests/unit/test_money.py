"""Rupee formatting.

Indian grouping separates the last three digits, then every two — ₹12,50,000,
not ₹1,250,000. Getting it wrong makes every figure in a plan read as foreign
to the person it was written for, and a model told to "use rupees" will produce
Western grouping unless something downstream fixes it.
"""

import pytest

from travel_planner.core.money import (
    compact_rupees,
    group_indian,
    per_person_per_day,
    rupees,
)


@pytest.mark.parametrize(
    "n,expected",
    [
        (0, "0"),
        (7, "7"),
        (450, "450"),
        (4500, "4,500"),
        (45000, "45,000"),
        (100000, "1,00,000"),  # one lakh
        (125000, "1,25,000"),
        (1250000, "12,50,000"),
        (10000000, "1,00,00,000"),  # one crore
        (125000000, "12,50,00,000"),
        (-125000, "-1,25,000"),
    ],
)
def test_indian_grouping(n, expected):
    assert group_indian(n) == expected


def test_grouping_is_not_western():
    """The bug this module exists to prevent."""
    assert group_indian(1250000) != f"{1250000:,}"


def test_rupees_prefixes_and_rounds():
    assert rupees(4500) == "₹4,500"
    assert rupees(4500.4) == "₹4,500"
    assert rupees(4500.6) == "₹4,501"
    assert rupees(125000) == "₹1,25,000"


def test_rupees_with_paise():
    assert rupees(4500.25, paise=True) == "₹4,500.25"
    assert rupees(4500.5, paise=True) == "₹4,500.50"


@pytest.mark.parametrize(
    "n,expected",
    [
        (45000, "₹45,000"),  # below a lakh, plain is shorter and exact
        (125000, "₹1.25 lakh"),
        (1250000, "₹12.5 lakh"),
        (12500000, "₹1.25 crore"),
        (10000000, "₹1 crore"),  # trailing zeros trimmed
    ],
)
def test_compact_form(n, expected):
    assert compact_rupees(n) == expected


def test_per_person_per_day():
    assert per_person_per_day(84000, 4, 2) == "₹10,500"


def test_per_person_per_day_guards_division():
    assert per_person_per_day(1000, 0, 2) == "n/a"
    assert per_person_per_day(1000, 2, 0) == "n/a"
