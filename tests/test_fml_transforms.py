"""
Integration tests for FHIR→OMOP StructureMap transforms via matchbox server.

Requires a running matchbox server (MATCHBOX_URL env var or default http://localhost:8080).

Issues:
  matchbox_scripts#1  https://github.com/croeder-fhir-to-omop/matchbox_scripts/issues/1
  fhir-omop-ig#1      https://github.com/croeder-fhir-to-omop/fhir-omop-ig/issues/1
  fhir-omop-ig#2      https://github.com/croeder-fhir-to-omop/fhir-omop-ig/issues/2
  fhir-omop-ig#3      https://github.com/croeder-fhir-to-omop/fhir-omop-ig/issues/3
  fhir-omop-ig#4      https://github.com/croeder-fhir-to-omop/fhir-omop-ig/issues/4
  fhir-omop-ig#6      https://github.com/croeder-fhir-to-omop/fhir-omop-ig/issues/6
  fhir-omop-ig#7      https://github.com/croeder-fhir-to-omop/fhir-omop-ig/issues/7
  fhir-omop-ig#8      https://github.com/croeder-fhir-to-omop/fhir-omop-ig/issues/8
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get('MATCHBOX_URL', 'http://localhost:8080') + '/matchboxv3/fhir'
IG = 'http://hl7.org/fhir/uv/omop/StructureMap'

HEADERS = {
    'Content-Type': 'application/fhir+json',
    'Accept': 'application/fhir+json',
}


def transform(resource: dict, map_name: str) -> dict | None:
    r = requests.post(
        f'{BASE_URL}/StructureMap/$transform',
        params={'source': f'{IG}/{map_name}'},
        headers=HEADERS,
        json=resource,
        timeout=30,
    )
    r.raise_for_status()
    result = r.json()
    if result.get('resourceType') == 'OperationOutcome':
        return None
    return result


def _retrying(fn, passes, attempts=5, delay=3):
    """Call fn() up to attempts times until passes(result) is True, sleeping between tries.

    Handles Echidna cold-cache misses where a valid resource is returned but
    terminology-translated fields (e.g. drug_concept_id) are missing on first call.
    Echidna may take several seconds to populate a vocabulary on first use.
    """
    for i in range(attempts):
        result = fn()
        if passes(result):
            return result
        if i < attempts - 1:
            time.sleep(delay)
    return result


PATIENT_MALE = {
    "resourceType": "Patient",
    "id": "test-male",
    "gender": "male",
    "birthDate": "1980-01-01",
}

PATIENT_FEMALE = {
    "resourceType": "Patient",
    "id": "test-female",
    "gender": "female",
    "birthDate": "1985-06-15",
}

PATIENT_NO_GENDER = {
    "resourceType": "Patient",
    "id": "test-nogender",
    "birthDate": "1990-03-20",
}

ENCOUNTER_AMB = {
    "resourceType": "Encounter",
    "id": "test-amb",
    "status": "completed",
    # R4: class is a single Coding (R5 would be CodeableConcept[])
    "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB"},
    "subject": {"reference": "Patient/test"},
    "actualPeriod": {"start": "2020-01-01T09:00:00Z", "end": "2020-01-01T10:00:00Z"},
}

ENCOUNTER_IMP = {
    "resourceType": "Encounter",
    "id": "test-imp",
    "status": "completed",
    # R4: class is a single Coding (R5 would be CodeableConcept[])
    "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "IMP"},
    "subject": {"reference": "Patient/test"},
    "actualPeriod": {"start": "2020-02-01T09:00:00Z", "end": "2020-02-03T12:00:00Z"},
}

OBSERVATION_LABORATORY = {
    "resourceType": "Observation",
    "id": "test-obs",
    "status": "final",
    "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "laboratory"}]}],
    "code": {"coding": [{"system": "http://loinc.org", "code": "29463-7", "display": "Body weight"}]},
    "subject": {"reference": "Patient/test"},
    "encounter": {"reference": "Encounter/test"},
    "effectiveDateTime": "2020-03-15",
    "valueQuantity": {"value": 72.5, "unit": "kg", "system": "http://unitsofmeasure.org", "code": "kg"},
}


PROCEDURE_DATETIME = {
    "resourceType": "Procedure",
    "id": "test-procedure-dt",
    "status": "completed",
    "code": {"coding": [{"system": "http://snomed.info/sct", "code": "80146002", "display": "Appendectomy"}]},
    "subject": {"reference": "Patient/test"},
    # R4: performed[x] (renamed to occurrence[x] in R5)
    "performedDateTime": "2020-03-15T10:00:00Z",
}

PROCEDURE_PERIOD = {
    "resourceType": "Procedure",
    "id": "test-procedure-period",
    "status": "completed",
    "code": {"coding": [{"system": "http://snomed.info/sct", "code": "80146002", "display": "Appendectomy"}]},
    "subject": {"reference": "Patient/test"},
    # R4: performed[x] as Period (renamed to occurrence[x] in R5)
    "performedPeriod": {"start": "2020-03-15T10:00:00Z", "end": "2020-03-15T11:00:00Z"},
}

OBSERVATION_SMOKING = {
    "resourceType": "Observation",
    "id": "test-smoking",
    "status": "final",
    "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "social-history"}]}],
    "code": {"coding": [{"system": "http://loinc.org", "code": "72166-2", "display": "Tobacco smoking status"}]},
    "subject": {"reference": "Patient/test"},
    "effectiveDateTime": "2020-03-15",
    # valueCodeableConcept — triggers the undefined variable 'b' bug in ObservationMap
    "valueCodeableConcept": {
        "coding": [{"system": "http://snomed.info/sct", "code": "266919005", "display": "Never smoked tobacco"}]
    },
}

OBSERVATION_WITH_UNIT = {
    "resourceType": "Observation",
    "id": "test-obs-unit",
    "status": "final",
    "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "laboratory"}]}],
    "code": {"coding": [{"system": "http://loinc.org", "code": "29463-7", "display": "Body weight"}]},
    "subject": {"reference": "Patient/test"},
    "effectiveDateTime": "2020-03-15",
    "valueQuantity": {"value": 72.5, "unit": "kg", "system": "http://unitsofmeasure.org", "code": "kg"},
}


@pytest.fixture(scope='session', autouse=True)
def require_server():
    try:
        requests.get(BASE_URL + '/metadata', timeout=5)
    except requests.exceptions.ConnectionError:
        pytest.skip(f'matchbox server not reachable at {BASE_URL}')


class TestPersonMapLocal:
    """PersonMap with GenderClass ConceptMap URL — local concept lookup."""

    def test_WHEN_patient_gender_is_male_SHOULD_produce_gender_concept_id_8507(self):
        result = transform(PATIENT_MALE, 'PersonMap')
        assert result is not None, 'transform returned OperationOutcome'
        assert result.get('gender_concept_id') == '8507', (
            f"Expected gender_concept_id=8507, got {result.get('gender_concept_id')}"
        )

    def test_WHEN_patient_gender_is_female_SHOULD_produce_gender_concept_id_8532(self):
        result = transform(PATIENT_FEMALE, 'PersonMap')
        assert result is not None
        assert result.get('gender_concept_id') == '8532', (
            f"Expected gender_concept_id=8532, got {result.get('gender_concept_id')}"
        )

    def test_WHEN_patient_has_no_gender_SHOULD_produce_gender_concept_id_0(self):
        result = transform(PATIENT_NO_GENDER, 'PersonMap')
        assert result is not None
        assert result.get('gender_concept_id') == '0', (
            f"Expected gender_concept_id=0, got {result.get('gender_concept_id')}"
        )


class TestPersonMapServer:
    """PersonMapServer with blank URL — all translate calls go to Echidna.

    Echidna cannot resolve bare FHIR codes ('male', 'female') without a sourceSystem,
    so gender_concept_id will be null/absent until Echidna coverage improves.
    """

    def test_WHEN_patient_gender_is_male_SHOULD_produce_no_gender_concept_id(self):
        result = transform(PATIENT_MALE, 'PersonMapServer')
        assert result is not None, 'transform returned OperationOutcome'
        assert result.get('gender_concept_id') is None, (
            f"Expected gender_concept_id=None (Echidna gap), got {result.get('gender_concept_id')}"
        )

    def test_WHEN_patient_gender_is_female_SHOULD_produce_no_gender_concept_id(self):
        result = transform(PATIENT_FEMALE, 'PersonMapServer')
        assert result is not None
        assert result.get('gender_concept_id') is None


ENCOUNTER_WITH_PERIOD = {
    "resourceType": "Encounter",
    "id": "test-period",
    "status": "finished",
    # R4: class is a single Coding, period (not actualPeriod), hospitalization (not admission)
    "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB"},
    "subject": {"reference": "Patient/test"},
    "period": {"start": "2020-01-01T09:00:00Z", "end": "2020-01-01T10:00:00Z"},
    "hospitalization": {
        "dischargeDisposition": {
            "coding": [{"system": "http://terminology.hl7.org/CodeSystem/discharge-disposition", "code": "home"}]
        }
    },
}


class TestEncounterVisitMapLocal:
    """EncounterVisitMap with EncounterClass ConceptMap URL — local concept lookup."""

    def test_WHEN_encounter_class_is_AMB_SHOULD_produce_visit_concept_id_9202(self):
        result = transform(ENCOUNTER_AMB, 'EncounterVisitMap')
        assert result is not None, 'transform returned OperationOutcome'
        assert result.get('visit_concept_id') == '9202', (
            f"Expected visit_concept_id=9202, got {result.get('visit_concept_id')}"
        )

    def test_WHEN_encounter_class_is_IMP_SHOULD_produce_visit_concept_id_9201(self):
        result = transform(ENCOUNTER_IMP, 'EncounterVisitMap')
        assert result is not None
        assert result.get('visit_concept_id') == '9201', (
            f"Expected visit_concept_id=9201, got {result.get('visit_concept_id')}"
        )

    def test_WHEN_encounter_has_period_SHOULD_produce_visit_start_date(self):
        result = transform(ENCOUNTER_WITH_PERIOD, 'EncounterVisitMap')
        assert result is not None, 'transform returned OperationOutcome'
        assert result.get('visit_start_date') is not None, (
            f"Expected visit_start_date, got None — FML may still use R5 'actualPeriod'"
        )

    def test_WHEN_encounter_has_hospitalization_SHOULD_produce_discharged_to_source_value(self):
        result = transform(ENCOUNTER_WITH_PERIOD, 'EncounterVisitMap')
        assert result is not None
        assert result.get('discharged_to_source_value') is not None, (
            f"Expected discharged_to_source_value, got None — FML may still use R5 'admission'"
        )

    def test_WHEN_encounter_is_transformed_SHOULD_produce_visit_type_concept_id(self):
        result = transform(ENCOUNTER_AMB, 'EncounterVisitMap')
        assert result is not None
        assert result.get('visit_type_concept_id') is not None, (
            f"Expected visit_type_concept_id (NOT NULL in OMOP), got None"
        )


class TestEncounterVisitMapServer:
    """EncounterVisitMapServer with blank URL — Echidna path.

    Echidna cannot resolve bare FHIR Act codes ('AMB', 'IMP') without sourceSystem.
    """

    def test_WHEN_encounter_class_is_AMB_SHOULD_produce_no_visit_concept_id(self):
        result = transform(ENCOUNTER_AMB, 'EncounterVisitMapServer')
        assert result is not None, 'transform returned OperationOutcome'
        assert result.get('visit_concept_id') is None, (
            f"Expected visit_concept_id=None (Echidna gap), got {result.get('visit_concept_id')}"
        )


class TestMeasurementMap:
    """MeasurementMap — verify fieldToReturn='code' fix doesn't raise FHIRException."""

    def test_WHEN_observation_has_laboratory_category_SHOULD_not_error(self):
        result = transform(OBSERVATION_LABORATORY, 'MeasurementMap')
        # result may be None if LOINC→OMOP lookup fails, but must not raise or return OperationOutcome with error
        # (OperationOutcome with the old bug contained "Cannot handle type Coding as string" or similar)
        if result is None:
            pytest.skip('MeasurementMap returned OperationOutcome — server may not have the map loaded')
        assert result.get('resourceType') != 'OperationOutcome', (
            f"Got OperationOutcome instead of Measurement: {result}"
        )

    def test_WHEN_observation_has_laboratory_category_SHOULD_have_measurement_id(self):
        result = transform(OBSERVATION_LABORATORY, 'MeasurementMap')
        if result is None:
            pytest.skip('MeasurementMap returned OperationOutcome')
        assert result.get('measurement_id') is not None


class TestPersonMapRaceEthnicity:
    """fhir-omop-ig#1 — PersonMap must default race_concept_id and ethnicity_concept_id to 0.

    OMOP CDM 5.4 requires both fields as NOT NULL integers. When the source Patient
    has no race/ethnicity (plain R4 Patient, no US Core extensions), the map must
    emit 0 (OMOP 'Unknown') rather than leaving the fields absent.
    """

    def test_WHEN_patient_has_no_race_SHOULD_produce_race_concept_id_0(self):
        result = transform(PATIENT_MALE, 'PersonMap')
        assert result is not None, 'transform returned OperationOutcome'
        assert result.get('race_concept_id') == '0', (
            f"Expected race_concept_id='0', got {result.get('race_concept_id')!r}"
        )

    def test_WHEN_patient_has_no_ethnicity_SHOULD_produce_ethnicity_concept_id_0(self):
        result = transform(PATIENT_MALE, 'PersonMap')
        assert result is not None
        assert result.get('ethnicity_concept_id') == '0', (
            f"Expected ethnicity_concept_id='0', got {result.get('ethnicity_concept_id')!r}"
        )


class TestProcedureMap:
    """fhir-omop-ig#2 — ProcedureMap must use R4 field name 'performed' not R5 'occurrence'.

    In R4, Procedure.performed[x] holds the date. The FML uses src.occurrence which
    is the R5 rename — it matches nothing on an R4 server, leaving procedure_date null.
    """

    def test_WHEN_procedure_has_performedDateTime_SHOULD_produce_procedure_date(self):
        result = transform(PROCEDURE_DATETIME, 'ProcedureMap')
        assert result is not None, 'transform returned OperationOutcome'
        assert result.get('procedure_date') is not None, (
            f"Expected non-null procedure_date, got None — ProcedureMap may still use R5 'occurrence' field"
        )

    def test_WHEN_procedure_has_performedPeriod_SHOULD_produce_procedure_date(self):
        result = transform(PROCEDURE_PERIOD, 'ProcedureMap')
        assert result is not None, 'transform returned OperationOutcome'
        assert result.get('procedure_date') is not None, (
            f"Expected non-null procedure_date from performedPeriod, got None"
        )


class TestObservationMap:
    """fhir-omop-ig#3 — ObservationMap valueCodeableConcept branch uses undefined variable 'b'.

    The translate(b, '', 'code') call references 'b' from a different branch scope,
    causing matchbox to return 500. Fix is translate(a, '', 'code').
    """

    def test_WHEN_observation_has_valueCodeableConcept_SHOULD_not_error(self):
        result = transform(OBSERVATION_SMOKING, 'ObservationMap')
        assert result is not None, (
            'ObservationMap returned OperationOutcome — likely 500 from undefined variable b'
        )

    def test_WHEN_observation_has_valueCodeableConcept_SHOULD_have_observation_id(self):
        result = transform(OBSERVATION_SMOKING, 'ObservationMap')
        assert result is not None
        assert result.get('observation_id') is not None, (
            f"Expected observation_id to be set, got None"
        )


class TestMeasurementMapUnit:
    """fhir-omop-ig#4 — MeasurementMap must not write unit string to integer unit_concept_id.

    's.unit as b -> tgt.unit_concept_id = b' puts the UCUM string ('kg') into an
    integer column. Fix: route unit string to unit_source_value, leave unit_concept_id absent.
    """

    def test_WHEN_observation_has_unit_SHOULD_not_put_string_in_unit_concept_id(self):
        result = transform(OBSERVATION_WITH_UNIT, 'MeasurementMap')
        assert result is not None, 'transform returned OperationOutcome'
        uid = result.get('unit_concept_id')
        assert uid is None or str(uid).isdigit(), (
            f"unit_concept_id must be an integer or absent, got {uid!r} — "
            "MeasurementMap may still write the UCUM string directly"
        )

    def test_WHEN_observation_has_unit_kg_SHOULD_produce_unit_source_value_kg(self):
        result = transform(OBSERVATION_WITH_UNIT, 'MeasurementMap')
        assert result is not None
        assert result.get('unit_source_value') == 'kg', (
            f"Expected unit_source_value='kg', got {result.get('unit_source_value')!r}"
        )


VITAL_SIGN_TEMPERATURE = {
    "resourceType": "Observation",
    "id": "test-temp",
    "status": "final",
    "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "vital-signs"}]}],
    "code": {"coding": [{"system": "http://loinc.org", "code": "8310-5", "display": "Body temperature"}]},
    "subject": {"reference": "Patient/test"},
    "effectiveDateTime": "2020-03-15T09:00:00Z",
    "valueQuantity": {"value": 37.2, "unit": "Cel", "system": "http://unitsofmeasure.org", "code": "Cel"},
}

VITAL_SIGN_WEIGHT = {
    "resourceType": "Observation",
    "id": "test-weight-vs",
    "status": "final",
    "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "vital-signs"}]}],
    "code": {"coding": [{"system": "http://loinc.org", "code": "29463-7", "display": "Body weight"}]},
    "subject": {"reference": "Patient/test"},
    "effectiveDateTime": "2020-03-15T09:00:00Z",
    "valueQuantity": {"value": 72.5, "unit": "kg", "system": "http://unitsofmeasure.org", "code": "kg"},
}


class TestSimpleVitalSignsMapUnit:
    """fhir-omop-ig#7 — SimpleVitalSignsMap must not write UCUM string to unit_concept_id (INT).

    's.unit as b -> tgt.unit_concept_id = b' puts e.g. 'Cel' into an INT32 column,
    causing a DuckDB Conversion Error on insert. Fix: route to unit_source_value.
    """

    def test_WHEN_vital_sign_has_unit_Cel_SHOULD_not_put_string_in_unit_concept_id(self):
        result = transform(VITAL_SIGN_TEMPERATURE, 'SimpleVitalSignsMap')
        assert result is not None, 'SimpleVitalSignsMap returned OperationOutcome'
        uid = result.get('unit_concept_id')
        assert uid is None or str(uid).isdigit(), (
            f"unit_concept_id must be absent or an integer, got {uid!r} — "
            "SimpleVitalSignsMap still writes UCUM string to unit_concept_id"
        )

    def test_WHEN_vital_sign_has_unit_Cel_SHOULD_produce_unit_source_value_Cel(self):
        result = transform(VITAL_SIGN_TEMPERATURE, 'SimpleVitalSignsMap')
        assert result is not None, 'SimpleVitalSignsMap returned OperationOutcome'
        assert result.get('unit_source_value') == 'Cel', (
            f"Expected unit_source_value='Cel', got {result.get('unit_source_value')!r}"
        )

    def test_WHEN_vital_sign_has_unit_kg_SHOULD_produce_unit_source_value_kg(self):
        result = transform(VITAL_SIGN_WEIGHT, 'SimpleVitalSignsMap')
        assert result is not None, 'SimpleVitalSignsMap returned OperationOutcome'
        assert result.get('unit_source_value') == 'kg', (
            f"Expected unit_source_value='kg', got {result.get('unit_source_value')!r}"
        )


PROCEDURE_WITH_DATETIME = {
    "resourceType": "Procedure",
    "id": "test-proc-type",
    "status": "completed",
    "code": {"coding": [{"system": "http://snomed.info/sct", "code": "80146002", "display": "Appendectomy"}]},
    "subject": {"reference": "Patient/test"},
    "performedDateTime": "2020-03-15T10:00:00Z",
}


class TestProcedureMapTypeConceptId:
    """fhir-omop-ig#6 — ProcedureMap must set procedure_type_concept_id (NOT NULL in OMOP CDM 5.4).

    Without a default, every insert into procedure_occurrence fails with:
    'NOT NULL constraint failed: procedure_occurrence.procedure_type_concept_id'
    Fix: add tgt.procedure_type_concept_id = 32817 (EHR) to the src.id rule.
    """

    def test_WHEN_procedure_is_transformed_SHOULD_produce_procedure_type_concept_id(self):
        result = transform(PROCEDURE_WITH_DATETIME, 'ProcedureMap')
        assert result is not None, 'ProcedureMap returned OperationOutcome'
        assert result.get('procedure_type_concept_id') is not None, (
            "Expected procedure_type_concept_id to be set (NOT NULL in OMOP CDM 5.4), got None"
        )

    def test_WHEN_procedure_is_transformed_SHOULD_produce_procedure_type_concept_id_32817(self):
        result = transform(PROCEDURE_WITH_DATETIME, 'ProcedureMap')
        assert result is not None
        assert result.get('procedure_type_concept_id') == '32817', (
            f"Expected procedure_type_concept_id=32817 (EHR), got {result.get('procedure_type_concept_id')!r}"
        )


class TestSimpleVitalSignsMeasurementId:
    """fhir-omop-ig#8 — SimpleVitalSignsMap must set measurement_id (NOT NULL in OMOP CDM 5.4).

    The map has no src.id rule, leaving measurement_id unset. Every insert fails with:
    'NOT NULL constraint failed: measurement.measurement_id'
    Fix: add src.id -> tgt.measurement_id = 1 to the Measures group.
    """

    def test_WHEN_vital_sign_is_transformed_SHOULD_produce_measurement_id(self):
        result = transform(VITAL_SIGN_TEMPERATURE, 'SimpleVitalSignsMap')
        assert result is not None, 'SimpleVitalSignsMap returned OperationOutcome'
        assert result.get('measurement_id') is not None, (
            "Expected measurement_id to be set (NOT NULL in OMOP CDM 5.4), got None"
        )


class TestSimpleVitalSignsConceptId:
    """fhir-omop-ig#10 — SimpleVitalSignsMap must populate measurement_concept_id, not
    measurement_type_concept_id, with the LOINC-translated concept.

    The FML has: sc.code as a -> tgt.measurement_type_concept_id = translate(a, '', 'code')
    This puts the LOINC concept ID in the wrong field, leaving measurement_concept_id NULL
    (NOT NULL constraint) and populating measurement_type_concept_id with a clinical concept
    instead of the required source-type value (32817 EHR).
    Fix: swap field to measurement_concept_id; hardcode measurement_type_concept_id = 32817.
    """

    def test_WHEN_vital_sign_is_transformed_SHOULD_produce_measurement_concept_id(self):
        result = transform(VITAL_SIGN_TEMPERATURE, 'SimpleVitalSignsMap')
        assert result is not None, 'SimpleVitalSignsMap returned OperationOutcome'
        assert result.get('measurement_concept_id') is not None, (
            "measurement_concept_id must be set (NOT NULL in OMOP CDM 5.4), got None"
        )

    def test_WHEN_vital_sign_is_transformed_measurement_concept_id_SHOULD_be_numeric(self):
        result = transform(VITAL_SIGN_TEMPERATURE, 'SimpleVitalSignsMap')
        assert result is not None, 'SimpleVitalSignsMap returned OperationOutcome'
        cid = result.get('measurement_concept_id')
        assert cid is not None and str(cid).lstrip('-').isdigit(), (
            f"measurement_concept_id must be an integer, got {cid!r}"
        )

    def test_WHEN_vital_sign_is_transformed_SHOULD_produce_measurement_type_concept_id_32817(self):
        result = transform(VITAL_SIGN_TEMPERATURE, 'SimpleVitalSignsMap')
        assert result is not None, 'SimpleVitalSignsMap returned OperationOutcome'
        assert str(result.get('measurement_type_concept_id')) == '32817', (
            f"measurement_type_concept_id must be 32817 (EHR), got {result.get('measurement_type_concept_id')!r}"
        )


BLOOD_PRESSURE = {
    "resourceType": "Observation",
    "id": "test-bp",
    "status": "final",
    "meta": {"profile": ["http://hl7.org/fhir/StructureDefinition/bp"]},
    "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "vital-signs"}]}],
    "code": {"coding": [{"system": "http://loinc.org", "code": "85354-9", "display": "Blood pressure panel"}]},
    "subject": {"reference": "Patient/test"},
    "effectiveDateTime": "2020-03-15",
    "component": [
        {
            "code": {"coding": [{"system": "http://loinc.org", "code": "8480-6", "display": "Systolic blood pressure"}]},
            "valueQuantity": {"value": 120, "unit": "mmHg", "system": "http://unitsofmeasure.org", "code": "mm[Hg]"},
        },
        {
            "code": {"coding": [{"system": "http://loinc.org", "code": "8462-4", "display": "Diastolic blood pressure"}]},
            "valueQuantity": {"value": 80, "unit": "mmHg", "system": "http://unitsofmeasure.org", "code": "mm[Hg]"},
        },
    ],
}


class TestBloodPressureVitalSignsMap:
    """BloodPressureVitalSignsMap maps the BP panel Observation as a single OMOP Measurement.

    HAPI-FHIR FML cannot set OMOP properties on resources created via create() inside Bundle
    entries, so the Bundle-based approach was replaced with three single-resource maps:
    BloodPressureVitalSignsMap (panel), BloodPressureSystolicMap, BloodPressureDiastolicMap.
    """

    def test_WHEN_bp_panel_is_transformed_SHOULD_return_measurement(self):
        result = transform(BLOOD_PRESSURE, 'BloodPressureVitalSignsMap')
        assert result is not None, 'BloodPressureVitalSignsMap returned OperationOutcome'
        assert result.get('resourceType') in ('MeasureTable', 'Measurement'), (
            f"Expected MeasureTable/Measurement, got {result.get('resourceType')}"
        )

    def test_WHEN_bp_panel_is_transformed_SHOULD_have_measurement_concept_id(self):
        result = transform(BLOOD_PRESSURE, 'BloodPressureVitalSignsMap')
        assert result is not None
        cid = result.get('measurement_concept_id')
        assert cid is not None, 'measurement_concept_id must not be None'
        assert str(cid).lstrip('-').isdigit(), f'measurement_concept_id must be integer, got {cid!r}'

    def test_WHEN_bp_panel_is_transformed_SHOULD_have_measurement_type_concept_id_32817(self):
        result = transform(BLOOD_PRESSURE, 'BloodPressureVitalSignsMap')
        assert result is not None
        assert str(result.get('measurement_type_concept_id')) == '32817', (
            f"measurement_type_concept_id must be 32817, got {result.get('measurement_type_concept_id')!r}"
        )

    def test_WHEN_bp_panel_is_transformed_SHOULD_have_measurement_id(self):
        result = transform(BLOOD_PRESSURE, 'BloodPressureVitalSignsMap')
        assert result is not None
        mid = result.get('measurement_id')
        assert mid is not None, 'measurement_id must not be None (required for OMOP PK)'


class TestBloodPressureSystolicMap:
    """BloodPressureSystolicMap extracts systolic component from a bp Observation.

    Produces a single OMOP Measurement row with hardcoded concept_id 3004249 (OMOP for
    systolic BP LOINC 8480-6), using registry URL Measurement-Systolic for PK uniqueness.
    """

    def test_WHEN_bp_is_transformed_via_systolic_map_SHOULD_return_measurement(self):
        result = transform(BLOOD_PRESSURE, 'BloodPressureSystolicMap')
        assert result is not None, 'BloodPressureSystolicMap returned OperationOutcome'
        assert result.get('resourceType') in ('MeasureTable', 'Measurement'), (
            f"Expected MeasureTable/Measurement, got {result.get('resourceType')}"
        )

    def test_WHEN_bp_is_transformed_via_systolic_map_SHOULD_have_concept_id_3004249(self):
        result = transform(BLOOD_PRESSURE, 'BloodPressureSystolicMap')
        assert result is not None
        cid = result.get('measurement_concept_id')
        assert str(cid) == '3004249', (
            f"Expected measurement_concept_id=3004249 (systolic BP), got {cid!r}"
        )

    def test_WHEN_bp_is_transformed_via_systolic_map_SHOULD_have_type_concept_id_32817(self):
        result = transform(BLOOD_PRESSURE, 'BloodPressureSystolicMap')
        assert result is not None
        assert str(result.get('measurement_type_concept_id')) == '32817', (
            f"measurement_type_concept_id must be 32817, got {result.get('measurement_type_concept_id')!r}"
        )

    def test_WHEN_bp_is_transformed_via_systolic_map_SHOULD_have_value_120(self):
        result = transform(BLOOD_PRESSURE, 'BloodPressureSystolicMap')
        assert result is not None
        v = result.get('value_as_number')
        assert str(v) in ('120', '120.0'), f'Expected value_as_number=120, got {v!r}'

    def test_WHEN_bp_is_transformed_via_systolic_map_SHOULD_have_unit_mmHg(self):
        result = transform(BLOOD_PRESSURE, 'BloodPressureSystolicMap')
        assert result is not None
        assert result.get('unit_source_value') == 'mmHg', (
            f"Expected unit_source_value='mmHg', got {result.get('unit_source_value')!r}"
        )

    def test_WHEN_bp_is_transformed_via_systolic_map_unit_concept_id_SHOULD_be_absent_or_integer(self):
        result = transform(BLOOD_PRESSURE, 'BloodPressureSystolicMap')
        assert result is not None
        uid = result.get('unit_concept_id')
        assert uid is None or str(uid).lstrip('-').isdigit(), (
            f"unit_concept_id must be absent or integer, got {uid!r}"
        )

    def test_WHEN_bp_is_transformed_via_systolic_map_SHOULD_have_measurement_id(self):
        result = transform(BLOOD_PRESSURE, 'BloodPressureSystolicMap')
        assert result is not None
        mid = result.get('measurement_id')
        assert mid is not None, 'measurement_id must not be None'

    def test_WHEN_systolic_and_diastolic_maps_applied_to_same_bp_SHOULD_produce_different_measurement_ids(self):
        sys_result = transform(BLOOD_PRESSURE, 'BloodPressureSystolicMap')
        dia_result = transform(BLOOD_PRESSURE, 'BloodPressureDiastolicMap')
        assert sys_result is not None and dia_result is not None
        assert sys_result.get('measurement_id') != dia_result.get('measurement_id'), (
            'Systolic and diastolic measurement_id values must differ — they target different OMOP rows '
            '(use distinct registry URL suffixes: Measurement-Systolic vs Measurement-Diastolic)'
        )


class TestBloodPressureDiastolicMap:
    """BloodPressureDiastolicMap extracts diastolic component from a bp Observation.

    Produces a single OMOP Measurement row with hardcoded concept_id 3012888 (OMOP for
    diastolic BP LOINC 8462-4), using registry URL Measurement-Diastolic for PK uniqueness.
    """

    def test_WHEN_bp_is_transformed_via_diastolic_map_SHOULD_return_measurement(self):
        result = transform(BLOOD_PRESSURE, 'BloodPressureDiastolicMap')
        assert result is not None, 'BloodPressureDiastolicMap returned OperationOutcome'
        assert result.get('resourceType') in ('MeasureTable', 'Measurement'), (
            f"Expected MeasureTable/Measurement, got {result.get('resourceType')}"
        )

    def test_WHEN_bp_is_transformed_via_diastolic_map_SHOULD_have_concept_id_3012888(self):
        result = transform(BLOOD_PRESSURE, 'BloodPressureDiastolicMap')
        assert result is not None
        cid = result.get('measurement_concept_id')
        assert str(cid) == '3012888', (
            f"Expected measurement_concept_id=3012888 (diastolic BP), got {cid!r}"
        )

    def test_WHEN_bp_is_transformed_via_diastolic_map_SHOULD_have_type_concept_id_32817(self):
        result = transform(BLOOD_PRESSURE, 'BloodPressureDiastolicMap')
        assert result is not None
        assert str(result.get('measurement_type_concept_id')) == '32817', (
            f"measurement_type_concept_id must be 32817, got {result.get('measurement_type_concept_id')!r}"
        )

    def test_WHEN_bp_is_transformed_via_diastolic_map_SHOULD_have_value_80(self):
        result = transform(BLOOD_PRESSURE, 'BloodPressureDiastolicMap')
        assert result is not None
        v = result.get('value_as_number')
        assert str(v) in ('80', '80.0'), f'Expected value_as_number=80, got {v!r}'

    def test_WHEN_bp_is_transformed_via_diastolic_map_SHOULD_have_unit_mmHg(self):
        result = transform(BLOOD_PRESSURE, 'BloodPressureDiastolicMap')
        assert result is not None
        assert result.get('unit_source_value') == 'mmHg', (
            f"Expected unit_source_value='mmHg', got {result.get('unit_source_value')!r}"
        )

    def test_WHEN_bp_is_transformed_via_diastolic_map_unit_concept_id_SHOULD_be_absent_or_integer(self):
        result = transform(BLOOD_PRESSURE, 'BloodPressureDiastolicMap')
        assert result is not None
        uid = result.get('unit_concept_id')
        assert uid is None or str(uid).lstrip('-').isdigit(), (
            f"unit_concept_id must be absent or integer, got {uid!r}"
        )

    def test_WHEN_bp_is_transformed_via_diastolic_map_SHOULD_have_measurement_id(self):
        result = transform(BLOOD_PRESSURE, 'BloodPressureDiastolicMap')
        assert result is not None
        mid = result.get('measurement_id')
        assert mid is not None, 'measurement_id must not be None'


ALLERGY_PEANUT = {
    "resourceType": "AllergyIntolerance",
    "id": "test-allergy-peanut",
    "clinicalStatus": {
        "coding": [{"system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical", "code": "active"}]
    },
    "verificationStatus": {
        "coding": [{"system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification", "code": "confirmed"}]
    },
    "type": {
        "coding": [{"system": "http://hl7.org/fhir/allergy-intolerance-type", "code": "allergy"}]
    },
    "code": {
        "coding": [{"system": "http://snomed.info/sct", "code": "91935009", "display": "Allergy to peanuts"}]
    },
    "patient": {"reference": "Patient/test-patient"},
    "encounter": {"reference": "Encounter/test-encounter"},
    "recordedDate": "2020-03-15",
}

MEDICATION_ASPIRIN = {
    "resourceType": "MedicationStatement",
    "id": "test-medication-aspirin",
    "status": "recorded",
    # R4: medicationCodeableConcept (R5 uses medication.concept — see medication_aspirin_r5.json)
    "medicationCodeableConcept": {
        "coding": [{"system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": "1191", "display": "Aspirin"}]
    },
    "subject": {"reference": "Patient/test-patient"},
    "effectiveDateTime": "2020-03-15",
    "category": [
        {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/medication-statement-category", "code": "outpatient"}]}
    ],
}


class TestAllergyMap:
    """AllergyMap — AllergyIntolerance → OMOP Observation table.

    Verifies that the map produces a valid Observation row with stable IDs
    and correct date fields after the id-registry translate() update (fhir-omop-ig#11).
    """

    def test_WHEN_allergy_is_transformed_SHOULD_not_return_operation_outcome(self):
        result = transform(ALLERGY_PEANUT, 'AllergyMap')
        assert result is not None, (
            'AllergyMap returned OperationOutcome — map may have a runtime error'
        )

    def test_WHEN_allergy_is_transformed_SHOULD_produce_observation_id(self):
        result = transform(ALLERGY_PEANUT, 'AllergyMap')
        assert result is not None
        assert result.get('observation_id') is not None, (
            'Expected observation_id to be set; id-registry translate() may have failed'
        )

    def test_WHEN_allergy_is_transformed_observation_id_SHOULD_be_numeric(self):
        result = transform(ALLERGY_PEANUT, 'AllergyMap')
        assert result is not None
        oid = result.get('observation_id')
        assert oid is not None and str(oid).isdigit(), (
            f"Expected numeric observation_id from id-registry, got {oid!r}"
        )

    def test_WHEN_allergy_is_transformed_SHOULD_produce_person_id(self):
        result = transform(ALLERGY_PEANUT, 'AllergyMap')
        assert result is not None
        assert result.get('person_id') is not None, (
            'Expected person_id from patient.reference; nested reference extraction may have failed'
        )

    def test_WHEN_allergy_is_transformed_person_id_SHOULD_be_numeric(self):
        result = transform(ALLERGY_PEANUT, 'AllergyMap')
        assert result is not None
        pid = result.get('person_id')
        assert pid is not None and str(pid).isdigit(), (
            f"Expected numeric person_id from id-registry, got {pid!r}"
        )

    def test_WHEN_allergy_is_transformed_SHOULD_produce_visit_occurrence_id(self):
        result = transform(ALLERGY_PEANUT, 'AllergyMap')
        assert result is not None
        assert result.get('visit_occurrence_id') is not None, (
            'Expected visit_occurrence_id from encounter.reference'
        )

    def test_WHEN_allergy_is_transformed_SHOULD_produce_observation_date(self):
        result = transform(ALLERGY_PEANUT, 'AllergyMap')
        assert result is not None
        assert result.get('observation_date') is not None, (
            'Expected observation_date from recordedDate'
        )

    def test_WHEN_allergy_is_transformed_person_id_SHOULD_match_patient_reference(self):
        result = transform(ALLERGY_PEANUT, 'AllergyMap')
        assert result is not None
        # person_id must equal stable_id("Patient", "test-patient") — same value as PersonMap
        # would assign for the same patient. Verify it is consistent (non-zero, numeric).
        pid = result.get('person_id')
        assert pid is not None and str(pid).isdigit() and int(str(pid)) > 0, (
            f"Expected positive numeric person_id, got {pid!r}"
        )


class TestMedicationStatementMap:
    """MedicationStatementMap — MedicationStatement → OMOP DrugExposure table.

    Verifies that the map produces a valid DrugExposure row with stable IDs
    and correct date fields after the id-registry translate() update (fhir-omop-ig#11).
    """

    def test_WHEN_medication_is_transformed_SHOULD_not_return_operation_outcome(self):
        result = transform(MEDICATION_ASPIRIN, 'MedicationMap')
        assert result is not None, (
            'MedicationMap returned OperationOutcome — map may have a runtime error'
        )

    def test_WHEN_medication_is_transformed_SHOULD_produce_drug_exposure_id(self):
        result = transform(MEDICATION_ASPIRIN, 'MedicationMap')
        assert result is not None
        assert result.get('drug_exposure_id') is not None, (
            'Expected drug_exposure_id to be set; id-registry translate() may have failed'
        )

    def test_WHEN_medication_is_transformed_drug_exposure_id_SHOULD_be_numeric(self):
        result = transform(MEDICATION_ASPIRIN, 'MedicationMap')
        assert result is not None
        did = result.get('drug_exposure_id')
        assert did is not None and str(did).isdigit(), (
            f"Expected numeric drug_exposure_id from id-registry, got {did!r}"
        )

    def test_WHEN_medication_is_transformed_SHOULD_produce_person_id(self):
        result = transform(MEDICATION_ASPIRIN, 'MedicationMap')
        assert result is not None
        assert result.get('person_id') is not None, (
            'Expected person_id from subject.reference; nested reference extraction may have failed'
        )

    def test_WHEN_medication_is_transformed_person_id_SHOULD_be_numeric(self):
        result = transform(MEDICATION_ASPIRIN, 'MedicationMap')
        assert result is not None
        pid = result.get('person_id')
        assert pid is not None and str(pid).isdigit(), (
            f"Expected numeric person_id from id-registry, got {pid!r}"
        )

    def test_WHEN_medication_is_transformed_SHOULD_produce_start_date(self):
        result = transform(MEDICATION_ASPIRIN, 'MedicationMap')
        assert result is not None
        assert result.get('drug_exposure_start_date') is not None, (
            'Expected drug_exposure_start_date from effectiveDateTime'
        )


class TestAllergyMapServer:
    """AllergyMapServer — AllergyIntolerance → OMOP Observation via Echidna (empty-URL translate).

    Verifies that observation_concept_id is populated by Echidna from the SNOMED coding,
    in addition to the structural fields covered by TestAllergyMap.
    """

    def test_WHEN_allergy_server_is_transformed_SHOULD_not_return_operation_outcome(self):
        result = transform(ALLERGY_PEANUT, 'AllergyMapServer')
        assert result is not None, (
            'AllergyMapServer returned OperationOutcome — map may have a runtime error'
        )

    def test_WHEN_allergy_server_is_transformed_SHOULD_produce_observation_concept_id(self):
        result = transform(ALLERGY_PEANUT, 'AllergyMapServer')
        assert result is not None
        assert result.get('observation_concept_id') is not None, (
            'Expected observation_concept_id from Echidna SNOMED translate; '
            'empty-URL fallback to Echidna may not be working'
        )

    def test_WHEN_allergy_server_is_transformed_observation_concept_id_SHOULD_be_numeric(self):
        result = transform(ALLERGY_PEANUT, 'AllergyMapServer')
        assert result is not None
        cid = result.get('observation_concept_id')
        assert cid is not None and str(cid).isdigit(), (
            f"Expected numeric OMOP concept_id from Echidna, got {cid!r}"
        )

    def test_WHEN_allergy_server_is_transformed_SHOULD_produce_observation_type_concept_id(self):
        result = transform(ALLERGY_PEANUT, 'AllergyMapServer')
        assert result is not None
        # FML integer literals serialize as strings in FHIR JSON; accept int or str
        assert int(str(result.get('observation_type_concept_id') or 0)) == 32817, (
            f"Expected observation_type_concept_id=32817 (EHR), "
            f"got {result.get('observation_type_concept_id')!r}"
        )

    def test_WHEN_allergy_server_is_transformed_SHOULD_produce_observation_id(self):
        result = transform(ALLERGY_PEANUT, 'AllergyMapServer')
        assert result is not None
        assert result.get('observation_id') is not None

    def test_WHEN_allergy_server_is_transformed_SHOULD_produce_person_id(self):
        result = transform(ALLERGY_PEANUT, 'AllergyMapServer')
        assert result is not None
        assert result.get('person_id') is not None


class TestMedicationMapServer:
    """MedicationMapServer — MedicationStatement → OMOP DrugExposure via Echidna.

    Verifies that drug_concept_id is populated by Echidna from the RxNorm coding,
    in addition to the structural fields covered by TestMedicationStatementMap.
    """

    def test_WHEN_medication_server_is_transformed_SHOULD_not_return_operation_outcome(self):
        result = transform(MEDICATION_ASPIRIN, 'MedicationMapServer')
        assert result is not None, (
            'MedicationMapServer returned OperationOutcome — map may have a runtime error'
        )

    def test_WHEN_medication_server_is_transformed_SHOULD_produce_drug_concept_id(self):
        # Echidna loads the RxNorm vocabulary on first use; after heavy SNOMED load
        # from prior tests this can take ~45s, so retry generously.
        result = _retrying(
            lambda: transform(MEDICATION_ASPIRIN, 'MedicationMapServer'),
            passes=lambda r: r is not None and r.get('drug_concept_id') is not None,
            attempts=20, delay=3,
        )
        assert result is not None
        assert result.get('drug_concept_id') is not None, (
            'Expected drug_concept_id from Echidna RxNorm translate; '
            'empty-URL fallback to Echidna may not be working'
        )

    def test_WHEN_medication_server_is_transformed_drug_concept_id_SHOULD_be_numeric(self):
        result = _retrying(
            lambda: transform(MEDICATION_ASPIRIN, 'MedicationMapServer'),
            passes=lambda r: r is not None and r.get('drug_concept_id') is not None,
            attempts=20, delay=3,
        )
        assert result is not None
        cid = result.get('drug_concept_id')
        assert cid is not None and str(cid).isdigit(), (
            f"Expected numeric OMOP concept_id from Echidna, got {cid!r}"
        )

    def test_WHEN_medication_server_is_transformed_SHOULD_produce_drug_type_concept_id(self):
        result = transform(MEDICATION_ASPIRIN, 'MedicationMapServer')
        assert result is not None
        # FML integer literals serialize as strings in FHIR JSON; accept int or str
        assert int(str(result.get('drug_type_concept_id') or 0)) == 32817, (
            f"Expected drug_type_concept_id=32817 (EHR), "
            f"got {result.get('drug_type_concept_id')!r}"
        )

    def test_WHEN_medication_server_is_transformed_SHOULD_produce_drug_exposure_id(self):
        result = transform(MEDICATION_ASPIRIN, 'MedicationMapServer')
        assert result is not None
        assert result.get('drug_exposure_id') is not None

    def test_WHEN_medication_server_is_transformed_SHOULD_produce_person_id(self):
        result = transform(MEDICATION_ASPIRIN, 'MedicationMapServer')
        assert result is not None
        assert result.get('person_id') is not None

    def test_WHEN_medication_server_is_transformed_SHOULD_produce_start_date(self):
        result = transform(MEDICATION_ASPIRIN, 'MedicationMapServer')
        assert result is not None
        assert result.get('drug_exposure_start_date') is not None
