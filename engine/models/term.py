"""Terms: the codes the registration system uses, and which term is on now."""

from datetime import date

_QUARTER_DIGIT = {"summer": 1, "fall": 2, "winter": 3, "spring": 4}
_DE_ANZA = 2


def term_code(year: int, quarter: str) -> str:
    """把 (2026, "fall") 转成接口用的学期代码 "202722"。

    代码里的年份是学年的结束年：夏、秋两季要 +1，冬、春两季不变。
    """
    quarter = quarter.lower()
    if quarter not in _QUARTER_DIGIT:
        raise ValueError(f"unknown quarter: {quarter!r}")
    academic_year = year + 1 if quarter in ("summer", "fall") else year
    return f"{academic_year}{_QUARTER_DIGIT[quarter]}{_DE_ANZA}"


def term_name(code: str) -> str:
    """term_code 的逆运算："202722" -> "2026 fall"。"""
    quarter = next(q for q, digit in _QUARTER_DIGIT.items() if str(digit) == code[4])
    year = int(code[:4]) - 1 if quarter in ("summer", "fall") else int(code[:4])
    return f"{year} {quarter}"


def get_season(md: tuple[int, int]) -> str:
    """The quarter a (month, day) falls in."""
    if (3, 27) <= md < (6, 26):
        return "spring"
    if (6, 26) <= md < (8, 6):
        return "summer"
    if (8, 6) <= md < (12, 12):
        return "fall"
    return "winter"  # 12/12 - 3/26


def current_term(today: date | None = None) -> tuple[int, str]:
    """The (year, quarter) that a date falls in; today's local date by default."""
    today = today or date.today()
    season = get_season((today.month, today.day))
    # the winter quarter that starts in December belongs to the next year
    if season == "winter" and today.month == 12:
        return today.year + 1, season
    return today.year, season
