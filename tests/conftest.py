"""
Pytest session hooks — capture test failures and matchbox Echidna error lines,
then write a combined HTML report alongside the ETL report (OMOP_DB_PATH directory).
"""
import html
import os
import subprocess
from pathlib import Path

_failed_tests: list[dict] = []

DQD_DIR = Path(__file__).parent.parent.parent / 'dqd_docker'


def pytest_runtest_logreport(report):
    if report.failed and report.when == 'call':
        _failed_tests.append({
            'nodeid': report.nodeid,
            'message': str(report.longrepr),
        })


def pytest_sessionfinish(session, exitstatus):
    _write_report()


def _matchbox_echidna_lines() -> list[str]:
    try:
        result = subprocess.run(
            ['docker', 'compose', 'logs', 'matchbox', '--no-color', '--tail=2000'],
            capture_output=True, text=True, cwd=str(DQD_DIR), timeout=15,
        )
        return [
            line.strip()
            for line in result.stdout.splitlines()
            if any(kw in line for kw in (
                'translate failed', 'Terminology server', '429', 'NullPointer',
                'InvocationTargetException', 'null code',
            ))
        ]
    except Exception:
        return []


def _write_report():
    db_path = os.environ.get('OMOP_DB_PATH', '/omop/omop.ddb')
    report_path = Path(db_path).parent / 'test_failures.html'

    echidna_lines = _matchbox_echidna_lines()

    test_rows = ''.join(
        f'<tr>'
        f'<td style="white-space:nowrap">{html.escape(f["nodeid"])}</td>'
        f'<td><pre style="white-space:pre-wrap;font-size:0.75em">{html.escape(f["message"][:600])}</pre></td>'
        f'</tr>\n'
        for f in _failed_tests
    )

    log_rows = ''.join(
        f'<tr><td><code style="font-size:0.8em">{html.escape(line)}</code></td></tr>\n'
        for line in echidna_lines
    )

    content = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Echidna / Test Failures</title>
<style>
  body{{font-family:sans-serif;margin:1em 2em}}
  h2{{margin-top:1.5em}}
  table{{border-collapse:collapse;width:100%}}
  td,th{{border:1px solid #ccc;padding:6px;vertical-align:top}}
  th{{background:#f0f0f0}}
  pre{{margin:0}}
</style>
</head><body>
<h1>Echidna / Test Failure Report</h1>

<h2>Test Failures ({len(_failed_tests)})</h2>
{'<p style="color:green">All tests passed.</p>' if not _failed_tests else
 f'<table><tr><th>Test</th><th>Failure</th></tr>{test_rows}</table>'}

<h2>Matchbox Echidna Error Log ({len(echidna_lines)} lines)</h2>
{'<p style="color:green">No Echidna errors found in matchbox logs.</p>' if not echidna_lines else
 f'<table>{log_rows}</table>'}

</body></html>"""

    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(content)
        print(f'\nEchidna/test failure report: {report_path}')
    except Exception as e:
        print(f'Could not write test failure report to {report_path}: {e}')
