"""
Unit tests for build.py utilities.

Does not require a running matchbox server, Docker, or DuckDB.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from build import _analyze_report


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
