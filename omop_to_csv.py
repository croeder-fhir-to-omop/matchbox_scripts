#!/usr/bin/env python3
"""Convert FHIR-shaped OMOP resource JSON (matchbox $transform output) to a CSV row.

Usage:
  python3 omop_to_csv.py [--no-header] [file.json]
  bash transform_condition_fever.sh | python3 omop_to_csv.py
"""

import csv
import json
import sys

COLUMNS = {
    "ConditionOccurrence": [
        "condition_occurrence_id",
        "person_id",
        "condition_concept_id",
        "condition_start_date",
        "condition_start_datetime",
        "condition_end_date",
        "condition_end_datetime",
        "condition_type_concept_id",
        "condition_status_concept_id",
        "stop_reason",
        "provider_id",
        "visit_occurrence_id",
        "visit_detail_id",
        "condition_source_value",
        "condition_source_concept_id",
        "condition_status_source_value",
    ],
    "Person": [
        "person_id",
        "gender_concept_id",
        "year_of_birth",
        "month_of_birth",
        "day_of_birth",
        "birth_datetime",
        "race_concept_id",
        "ethnicity_concept_id",
        "location_id",
        "provider_id",
        "care_site_id",
        "person_source_value",
        "gender_source_value",
        "gender_source_concept_id",
        "race_source_value",
        "race_source_concept_id",
        "ethnicity_source_value",
        "ethnicity_source_concept_id",
    ],
}

def main():
    no_header = "--no-header" in sys.argv
    file_args = [a for a in sys.argv[1:] if not a.startswith("--")]

    src = open(file_args[0]) if file_args else sys.stdin
    try:
        data = json.load(src)
    finally:
        if file_args:
            src.close()

    resource_type = data.get("resourceType")
    cols = COLUMNS.get(resource_type)
    if cols is None:
        print(f"Unknown resourceType: {resource_type!r}", file=sys.stderr)
        sys.exit(1)

    writer = csv.writer(sys.stdout)
    if not no_header:
        writer.writerow(cols)
    writer.writerow([data.get(col, "") for col in cols])


if __name__ == "__main__":
    main()
