import pytest

from app.core.exports import export_csv
from app.core.ingestion import is_date, parse_csv
from app.models import ApiError


def parse(content, name="test.csv"):
    return parse_csv(dict(name=name, content=content))


def test_types_bom_quotes_missing_and_identifiers():
    dataset = parse(
        '\ufeffid,date,amount,note\n001,2025-01-01,10,"hello, world"\n002,2025-02-01,,ok'
    )
    assert dataset.rows[0] == dict(id="001", date="2025-01-01", amount=10, note="hello, world")
    assert dataset.rows[1]["amount"] is None
    assert dataset.columns[1]["type"] == "date"


@pytest.mark.parametrize(
    "content",
    [
        "x,x\n1,2",
        "x,y\n1",
        "x,y\n1,2,3",
        "x,y",
        "__proto__,x\n1,2",
        'x,y\n"unterminated,2',
        "x\n\ufffd",
    ],
)
def test_rejects_invalid_csv(content):
    with pytest.raises(ApiError):
        parse(content)


def test_rejects_wrong_extension():
    with pytest.raises(ApiError):
        parse("x\n1", "x.txt")


def test_retains_duplicates_and_flags_mixed_values():
    dataset = parse("x,y\n1,yes\n1,yes\nnone,no")
    assert dataset.duplicates == 1
    assert dataset.columns[0]["mixedNumeric"]
    assert len(dataset.rows) == 3


@pytest.mark.parametrize(
    ("value", "valid"), [("2025-02-29", False), ("2024-02-29", True), ("01/02/2025", False)]
)
def test_dates(value, valid):
    assert is_date(value) is valid


def test_formula_export_safety():
    text = export_csv(
        [dict(value='=HYPERLINK("bad")'), dict(value="+SUM(1,2)"), dict(value="safe")]
    )
    assert "'=HYPERLINK" in text
    assert "'+SUM" in text


def test_multiline_and_semicolon_files():
    dataset = parse('name;note\nAda;"hello\nworld"\nGrace;ok')
    assert dataset.rows[0]["note"] == "hello\nworld"
