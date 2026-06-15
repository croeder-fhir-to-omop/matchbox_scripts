"""
Unit tests for transforms.py R5 support.

Tests that R5 transform functions use the R5 matchbox URL and R5 map names,
and that the medication R5 dispatch works without SkipResource.

Does not require a running matchbox server — all HTTP calls are mocked.
"""
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import transforms
import load_duckdb


# Minimal R5 FHIR resources for testing dispatch logic
MEDICATION_STATEMENT_R5 = {
    "resourceType": "MedicationStatement",
    "id": "test-r5",
    "status": "recorded",
    "medication": {
        "concept": {
            "coding": [{"system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": "1191"}]
        }
    },
    "subject": {"reference": "Patient/1"},
    "effectiveDateTime": "2020-03-15",
}

MEDICATION_REQUEST_R5 = {
    "resourceType": "MedicationRequest",
    "id": "test-r5-req",
    "status": "active",
    "intent": "order",
    "medication": {
        "concept": {
            "coding": [{"system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": "860975"}]
        }
    },
    "subject": {"reference": "Patient/1"},
    "authoredOn": "2020-03-15",
}

PATIENT_R5 = {
    "resourceType": "Patient",
    "id": "1",
    "gender": "male",
    "birthDate": "1990-01-01",
}


def _make_mock_response(result_dict):
    mock = MagicMock()
    mock.json.return_value = result_dict
    mock.raise_for_status = MagicMock()
    return mock


class TestCallR5UsesR5Url:
    """_call_r5 should send requests to the R5 matchbox URL (port 8082 by default)."""

    def test_WHEN_call_r5_invoked_SHOULD_use_r5_base_url(self):
        drug_result = {"resourceType": "DrugExposure", "drug_exposure_id": 1, "drug_concept_id": 99}
        with patch('transforms.requests.post', return_value=_make_mock_response(drug_result)) as mock_post:
            transforms._call_r5(MEDICATION_STATEMENT_R5, 'MedicationStatementMapR5')
        url = mock_post.call_args[0][0]
        assert '8082' in url or 'matchbox-r5' in url, (
            f'Expected R5 matchbox URL (port 8082 or matchbox-r5), got {url}'
        )

    def test_WHEN_matchbox_r5_url_env_set_SHOULD_use_env_url(self):
        drug_result = {"resourceType": "DrugExposure", "drug_exposure_id": 1}
        with patch.dict(os.environ, {'MATCHBOX_R5_URL': 'http://custom-r5:9999'}):
            # Force re-initialization of cached URL
            transforms._BASE_URL_R5 = None
            with patch('transforms.requests.post', return_value=_make_mock_response(drug_result)) as mock_post:
                transforms._call_r5(MEDICATION_STATEMENT_R5, 'MedicationStatementMapR5')
            url = mock_post.call_args[0][0]
            assert 'custom-r5:9999' in url, f'Expected custom R5 URL in {url}'
        transforms._BASE_URL_R5 = None


class TestTransformMedicationR5NoSkip:
    """transform_medication_r5 must NOT raise SkipResource for R5 medication.concept resources."""

    def test_WHEN_r5_medication_statement_SHOULD_not_raise_skip_resource(self):
        drug_result = {
            "resourceType": "DrugExposure",
            "drug_exposure_id": 1,
            "drug_concept_id": 99,
            "drug_source_value": "1191",
        }
        with patch('transforms._call_r5', return_value=drug_result):
            try:
                result = transforms.transform_medication_r5(MEDICATION_STATEMENT_R5)
            except transforms.SkipResource:
                assert False, 'transform_medication_r5 raised SkipResource for R5 medication.concept'
        assert result is not None

    def test_WHEN_r5_medication_request_SHOULD_not_raise_skip_resource(self):
        drug_result = {
            "resourceType": "DrugExposure",
            "drug_exposure_id": 1,
            "drug_concept_id": 99,
        }
        with patch('transforms._call_r5', return_value=drug_result):
            try:
                result = transforms.transform_medication_r5(MEDICATION_REQUEST_R5)
            except transforms.SkipResource:
                assert False, 'transform_medication_r5 raised SkipResource for R5 MedicationRequest'
        assert result is not None

    def test_WHEN_r5_medication_statement_SHOULD_call_medication_statement_map_r5(self):
        drug_result = {"resourceType": "DrugExposure", "drug_exposure_id": 1, "drug_concept_id": 99}
        with patch('transforms._call_r5', return_value=drug_result) as mock_call:
            transforms.transform_medication_r5(MEDICATION_STATEMENT_R5)
        map_name = mock_call.call_args[0][1]
        assert map_name == 'MedicationStatementMapR5', (
            f'Expected MedicationStatementMapR5, got {map_name}'
        )

    def test_WHEN_r5_medication_request_SHOULD_call_medication_request_map_r5(self):
        drug_result = {"resourceType": "DrugExposure", "drug_exposure_id": 1, "drug_concept_id": 99}
        with patch('transforms._call_r5', return_value=drug_result) as mock_call:
            transforms.transform_medication_r5(MEDICATION_REQUEST_R5)
        map_name = mock_call.call_args[0][1]
        assert map_name == 'MedicationRequestMapR5', (
            f'Expected MedicationRequestMapR5, got {map_name}'
        )


class TestFixtureTransformsR5:
    """load_duckdb.FIXTURE_TRANSFORMS_R5 should exist and use R5 map names."""

    def test_WHEN_fixture_transforms_r5_exists_SHOULD_have_entries(self):
        assert hasattr(load_duckdb, 'FIXTURE_TRANSFORMS_R5'), (
            'load_duckdb missing FIXTURE_TRANSFORMS_R5'
        )
        assert len(load_duckdb.FIXTURE_TRANSFORMS_R5) > 0

    def test_WHEN_fixture_transforms_r5_SHOULD_contain_r5_map_names(self):
        map_names = [entry[3] for entry in load_duckdb.FIXTURE_TRANSFORMS_R5]
        r5_maps = [m for m in map_names if m.endswith('R5')]
        assert len(r5_maps) > 0, f'No R5 map names in FIXTURE_TRANSFORMS_R5: {map_names}'

    def test_WHEN_fixture_transforms_r5_SHOULD_include_medication_statement_map_r5(self):
        map_names = [entry[3] for entry in load_duckdb.FIXTURE_TRANSFORMS_R5]
        assert 'MedicationStatementMapR5' in map_names

    def test_WHEN_fixture_transforms_r5_SHOULD_include_condition_map_r5(self):
        map_names = [entry[3] for entry in load_duckdb.FIXTURE_TRANSFORMS_R5]
        assert 'ConditionMapR5' in map_names

    def test_WHEN_fixture_transforms_r5_SHOULD_include_encounter_visit_map_r5(self):
        map_names = [entry[3] for entry in load_duckdb.FIXTURE_TRANSFORMS_R5]
        assert 'EncounterVisitMapR5' in map_names


class TestLoadDuckdbFhirVersionArg:
    """load_duckdb should accept --fhir-version r5 and select FIXTURE_TRANSFORMS_R5."""

    def test_WHEN_fhir_version_r5_arg_SHOULD_parse_correctly(self):
        args = load_duckdb.parse_args(['--fhir-version', 'r5'])
        assert args.fhir_version == 'r5'

    def test_WHEN_no_fhir_version_arg_SHOULD_default_to_r4(self):
        args = load_duckdb.parse_args([])
        assert args.fhir_version == 'r4'

    def test_WHEN_fhir_version_r5_SHOULD_use_r5_fixture_transforms(self):
        selected = load_duckdb.select_fixture_transforms('r5')
        map_names = [entry[3] for entry in selected]
        r5_maps = [m for m in map_names if m.endswith('R5')]
        assert len(r5_maps) > 0, 'R5 version should select R5 fixture transforms'

    def test_WHEN_fhir_version_r4_SHOULD_use_r4_fixture_transforms(self):
        selected = load_duckdb.select_fixture_transforms('r4')
        map_names = [entry[3] for entry in selected]
        r5_maps = [m for m in map_names if m.endswith('R5')]
        assert len(r5_maps) == 0, 'R4 version should not include R5 map names'
