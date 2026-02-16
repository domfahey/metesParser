def test_parse_comma_number():
    from mp_parse.numbers import parse_comma_number

    assert parse_comma_number("1,200.50") == 1200.50
    assert parse_comma_number("100") == 100.0


def test_comma_number_pattern():
    import re

    from mp_parse.numbers import COMMA_NUMBER

    pattern = re.compile(COMMA_NUMBER)
    assert pattern.match("1,200.50")
    assert pattern.match("100")
