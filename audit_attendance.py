import csv
import re
import os
import time
from datetime import datetime, timedelta
from collections import defaultdict

INPUT_FILE = "raw_punches.csv"
OUTPUT_DIR = "Generated Files"
CLEAN_FILE = os.path.join(OUTPUT_DIR, "clean_punches.csv")
REJECTED_FILE = os.path.join(OUTPUT_DIR, "rejected_punches.csv")
SUMMARY_FILE = os.path.join(OUTPUT_DIR, "audit_summary.txt")

EXPECTED_HEADERS = [
    "employee_id",
    "employee_name",
    "device_ip",
    "punch_type",
    "punch_time",
    "building_code"
]

class InvalidHeaderError(Exception):
    pass
class InvalidTimestampError(Exception):
    pass

def execution_time(func):
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        end = time.perf_counter()
        print(f"Execution Time: {end - start:.6f} seconds")
        return result
    return wrapper

def is_valid(value, *patterns, **options):
    value = str(value).strip()
    for pattern in patterns:
        if not re.fullmatch(pattern, value):
            return False
    if options.get("required", True) and not value:
        return False
    return True

def parse_timestamp(value):
    try:
        return datetime.strptime(
            value.strip(),
            "%d-%m-%Y %H:%M:%S"
        )
    except (ValueError, AttributeError) as error:
        raise InvalidTimestampError(
            f"Invalid timestamp: {value}"
        ) from error

def read_csv_file(filename):
    if not os.path.exists(filename):
        raise FileNotFoundError(
            f"Input file not found: {filename}"
        )
    with open(filename, "r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            raise InvalidHeaderError("CSV header is missing.")
        headers = [h.strip() for h in reader.fieldnames]
        if headers != EXPECTED_HEADERS:
            raise InvalidHeaderError(
                f"Invalid CSV header. Expected: {EXPECTED_HEADERS}"
            )
        original_rows = list(reader)
    return original_rows

def validate_row(row):
    errors = []
    employee_id = row.get("employee_id", "").strip()
    employee_name = row.get("employee_name", "").strip()
    device_ip = row.get("device_ip", "").strip()
    punch_type = row.get("punch_type", "").strip().upper()
    punch_time = row.get("punch_time", "").strip()
    building_code = row.get("building_code", "").strip()
    if not is_valid(employee_id, r"E\d{3}"):
        errors.append("Invalid employee ID")
    if not employee_name:
        errors.append("Missing employee name")
    ip_pattern = (
        r"(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)"
        r"(?:\.(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)){3}"
    )
    if not is_valid(device_ip, ip_pattern):
        errors.append("Invalid device IP")
    if punch_type not in ("IN", "OUT"):
        errors.append("Invalid punch type")
    if not building_code:
        errors.append("Missing building code")
    parsed_time = None
    try:
        parsed_time = parse_timestamp(punch_time)
    except InvalidTimestampError:
        errors.append("Invalid timestamp")
    return errors, parsed_time

def get_working_date(punch_type, punch_time):
    working_date = punch_time.date()
    if (
        punch_type == "OUT"
        and punch_time.hour < 4
    ):
        working_date -= timedelta(days=1)
    return working_date

def separate_duplicates(records):
    grouped = defaultdict(list)
    for record in records:
        key = (
            record["employee_id"],
            record["punch_type"],
            record["device_ip"]
        )
        grouped[key].append(record)
    clean_candidates = []
    duplicates = []
    for key, group in grouped.items():
        group.sort(key=lambda x: (x["_parsed_time"], x["_row_number"]))
        previous_valid_time = None
        for record in group:
            current_time = record["_parsed_time"]
            if (
                previous_valid_time is not None
                and (current_time - previous_valid_time).total_seconds() <= 60
            ):
                record["_reason"] = "Duplicate punch within 60 seconds"
                duplicates.append(record)
            else:
                clean_candidates.append(record)
                previous_valid_time = current_time
    return clean_candidates, duplicates

def separate_suspicious(records):
    employee_dates = defaultdict(set)
    for record in records:
        key = (
            record["employee_id"],
            record["working_date"]
        )
        employee_dates[key].add(record["building_code"])
    clean = []
    suspicious = []
    for record in records:
        key = (
            record["employee_id"],
            record["working_date"]
        )
        if len(employee_dates[key]) > 1:
            record["_reason"] = (
                "Employee appeared in multiple buildings "
                "on the same working date"
            )
            suspicious.append(record)
        else:
            clean.append(record)
    return clean, suspicious

def write_csv(filename, records, headers):
    with open(filename, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=headers,
            extrasaction="ignore"
        )
        writer.writeheader()
        for record in records:
            writer.writerow(record)

def generate_summary(
    total_rows,
    clean,
    duplicates,
    suspicious,
    rejected,
    **kwargs
):
    employee_summary = defaultdict(
        lambda: {
            "clean": 0,
            "duplicate": 0,
            "suspicious": 0,
            "rejected": 0
        }
    )
    groups = {
        "clean": clean,
        "duplicate": duplicates,
        "suspicious": suspicious,
        "rejected": rejected
    }
    for category, records in groups.items():
        for record in records:
            employee_id = record.get(
                "employee_id", "UNKNOWN"
            )
            employee_summary[employee_id][category] += 1
    lines = [
        "ATTENDANCE PUNCH LOG AUDIT REPORT",
        "=" * 45,
        f"Total Rows      : {total_rows}",
        f"Clean Rows      : {len(clean)}",
        f"Duplicate Count : {len(duplicates)}",
        f"Suspicious Count: {len(suspicious)}",
        f"Rejected Count  : {len(rejected)}",
        "",
        "EMPLOYEE-WISE SUMMARY",
        "=" * 45
    ]
    for employee_id in sorted(employee_summary):
        data = employee_summary[employee_id]
        lines.append(
            f"{employee_id}: "
            f"Clean={data['clean']}, "
            f"Duplicate={data['duplicate']}, "
            f"Suspicious={data['suspicious']}, "
            f"Rejected={data['rejected']}"
        )
    lines.extend([
        "",
        "DUPLICATE RECORD DETAILS",
        "=" * 45
    ])
    for record in duplicates:
        lines.append(
            f"Row {record['_row_number']}: "
            f"{record['employee_id']} - {record['_reason']}"
        )
    lines.extend([
        "",
        "SUSPICIOUS RECORD DETAILS",
        "=" * 45
    ])
    for record in suspicious:
        lines.append(
            f"Row {record['_row_number']}: "
            f"{record['employee_id']} - "
            f"{record['building_code']} - {record['_reason']}"
        )

    with open(SUMMARY_FILE, "w", encoding="utf-8") as file:
        file.write("\n".join(lines))

@execution_time
def audit_attendance():
    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        original_rows = read_csv_file(INPUT_FILE)
        working_rows = [row.copy() for row in original_rows] # Shallow copy is creating separate dictionaries for processing.
        valid_records = []
        rejected_records = []
        for row_number, row in enumerate(working_rows, start=2):
            errors, parsed_time = validate_row(row)
            row["_row_number"] = row_number
            if errors:
                row["_reason"] = "; ".join(errors)
                rejected_records.append(row)
                continue
            row["punch_type"] = row["punch_type"].strip().upper()
            row["_parsed_time"] = parsed_time
            working_date = get_working_date(
                row["punch_type"],
                parsed_time
            )
            row["working_date"] = working_date.strftime(
                "%d-%m-%Y"
            )
            row["working_date"] = working_date  # Store date object for reliable sorting/grouping
            valid_records.append(row)
        non_duplicates, duplicates = separate_duplicates(       # Step 1: Separate duplicate records
            valid_records
        )
        clean, suspicious = separate_suspicious(                 # Step 2: Detect suspicious building switches
            non_duplicates
        )
        clean.sort(
            key=lambda x: (
                x["employee_id"],
                x["working_date"],       # Sort output
                x["_parsed_time"],
                x["_row_number"]
            )
        )
        clean_headers = EXPECTED_HEADERS + ["working_date"]
        write_csv(CLEAN_FILE, clean, clean_headers)
        rejected_headers = EXPECTED_HEADERS + ["rejection_reason"]
        for record in rejected_records:
            record["rejection_reason"] = record["_reason"]
        write_csv(
            REJECTED_FILE,
            rejected_records,
            rejected_headers
        )
        generate_summary(
            len(original_rows),
            clean,
            duplicates,
            suspicious,
            rejected_records
        )
        print("\nAUDIT COMPLETED SUCCESSFULLY")
        print(f"Total Rows: {len(original_rows)}")
        print(f"Clean: {len(clean)}")
        print(f"Duplicates: {len(duplicates)}")
        print(f"Suspicious: {len(suspicious)}")
        print(f"Rejected: {len(rejected_records)}")
        print("\nGenerated Files:")
        print(CLEAN_FILE)
        print(REJECTED_FILE)
        print(SUMMARY_FILE)

    except (
        FileNotFoundError,
        InvalidHeaderError,
        PermissionError,
        OSError
    ) as error:
        print(f"Audit Error: {error}")

if __name__ == "__main__":
    audit_attendance()
