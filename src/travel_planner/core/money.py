"""Rupee formatting, in the Indian numbering system.

Western grouping puts a separator every three digits: 1,250,000. Indian
grouping separates the last three, then every two above that: 12,50,000 — and
the units have names people actually use, so a hotel is quoted at ₹4,500 and a
trip budget at ₹1.2 lakh rather than ₹120,000.

This is not cosmetic. A plan that prints ₹120,000 reads as foreign to the person
it was written for, and a model asked to "keep amounts in rupees" will happily
produce Western grouping unless something downstream fixes it. Formatting is
done here, deterministically, rather than trusted to a prompt.
"""

from decimal import ROUND_HALF_UP, Decimal

RUPEE = "₹"

LAKH = 100_000
CRORE = 100 * LAKH


def group_indian(n: int) -> str:
    """Group digits the Indian way: last three, then pairs.

    >>> group_indian(1250000)
    '12,50,000'
    """
    s = str(abs(int(n)))
    if len(s) <= 3:
        head = s
    else:
        last3, rest = s[-3:], s[:-3]
        # Pairs, right to left, over everything above the final three digits.
        pairs: list[str] = []
        while len(rest) > 2:
            pairs.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            pairs.insert(0, rest)
        head = ",".join([*pairs, last3])
    return ("-" if n < 0 else "") + head


def rupees(amount: float | int | Decimal, *, paise: bool = False) -> str:
    """A rupee amount with Indian grouping.

    >>> rupees(4500)
    '₹4,500'
    >>> rupees(125000)
    '₹1,25,000'
    """
    d = Decimal(str(amount))
    if paise:
        d = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        whole, frac = divmod(abs(d), 1)
        sign = "-" if d < 0 else ""
        return f"{sign}{RUPEE}{group_indian(int(whole))}.{str(frac)[2:4].ljust(2, '0')}"
    return f"{RUPEE}{group_indian(int(d.quantize(Decimal('1'), rounding=ROUND_HALF_UP)))}"


def compact_rupees(amount: float | int) -> str:
    """A short form using lakh and crore, for headline figures.

    Below a lakh the plain grouped form is already short and more precise, so it
    is used unchanged — ₹45,000 reads better than ₹0.45 lakh.

    >>> compact_rupees(125000)
    '₹1.25 lakh'
    >>> compact_rupees(45000)
    '₹45,000'
    """
    n = float(amount)
    if abs(n) >= CRORE:
        return f"{RUPEE}{_trim(n / CRORE)} crore"
    if abs(n) >= LAKH:
        return f"{RUPEE}{_trim(n / LAKH)} lakh"
    return rupees(n)


def _trim(x: float) -> str:
    """Two decimals, without trailing zeros: 1.25, 2.5, 3."""
    return f"{x:.2f}".rstrip("0").rstrip(".")


def per_person_per_day(total: float, days: int, travelers: int) -> str:
    """The figure people actually compare trips on."""
    if days <= 0 or travelers <= 0:
        return "n/a"
    return rupees(total / days / travelers)
