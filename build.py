#!/usr/bin/env python3
"""
Build pipeline: IG → matchbox JAR → Docker images → restart → tests → release.

Usage:
  python3 build.py                            # full pipeline (ig docker enchilada restart test)
  python3 build.py mvn                        # rebuild matchbox JAR only (skips tests)
  python3 build.py ig                         # rebuild IG only
  python3 build.py docker                     # rebuild matchbox Docker image only
  python3 build.py enchilada                  # rebuild enchilada Docker image only
  python3 build.py restart                    # restart dqd_docker (wipes matchbox-db)
  python3 build.py etl                        # re-run ETL in container; analyze etl_report.html
  python3 build.py test                       # run matchbox_scripts integration tests
  python3 build.py release                    # build and push both images to Docker Hub
  python3 build.py mvn ig release             # full release with Java + IG rebuild
  python3 build.py --version r5 etl           # run ETL with R5 fixtures
  python3 build.py --version r5 docker restart etl  # R5 stack
"""

import argparse
import platform
import subprocess
import sys
import shutil
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

REPO_ROOT       = Path(__file__).parent.parent
IG_DIR          = REPO_ROOT / 'fhir-omop-ig'
MATCHBOX_DIR    = REPO_ROOT / 'matchbox_docker'
DQD_DIR         = REPO_ROOT / 'dqd_docker'
ENCHILADA_DIR   = REPO_ROOT / 'enchilada'
SCRIPTS_DIR   = Path(__file__).parent
PACKAGE_SRC   = IG_DIR / 'output' / 'package.tgz'
PACKAGE_DST   = MATCHBOX_DIR / 'igs' / 'hl7.fhir.uv.omop-1.0.1.tgz'
MATCHBOX_SRC  = REPO_ROOT / 'matchbox' / 'matchbox-server'
PYTEST        = [SCRIPTS_DIR / 'env' / 'bin' / 'python3', '-m', 'pytest']
ETL_REPORT    = SCRIPTS_DIR / 'etl_report.html'


def _dqd_container() -> str:
    return 'dqd_docker-dqd-r5-1' if _FHIR_VERSION == 'r5' else 'dqd_docker-dqd-1'


def _matchbox_image() -> str:
    return f'croeder/matchbox:{_FHIR_VERSION}'


def _matchbox_health_url() -> str:
    port = 8082 if _FHIR_VERSION == 'r5' else 8080
    return f'http://localhost:{port}/matchboxv3/actuator/health'

STEPS = ['mvn', 'ig', 'docker', 'enchilada', 'restart', 'stop', 'etl', 'test', 'release']
DEFAULT_STEPS = ['ig', 'docker', 'enchilada', 'restart', 'test']

# Version-controlled globals — overridden by --version flag in main()
_FHIR_VERSION = 'r4'


def fixture_dirs(version: str) -> tuple[str, str]:
    """Return (test_fixtures_dir, sample_fixtures_dir) for the given FHIR version."""
    return {
        'r4': ('test_files', 'sample_fixtures'),
        'r5': ('test_files_r5', 'sample_fixtures_r5'),
    }[version]


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='FHIR→OMOP build pipeline')
    parser.add_argument('--version', choices=['r4', 'r5'], default='r4',
                        help='FHIR version to target (default: r4)')
    parser.add_argument('steps', nargs='*',
                        help=f'Build steps to run (default: {DEFAULT_STEPS})')
    return parser.parse_args(argv)


def run(cmd, cwd=None, check=True):
    print(f'\n>>> {" ".join(str(c) for c in cmd)}')
    result = subprocess.run([str(c) for c in cmd], cwd=str(cwd) if cwd else None, check=check)
    return result.returncode


def step_mvn():
    print('\n=== Building matchbox JAR (mvn package -DskipTests) ===')
    matchbox_root = REPO_ROOT / 'matchbox'
    run(['mvn', 'package', '-DskipTests'], cwd=matchbox_root)
    print('matchbox JAR built.')


def step_ig():
    print('\n=== Building fhir-omop-ig ===')
    run([
        'docker', 'run', '--rm',
        '-v', f'{IG_DIR}:/workspace',
        '-w', '/workspace',
        'ghcr.io/bonfhir/ig-toolbox:latest',
        'java', '-jar', 'input-cache/publisher.jar', '-ig', '.', '-tx', 'https://tx.fhir.org',
    ])
    print(f'\n>>> cp {PACKAGE_SRC} {PACKAGE_DST}')
    shutil.copy2(PACKAGE_SRC, PACKAGE_DST)
    print('IG package copied.')


def _fix_null_params(obj):
    """Replace null entries in StructureMap target parameter arrays with {"valueString": ""}.

    The R4 IG publisher serializes empty-string FML translate() parameters as JSON null,
    which the HAPI FHIR R4 parser rejects.  Replacing null with {"valueString": ""} restores
    the intended empty-string semantics and keeps the JSON parseable.
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == 'parameter' and isinstance(v, list):
                obj[k] = [{"valueString": ""} if item is None else item for item in v]
            else:
                _fix_null_params(v)
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict):
                _fix_null_params(item)


def _strip_package_deps(tgz_path: Path) -> None:
    """Repack a FHIR package tgz with an empty dependencies map.

    HAPI FHIR fetches transitive dependencies from the network when installing
    a package.  For packages we bundle locally, we clear the dependency list so
    HAPI never makes those network calls — the bundles themselves are all we need.

    Also fixes null StructureMap parameters produced by the R4 IG publisher (see
    _fix_null_params).
    """
    import json, tarfile, io
    print(f'  Stripping dependencies from {tgz_path.name}', flush=True)
    members = []
    contents = {}
    with tarfile.open(tgz_path, 'r:gz') as tf:
        for member in tf.getmembers():
            data = tf.extractfile(member)
            contents[member.name] = (member, data.read() if data else b'')
    pkg_key = next(k for k in contents if k.endswith('package.json'))
    member, raw = contents[pkg_key]
    pkg = json.loads(raw)
    pkg['dependencies'] = {}
    contents[pkg_key] = (member, json.dumps(pkg, indent=2).encode())
    for name, (member, data) in list(contents.items()):
        if 'StructureMap-' in name and name.endswith('.json'):
            sm = json.loads(data)
            _fix_null_params(sm)
            contents[name] = (member, json.dumps(sm, separators=(',', ':')).encode())
    with tarfile.open(tgz_path, 'w:gz') as tf:
        for name, (member, data) in contents.items():
            member.size = len(data)
            tf.addfile(member, io.BytesIO(data))


def step_docker():
    svc = 'matchbox-r5' if _FHIR_VERSION == 'r5' else 'matchbox'
    print(f'\n=== Building {_matchbox_image()} Docker image ===')
    for pkg in (MATCHBOX_DIR / 'igs').glob('*.tgz'):
        _strip_package_deps(pkg)
    run(['docker', 'compose', '-f', 'docker-compose.build.yml', 'build', svc], cwd=MATCHBOX_DIR)


def step_enchilada():
    print('\n=== Building enchilada Docker image ===')
    run(['docker', 'compose', 'build', 'enchilada'], cwd=DQD_DIR)


def step_release():
    print('\n=== Building and pushing all release images ===')
    print('--- matchbox (r4) ---')
    for pkg in (MATCHBOX_DIR / 'igs').glob('*.tgz'):
        _strip_package_deps(pkg)
    run(['docker', 'compose', '-f', 'docker-compose.build.yml', 'build', 'matchbox'], cwd=MATCHBOX_DIR)
    run(['docker', 'compose', '-f', 'docker-compose.build.yml', 'push', 'matchbox'], cwd=MATCHBOX_DIR)
    print('--- matchbox (r5) ---')
    run(['docker', 'compose', '-f', 'docker-compose.build.yml', 'build', 'matchbox-r5'], cwd=MATCHBOX_DIR)
    run(['docker', 'compose', '-f', 'docker-compose.build.yml', 'push', 'matchbox-r5'], cwd=MATCHBOX_DIR)
    print('--- dqd ---')
    run(['docker', 'compose', '-f', 'docker-compose.build.yml', 'build'], cwd=DQD_DIR)
    run(['docker', 'compose', '-f', 'docker-compose.build.yml', 'push'], cwd=DQD_DIR)


def step_restart():
    profile = _FHIR_VERSION
    print(f'\n=== Restarting dqd_docker --profile {profile} (down -v to wipe matchbox-db, force IG reload) ===')
    run(['docker', 'compose', '--profile', profile, 'down', '-v'], cwd=DQD_DIR, check=False)
    run(['docker', 'compose', '--profile', profile, 'up', '-d'], cwd=DQD_DIR)
    health_url = _matchbox_health_url()
    print(f'Waiting for matchbox to become healthy ({health_url})...')
    run([
        'bash', '-c',
        f'until curl -sf {health_url} | grep -q \'"status":"UP"\'; do sleep 5; done && echo "Matchbox is up"',
    ])
    step_etl()


def step_stop():
    profile = _FHIR_VERSION
    print(f'\n=== Stopping dqd_docker --profile {profile} containers (frees memory) ===')
    run(['docker', 'compose', '--profile', profile, 'stop'], cwd=DQD_DIR, check=False)


ETL_REPORT_SAMPLES = SCRIPTS_DIR / 'etl_report_samples.html'

def step_etl():
    print('\n=== Re-running ETL in dqd container ===')
    test_dir, sample_dir = fixture_dirs(_FHIR_VERSION)
    # REPORT_PATH = dirname(DB_PATH)/etl_report.html, so use subdirs to get separate reports.
    runs = [
        (test_dir,   '/tmp/etl_test/omop.ddb',    '/tmp/etl_test_csv',    '/tmp/etl_test/etl_report.html',    ETL_REPORT),
        (sample_dir, '/tmp/etl_samples/omop.ddb', '/tmp/etl_samples_csv', '/tmp/etl_samples/etl_report.html', ETL_REPORT_SAMPLES),
    ]
    for fixtures_dir, tmp_db, tmp_csv, tmp_report, local_report in runs:
        print(f'\n--- {fixtures_dir} ---')
        container = _dqd_container()
        run(['docker', 'exec', container,
             'bash', '-c',
             f'mkdir -p $(dirname {tmp_db}) && rm -f {tmp_db} && '
             f'OMOP_DB_PATH={tmp_db} OMOP_CSV_DIR={tmp_csv} '
             f'python3 /etl/load_duckdb.py --fixtures-dir {fixtures_dir}'])

        print(f'\n>>> docker cp {container}:{tmp_report} {local_report}')
        subprocess.run(['docker', 'cp', f'{container}:{tmp_report}', str(local_report)], check=True)

        # Also publish each report to /omop so it's visible at localhost:8088.
        omop_dest = '/omop/' + local_report.name
        run(['docker', 'exec', container, 'cp', tmp_report, omop_dest])

        print(f'\n--- Report: {local_report.name} ---')
        _analyze_report(local_report)

    # Write an index page at localhost:8088 linking to both reports.
    index_path = SCRIPTS_DIR / 'etl_index.html'
    index_path.write_text(
        '<!DOCTYPE html>\n'
        '<html><head><title>ETL Reports</title>\n'
        '<style>body{font-family:sans-serif;max-width:600px;margin:2rem auto;}'
        'a{display:block;margin:.5rem 0;}</style>\n'
        '</head><body>\n'
        '<h2>FHIR→OMOP ETL Reports</h2>\n'
        '<a href="etl_report.html">etl_report.html — test_files fixtures</a>\n'
        '<a href="etl_report_samples.html">etl_report_samples.html — sample_fixtures</a>\n'
        '</body></html>\n'
    )
    subprocess.run(['docker', 'cp', str(index_path), f'{_dqd_container()}:/omop/index.html'], check=True)

    if platform.system() == 'Darwin':
        subprocess.run(['open', str(ETL_REPORT)])
        subprocess.run(['open', str(ETL_REPORT_SAMPLES)])


def _analyze_report(path):
    STATUSES = {'OK', 'WARN', 'SUPPRESSED', 'SKIP', 'ERROR', 'XFAIL', 'XPASS'}

    class _RowParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.in_td = False
            self.current_row = []
            self.rows = []
        def handle_starttag(self, tag, attrs):
            if tag == 'tr':
                self.current_row = []
            if tag == 'td':
                self.in_td = True
        def handle_endtag(self, tag):
            if tag == 'td':
                self.in_td = False
            if tag == 'tr' and self.current_row:
                self.rows.append(self.current_row[:])
        def handle_data(self, data):
            if self.in_td:
                d = data.strip()
                if d:
                    self.current_row.append(d)

    p = _RowParser()
    p.feed(path.read_text())

    counts = {}
    issues = []
    for row in p.rows:
        if len(row) < 4:        # legend rows have 2 cells; data rows have 4–6
            continue
        status = next((c for c in row if c in STATUSES), None)
        if not status:
            continue
        counts[status] = counts.get(status, 0) + 1
        if status not in ('OK', 'SUPPRESSED', 'XFAIL'):
            fname  = row[0] if row else '?'
            map_nm = row[1] if len(row) > 1 else '?'
            detail = row[-1] if len(row) > 4 else ''
            issues.append((status, fname, map_nm, detail[:120]))

    print('\n--- ETL Report Summary ---')
    for s in ('OK', 'WARN', 'XFAIL', 'XPASS', 'SUPPRESSED', 'SKIP', 'ERROR'):
        if s in counts:
            print(f'  {s}: {counts[s]}')
    if issues:
        print('\n  Issues:')
        for status, fname, map_nm, detail in issues:
            print(f'    [{status}] {fname}  ({map_nm}): {detail}')
    else:
        print('\n  No issues — all transforms OK or SUPPRESSED.')
    print()
    return counts


def step_test():
    print('\n=== Running integration tests ===')
    run([*PYTEST, 'tests/test_fml_transforms.py', '-v'], cwd=SCRIPTS_DIR)


STEP_FNS = {
    'mvn':       step_mvn,
    'ig':        step_ig,
    'docker':    step_docker,
    'enchilada': step_enchilada,
    'restart':   step_restart,
    'stop':      step_stop,
    'etl':       step_etl,
    'test':      step_test,
    'release':   step_release,
}


# ---------------------------------------------------------------------------
# Staleness checks and auto-prerequisites
# ---------------------------------------------------------------------------

def _image_mtime(image):
    """Creation timestamp of a local Docker image as Unix float; 0.0 if absent."""
    r = subprocess.run(
        ['docker', 'inspect', '--format', '{{.Created}}', image],
        capture_output=True, text=True,
    )
    if r.returncode != 0 or not r.stdout.strip():
        return 0.0
    try:
        ts = r.stdout.strip().rstrip('Z').split('.')[0]
        return datetime.fromisoformat(ts).replace(tzinfo=timezone.utc).timestamp()
    except Exception:
        return 0.0


def _max_mtime(paths):
    """Latest mtime of any regular file under the given paths (files or dirs).
    Skips .git directories and editor backup files."""
    latest = 0.0
    for p in paths:
        p = Path(p)
        if p.is_file():
            latest = max(latest, p.stat().st_mtime)
        elif p.is_dir():
            for f in p.rglob('*'):
                if not f.is_file():
                    continue
                if any(part.startswith('.') for part in f.parts):
                    continue
                if f.suffix == '~' or f.name.endswith('.pyc'):
                    continue
                latest = max(latest, f.stat().st_mtime)
    return latest


def _ig_stale():
    """True if fhir-omop-ig/input/ is newer than the copied IG package."""
    if not PACKAGE_DST.exists():
        return True
    return _max_mtime([IG_DIR / 'input']) > PACKAGE_DST.stat().st_mtime


def _matchbox_image_stale():
    """True if matchbox_docker/ sources are newer than the local matchbox image."""
    return _max_mtime([MATCHBOX_DIR]) > _image_mtime(_matchbox_image())


def _enchilada_image_stale():
    """True if enchilada sources or supplemental TSV files are newer than the enchilada image."""
    sources = [
        ENCHILADA_DIR,
        SCRIPTS_DIR / 'concept_extra.tsv',
        SCRIPTS_DIR / 'concept_relationship_extra.tsv',
        SCRIPTS_DIR / 'vocabulary_extra.tsv',
    ]
    return _max_mtime(sources) > _image_mtime('dqd_docker-enchilada:latest')


def _dqd_image_stale():
    """True if ETL sources are newer than the local dqd image."""
    test_dir, sample_dir = fixture_dirs(_FHIR_VERSION)
    test_path   = SCRIPTS_DIR / test_dir
    sample_path = SCRIPTS_DIR / sample_dir
    sources = (
        [
            SCRIPTS_DIR / 'transforms.py',
            SCRIPTS_DIR / 'load_duckdb.py',
            SCRIPTS_DIR / 'omop_to_csv.py',
            SCRIPTS_DIR / 'ddl',
            DQD_DIR,
        ]
        + (list(test_path.glob('*.json'))   if test_path.exists()   else [])
        + (list(sample_path.glob('*.json')) if sample_path.exists() else [])
    )
    return _max_mtime(sources) > _image_mtime('croeder/dqd:latest')


def _rebuild_and_reload_dqd():
    """Build dqd image locally (no push) and recreate the dqd container."""
    dqd_svc = 'dqd-r5' if _FHIR_VERSION == 'r5' else 'dqd'
    print('\n=== [auto] dqd sources changed — rebuilding image (local only) ===')
    run(['docker', 'compose', '-f', 'docker-compose.build.yml', 'build'], cwd=DQD_DIR)
    print('\n=== [auto] Reloading dqd container ===')
    # --no-deps: don't touch matchbox; recreates dqd only if image changed
    run(['docker', 'compose', '--profile', _FHIR_VERSION, 'up', '-d', '--no-deps', dqd_svc], cwd=DQD_DIR)


# Each entry: (human label, stale_check_fn, auto_fix_fn)
STEP_PREREQS = {
    'docker':    [('fhir-omop-ig package',      _ig_stale,              step_ig)],
    'restart':   [('croeder/matchbox image',    _matchbox_image_stale,  step_docker),
                  ('dqd_docker-enchilada image', _enchilada_image_stale, step_enchilada)],
    'test':      [('croeder/matchbox image',    _matchbox_image_stale,  step_docker),
                  ('dqd_docker-enchilada image', _enchilada_image_stale, step_enchilada)],
    'etl':       [('croeder/dqd image',         _dqd_image_stale,       _rebuild_and_reload_dqd)],
    'release':   [('fhir-omop-ig package',      _ig_stale,              step_ig)],
}


def _run_prereqs(step):
    for label, is_stale, fix_fn in STEP_PREREQS.get(step, []):
        if is_stale():
            print(f'\n  [stale] {label} — auto-running prerequisite')
            fix_fn()


def main():
    global _FHIR_VERSION
    parsed = parse_args()
    _FHIR_VERSION = parsed.version
    steps = parsed.steps or DEFAULT_STEPS
    unknown = [s for s in steps if s not in STEP_FNS]
    if unknown:
        print(f'Unknown steps: {unknown}. Valid: {STEPS}')
        sys.exit(1)
    if _FHIR_VERSION != 'r4':
        print(f'\n=== FHIR version: {_FHIR_VERSION.upper()} ===')
    for step in steps:
        _run_prereqs(step)
        STEP_FNS[step]()
    print('\n=== Done ===')


if __name__ == '__main__':
    main()
