"""Focused OOXML table persistence; no workbook redesign or seed migration.

Unchanged ZIP entries (including source sheets, drawings and formulas) are retained
byte-for-byte. Text is always literal inline-string data, never an Excel formula.
"""
import math
import posixpath
import re
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from defusedxml import ElementTree as ET

MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
EPOCH = date(1899, 12, 30)


def column(index: int) -> str:
    result = ""
    while index >= 0:
        index, remainder = divmod(index, 26)
        result = chr(65 + remainder) + result
        index -= 1
    return result


def column_index(address: str) -> int:
    result = 0
    for char in re.sub(r"\d", "", address):
        result = result * 26 + ord(char) - 64
    return result - 1


def text_nodes(element) -> str:
    return "".join(t.text or "" for t in element.iter(MAIN + "t"))


class ExcelFile:
    def __init__(self, file: Path):
        if file.stat().st_size > 20 * 1024 * 1024:
            raise ValueError("Workbook exceeds the 20 MB prototype limit.")
        with ZipFile(file) as archive:
            if sum(info.file_size for info in archive.infolist()) > 100 * 1024 * 1024:
                raise ValueError("Workbook exceeds the uncompressed prototype limit.")
            self.entries = {name: archive.read(name) for name in archive.namelist()}
        workbook = ET.fromstring(self.entries["xl/workbook.xml"])
        relations = ET.fromstring(self.entries["xl/_rels/workbook.xml.rels"])
        targets = {r.attrib["Id"]: r.attrib["Target"] for r in relations}
        self.sheets = {}
        for sheet in workbook.iter(MAIN + "sheet"):
            target = targets[sheet.attrib[REL + "id"]]
            self.sheets[sheet.attrib["name"]] = self.resolve("xl", target)
        shared = self.entries.get("xl/sharedStrings.xml")
        self.shared = [text_nodes(si) for si in ET.fromstring(shared)] if shared else []

    @staticmethod
    def resolve(base, target):
        return target.lstrip("/") if target.startswith("/") else posixpath.normpath(base + "/" + target)

    def read_rows(self, name: str) -> list[list]:
        if name not in self.sheets:
            raise ValueError(f"Workbook is missing the {name} sheet.")
        root = ET.fromstring(self.entries[self.sheets[name]])
        rows = []
        for row in root.iter(MAIN + "row"):
            cells = []
            for cell in row.findall(MAIN + "c"):
                if cell.find(MAIN + "f") is not None:
                    raise ValueError(f"Formula in application data sheet {name}. Store literal database values.")
                raw = cell.findtext(MAIN + "v", "")
                kind = cell.attrib.get("t")
                if kind == "s":
                    value = self.shared[int(raw)]
                elif kind == "inlineStr":
                    value = text_nodes(cell)
                elif kind == "b":
                    value = raw == "1"
                elif kind in {"str", "e"}:
                    value = raw
                else:
                    value = float(raw) if raw else ""
                    if isinstance(value, float) and not math.isfinite(value):
                        raise ValueError(f"Invalid number in {name}.")
                    if isinstance(value, float) and value.is_integer():
                        value = int(value)
                index = column_index(cell.attrib["r"])
                cells.extend([""] * (index + 1 - len(cells)))
                cells[index] = value
            index = int(row.attrib["r"]) - 1
            rows.extend([[] for _ in range(index + 1 - len(rows))])
            rows[index] = cells
        return rows

    def replace_rows(self, name: str, columns: list[str], records: list[dict]):
        path = self.sheets[name]
        xml = self.entries[path].decode("utf-8")
        root = ET.fromstring(xml)
        prefix = re.search(r"<([\w]+:)?worksheet\b", xml).group(1) or ""
        old_rows = list(root.iter(MAIN + "row"))
        styles = {column_index(c.attrib["r"]): c.attrib.get("s", "") for c in old_rows[1]} if len(old_rows) > 1 else {}

        def cell(value, row, col):
            if columns[col] in {"starts_on", "ends_on", "needed_by"} and isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                value = (date.fromisoformat(value) - EPOCH).days
            address = column(col) + str(row)
            style = f' s="{styles[col]}"' if styles.get(col) else ""
            if isinstance(value, bool):
                content = f'<{prefix}v>{int(value)}</{prefix}v>'
                kind = ' t="b"'
            elif isinstance(value, (int, float)):
                if not math.isfinite(value):
                    raise ValueError("Non-finite numeric database value.")
                content = f'<{prefix}v>{value}</{prefix}v>'
                kind = ""
            else:
                value = str(value if value is not None else "")
                if len(value) > 32000:
                    raise ValueError("A database text value exceeds the Excel cell limit.")
                value = escape(re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", value))
                content = f'<{prefix}is><{prefix}t xml:space="preserve">{value}</{prefix}t></{prefix}is>'
                kind = ' t="inlineStr"'
            return f'<{prefix}c r="{address}"{style}{kind}>{content}</{prefix}c>'

        header = re.search(r'<(?:\w+:)?row\b[^>]*\br="1"[^>]*>[\s\S]*?</(?:\w+:)?row>', xml)
        data = header.group(0) if header else f'<{prefix}row r="1">' + "".join(cell(v, 1, i) for i, v in enumerate(columns)) + f'</{prefix}row>'
        for row, record in enumerate(records, 2):
            data += f'<{prefix}row r="{row}">' + "".join(cell(record.get(key, ""), row, col) for col, key in enumerate(columns)) + f'</{prefix}row>'
        pattern = r'<(?:\w+:)?sheetData\b[^>]*>[\s\S]*?</(?:\w+:)?sheetData>|<(?:\w+:)?sheetData\s*/>'
        xml, count = re.subn(pattern, lambda _: f'<{prefix}sheetData>{data}</{prefix}sheetData>', xml, count=1)
        if not count:
            raise ValueError(f"Cannot locate data in {name}.")
        ref = f'A1:{column(len(columns) - 1)}{max(1, len(records) + 1)}'
        for tag in ("dimension", "autoFilter"):
            xml = re.sub(rf'<(?:\w+:)?{tag}\b[^>]*/>', f'<{prefix}{tag} ref="{ref}"/>', xml, count=1)
        self.entries[path] = xml.encode("utf-8")
        rel_path = posixpath.dirname(path) + "/_rels/" + posixpath.basename(path) + ".rels"
        if rel_path in self.entries:
            for relation in ET.fromstring(self.entries[rel_path]):
                if not relation.attrib.get("Type", "").endswith("/table"):
                    continue
                table_path = self.resolve(posixpath.dirname(path), relation.attrib["Target"])
                if table_path in self.entries:
                    table = self.entries[table_path].decode("utf-8")
                    table = re.sub(r'(<(?:\w+:)?(?:table|autoFilter)\b[^>]*\bref=")[^"]+"', lambda m: m.group(1) + ref + '"', table)
                    self.entries[table_path] = table.encode("utf-8")

    def save(self, path: Path):
        with ZipFile(path, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
            for name, data in self.entries.items():
                archive.writestr(name, data)
