"""
FHIR -> OMOP transforms via matchbox $transform.

Each function takes a FHIR resource dict and returns an OMOP dict,
or None if the resource should be suppressed.
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


def transform_encounter(resource):
    return _call(resource, 'EncounterVisitMap')


def transform_immunization(resource):
    return _call(resource, 'ImmunizationMap')


def transform_measurement(resource):
    return _call(resource, 'MeasurementMap')


def transform_observation(resource):
    return _call(resource, 'ObservationMap')


def transform_vital_signs(resource):
    return _call(resource, 'SimpleVitalSignsMap')


def transform_medication(resource):
    return _call(resource, 'MedicationMap')
