"""What the voice says for a reading, in the three styles of the VOICE menu.

    count_after     "Borase, times 3"                    (the original wording)
    count_before    "Three Borase"
    with_signature  "Borase, three rocks, fourteen thousand four hundred"

The second and third styles say numbers as words, so every engine reads them
the same way. A count of 1 is never spoken in the first two styles ("Borase").
"""
from __future__ import annotations

STYLES = ("count_after", "count_before", "with_signature")
STYLE_LABELS = {
    "count_after": "Borase, times 3",
    "count_before": "Three Borase",
    "with_signature": "Borase, three rocks, fourteen thousand four hundred",
}
DEFAULT_STYLE = "count_after"

# What one item of a reading is called, per match kind (app.mining.Match.kind).
UNITS = {
    "ship": ("rock", "rocks"),
    "roc": ("deposit", "deposits"),
    "fps": ("deposit", "deposits"),
    "debris": ("piece", "pieces"),
    "harvest": ("plant", "plants"),
}

# The TEST button's phrase: "Feynmaline, nineteen deposits" (57,000 = 3,000 x 19).
TEST_LABEL = "Feynmaline"
TEST_COUNT = 19
TEST_VALUE = 57000
TEST_UNIT = "deposits"

_ONES = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
         "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
         "sixteen", "seventeen", "eighteen", "nineteen")
_TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
         "eighty", "ninety")
_SCALES = ((1_000_000_000, "billion"), (1_000_000, "million"), (1_000, "thousand"))


def _below_thousand(n: int) -> str:
    parts = []
    hundreds, rest = divmod(n, 100)
    if hundreds:
        parts.append(f"{_ONES[hundreds]} hundred")
    if rest:
        if rest < 20:
            parts.append(_ONES[rest])
        else:
            tens, ones = divmod(rest, 10)
            parts.append(_TENS[tens] + (f"-{_ONES[ones]}" if ones else ""))
    return " ".join(parts)


def number_words(value: int | float) -> str:
    """76000 -> 'seventy-six thousand'; 14400 -> 'fourteen thousand four hundred'."""
    n = int(round(float(value)))
    if n == 0:
        return "zero"
    if n < 0:
        return "minus " + number_words(-n)
    parts = []
    for size, name in _SCALES:
        if n >= size:
            head, n = divmod(n, size)
            parts.append(f"{number_words(head)} {name}")
    if n:
        parts.append(_below_thousand(n))
    return " ".join(parts)


def unit_for(kind: str, count: int) -> str:
    """'ship', 3 -> 'rocks'; 'roc', 1 -> 'deposit'."""
    one, many = UNITS.get(kind, ("rock", "rocks"))
    return one if count == 1 else many


def _singular(unit: str) -> str:
    for one, many in UNITS.values():
        if unit == many:
            return one
    return unit[:-1] if unit.endswith("s") and len(unit) > 1 else unit


def spoken_text(label: str, count: int = 1, value: int | float | None = None,
                style: str = DEFAULT_STYLE, unit: str = "rocks") -> str:
    """The phrase for one reading.

    ``label`` is the ore / reading name, ``count`` the number of rocks or
    deposits, ``value`` the scan signature (only the ``with_signature`` style
    says it), ``unit`` the plural word for the count (see ``unit_for``).
    """
    text = (label or "").strip()
    if not text:
        return ""
    try:
        count = int(count or 0)
    except (TypeError, ValueError):
        count = 0
    if style not in STYLES:
        style = DEFAULT_STYLE

    if style == "count_after":
        return f"{text}, times {count}" if count > 1 else text

    if style == "count_before":
        if count > 1:
            return f"{number_words(count).capitalize()} {text}"
        return text

    parts = [text]
    if count >= 1:
        word = _singular(unit) if count == 1 else unit
        parts.append(f"{number_words(count)} {word}")
    if value is not None:
        try:
            parts.append(number_words(value))
        except (TypeError, ValueError):
            pass
    return ", ".join(parts)


def test_phrase(style: str = DEFAULT_STYLE) -> str:
    """What the TEST button says: the reading "Feynmaline, nineteen deposits"
    worded in ``style`` ("Feynmaline, times 19" / "Nineteen Feynmaline" /
    "Feynmaline, nineteen deposits, fifty-seven thousand")."""
    return spoken_text(TEST_LABEL, TEST_COUNT, TEST_VALUE, style, TEST_UNIT)
