#!/usr/bin/env python3
"""
Simple FHIR R4 / IG 1.0.0 build pipeline.

Granular steps:
  python3 build_r4.py                                    # full pipeline
  python3 build_r4.py ig                                 # rebuild IG only
  python3 build_r4.py mvn                                # rebuild matchbox JAR only
  python3 build_r4.py docker                             # rebuild matchbox Docker image only
  python3 build_r4.py enchilada                          # rebuild enchilada Docker image only
  python3 build_r4.py restart                            # restart the r4-1.0.0 stack (wipes matchbox-db)
  python3 build_r4.py stop                               # stop the r4-1.0.0 containers
  python3 build_r4.py etl                                # re-run ETL; open reports at localhost
  python3 build_r4.py test                               # run integration tests (see note below)
  python3 build_r4.py release                            # build and push images to Docker Hub
  python3 build_r4.py ig docker restart etl              # run specific steps in sequence

Note on 'test': there is no R4 FML transform test suite yet
(see matchbox_scripts#8). This step currently prints a notice and exits
cleanly rather than running the R5 suite against the r4 server.
"""

import os
import platform
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
import argparse

REPO_ROOT     = Path(__file__).parent.parent
IG_DIR        = REPO_ROOT / 'fhir-omop-ig'
MATCHBOX_DIR  = REPO_ROOT / 'matchbox_docker'
DQD_DIR       = REPO_ROOT / 'dqd_docker'
ENCHILADA_DIR = REPO_ROOT / 'enchilada'
SCRIPTS_DIR   = Path(__file__).parent
PACKAGE_SRC   = IG_DIR / 'output' / 'package.tgz'
PACKAGE_DST   = MATCHBOX_DIR / 'igs' / 'hl7.fhir.uv.omop-1.0.0.tgz'
PYTEST        = [SCRIPTS_DIR / 'env' / 'bin' / 'python3', '-m', 'pytest']

ETL_REPORT         = SCRIPTS_DIR / 'etl_report_test.html'
ETL_REPORT_SAMPLES = SCRIPTS_DIR / 'etl_report_sample.html'
UNIT_TEST_REPORT   = SCRIPTS_DIR / 'unit_test_report.html'

MATCHBOX_IMAGE   = 'croeder/matchbox:r4-1.0.0'
MATCHBOX_TAG     = 'r4-1.0.0'
MATCHBOX_PORT    = 8084
DQD_HTTP_PORT    = 8091
DOCKER_PROFILE   = 'r4-1.0.0'
DQD_SVC          = 'dqd-r4-1.0.0'
MATCHBOX_SVC     = 'matchbox-r4-1.0.0'
DQD_CONTAINER    = f'dqd_docker-{DQD_SVC}-1'
DQD_COMPOSE_FILE = 'docker-compose.profiles.yml'
TEST_FIXTURES_DIR   = 'test_files_r4'
SAMPLE_FIXTURES_DIR = 'sample_fixtures_r4'

STEPS = ['ig', 'mvn', 'docker', 'enchilada', 'restart', 'stop', 'etl', 'test', 'release']
DEFAULT_STEPS = ['ig', 'docker', 'enchilada', 'restart', 'etl']


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='FHIR R4/IG 1.0.0 build pipeline')
    parser.add_argument('steps', nargs='*',
                        help=f'Steps to run (default: {DEFAULT_STEPS}). Choices: {STEPS}')
    return parser.parse_args(argv)


def run(cmd, cwd=None, check=True, env=None):
    print(f'\n>>> {" ".join(str(c) for c in cmd)}')
    result = subprocess.run([str(c) for c in cmd], cwd=str(cwd) if cwd else None, check=check, env=env)
    return result.returncode


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
    import shutil
    shutil.copy2(PACKAGE_SRC, PACKAGE_DST)
    print('IG package copied.')


def step_mvn():
    print('\n=== Building matchbox JAR (mvn package -DskipTests) ===')
    run(['mvn', 'package', '-DskipTests'], cwd=REPO_ROOT / 'matchbox')
    print('matchbox JAR built.')


def _fix_null_params(obj):
    """Replace null entries in StructureMap parameter arrays with {"valueString": ""}."""
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
    """Repack a FHIR package tgz with an empty dependencies map so HAPI never fetches
    transitive deps over the network, and fix null StructureMap parameters (see
    _fix_null_params) produced by the R4 IG publisher."""
    import json, tarfile, io
    print(f'  Stripping dependencies from {tgz_path.name}', flush=True)
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
    print(f'\n=== Building {MATCHBOX_IMAGE} Docker image ===')
    for pkg in (MATCHBOX_DIR / 'igs').glob('*.tgz'):
        _strip_package_deps(pkg)
    run(['docker', 'compose', '-f', 'docker-compose.build.profiles.yml', 'build', 'matchbox-r4-1.0.0'],
        cwd=MATCHBOX_DIR)


def step_enchilada():
    print('\n=== Building enchilada Docker image ===')
    run(['docker', 'compose', '-f', DQD_COMPOSE_FILE, 'build', 'enchilada'], cwd=DQD_DIR)


def _ensure_multiarch_builder():
    """Ensure a buildx builder with docker-container driver exists for multi-arch builds."""
    result = subprocess.run(['docker', 'buildx', 'ls'], capture_output=True, text=True)
    if 'multiarch' not in result.stdout:
        print('\n>>> Creating multi-arch buildx builder (docker-container driver)')
        subprocess.run(
            ['docker', 'buildx', 'create', '--name', 'multiarch',
             '--driver', 'docker-container', '--bootstrap'],
            check=True,
        )
    subprocess.run(['docker', 'buildx', 'use', 'multiarch'], check=True)


def step_release():
    print(f'\n=== Building and pushing release image ({MATCHBOX_IMAGE}) ===')
    for pkg in (MATCHBOX_DIR / 'igs').glob('*.tgz'):
        _strip_package_deps(pkg)
    _ensure_multiarch_builder()
    # Multi-platform images (linux/amd64 + linux/arm64) can only be assembled into a
    # correct manifest list via a single combined build+push -- a plain `docker compose
    # build` followed by a separate `push` cannot join the two platform variants into
    # one manifest.
    run(['docker', 'buildx', 'bake', '--allow=fs.read=../matchbox/matchbox-server',
         '-f', 'docker-compose.build.profiles.yml', '--push', 'matchbox-r4-1.0.0'],
        cwd=MATCHBOX_DIR)


def _enchilada_healthy() -> bool:
    import urllib.request, ssl
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        urllib.request.urlopen('https://localhost:8081/r4/metadata', context=ctx, timeout=5)
        return True
    except Exception:
        return False


def _wait_for_matchbox_health():
    health_url = f'http://localhost:{MATCHBOX_PORT}/matchboxv3/actuator/health'
    print(f'Waiting for matchbox to become healthy ({health_url})...')
    run([
        'bash', '-c',
        f'until curl -sf {health_url} | grep -q \'"status":"UP"\'; do sleep 5; done && echo "Matchbox is up"',
    ])


def step_restart():
    matchbox_volume = 'dqd_docker_matchbox-r4-1.0.0-db'
    omop_volume = 'dqd_docker_omop-r4-1.0.0-db'
    if _enchilada_healthy():
        print(f'\n=== Restarting matchbox+dqd for profile {DOCKER_PROFILE} (enchilada already healthy, leaving it running) ===')
        run(['docker', 'compose', '-f', DQD_COMPOSE_FILE, 'stop', MATCHBOX_SVC, DQD_SVC], cwd=DQD_DIR, check=False)
        run(['docker', 'compose', '-f', DQD_COMPOSE_FILE, 'rm', '-f', MATCHBOX_SVC, DQD_SVC], cwd=DQD_DIR, check=False)
        run(['docker', 'volume', 'rm', '-f', matchbox_volume, omop_volume], check=False)
        run(['docker', 'compose', '-f', DQD_COMPOSE_FILE, '--profile', DOCKER_PROFILE, 'up', '-d'], cwd=DQD_DIR)
    else:
        print(f'\n=== Restarting dqd_docker --profile {DOCKER_PROFILE} (down -v to wipe matchbox-db, force IG reload) ===')
        run(['docker', 'compose', '-f', DQD_COMPOSE_FILE, '--profile', DOCKER_PROFILE, 'down', '-v'], cwd=DQD_DIR, check=False)
        run(['docker', 'compose', '-f', DQD_COMPOSE_FILE, '--profile', DOCKER_PROFILE, 'up', '-d'], cwd=DQD_DIR)
    _wait_for_matchbox_health()


def step_stop():
    print(f'\n=== Stopping dqd_docker --profile {DOCKER_PROFILE} containers ===')
    run(['docker', 'compose', '-f', DQD_COMPOSE_FILE, '--profile', DOCKER_PROFILE, 'stop'], cwd=DQD_DIR, check=False)


def step_etl():
    # Ensure the dqd container for this profile is running the current image
    # (no-op if already up to date).
    run(['docker', 'compose', '-f', DQD_COMPOSE_FILE, '--profile', DOCKER_PROFILE, 'up', '-d', '--no-deps', DQD_SVC], cwd=DQD_DIR)
    print('\n=== Re-running ETL in dqd container ===')
    runs = [
        (TEST_FIXTURES_DIR,   '/tmp/etl_test/omop.ddb',    '/tmp/etl_test_csv',    '/tmp/etl_test/etl_report.html',    ETL_REPORT),
        (SAMPLE_FIXTURES_DIR, '/tmp/etl_samples/omop.ddb', '/tmp/etl_samples_csv', '/tmp/etl_samples/etl_report.html', ETL_REPORT_SAMPLES),
    ]
    for fixtures_dir, tmp_db, tmp_csv, tmp_report, local_report in runs:
        print(f'\n--- {fixtures_dir} ---')
        run(['docker', 'exec', DQD_CONTAINER,
             'bash', '-c',
             f'mkdir -p $(dirname {tmp_db}) && rm -f {tmp_db} && '
             f'OMOP_DB_PATH={tmp_db} OMOP_CSV_DIR={tmp_csv} '
             f'python3 /etl/load_duckdb.py --fixtures-dir {fixtures_dir} --fhir-version r4'])
        print(f'\n>>> docker cp {DQD_CONTAINER}:{tmp_report} {local_report}')
        subprocess.run(['docker', 'cp', f'{DQD_CONTAINER}:{tmp_report}', str(local_report)], check=True)
        run(['docker', 'exec', DQD_CONTAINER, 'cp', tmp_report, '/omop/' + local_report.name])
        print(f'\n--- Report: {local_report.name} ---')
        _analyze_report(local_report)
    if platform.system() == 'Darwin':
        subprocess.run(['open', f'http://localhost:{DQD_HTTP_PORT}/'])


def _analyze_report(path):
    STATUSES = {'OK', 'WARN', 'NO_OUTPUT', 'SKIP', 'EXCEPT', 'DBERROR', 'XFAIL', 'UPASS'}

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
        if len(row) < 4:
            continue
        status = next((c for c in row if c in STATUSES), None)
        if not status:
            continue
        counts[status] = counts.get(status, 0) + 1
        if status not in ('OK', 'NO_OUTPUT', 'XFAIL'):
            fname  = row[0] if row else '?'
            map_nm = row[1] if len(row) > 1 else '?'
            detail = row[-1] if len(row) > 4 else ''
            issues.append((status, fname, map_nm, detail[:120]))

    print('\n--- ETL Report Summary ---')
    for s in ('OK', 'WARN', 'XFAIL', 'UPASS', 'NO_OUTPUT', 'SKIP', 'EXCEPT', 'DBERROR'):
        if s in counts:
            print(f'  {s}: {counts[s]}')
    if issues:
        print('\n  Issues:')
        for status, fname, map_nm, detail in issues:
            print(f'    [{status}] {fname}  ({map_nm}): {detail}')
    else:
        print('\n  No issues — all transforms OK or NO_OUTPUT.')
    print()
    return counts


def step_test():
    print('\n=== Running integration tests ===')
    env = os.environ.copy()
    env['MATCHBOX_URL'] = f'http://localhost:{MATCHBOX_PORT}'
    rc = run([*PYTEST, 'tests/test_r4_fml_transforms.py', '-v',
              f'--html={UNIT_TEST_REPORT}', '--self-contained-html'],
             cwd=SCRIPTS_DIR, env=env, check=False)
    if UNIT_TEST_REPORT.exists():
        subprocess.run(['docker', 'cp', str(UNIT_TEST_REPORT),
                        f'{DQD_CONTAINER}:/omop/unit_test_report.html'], check=False)
    if rc != 0:
        raise SystemExit(rc)


STEP_FNS = {
    'ig':        step_ig,
    'mvn':       step_mvn,
    'docker':    step_docker,
    'enchilada': step_enchilada,
    'restart':   step_restart,
    'stop':      step_stop,
    'etl':       step_etl,
    'test':      step_test,
    'release':   step_release,
}


def main():
    parsed = parse_args()
    steps = parsed.steps or DEFAULT_STEPS
    unknown = [s for s in steps if s not in STEP_FNS]
    if unknown:
        print(f'Unknown steps: {unknown}. Valid: {STEPS}')
        sys.exit(1)

    print(f'\n=== Stack: FHIR R4, IG 1.0.0 | image: {MATCHBOX_IMAGE} | profile: {DOCKER_PROFILE} ===')
    for step in steps:
        STEP_FNS[step]()
    print('\n=== Done ===')


if __name__ == '__main__':
    main()
