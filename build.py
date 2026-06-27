#!/usr/bin/env python3
"""
Simple FHIR R5 / IG 1.0.0 build pipeline.

Task commands (preferred):
  python3 build.py run                # restart stack, run ETL with current images
  python3 build.py run upstream       # rebuild from HL7 upstream main, restart, ETL
  python3 build.py run local          # detect local changes, rebuild what's needed, restart, ETL
  python3 build.py run <branch>       # rebuild fhir-omop-ig from named branch, restart, ETL
  python3 build.py test               # same as 'run' but also executes the test suite
  python3 build.py test upstream
  python3 build.py test local
  python3 build.py test <branch>

  'local' detects dirty sub-projects automatically:
    fhir-omop-ig dirty       → ig + docker steps (uses working tree as-is)
    matchbox dirty           → mvn + docker steps
    matchbox_scripts/dqd_docker dirty → rebuilds dqd image from local source

Granular steps (surgical control):
  python3 build.py                                       # full pipeline; HL7 upstream main → :latest
  python3 build.py ig                                    # rebuild IG only
  python3 build.py mvn                                   # rebuild matchbox JAR only
  python3 build.py docker                                # rebuild matchbox Docker image only
  python3 build.py release                               # build and push images to Docker Hub
  python3 build.py start                                 # start the stack
  python3 build.py restart                               # wipe and restart the stack (forces IG reload)
  python3 build.py stop                                  # stop the stack
  python3 build.py down                                  # tear down stack and remove all volumes
  python3 build.py etl                                   # re-run ETL; open reports at localhost
  python3 build.py ig docker restart                     # run specific steps in sequence

  python3 build.py --ig-source main ig docker release    # fork main → croeder/matchbox:main
  python3 build.py --ig-source fix-translate-rule-names ig docker  # fork branch → croeder/matchbox:fix-translate-rule-names
  python3 build.py --tx-server n/a ig                   # skip terminology validation

--ig-source values:
  (omitted)       HL7/fhir-omop-ig upstream/main — the release source; image tagged :latest
  main            croeder-fhir-to-omop/fhir-omop-ig main; image tagged :main
  <branch>        croeder-fhir-to-omop/fhir-omop-ig branch <branch>; image tagged :<branch>

--tx-server values:
  https://tx.fhir.org   default HL7 terminology server
  n/a                   skip terminology validation entirely
  <url>                 any custom terminology server URL
"""

import contextlib
import os
import platform
import subprocess
import sys
import shutil
from html.parser import HTMLParser
from pathlib import Path
import argparse

REPO_ROOT        = Path(__file__).parent.parent
IG_DIR           = REPO_ROOT / 'fhir-omop-ig'
MATCHBOX_DIR     = REPO_ROOT / 'matchbox_docker'
DQD_DIR          = REPO_ROOT / 'dqd_docker'
ENCHILADA_DIR    = REPO_ROOT / 'enchilada'
SCRIPTS_DIR      = Path(__file__).parent
PACKAGE_SRC      = IG_DIR / 'output' / 'package.tgz'
PACKAGE_DST      = MATCHBOX_DIR / 'igs' / 'hl7.fhir.uv.omop-1.0.0.tgz'
MATCHBOX_PORT    = 8080
DQD_HTTP_PORT    = 8088
DQD_CONTAINER    = 'dqd_docker-dqd-1'
PYTEST           = [SCRIPTS_DIR / 'env' / 'bin' / 'python3', '-m', 'pytest']
ETL_REPORT       = SCRIPTS_DIR / 'etl_report_test.html'
ETL_REPORT_SAMPLES = SCRIPTS_DIR / 'etl_report_sample.html'
UNIT_TEST_REPORT = SCRIPTS_DIR / 'unit_test_report.html'

STEPS = ['ig', 'mvn', 'docker', 'release', 'start', 'restart', 'stop', 'down', 'etl', 'test']
DEFAULT_STEPS = ['ig', 'mvn', 'docker', 'restart', 'etl', 'test']

# Set by main() from --ig-source or task command source.
# 'upstream' = HL7/fhir-omop-ig main → :latest; 'local' = working tree as-is → :local;
# 'main' = fork main → :main; any branch name = that fork branch → :<branch>.
_IG_SOURCE: str = 'upstream'

_TX_SERVER = 'https://tx.fhir.org'

# Captured inside _ig_source_checkout() after the checkout; used by _matchbox_compose_env().
_IG_COMMIT: str = ''

# When True, restart/start use docker-compose.dev.yml overlay to rebuild the dqd image
# from local matchbox_scripts/dqd_docker source instead of pulling croeder/dqd:latest.
_USE_DEV_OVERLAY: bool = False


def _matchbox_tag() -> str:
    if _IG_SOURCE == 'upstream':
        return 'latest'
    if _IG_SOURCE == 'local':
        return 'local'
    return _IG_SOURCE.replace('/', '-')


def _matchbox_image() -> str:
    # Full Docker image reference, e.g. croeder/matchbox:latest or croeder/matchbox:main.
    return f'croeder/matchbox:{_matchbox_tag()}'



@contextlib.contextmanager
def _ig_source_checkout():
    """Fetch/checkout the requested IG source in fhir-omop-ig, then restore the original branch."""
    global _IG_COMMIT

    if _IG_SOURCE == 'local':
        # Use the working tree as-is, including any uncommitted changes.
        _IG_COMMIT = subprocess.run(
            ['git', 'rev-parse', 'HEAD'], capture_output=True, text=True, cwd=str(IG_DIR)
        ).stdout.strip()
        print(f'\n>>> Using local fhir-omop-ig working tree (base commit: {_IG_COMMIT[:8]})')
        yield
        return

    # FHIR-omop.xml is regenerated by the IG publisher on every build — reset it silently.
    subprocess.run(['git', 'checkout', 'FHIR-omop.xml'], cwd=str(IG_DIR), check=False)
    # Only block on staged/unstaged changes to other tracked files; untracked files are fine.
    dirty = subprocess.run(
        ['git', 'diff', '--quiet', 'HEAD'], cwd=str(IG_DIR)
    ).returncode != 0
    if dirty:
        print('ERROR: fhir-omop-ig has uncommitted changes to tracked files. Stash or commit before running the ig step.')
        sys.exit(1)

    orig = subprocess.run(
        ['git', 'branch', '--show-current'], capture_output=True, text=True, cwd=str(IG_DIR)
    ).stdout.strip()

    if _IG_SOURCE == 'upstream':
        print('\n>>> git fetch upstream  (in fhir-omop-ig)')
        subprocess.run(['git', 'fetch', 'upstream'], cwd=str(IG_DIR), check=True)
        print('\n>>> git checkout --detach upstream/main  (in fhir-omop-ig)')
        subprocess.run(['git', 'checkout', '--detach', 'upstream/main'], cwd=str(IG_DIR), check=True)
    else:
        print(f'\n>>> git checkout {_IG_SOURCE}  (in fhir-omop-ig)')
        subprocess.run(['git', 'checkout', _IG_SOURCE], cwd=str(IG_DIR), check=True)

    _IG_COMMIT = subprocess.run(
        ['git', 'rev-parse', 'HEAD'], capture_output=True, text=True, cwd=str(IG_DIR)
    ).stdout.strip()

    try:
        yield
    finally:
        restore = orig or 'HEAD'
        print(f'\n>>> Restoring fhir-omop-ig to: {restore}')
        subprocess.run(['git', 'checkout', restore], cwd=str(IG_DIR), check=False)


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='FHIR R5/1.0.0 build pipeline')
    parser.add_argument('steps', nargs='*',
                        help=f'Steps to run (default: {DEFAULT_STEPS}). Choices: {STEPS}')
    parser.add_argument('--ig-source', metavar='SOURCE', default='upstream',
                        help='IG source for the build. Default: "upstream" (HL7/fhir-omop-ig main → :latest). '
                             '"main" builds from croeder-fhir-to-omop/fhir-omop-ig main → :main. '
                             'Any other value is treated as a branch name in the fork → :<branch>. '
                             'Checks out fhir-omop-ig before the ig step and restores it after.')
    parser.add_argument('--tx-server', metavar='URL', default='https://tx.fhir.org',
                        help='Terminology server URL passed to the IG publisher '
                             '(default: https://tx.fhir.org). Use "n/a" to skip terminology validation.')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print the resolved steps and configuration without executing anything.')
    return parser.parse_args(argv)


def run(cmd, cwd=None, check=True, env=None):
    print(f'\n>>> {" ".join(str(c) for c in cmd)}')
    result = subprocess.run([str(c) for c in cmd], cwd=str(cwd) if cwd else None, check=check, env=env)
    return result.returncode


def step_ig():
    print('\n=== Building fhir-omop-ig ===')
    with _ig_source_checkout():
        run([
            'docker', 'run', '--rm',
            '-v', f'{IG_DIR}:/workspace',
            '-w', '/workspace',
            'ghcr.io/bonfhir/ig-toolbox:latest',
            'java', '-jar', 'input-cache/publisher.jar', '-ig', '.', '-tx', _TX_SERVER,
        ])
        print(f'\n>>> cp {PACKAGE_SRC} {PACKAGE_DST}')
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
    """Clear dependency list from a FHIR package tgz so HAPI never fetches transitive deps."""
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


def _matchbox_compose_env() -> dict:
    from datetime import datetime, timezone
    commit = _IG_COMMIT or subprocess.run(
        ['git', 'rev-parse', 'HEAD'], capture_output=True, text=True, cwd=str(IG_DIR)
    ).stdout.strip()
    return {
        **os.environ,
        'MATCHBOX_TAG':    _matchbox_tag(),
        'IG_SOURCE':       _IG_SOURCE,
        'IG_COMMIT':       commit,
        'IG_BUILD_DATE':   datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    }


def step_docker():
    print(f'\n=== Building {_matchbox_image()} Docker image ===')
    for pkg in (MATCHBOX_DIR / 'igs').glob('*.tgz'):
        _strip_package_deps(pkg)
    run(['docker', 'compose', '-f', 'docker-compose.build.yml', 'build', 'matchbox'],
        cwd=MATCHBOX_DIR, env=_matchbox_compose_env())


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
    print(f'\n=== Building and pushing release images ({_matchbox_image()}) ===')
    if not _IG_COMMIT:
        print(
            'WARNING: ig step was not run in this invocation. '
            'The fhir-omop-ig.commit label will reflect the current fhir-omop-ig checkout, '
            'which may not match the IG package baked into the image. '
            'Run "python3 build.py ig release" to guarantee an accurate label.'
        )
    _ensure_multiarch_builder()
    for pkg in (MATCHBOX_DIR / 'igs').glob('*.tgz'):
        _strip_package_deps(pkg)
    env = _matchbox_compose_env()
    # buildx bake reads the platforms list from the compose file and pushes a proper
    # multi-arch manifest (linux/amd64 + linux/arm64) in a single step.
    run(['docker', 'buildx', 'bake', '-f', 'docker-compose.build.yml', '--push', 'matchbox'],
        cwd=MATCHBOX_DIR, env=env)
    run(['docker', 'buildx', 'bake', '-f', 'docker-compose.build.yml', '--push'],
        cwd=DQD_DIR)
    run(['docker', 'buildx', 'bake', '-f', 'docker-compose.build.yml', '--push'],
        cwd=ENCHILADA_DIR)


def _dqd_compose_up(build=False, check=True):
    """Run docker compose up -d in dqd_docker, using the dev overlay when _USE_DEV_OVERLAY is set."""
    cmd = ['docker', 'compose']
    if _USE_DEV_OVERLAY:
        cmd += ['-f', 'docker-compose.yml', '-f', 'docker-compose.dev.yml']
    if build and _USE_DEV_OVERLAY:
        cmd += ['up', '--build', '-d']
    else:
        cmd += ['up', '-d']
    run(cmd, cwd=DQD_DIR, check=check)


def step_start():
    print('\n=== Starting stack ===')
    _dqd_compose_up(build=True, check=False)
    health_url = f'http://localhost:{MATCHBOX_PORT}/matchboxv3/actuator/health'
    run([
        'bash', '-c',
        f'until curl -sf {health_url} | grep -q \'"status":"UP"\'; do sleep 5; done && echo "Matchbox is up"',
    ])
    _dqd_compose_up()
    try:
        step_test()
    except SystemExit:
        pass


def step_restart():
    print('\n=== Restarting stack (wiping matchbox-db to force IG reload) ===')
    run(['docker', 'compose', 'down'], cwd=DQD_DIR, check=False)
    # Wipe only matchbox-db (forces IG reload) and omop-db; preserve enchilada-db
    # so the SQLite vocabulary cache survives restarts (saves ~2 min CSV reload).
    for vol in ['dqd_docker_matchbox-db', 'dqd_docker_omop-db']:
        run(['docker', 'volume', 'rm', '-f', vol], check=False)
    # First pass: starts enchilada and matchbox; dqd may fail its dependency check
    # since matchbox isn't healthy yet — that's expected, ignore the exit code.
    # build=True triggers --build when using the dev overlay to rebuild the dqd image.
    _dqd_compose_up(build=True, check=False)
    health_url = f'http://localhost:{MATCHBOX_PORT}/matchboxv3/actuator/health'
    print(f'Waiting for matchbox to become healthy ({health_url})...')
    run([
        'bash', '-c',
        f'until curl -sf {health_url} | grep -q \'"status":"UP"\'; do sleep 5; done && echo "Matchbox is up"',
    ])
    # Second pass: matchbox is now healthy, so dqd's dependency check passes.
    _dqd_compose_up()
    try:
        step_test()
    except SystemExit:
        pass


def step_stop():
    print('\n=== Stopping stack ===')
    run(['docker', 'compose', 'stop'], cwd=DQD_DIR, check=False)


def step_down():
    print('\n=== Tearing down stack and removing all volumes ===')
    run(['docker', 'compose', 'down'], cwd=DQD_DIR, check=False)
    for vol in ['dqd_docker_matchbox-db', 'dqd_docker_omop-db', 'dqd_docker_enchilada-db']:
        run(['docker', 'volume', 'rm', '-f', vol], check=False)


def step_etl():
    print('\n=== Re-running ETL in dqd container ===')
    runs = [
        ('test_files_r5',      '/tmp/etl_test/omop.ddb',    '/tmp/etl_test_csv',    '/tmp/etl_test/etl_report.html',    ETL_REPORT),
        ('sample_fixtures_r5', '/tmp/etl_samples/omop.ddb', '/tmp/etl_samples_csv', '/tmp/etl_samples/etl_report.html', ETL_REPORT_SAMPLES),
    ]
    for fixtures_dir, tmp_db, tmp_csv, tmp_report, local_report in runs:
        print(f'\n--- {fixtures_dir} ---')
        run(['docker', 'exec', DQD_CONTAINER,
             'bash', '-c',
             f'mkdir -p $(dirname {tmp_db}) && rm -f {tmp_db} && '
             f'OMOP_DB_PATH={tmp_db} OMOP_CSV_DIR={tmp_csv} '
             f'python3 /etl/load_duckdb.py --fixtures-dir {fixtures_dir} --fhir-version r5'])
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
    print('\n=== Running unit tests (mock + real-git) ===')
    rc = run([*PYTEST, 'tests/test_build_commands.py', 'tests/test_build_commands_real.py', '-v'],
             cwd=SCRIPTS_DIR, check=False)
    if rc != 0:
        raise SystemExit(rc)

    print('\n=== Running integration tests ===')
    env = os.environ.copy()
    env['MATCHBOX_URL'] = f'http://localhost:{MATCHBOX_PORT}'
    rc = run([*PYTEST, 'tests/test_r5_fml_transforms.py', '-v',
              f'--html={UNIT_TEST_REPORT}', '--self-contained-html'],
             cwd=SCRIPTS_DIR, env=env, check=False)
    if UNIT_TEST_REPORT.exists():
        subprocess.run(['docker', 'cp', str(UNIT_TEST_REPORT),
                        f'{DQD_CONTAINER}:/omop/unit_test_report.html'], check=False)
    if rc != 0:
        raise SystemExit(rc)


def _detect_dirty(path: Path, exclude: list = ()) -> bool:
    cmd = ['git', 'diff', '--quiet', 'HEAD']
    if exclude:
        cmd += ['--', '.'] + [f':!{p}' for p in exclude]
    return subprocess.run(cmd, cwd=str(path), capture_output=True).returncode != 0


def _resolve_run(source: str | None, include_test: bool) -> list:
    """Translate a task command + source into a step list, setting module-level flags as needed."""
    global _IG_SOURCE, _USE_DEV_OVERLAY

    tail = ['etl', 'test'] if include_test else ['etl']

    if source is None:
        return ['restart'] + tail

    if source == 'upstream':
        _IG_SOURCE = 'upstream'
        return ['ig', 'docker', 'restart'] + tail

    if source == 'local':
        ig_dirty      = _detect_dirty(IG_DIR, exclude=['FHIR-omop.xml'])
        matchbox_dirty = _detect_dirty(REPO_ROOT / 'matchbox')
        scripts_dirty  = _detect_dirty(SCRIPTS_DIR) or _detect_dirty(DQD_DIR)

        steps = []
        need_docker = False
        if ig_dirty:
            _IG_SOURCE = 'local'
            steps.append('ig')
            need_docker = True
        if matchbox_dirty:
            steps.append('mvn')
            need_docker = True
        if need_docker:
            steps.append('docker')
        if scripts_dirty:
            _USE_DEV_OVERLAY = True

        parts = (['fhir-omop-ig'] if ig_dirty else []) + \
                (['matchbox'] if matchbox_dirty else []) + \
                (['matchbox_scripts/dqd_docker'] if scripts_dirty else [])
        if parts:
            print(f'\n>>> Local changes detected in: {", ".join(parts)}')
        else:
            print('\n>>> No local changes detected; restarting with current images')

        return steps + ['restart'] + tail

    # branch name
    _IG_SOURCE = source
    return ['ig', 'docker', 'restart'] + tail


STEP_FNS = {
    'ig':      step_ig,
    'mvn':     step_mvn,
    'docker':  step_docker,
    'release': step_release,
    'start':   step_start,
    'restart': step_restart,
    'stop':    step_stop,
    'down':    step_down,
    'etl':     step_etl,
    'test':    step_test,
}


def main():
    global _IG_SOURCE, _TX_SERVER
    parsed = parse_args()
    _IG_SOURCE = parsed.ig_source
    _TX_SERVER = parsed.tx_server
    raw = parsed.steps

    if raw and raw[0] in ('run', 'test'):
        command = raw[0]
        if len(raw) > 2:
            print(f'Usage: build.py {command} [upstream|local|<branch>]')
            sys.exit(1)
        source = raw[1] if len(raw) == 2 else None
        steps = _resolve_run(source, include_test=(command == 'test'))
    else:
        steps = raw or DEFAULT_STEPS
        unknown = [s for s in steps if s not in STEP_FNS]
        if unknown:
            print(f'Unknown steps: {unknown}. Valid: {STEPS}')
            sys.exit(1)

    dev_note = ' | dev-overlay=dqd' if _USE_DEV_OVERLAY else ''
    print(f'\n=== Stack: FHIR R5, IG 1.0.0 | image: {_matchbox_image()} | ig-source={_IG_SOURCE}{dev_note} ===')

    if parsed.dry_run:
        print('DRY RUN — no steps will be executed')
        print(f'steps: {" ".join(steps)}')
        print(f'ig-source: {_IG_SOURCE}')
        print(f'dev-overlay: {_USE_DEV_OVERLAY}')
        return

    for step in steps:
        STEP_FNS[step]()
    print('\n=== Done ===')


if __name__ == '__main__':
    main()
