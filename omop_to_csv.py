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
    "ProcedureOccurrence": [
        "procedure_occurrence_id",
        "person_id",
        "procedure_concept_id",
        "procedure_date",
        "procedure_datetime",
        "procedure_end_date",
        "procedure_end_datetime",
        "procedure_type_concept_id",
        "modifier_concept_id",
        "quantity",
        "provider_id",
        "visit_occurrence_id",
        "visit_detail_id",
        "procedure_source_value",
        "procedure_source_concept_id",
        "modifier_source_value",
    ],
    "VisitOccurrence": [
        "visit_occurrence_id",
        "person_id",
        "visit_concept_id",
        "visit_start_date",
        "visit_start_datetime",
        "visit_end_date",
        "visit_end_datetime",
        "visit_type_concept_id",
        "provider_id",
        "care_site_id",
        "visit_source_value",
        "visit_source_concept_id",
        "admitted_from_concept_id",
        "admitted_from_source_value",
        "discharged_to_concept_id",
        "discharged_to_source_value",
        "preceding_visit_occurrence_id",
    ],
    "DrugExposure": [
        "drug_exposure_id",
        "person_id",
        "drug_concept_id",
        "drug_exposure_start_date",
        "drug_exposure_start_datetime",
        "drug_exposure_end_date",
        "drug_exposure_end_datetime",
        "verbatim_end_date",
        "drug_type_concept_id",
        "stop_reason",
        "refills",
        "quantity",
        "days_supply",
        "sig",
        "route_concept_id",
        "lot_number",
        "provider_id",
        "visit_occurrence_id",
        "visit_detail_id",
        "drug_source_value",
        "drug_source_concept_id",
        "route_source_value",
        "dose_unit_source_value",
    ],
    "Measurement": [
        "measurement_id",
        "person_id",
        "measurement_concept_id",
        "measurement_date",
        "measurement_datetime",
        "measurement_time",
        "measurement_type_concept_id",
        "operator_concept_id",
        "value_as_number",
        "value_as_concept_id",
        "unit_concept_id",
        "range_low",
        "range_high",
        "provider_id",
        "visit_occurrence_id",
        "visit_detail_id",
        "measurement_source_value",
        "measurement_source_concept_id",
        "unit_source_value",
        "unit_source_concept_id",
        "value_source_value",
        "measurement_event_id",
        "meas_event_field_concept_id",
    ],
    "Observation": [
        "observation_id",
        "person_id",
        "observation_concept_id",
        "observation_date",
        "observation_datetime",
        "observation_type_concept_id",
        "value_as_number",
        "value_as_string",
        "value_as_concept_id",
        "qualifier_concept_id",
        "unit_concept_id",
        "provider_id",
        "visit_occurrence_id",
        "visit_detail_id",
        "observation_source_value",
        "observation_source_concept_id",
        "unit_source_value",
        "qualifier_source_value",
        "value_source_value",
        "observation_event_id",
        "obs_event_field_concept_id",
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
