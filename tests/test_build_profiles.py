"""
Unit tests for build.py utilities.

Does not require a running matchbox server, Docker, or DuckDB.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from build_profiles import _analyze_report, parse_args, fixture_dirs


def test_WHEN_report_has_legend_table_SHOULD_not_count_legend_rows_as_errors(tmp_path):
    html = '''<!DOCTYPE html><html><body>
    <div class="legend"><table>
      <tr><td>ERROR</td><td>Critical DB error description</td></tr>
      <tr><td>WARN</td><td>Unexpected failure description</td></tr>
    </table></div>
    <table>
      <tr><th>File</th><th>Map</th><th>Table</th><th>Status</th><th>CSV</th><th>Root</th></tr>
      <tr><td>patient.json</td><td>PersonMap</td><td>person</td><td>OK</td><td></td><td></td></tr>
    </table>
    </body></html>'''
    p = tmp_path / 'report.html'
    p.write_text(html)
    counts = _analyze_report(p)
    assert counts.get('ERROR', 0) == 0
    assert counts.get('WARN', 0) == 0
    assert counts.get('OK', 0) == 1


# ---------------------------------------------------------------------------
# --version flag tests
# ---------------------------------------------------------------------------

def test_WHEN_no_version_flag_SHOULD_default_to_r4():
    args = parse_args([])
    assert args.fhir_version == 'r4'
    assert args.ig_version == '1.0.1'


def test_WHEN_version_r5_SHOULD_parse_correctly():
    args = parse_args(['--fhir-version', 'r5'])
    assert args.fhir_version == 'r5'


def test_WHEN_version_r4_SHOULD_parse_correctly():
    args = parse_args(['--fhir-version', 'r4'])
    assert args.fhir_version == 'r4'


def test_WHEN_version_r4_fixture_dirs_SHOULD_use_r4_directories():
    dirs = fixture_dirs('r4')
    assert dirs[0] == 'test_files_r4'
    assert dirs[1] == 'sample_fixtures_r4'


def test_WHEN_version_r5_fixture_dirs_SHOULD_use_r5_directories():
    dirs = fixture_dirs('r5')
    assert dirs[0] == 'test_files_r5'
    assert dirs[1] == 'sample_fixtures_r5'


def test_WHEN_steps_provided_SHOULD_parse_step_names():
    args = parse_args(['etl', 'test'])
    assert args.steps == ['etl', 'test']


def test_WHEN_version_and_steps_SHOULD_parse_both():
    args = parse_args(['--fhir-version', 'r5', '--ig-version', '1.0.0', 'etl'])
    assert args.fhir_version == 'r5'
    assert args.ig_version == '1.0.0'
    assert args.steps == ['etl']


def test_WHEN_report_has_only_data_rows_SHOULD_count_them_correctly(tmp_path):
    html = '''<!DOCTYPE html><html><body>
    <table>
      <tr><th>File</th><th>Map</th><th>Table</th><th>Status</th><th>CSV</th><th>Root</th></tr>
      <tr><td>patient.json</td><td>PersonMap</td><td>person</td><td>OK</td><td></td><td></td></tr>
      <tr><td>condition.json</td><td>ConditionMap</td><td>condition_occurrence</td><td>WARN</td><td></td><td>FK violation</td></tr>
      <tr><td>procedure.json</td><td>ProcedureMap</td><td>procedure_occurrence</td><td>ERROR</td><td></td><td>PK conflict</td></tr>
    </table>
    </body></html>'''
    p = tmp_path / 'report.html'
    p.write_text(html)
    counts = _analyze_report(p)
    assert counts.get('OK', 0) == 1
    assert counts.get('WARN', 0) == 1
    assert counts.get('ERROR', 0) == 1
