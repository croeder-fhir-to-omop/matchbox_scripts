"""
FHIR -> OMOP transforms via matchbox $transform.

Each function takes a FHIR resource dict and returns an OMOP dict,
None if the resource should be suppressed, or raises SkipResource if
the resource is explicitly incompatible (shown as SKIP in the report).
"""

import os
import requests

_BASE_URL = None

def _base_url():
    global _BASE_URL
    if _BASE_URL is None:
        _BASE_URL = os.environ.get('MATCHBOX_URL', 'http://matchbox:8080') + '/matchboxv3/fhir'
    return _BASE_URL

_HEADERS = {
    'Content-Type': 'application/fhir+json',
    'Accept': 'application/fhir+json',
}

_IG = 'http://hl7.org/fhir/uv/omop/StructureMap'


class SkipResource(Exception):
    """Raised when a fixture is explicitly incompatible with the current server configuration."""


def _call(resource, map_name):
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


def transform_condition(resource):
    # what is this 'refuted' business? TODO
    ver_status = (
        resource.get('verificationStatus', {})
        .get('coding', [{}])[0]
        .get('code')
    )
    if ver_status == 'refuted':
        return None
    return _call(resource, 'ConditionMap')


def transform_patient(resource):
    return _call(resource, 'PersonMap')


def transform_procedure(resource):
    if resource.get('status') == 'not-done':
        return None
    return _call(resource, 'ProcedureMap')


def transform_allergy(resource):
    return _call(resource, 'AllergyMap')


def transform_allergy_server(resource):
    return _call(resource, 'AllergyMapServer')


def transform_encounter(resource):
    return _call(resource, 'EncounterVisitMap')


def transform_encounter_server(resource):
    return _call(resource, 'EncounterVisitMapServer')


def transform_immunization(resource):
    return _call(resource, 'ImmunizationMap')


def transform_measurement(resource):
    return _call(resource, 'MeasurementMap')


def transform_observation(resource):
    return _call(resource, 'ObservationMap')


def transform_vital_signs(resource):
    return _call(resource, 'SimpleVitalSignsMap')


def _is_r5_medication(resource):
    # R5 MedicationStatement uses medication.concept (CodeableReference);
    # R4 uses medicationCodeableConcept / medicationReference (choice type).
    # Suppress R5 fixtures — matchbox runs FHIR R4 (see fhir-omop-ig issue for R4/R5 compat).
    med = resource.get('medication', {})
    return isinstance(med, dict) and 'concept' in med


def transform_medication(resource):
    if _is_r5_medication(resource):
        raise SkipResource('R5 MedicationStatement (medication.concept) not supported by R4 server')
    return _call(resource, 'MedicationMap')


def transform_medication_server(resource):
    if _is_r5_medication(resource):
        raise SkipResource('R5 MedicationStatement (medication.concept) not supported by R4 server')
    return _call(resource, 'MedicationMapServer')
