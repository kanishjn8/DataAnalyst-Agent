import csv
import io
import json
import math
import re
from dataclasses import dataclass
from datetime import date

from ..models import MAX_BYTES, MAX_COLUMNS, MAX_ROWS, ApiError, CsvFile, Json, Row

csv.field_size_limit(MAX_BYTES)
NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$", re.I)


@dataclass
class Dataset:
    name: str
    columns: list[Json]
    rows: list[Row]
    duplicates: int
    warnings: list[str]


def numeric(value: str) -> float | int | None:
    if not NUMBER.fullmatch(value) or re.match(r"^0\d", value):
        return None
    number = float(value)
    if not math.isfinite(number) or abs(number) > 9_007_199_254_740_991:
        return None
    return int(number) if number.is_integer() else number


def is_date(value: str) -> bool:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def parse_csv(file: CsvFile | Json) -> Dataset:
    file = (
        file
        if isinstance(file, CsvFile)
        else CsvFile.model_validate({k: file[k] for k in ("name", "content")})
    )
    if not file.name.lower().endswith(".csv"):
        raise ApiError("Please choose a .csv file.")
    if len(file.content.encode("utf-8")) > MAX_BYTES:
        raise ApiError("CSV files must total 15 MB or less.")
    if "\x00" in file.content or "\ufffd" in file.content:
        raise ApiError("Use UTF-8 CSV files without binary or invalid characters.")
    content = file.content.removeprefix("\ufeff")
    try:
        try:
            dialect = csv.Sniffer().sniff(content[:8192], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(io.StringIO(content, newline=""), dialect=dialect, strict=True)
        records = [row for row in reader if any(value.strip() for value in row)]
    except csv.Error as error:
        raise ApiError("Invalid CSV: check quoted fields and row formatting.") from error
    if not records:
        raise ApiError("The CSV is empty.")
    headers = [value.strip() for value in records[0]]
    if not 1 <= len(headers) <= MAX_COLUMNS or any(not h or len(h) > 120 for h in headers):
        raise ApiError("Use 1–40 named columns, each at most 120 characters.")
    if len(set(headers)) != len(headers):
        raise ApiError("Column names must be unique.")
    if {"__proto__", "constructor", "prototype"} & set(headers):
        raise ApiError("Reserved column name. Please rename it.")
    cells = [[value.strip() for value in row] for row in records[1:]]
    if not cells:
        raise ApiError("The CSV has headers but no data rows.")
    if len(cells) > MAX_ROWS:
        raise ApiError("Use at most 20,000 rows across your selected files.")
    for index, row in enumerate(cells, 2):
        if len(row) != len(headers):
            raise ApiError(f"Record {index} has {len(row)} fields; expected {len(headers)}.")
    columns = []
    for index, name in enumerate(headers):
        values = [row[index] for row in cells if row[index] != ""]
        numbers = sum(numeric(value) is not None for value in values)
        kind = (
            "number"
            if values and numbers == len(values)
            else "date"
            if values and all(is_date(v) for v in values)
            else "text"
        )
        columns.append(
            dict(
                name=name,
                type=kind,
                missing=len(cells) - len(values),
                unique=len(set(values)),
                mixedNumeric=0 < numbers < len(values),
            )
        )
    rows = [
        {
            c["name"]: None if raw == "" else numeric(raw) if c["type"] == "number" else raw
            for c, raw in zip(columns, row, strict=True)
        }
        for row in cells
    ]
    duplicates = len(rows) - len(
        {json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows}
    )
    warnings = []
    for column in columns:
        if column["missing"]:
            warnings.append(f"{column['name']}: {column['missing']} missing values.")
        if column["mixedNumeric"]:
            warnings.append(f"{column['name']}: mixed numeric/text values; treated as text.")
    if duplicates:
        warnings.append(f"{duplicates} duplicate rows retained in calculations.")
    return Dataset(file.name, columns, rows, duplicates, warnings)


def csv_text(headers: list[str], rows: list[Row], escape_formulas: bool = False) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")

    def safe(value):
        if (
            escape_formulas
            and isinstance(value, str)
            and value.startswith(("=", "+", "-", "@", "\t", "\r"))
        ):
            return "'" + value
        return "" if value is None else value

    writer.writerow([safe(h) for h in headers])
    for row in rows:
        writer.writerow([safe(row.get(h)) for h in headers])
    return output.getvalue()
