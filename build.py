#!/usr/bin/env python3
"""
Build pipeline: IG → matchbox JAR → Docker image → restart → tests → release.

Usage:
  python3 build.py                         # full pipeline (ig docker restart test)
  python3 build.py mvn                     # rebuild matchbox JAR only (skips tests)
  python3 build.py ig                      # rebuild IG only
  python3 build.py docker                  # rebuild matchbox Docker image only
  python3 build.py restart                 # restart dqd_docker (wipes matchbox-db)
  python3 build.py test                    # run tests only
  python3 build.py release                 # build and push both images to Docker Hub
  python3 build.py mvn ig release          # full release with Java + IG rebuild
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

STEPS = ['mvn', 'ig', 'docker', 'restart', 'test', 'release']
DEFAULT_STEPS = ['ig', 'docker', 'restart', 'test']


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
        'java', '-jar', 'input-cache/publisher.jar', '-ig', '.', '-tx', 'n/a',
    ])
    print(f'\n>>> cp {PACKAGE_SRC} {PACKAGE_DST}')
    shutil.copy2(PACKAGE_SRC, PACKAGE_DST)
    print('IG package copied.')


def step_docker():
    print('\n=== Building croeder/matchbox:latest Docker image ===')
    run(['docker', 'compose', '-f', 'docker-compose.build.yml', 'build'], cwd=MATCHBOX_DIR)


def step_release():
    print('\n=== Building and pushing all release images ===')
    print('--- matchbox ---')
    run(['docker', 'compose', '-f', 'docker-compose.build.yml', 'build'], cwd=MATCHBOX_DIR)
    run(['docker', 'compose', '-f', 'docker-compose.build.yml', 'push'], cwd=MATCHBOX_DIR)
    print('--- dqd ---')
    run(['docker', 'compose', '-f', 'docker-compose.build.yml', 'build'], cwd=DQD_DIR)
    run(['docker', 'compose', '-f', 'docker-compose.build.yml', 'push'], cwd=DQD_DIR)


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
    'mvn':     step_mvn,
    'ig':      step_ig,
    'docker':  step_docker,
    'restart': step_restart,
    'test':    step_test,
    'release': step_release,
}


def main():
    args = sys.argv[1:] or DEFAULT_STEPS
    unknown = [a for a in args if a not in STEP_FNS]
    if unknown:
        print(f'Unknown steps: {unknown}. Valid: {STEPS}')
        sys.exit(1)
    for step in args:
        STEP_FNS[step]()
    print('\n=== Done ===')


if __name__ == '__main__':
    main()
