"""
FHIR -> OMOP transforms via matchbox $transform.

Each function takes a FHIR resource dict and returns an OMOP dict,
None if the resource should be suppressed, or raises SkipResource if
the resource is explicitly incompatible (shown as SKIP in the report).

Post-processing sets correct OMOP PKs and FKs from the original FHIR
resource, overriding the FML placeholder value of 1. This avoids
id-registry (no terminology-server side effects) while keeping FML
maps simple enough to compile in the IG publisher.
"""

import os
import time

import requests

_BASE_URL = None
_BASE_URL_R5 = None

# Echidna free tier enforces ~60 req/min; set TRANSFORM_SLEEP=1 when using it.
# Not needed with enchilada (local) — defaults to 0.
_TRANSFORM_SLEEP = float(os.environ.get('TRANSFORM_SLEEP', '0'))


def _base_url():
    global _BASE_URL
    if _BASE_URL is None:
        _BASE_URL = os.environ.get('MATCHBOX_URL', 'http://matchbox:8080') + '/matchboxv3/fhir'
    return _BASE_URL


def _base_url_r5():
    global _BASE_URL_R5
    if _BASE_URL_R5 is None:
        _BASE_URL_R5 = os.environ.get('MATCHBOX_R5_URL', 'http://matchbox-r5:8082') + '/matchboxv3/fhir'
    return _BASE_URL_R5

_HEADERS = {
    'Content-Type': 'application/fhir+json',
    'Accept': 'application/fhir+json',
}

_IG = 'http://hl7.org/fhir/uv/omop/StructureMap'

_omop_id_counter = [0]


class SkipResource(Exception):
    """Raised when a fixture is explicitly incompatible with the current server configuration."""


def _next_id():
    _omop_id_counter[0] += 1
    return _omop_id_counter[0]


def _ref_int(ref_str):
    """Extract integer from a FHIR reference like 'Patient/1'. Returns None if not numeric."""
    if ref_str:
        tail = ref_str.split('/')[-1]
        try:
            return int(tail)
        except ValueError:
            pass
    return None


def _call(resource, map_name):
    time.sleep(_TRANSFORM_SLEEP)
    r = requests.post(
        f'{_base_url()}/StructureMap/$transform',
        params={'source': f'{_IG}/{map_name}'},
        headers=_HEADERS,
        json=resource,
    )
    r.raise_for_status()
    result = r.json()
    if result.get('resourceType') == 'OperationOutcome':
        return None
    return result


def _call_r5(resource, map_name):
    time.sleep(_TRANSFORM_SLEEP)
    r = requests.post(
        f'{_base_url_r5()}/StructureMap/$transform',
        params={'source': f'{_IG}/{map_name}'},
        headers=_HEADERS,
        json=resource,
    )
    r.raise_for_status()
    result = r.json()
    if result.get('resourceType') == 'OperationOutcome':
        return None
    return result


def _set_person_id(result, resource, ref_key='subject'):
    """Override person_id from the original FHIR resource's reference field."""
    ref_str = (resource.get(ref_key) or {}).get('reference')
    pid = _ref_int(ref_str)
    if pid is not None:
        result['person_id'] = pid
    elif result.get('person_id') is None:
        result['person_id'] = _next_id()


def _set_visit_id(result, resource):
    """Override visit_occurrence_id from the original FHIR resource's encounter reference."""
    ref_str = (resource.get('encounter') or {}).get('reference')
    vid = _ref_int(ref_str)
    if vid is not None:
        result['visit_occurrence_id'] = vid


def transform_patient(resource):
    result = _call(resource, 'PersonMap')
    if result:
        fhir_id = resource.get('id', '')
        try:
            result['person_id'] = int(fhir_id)
        except (ValueError, TypeError):
            result['person_id'] = _next_id()
    return result


def transform_encounter(resource):
    result = _call(resource, 'EncounterVisitMap')
    if result:
        fhir_id = resource.get('id', '')
        try:
            result['visit_occurrence_id'] = int(fhir_id)
        except (ValueError, TypeError):
            result['visit_occurrence_id'] = _next_id()
        _set_person_id(result, resource)
    return result


def transform_condition(resource):
    result = _call(resource, 'ConditionMap')
    if result:
        result['condition_occurrence_id'] = _next_id()
        _set_person_id(result, resource)
        _set_visit_id(result, resource)
    return result


def transform_procedure(resource):
    result = _call(resource, 'ProcedureMap')
    if result:
        result['procedure_occurrence_id'] = _next_id()
        _set_person_id(result, resource)
        _set_visit_id(result, resource)
    return result


def transform_allergy(resource):
    result = _call(resource, 'AllergyMap')
    if result:
        result['observation_id'] = _next_id()
        _set_person_id(result, resource, ref_key='patient')
        _set_visit_id(result, resource)
    return result


def transform_immunization(resource):
    result = _call(resource, 'ImmunizationMap')
    if result:
        result['drug_exposure_id'] = _next_id()
        _set_person_id(result, resource, ref_key='patient')
        _set_visit_id(result, resource)
    return result


def transform_measurement(resource):
    result = _call(resource, 'MeasurementMap')
    if result:
        result['measurement_id'] = _next_id()
        _set_person_id(result, resource)
        _set_visit_id(result, resource)
    return result


def transform_observation(resource):
    result = _call(resource, 'ObservationMap')
    if result:
        result['observation_id'] = _next_id()
        _set_person_id(result, resource)
        _set_visit_id(result, resource)
    return result


def transform_vital_signs(resource):
    result = _call(resource, 'SimpleVitalSignsMap')
    if result:
        result['measurement_id'] = _next_id()
        _set_person_id(result, resource)
        _set_visit_id(result, resource)
    return result


def _is_r5_medication(resource):
    # R5 MedicationStatement uses medication.concept (CodeableReference);
    # R4 uses medicationCodeableConcept / medicationReference (choice type).
    # Suppress R5 fixtures — matchbox runs FHIR R4 (see fhir-omop-ig issue for R4/R5 compat).
    med = resource.get('medication', {})
    return isinstance(med, dict) and 'concept' in med


def transform_medication(resource):
    if _is_r5_medication(resource):
        raise SkipResource('R5 MedicationStatement (medication.concept) not supported by R4 server')
    resource_type = resource.get('resourceType', '')
    if resource_type == 'MedicationRequest':
        result = _call(resource, 'MedicationRequestMap')
    else:
        result = _call(resource, 'MedicationMap')
    if result:
        result['drug_exposure_id'] = _next_id()
        _set_person_id(result, resource)
        _set_visit_id(result, resource)
    return result


def transform_bp_panel(resource):
    result = _call(resource, 'BloodPressureVitalSignsMap')
    if result:
        result['measurement_id'] = _next_id()
        _set_person_id(result, resource)
        _set_visit_id(result, resource)
    return result


def transform_bp_systolic(resource):
    result = _call(resource, 'BloodPressureSystolicMap')
    if result:
        result['measurement_id'] = _next_id()
        _set_person_id(result, resource)
        _set_visit_id(result, resource)
    return result


def transform_bp_diastolic(resource):
    result = _call(resource, 'BloodPressureDiastolicMap')
    if result:
        result['measurement_id'] = _next_id()
        _set_person_id(result, resource)
        _set_visit_id(result, resource)
    return result


# =============================================================================
# R5 transform functions — target the R5 matchbox on MATCHBOX_R5_URL.
# Each calls _call_r5() with the corresponding R5-suffixed map name.
# =============================================================================

def transform_patient_r5(resource):
    result = _call_r5(resource, 'PersonMap')
    if result:
        fhir_id = resource.get('id', '')
        try:
            result['person_id'] = int(fhir_id)
        except (ValueError, TypeError):
            result['person_id'] = _next_id()
    return result


def transform_encounter_r5(resource):
    result = _call_r5(resource, 'EncounterVisitMap')
    if result:
        fhir_id = resource.get('id', '')
        try:
            result['visit_occurrence_id'] = int(fhir_id)
        except (ValueError, TypeError):
            result['visit_occurrence_id'] = _next_id()
        _set_person_id(result, resource)
    return result


def transform_condition_r5(resource):
    result = _call_r5(resource, 'ConditionMap')
    if result:
        result['condition_occurrence_id'] = _next_id()
        _set_person_id(result, resource)
        _set_visit_id(result, resource)
    return result


def transform_procedure_r5(resource):
    result = _call_r5(resource, 'ProcedureMap')
    if result:
        result['procedure_occurrence_id'] = _next_id()
        _set_person_id(result, resource)
        _set_visit_id(result, resource)
    return result


def transform_allergy_r5(resource):
    result = _call_r5(resource, 'AllergyMap')
    if result:
        result['observation_id'] = _next_id()
        _set_person_id(result, resource, ref_key='patient')
        _set_visit_id(result, resource)
    return result


def transform_immunization_r5(resource):
    result = _call_r5(resource, 'ImmunizationMap')
    if result:
        result['drug_exposure_id'] = _next_id()
        _set_person_id(result, resource, ref_key='patient')
        _set_visit_id(result, resource)
    return result


def transform_measurement_r5(resource):
    result = _call_r5(resource, 'MeasurementMap')
    if result:
        result['measurement_id'] = _next_id()
        _set_person_id(result, resource)
        _set_visit_id(result, resource)
    return result


def transform_observation_r5(resource):
    result = _call_r5(resource, 'ObservationMap')
    if result:
        result['observation_id'] = _next_id()
        _set_person_id(result, resource)
        _set_visit_id(result, resource)
    return result


def transform_vital_signs_r5(resource):
    result = _call_r5(resource, 'SimpleVitalSignsMap')
    if result:
        result['measurement_id'] = _next_id()
        _set_person_id(result, resource)
        _set_visit_id(result, resource)
    return result


def transform_medication_r5(resource):
    resource_type = resource.get('resourceType', '')
    if resource_type == 'MedicationRequest':
        result = _call_r5(resource, 'MedicationRequestMap')
    else:
        result = _call_r5(resource, 'MedicationStatementMap')
    if result:
        result['drug_exposure_id'] = _next_id()
        _set_person_id(result, resource)
        _set_visit_id(result, resource)
    return result


def transform_bp_panel_r5(resource):
    result = _call_r5(resource, 'BloodPressureVitalSignsMap')
    if result:
        result['measurement_id'] = _next_id()
        _set_person_id(result, resource)
        _set_visit_id(result, resource)
    return result


def transform_bp_systolic_r5(resource):
    result = _call_r5(resource, 'BloodPressureSystolicMap')
    if result:
        result['measurement_id'] = _next_id()
        _set_person_id(result, resource)
        _set_visit_id(result, resource)
    return result


def transform_bp_diastolic_r5(resource):
    result = _call_r5(resource, 'BloodPressureDiastolicMap')
    if result:
        result['measurement_id'] = _next_id()
        _set_person_id(result, resource)
        _set_visit_id(result, resource)
    return result
