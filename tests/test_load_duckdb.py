"""
Unit tests for load_duckdb.py report generation.

Does not require a running matchbox server or DuckDB file.
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import load_duckdb


SAMPLE_RESULTS = [
    {'file': 'patient.json',   'map': 'PersonMap',    'table': 'person',               'status': 'OK'},
    {'file': 'condition.json', 'map': 'ConditionMap', 'table': 'condition_occurrence',  'status': 'OK'},
    {'file': 'procedure_not_done.json', 'map': 'ProcedureMap', 'table': 'procedure_occurrence', 'status': 'SUPPRESSED'},
]

SAMPLE_CSV_ROWS = {
    'person':               [{'person_id': 1, 'gender_concept_id': 8507},
                             {'person_id': 2, 'gender_concept_id': 8532}],
    'condition_occurrence': [{'condition_occurrence_id': 1, 'condition_concept_id': 320128}],
}


def _call_write_report(results, csv_rows=None):
    """Call write_report with file I/O mocked out; return the HTML string."""
    captured = {}
    mock_path = MagicMock()
    mock_path.write_text.side_effect = lambda text: captured.update({'html': text})
    with patch('load_duckdb.Path', return_value=mock_path):
        load_duckdb.write_report(results, csv_rows)
    return captured['html']


class TestWriteReportCsvSection:
    """write_report should embed CSV links as a column in the single transform table.

    Single-table design: one row per fixture file with an inline CSV download
    link and row count. No separate "Output Tables" section.
    """

    def test_WHEN_csv_rows_given_SHOULD_have_csv_column_header(self):
        html = _call_write_report(SAMPLE_RESULTS, SAMPLE_CSV_ROWS)
        assert '<th>CSV</th>' in html or '>CSV<' in html, (
            'Expected a CSV column header in the results table'
        )

    def test_WHEN_csv_rows_given_SHOULD_include_view_and_download_links_for_person_csv(self):
        html = _call_write_report(SAMPLE_RESULTS, SAMPLE_CSV_ROWS)
        assert 'csv/person.csv' in html, 'Expected href to csv/person.csv'
        assert 'download' in html, 'Expected a download attribute link'
        assert 'target="_blank"' in html, 'Expected a view (target=_blank) link'

    def test_WHEN_csv_rows_given_SHOULD_include_link_to_condition_occurrence_csv(self):
        html = _call_write_report(SAMPLE_RESULTS, SAMPLE_CSV_ROWS)
        assert 'csv/condition_occurrence.csv' in html, (
            'Expected href to csv/condition_occurrence.csv in the results table'
        )

    def test_WHEN_csv_rows_given_SHOULD_show_table_name_in_view_link_text(self):
        html = _call_write_report(SAMPLE_RESULTS, SAMPLE_CSV_ROWS)
        # The view link text (between > and </a>) must contain the filename
        assert '>person.csv' in html, (
            'Expected filename "person.csv" as visible link text in the view link, '
            'not just in an href attribute'
        )

    def test_WHEN_csv_rows_given_SHOULD_show_row_count_for_person(self):
        html = _call_write_report(SAMPLE_RESULTS, SAMPLE_CSV_ROWS)
        assert '2' in html, 'Expected row count 2 for person CSV link'

    def test_WHEN_csv_rows_given_SHOULD_show_row_count_for_condition_occurrence(self):
        html = _call_write_report(SAMPLE_RESULTS, SAMPLE_CSV_ROWS)
        assert '1' in html, 'Expected row count 1 for condition_occurrence CSV link'

    def test_WHEN_row_is_suppressed_SHOULD_not_have_csv_link_for_that_table(self):
        html = _call_write_report(SAMPLE_RESULTS, SAMPLE_CSV_ROWS)
        # procedure_occurrence is SUPPRESSED — no CSV was written for it
        assert 'csv/procedure_occurrence.csv' not in html, (
            'SUPPRESSED rows should not have a CSV link — no data was written'
        )

    def test_WHEN_csv_rows_is_none_SHOULD_not_crash(self):
        html = _call_write_report(SAMPLE_RESULTS, None)
        assert html is not None and len(html) > 0

    def test_WHEN_csv_rows_is_none_SHOULD_not_include_csv_links(self):
        html = _call_write_report(SAMPLE_RESULTS, None)
        assert 'csv/person.csv' not in html

    def test_WHEN_csv_rows_given_SHOULD_not_have_separate_output_tables_section(self):
        html = _call_write_report(SAMPLE_RESULTS, SAMPLE_CSV_ROWS)
        assert '<h2>Output Tables' not in html, (
            'Expected single-table design — no separate Output Tables section'
        )

    def test_WHEN_csv_rows_given_view_link_SHOULD_point_to_html_not_csv(self):
        html = _call_write_report(SAMPLE_RESULTS, SAMPLE_CSV_ROWS)
        assert 'csv/person.html' in html, (
            'View link should point to csv/person.html (HTML viewer), not the raw CSV'
        )

    def test_WHEN_csv_rows_given_download_link_SHOULD_point_to_csv(self):
        html = _call_write_report(SAMPLE_RESULTS, SAMPLE_CSV_ROWS)
        assert 'csv/person.csv' in html, (
            'Download link should still point to csv/person.csv'
        )


class TestWriteCsvs:
    """write_csvs should produce both a .csv file and a .html viewer page per table."""

    def test_WHEN_write_csvs_called_SHOULD_create_html_viewer_for_each_table(self):
        rows = {'person': [{'person_id': 1, 'gender_concept_id': 8507},
                            {'person_id': 2, 'gender_concept_id': 8532}]}
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(load_duckdb, 'CSV_DIR', Path(tmpdir)):
                load_duckdb.write_csvs(rows)
            viewer = Path(tmpdir) / 'person.html'
            assert viewer.exists(), 'Expected person.html viewer to be written alongside person.csv'

    def test_WHEN_write_csvs_called_html_viewer_SHOULD_contain_data_rows(self):
        rows = {'person': [{'person_id': 1, 'gender_concept_id': 8507},
                            {'person_id': 2, 'gender_concept_id': 8532}]}
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(load_duckdb, 'CSV_DIR', Path(tmpdir)):
                load_duckdb.write_csvs(rows)
            html = (Path(tmpdir) / 'person.html').read_text()
            assert '8507' in html, 'Expected gender_concept_id value in viewer HTML'
            assert '8532' in html

    def test_WHEN_write_csvs_called_html_viewer_SHOULD_have_column_headers(self):
        rows = {'person': [{'person_id': 1, 'gender_concept_id': 8507}]}
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(load_duckdb, 'CSV_DIR', Path(tmpdir)):
                load_duckdb.write_csvs(rows)
            html = (Path(tmpdir) / 'person.html').read_text()
            assert 'person_id' in html
            assert 'gender_concept_id' in html
