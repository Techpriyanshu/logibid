"""Extract only the e-bidding master tables from a MySQL dump."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


MASTER_FIELDS = {
    "zones": ("id", "code", "name", "is_active", "created_at", "updated_at"),
    "plants": ("id", "zone_id", "code", "name", "is_active", "created_at", "updated_at"),
    "depots": ("id", "code", "name", "metadata", "created_at", "updated_at"),
    "plant_depots": ("id", "plant_id", "depot_code", "sap_depot_id", "sort_order"),
    "depot_destinations": ("id", "depot_code", "destination", "sort_order", "created_at"),
    "tonnage_options": ("id", "value", "label", "is_active", "sort_order"),
}
MASTER_TABLES = tuple(MASTER_FIELDS)
SNAPSHOT_DATE = "2026-08-18"


def extract_table(source: str, table: str) -> tuple[str, str]:
    create_pattern = re.compile(
        rf"^CREATE TABLE `{re.escape(table)}` \([\s\S]*?^\) ENGINE=[^;]+;",
        re.MULTILINE,
    )
    insert_pattern = re.compile(
        rf"^INSERT INTO `{re.escape(table)}` VALUES .+;$",
        re.MULTILINE,
    )

    create_match = create_pattern.search(source)
    insert_match = insert_pattern.search(source)
    if create_match is None or insert_match is None:
        raise ValueError(f"Backup is missing the schema or seed rows for `{table}`.")

    create_sql = create_match.group(0).replace(
        f"CREATE TABLE `{table}`",
        f"CREATE TABLE IF NOT EXISTS `{table}`",
        1,
    ).replace("utf8mb4_0900_ai_ci", "utf8mb4_unicode_ci")
    insert_sql = insert_match.group(0).replace(
        f"INSERT INTO `{table}`",
        f"INSERT IGNORE INTO `{table}`",
        1,
    )
    return create_sql, insert_sql


def parse_insert_rows(statement: str) -> list[list[object]]:
    values = statement.split(" VALUES ", 1)[1].rstrip(";")
    rows: list[list[object]] = []
    index = 0

    while index < len(values):
        while index < len(values) and values[index] in " \r\n\t,":
            index += 1
        if index == len(values):
            break
        if values[index] != "(":
            raise ValueError("Unexpected data in a master-table INSERT statement.")
        index += 1
        row: list[object] = []

        while True:
            while index < len(values) and values[index].isspace():
                index += 1
            if index >= len(values):
                raise ValueError("Unterminated row in a master-table INSERT statement.")

            if values[index] == "'":
                index += 1
                chars: list[str] = []
                while index < len(values):
                    char = values[index]
                    if char == "\\" and index + 1 < len(values):
                        index += 1
                        chars.append(values[index])
                        index += 1
                        continue
                    if char == "'" and index + 1 < len(values) and values[index + 1] == "'":
                        chars.append("'")
                        index += 2
                        continue
                    if char == "'":
                        index += 1
                        break
                    chars.append(char)
                    index += 1
                else:
                    raise ValueError("Unterminated string in a master-table INSERT statement.")
                value: object = "".join(chars)
            else:
                start = index
                while index < len(values) and values[index] not in ",)":
                    index += 1
                token = values[start:index].strip()
                if token.upper() == "NULL":
                    value = None
                else:
                    try:
                        value = int(token)
                    except ValueError:
                        try:
                            value = float(token)
                        except ValueError as error:
                            raise ValueError("Unsupported master-table value.") from error

            row.append(value)
            while index < len(values) and values[index].isspace():
                index += 1
            if index >= len(values):
                raise ValueError("Unterminated row in a master-table INSERT statement.")
            if values[index] == ",":
                index += 1
                continue
            if values[index] == ")":
                index += 1
                break
            raise ValueError("Malformed row in a master-table INSERT statement.")

        rows.append(row)

    return rows


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate an SQL file containing only master-data tables."
    )
    parser.add_argument("backup", type=Path, help="Path to the existing MySQL SQL dump")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("backend/config/master_data_restore.sql"),
        help="Output SQL file (default: backend/config/master_data_restore.sql)",
    )
    parser.add_argument(
        "--snapshot-output",
        type=Path,
        default=Path("backend/config/master_data_snapshot.json"),
        help="Output JSON snapshot (default: backend/config/master_data_snapshot.json)",
    )
    args = parser.parse_args()

    source = args.backup.read_text(encoding="utf-8-sig")
    tables: dict[str, list[dict[str, object]]] = {}
    statements = [
        "-- Master-data-only restore generated from a local MySQL dump.",
        "-- Seed rows are from an August 2026 backup; verify they are current before live bidding.",
        "-- Does not drop tables or overwrite rows that already exist.",
        "-- Select the intended database before importing this file.",
        "",
    ]

    for table in MASTER_TABLES:
        create_sql, insert_sql = extract_table(source, table)
        statements.extend((create_sql, "", insert_sql, ""))
        rows = parse_insert_rows(insert_sql)
        fields = MASTER_FIELDS[table]
        if any(len(row) != len(fields) for row in rows):
            raise ValueError(f"Unexpected column count in `{table}` seed data.")
        tables[table] = [dict(zip(fields, row)) for row in rows]

    statements.extend((
        "CREATE TABLE IF NOT EXISTS `master_data_status` (",
        "  `id` tinyint unsigned NOT NULL PRIMARY KEY,",
        "  `source` varchar(32) NOT NULL,",
        "  `snapshot_date` date DEFAULT NULL,",
        "  `verified` tinyint(1) NOT NULL DEFAULT 0",
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;",
        "",
        "INSERT IGNORE INTO `master_data_status` (`id`, `source`, `snapshot_date`, `verified`)",
        f"VALUES (1, 'snapshot', '{SNAPSHOT_DATE}', 0);",
        "",
    ))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(statements), encoding="utf-8")
    snapshot = {
        "source": "local-mysql-backup",
        "snapshot_date": SNAPSHOT_DATE,
        "tables": tables,
    }
    args.snapshot_output.parent.mkdir(parents=True, exist_ok=True)
    args.snapshot_output.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Wrote master-data SQL for {len(MASTER_TABLES)} tables to {args.output}")
    print(f"Wrote dated read-only master-data snapshot to {args.snapshot_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
