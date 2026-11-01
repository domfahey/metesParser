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


def test_parse_comma_number_reads_two_digit_decimal_comma():
    from mp_parse.numbers import parse_comma_number

    assert parse_comma_number("300,07") == 300.07
    assert parse_comma_number("35,00") == 35.0
    assert parse_comma_number("1,200") == 1200.0
    assert parse_comma_number("1,200,000") == 1200000.0
