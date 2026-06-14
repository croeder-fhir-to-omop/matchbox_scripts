#!/usr/bin/env python3
"""Mine FHIR ConceptMaps from the IG output and write three supplemental files:

  concept_extra.tsv              — local source concepts (IDs > 2B, non-standard)
  concept_relationship_extra.tsv — 'Maps to' from local concept → Athena OMOP concept_id
  vocabulary_extra.tsv           — vocabulary definitions for locally-added vocabularies

Local concept IDs are assigned deterministically via SHA-256 hash of
(vocabulary_id, concept_code), mapped into the range [2_000_000_000, 3_000_000_000).
This satisfies the OMOP rule that local/custom concept IDs must be > 2B.

Standard clinical terminology systems (SNOMED, LOINC, RxNorm) already exist in OMOP's
CONCEPT.csv and are looked up directly by enchilada's translate Step 1; they do not
need entries in concept_extra.tsv.  Their ConceptMap entries are included here only to
backfill any codes absent from the Athena download.
"""

import csv
import hashlib
import json
import sys
from pathlib import Path

IG_OUTPUT = Path.home() / "git/fhir-omop-ig/output"
OUT_DIR = Path(__file__).parent

CONCEPT_EXTRA = OUT_DIR / "concept_extra.tsv"
CR_EXTRA = OUT_DIR / "concept_relationship_extra.tsv"
VOCAB_EXTRA = OUT_DIR / "vocabulary_extra.tsv"

# Systems whose codes already appear in CONCEPT.csv as standard concepts.
# Their ConceptMap entries are included only as fallback backfill.
STANDARD_SYSTEMS = {
    "http://snomed.info/sct",
    "http://hl7.org/fhir/sid/icd-10-cm",
    "http://hl7.org/fhir/sid/icd-9-cm",
    "http://www.nlm.nih.gov/research/umls/rxnorm",
    "http://loinc.org",
}

# Maps FHIR system URI → enchilada vocabulary_id.
# For standard systems the vocab_id matches the OMOP vocabulary_id in CONCEPT.csv.
# For FHIR administrative systems the vocab_id is a locally-defined identifier.
SYSTEM_TO_VOCAB_ID: dict[str, str] = {
    # Standard clinical terminologies
    "http://snomed.info/sct":                                         "SNOMED",
    "http://hl7.org/fhir/sid/icd-10-cm":                             "ICD10CM",
    "http://hl7.org/fhir/sid/icd-9-cm":                              "ICD9CM",
    "http://www.nlm.nih.gov/research/umls/rxnorm":                    "RxNorm",
    "http://loinc.org":                                               "LOINC",
    # FHIR administrative code systems — locally defined vocabularies
    "http://hl7.org/fhir/administrative-gender":                      "AdministrativeGender",
    "http://hl7.org/fhir/allergy-intolerance-category":               "AllergyIntoleranceCategory",
    "http://hl7.org/fhir/intolerance-category":                       "IntoleranceCategory",
    "http://hl7.org/fhir/sid/cvx":                                    "CVX",
    "http://terminology.hl7.org/CodeSystem/v3-ActCode":               "v3-ActCode",
    "http://terminology.hl7.org/CodeSystem/admit-source":             "AdmitSource",
    "http://terminology.hl7.org/CodeSystem/discharge-disposition":    "DischargeDisposition",
    "http://terminology.hl7.org/CodeSystem/v3-RouteOfAdministration": "RouteOfAdministration",
    "http://terminology.hl7.org/CodeSystem/immunization-origin":      "ImmunizationOrigin",
    "http://terminology.hl7.org/CodeSystem/condition-clinical":       "ConditionClinical",
}

# Per-file vocabulary_id override for ConceptMaps that share a source system
# but map to different OMOP target concepts (e.g. AllergyType vs IntoleranceType).
CONCEPTMAP_VOCAB_OVERRIDE: dict[str, str] = {
    "ConceptMap-IntoleranceType.json": "IntoleranceCategory",
}

# Human-readable vocabulary metadata for vocabulary_extra.tsv.
VOCAB_METADATA: dict[str, tuple[str, str]] = {
    # vocab_id: (name, reference_uri)
    "AdministrativeGender":      ("FHIR R4 Administrative Gender",
                                  "http://hl7.org/fhir/administrative-gender"),
    "AllergyIntoleranceCategory": ("FHIR R4 Allergy Intolerance Category (allergy type)",
                                   "http://hl7.org/fhir/allergy-intolerance-category"),
    "IntoleranceCategory":       ("FHIR R4 Allergy Intolerance Category (intolerance type)",
                                  "http://hl7.org/fhir/allergy-intolerance-category"),
    "CVX":                       ("CDC Vaccine Administered (CVX)",
                                  "http://hl7.org/fhir/sid/cvx"),
    "v3-ActCode":                ("HL7 v3 Act Code",
                                  "http://terminology.hl7.org/CodeSystem/v3-ActCode"),
    "AdmitSource":               ("HL7 Admit Source",
                                  "http://terminology.hl7.org/CodeSystem/admit-source"),
    "DischargeDisposition":      ("HL7 Discharge Disposition",
                                  "http://terminology.hl7.org/CodeSystem/discharge-disposition"),
    "RouteOfAdministration":     ("HL7 v3 Route of Administration",
                                  "http://terminology.hl7.org/CodeSystem/v3-RouteOfAdministration"),
    "ImmunizationOrigin":        ("HL7 Immunization Origin",
                                  "http://terminology.hl7.org/CodeSystem/immunization-origin"),
    "ConditionClinical":         ("HL7 Condition Clinical Status",
                                  "http://terminology.hl7.org/CodeSystem/condition-clinical"),
}


def local_concept_id(vocab_id: str, code: str) -> int:
    """Deterministic OMOP-compliant local concept ID (> 2B) from vocab + code."""
    key = f"{vocab_id}\x00{code}".encode()
    h = int(hashlib.sha256(key).hexdigest()[:15], 16)
    return 2_000_000_000 + (h % 999_999_999)


def mine_concept_maps(ig_output: Path) -> tuple[list[dict], list[dict], set[str]]:
    """Return (concept_rows, relationship_rows, new_vocab_ids)."""
    concept_rows: list[dict] = []
    relationship_rows: list[dict] = []
    new_vocab_ids: set[str] = set()

    for path in sorted(ig_output.glob("ConceptMap-*.json")):
        with open(path) as f:
            cm = json.load(f)
        for group in cm.get("group", []):
            source = group.get("source", "")
            vocab_id = CONCEPTMAP_VOCAB_OVERRIDE.get(path.name) or SYSTEM_TO_VOCAB_ID.get(source)
            if vocab_id is None:
                print(f"  WARN: unknown source system '{source}' in {path.name}", file=sys.stderr)
                continue

            is_standard_system = source in STANDARD_SYSTEMS

            for element in group.get("element", []):
                src_code = element.get("code", "")
                for target in element.get("target", []):
                    tgt_code = target.get("code", "")
                    if not (src_code and tgt_code):
                        continue

                    if is_standard_system:
                        # Backfill: add as a standard concept so Step 1 lookup finds it.
                        concept_rows.append({
                            "concept_id": tgt_code,
                            "concept_code": src_code,
                            "vocabulary_id": vocab_id,
                            "standard_concept": "S",
                        })
                    else:
                        # Local vocabulary: non-standard source concept + 'Maps to' relationship.
                        local_id = local_concept_id(vocab_id, src_code)
                        concept_rows.append({
                            "concept_id": local_id,
                            "concept_code": src_code,
                            "vocabulary_id": vocab_id,
                            "standard_concept": "",
                        })
                        relationship_rows.append({
                            "concept_id_1": local_id,
                            "concept_id_2": tgt_code,
                            "relationship_id": "Maps to",
                        })
                        new_vocab_ids.add(vocab_id)

    return concept_rows, relationship_rows, new_vocab_ids


def write_tsv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main():
    concept_rows, relationship_rows, new_vocab_ids = mine_concept_maps(IG_OUTPUT)

    write_tsv(CONCEPT_EXTRA,
              ["concept_id", "concept_code", "vocabulary_id", "standard_concept"],
              concept_rows)
    print(f"Wrote {len(concept_rows)} rows to {CONCEPT_EXTRA}")

    write_tsv(CR_EXTRA,
              ["concept_id_1", "concept_id_2", "relationship_id"],
              relationship_rows)
    print(f"Wrote {len(relationship_rows)} rows to {CR_EXTRA}")

    vocab_rows = [
        {"vocabulary_id": vid,
         "vocabulary_name": VOCAB_METADATA[vid][0],
         "vocabulary_reference": VOCAB_METADATA[vid][1]}
        for vid in sorted(new_vocab_ids)
        if vid in VOCAB_METADATA
    ]
    write_tsv(VOCAB_EXTRA,
              ["vocabulary_id", "vocabulary_name", "vocabulary_reference"],
              vocab_rows)
    print(f"Wrote {len(vocab_rows)} rows to {VOCAB_EXTRA}")


if __name__ == "__main__":
    main()
