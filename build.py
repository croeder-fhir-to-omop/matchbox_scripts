#!/usr/bin/env python3
"""
Build pipeline: IG → Docker image → restart → tests.

Usage:
  python3 build.py                    # full pipeline
  python3 build.py ig                 # rebuild IG only
  python3 build.py docker             # rebuild Docker image only
  python3 build.py restart            # restart dqd_docker (wipes matchbox-db)
  python3 build.py test               # run tests only
  python3 build.py ig docker restart test  # explicit step list
"""

import subprocess
import sys
import shutil
from pathlib import Path

REPO_ROOT     = Path(__file__).parent.parent
IG_DIR        = REPO_ROOT / 'fhir-omop-ig'
MATCHBOX_DIR  = REPO_ROOT / 'matchbox_docker'
DQD_DIR       = REPO_ROOT / 'dqd_docker'
SCRIPTS_DIR   = Path(__file__).parent
PACKAGE_SRC   = IG_DIR / 'output' / 'package.tgz'
PACKAGE_DST   = MATCHBOX_DIR / 'igs' / 'hl7.fhir.uv.omop-1.0.1.tgz'
MATCHBOX_SRC  = REPO_ROOT / 'matchbox' / 'matchbox-server'
PYTEST        = SCRIPTS_DIR / 'env' / 'bin' / 'pytest'
DQD_COMPOSE   = ['docker', 'compose', '-f', 'docker-compose.yml', '-f', 'docker-compose.matchbox-dev.yml']

STEPS = ['ig', 'docker', 'restart', 'test']


def run(cmd, cwd=None, check=True):
    print(f'\n>>> {" ".join(str(c) for c in cmd)}')
    result = subprocess.run([str(c) for c in cmd], cwd=str(cwd) if cwd else None, check=check)
    return result.returncode


def step_ig():
    print('\n=== Building fhir-omop-ig ===')
    run([
        'docker', 'run', '--rm',
        '-v', f'{IG_DIR}:/workspace',
        '-w', '/workspace',
        'ghcr.io/bonfhir/ig-toolbox:latest',
        'java', '-jar', 'input-cache/publisher.jar', '-ig', '.', '-tx', 'n/a',
    ])
    print(f'\n>>> cp {PACKAGE_SRC} {PACKAGE_DST}')
    shutil.copy2(PACKAGE_SRC, PACKAGE_DST)
    print('IG package copied.')


def step_docker():
    print('\n=== Building croeder/matchbox:latest Docker image ===')
    run([
        'docker', 'build',
        '-f', MATCHBOX_DIR / 'Dockerfile',
        '--platform', 'linux/arm64',
        '-t', 'croeder/matchbox:latest',
        str(MATCHBOX_SRC),
    ])


def step_restart():
    print('\n=== Restarting dqd_docker (wiping matchbox-db) ===')
    run(DQD_COMPOSE + ['down'], cwd=DQD_DIR, check=False)
    run(['docker', 'volume', 'rm', 'dqd_docker_matchbox-db'], check=False)
    run(DQD_COMPOSE + ['up', '-d'], cwd=DQD_DIR)
    print('Waiting for matchbox to become healthy...')
    run([
        'bash', '-c',
        'until curl -sf http://localhost:8080/matchboxv3/actuator/health | grep -q \'"status":"UP"\'; do sleep 5; done && echo "Matchbox is up"',
    ])


def step_test():
    print('\n=== Running integration tests ===')
    run([PYTEST, 'tests/test_fml_transforms.py', '-v'], cwd=SCRIPTS_DIR)


STEP_FNS = {
    'ig':      step_ig,
    'docker':  step_docker,
    'restart': step_restart,
    'test':    step_test,
}


def main():
    args = sys.argv[1:] or STEPS
    unknown = [a for a in args if a not in STEP_FNS]
    if unknown:
        print(f'Unknown steps: {unknown}. Valid: {STEPS}')
        sys.exit(1)
    for step in args:
        STEP_FNS[step]()
    print('\n=== Done ===')


if __name__ == '__main__':
    main()
