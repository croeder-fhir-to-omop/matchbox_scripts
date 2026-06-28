"""
Unit tests for build.py task commands (run/test + source routing).
Does not require a running matchbox server, Docker, or git operations.
"""
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import build
from build import _matchbox_tag, _resolve_run, _dqd_compose_up


@pytest.fixture(autouse=True)
def reset_build_globals():
    build._IG_SOURCE = 'upstream'
    build._USE_DEV_OVERLAY = False
    build._IG_COMMIT = ''
    yield
    build._IG_SOURCE = 'upstream'
    build._USE_DEV_OVERLAY = False
    build._IG_COMMIT = ''


def _dirty_side_effect(ig=False, matchbox=False, scripts=False):
    """Return a side_effect function for _detect_dirty covering all paths _resolve_run checks."""
    mapping = {
        build.IG_DIR:                   ig,
        build.REPO_ROOT / 'matchbox':   matchbox,
        build.SCRIPTS_DIR:              scripts,
        build.DQD_DIR:                  scripts,
    }
    return lambda p, *args, **kwargs: mapping.get(p, False)


class TestMatchboxTag:
    def test_WHEN_ig_source_upstream_SHOULD_return_latest(self):
        build._IG_SOURCE = 'upstream'
        assert _matchbox_tag() == 'latest'

    def test_WHEN_ig_source_local_SHOULD_return_local(self):
        build._IG_SOURCE = 'local'
        assert _matchbox_tag() == 'local'

    def test_WHEN_ig_source_is_branch_name_SHOULD_return_branch_name(self):
        build._IG_SOURCE = 'my-branch'
        assert _matchbox_tag() == 'my-branch'

    def test_WHEN_ig_source_has_slash_SHOULD_replace_with_hyphen(self):
        build._IG_SOURCE = 'refactor/foo'
        assert _matchbox_tag() == 'refactor-foo'


class TestResolveRunNonLocal:
    def test_WHEN_source_none_no_test_SHOULD_return_restart_etl(self):
        steps = _resolve_run(None, False)
        assert steps == ['restart', 'etl']
        assert build._IG_SOURCE == 'upstream'
        assert build._USE_DEV_OVERLAY is False

    def test_WHEN_source_none_with_test_SHOULD_append_test_step(self):
        steps = _resolve_run(None, True)
        assert steps == ['restart', 'etl', 'test']

    def test_WHEN_source_upstream_no_test_SHOULD_return_ig_docker_restart_etl(self):
        steps = _resolve_run('upstream', False)
        assert steps == ['ig', 'docker', 'restart', 'etl']
        assert build._IG_SOURCE == 'upstream'

    def test_WHEN_source_upstream_with_test_SHOULD_append_test_step(self):
        steps = _resolve_run('upstream', True)
        assert steps == ['ig', 'docker', 'restart', 'etl', 'test']

    def test_WHEN_source_branch_no_test_SHOULD_set_ig_source_and_return_ig_docker_restart_etl(self):
        steps = _resolve_run('my-branch', False)
        assert steps == ['ig', 'docker', 'restart', 'etl']
        assert build._IG_SOURCE == 'my-branch'

    def test_WHEN_source_branch_with_test_SHOULD_append_test_step(self):
        steps = _resolve_run('my-branch', True)
        assert steps == ['ig', 'docker', 'restart', 'etl', 'test']
        assert build._IG_SOURCE == 'my-branch'


class TestResolveRunLocal:
    def test_WHEN_nothing_dirty_SHOULD_return_restart_etl_no_dev_overlay(self):
        with patch('build._detect_dirty', side_effect=_dirty_side_effect()):
            steps = _resolve_run('local', False)
        assert steps == ['restart', 'etl']
        assert build._IG_SOURCE == 'upstream'
        assert build._USE_DEV_OVERLAY is False

    def test_WHEN_ig_dirty_SHOULD_return_ig_docker_restart_etl_and_set_local_source(self):
        with patch('build._detect_dirty', side_effect=_dirty_side_effect(ig=True)):
            steps = _resolve_run('local', False)
        assert steps == ['ig', 'docker', 'restart', 'etl']
        assert build._IG_SOURCE == 'local'
        assert build._USE_DEV_OVERLAY is False

    def test_WHEN_matchbox_dirty_SHOULD_return_mvn_docker_restart_etl(self):
        with patch('build._detect_dirty', side_effect=_dirty_side_effect(matchbox=True)):
            steps = _resolve_run('local', False)
        assert steps == ['mvn', 'docker', 'restart', 'etl']
        assert build._IG_SOURCE == 'upstream'
        assert build._USE_DEV_OVERLAY is False

    def test_WHEN_scripts_dirty_SHOULD_return_restart_etl_and_set_dev_overlay(self):
        with patch('build._detect_dirty', side_effect=_dirty_side_effect(scripts=True)):
            steps = _resolve_run('local', False)
        assert steps == ['restart', 'etl']
        assert build._USE_DEV_OVERLAY is True

    def test_WHEN_ig_and_matchbox_dirty_SHOULD_return_ig_mvn_docker_restart_etl(self):
        with patch('build._detect_dirty', side_effect=_dirty_side_effect(ig=True, matchbox=True)):
            steps = _resolve_run('local', False)
        assert steps == ['ig', 'mvn', 'docker', 'restart', 'etl']
        assert build._IG_SOURCE == 'local'
        assert build._USE_DEV_OVERLAY is False

    def test_WHEN_ig_and_scripts_dirty_SHOULD_set_both_local_source_and_dev_overlay(self):
        with patch('build._detect_dirty', side_effect=_dirty_side_effect(ig=True, scripts=True)):
            steps = _resolve_run('local', False)
        assert steps == ['ig', 'docker', 'restart', 'etl']
        assert build._IG_SOURCE == 'local'
        assert build._USE_DEV_OVERLAY is True

    def test_WHEN_all_dirty_SHOULD_include_all_rebuild_steps_and_dev_overlay(self):
        with patch('build._detect_dirty', side_effect=_dirty_side_effect(ig=True, matchbox=True, scripts=True)):
            steps = _resolve_run('local', False)
        assert steps == ['ig', 'mvn', 'docker', 'restart', 'etl']
        assert build._IG_SOURCE == 'local'
        assert build._USE_DEV_OVERLAY is True

    def test_WHEN_nothing_dirty_with_test_flag_SHOULD_append_test_step(self):
        with patch('build._detect_dirty', side_effect=_dirty_side_effect()):
            steps = _resolve_run('local', True)
        assert steps == ['restart', 'etl', 'test']


def _env_from_compose_up_call(mock_run):
    """Extract the env kwarg from the most recent call to build.run."""
    return mock_run.call_args[1].get('env', {})


class TestDqdComposeUp:
    def test_WHEN_no_overlay_no_build_SHOULD_run_plain_compose_up(self):
        build._USE_DEV_OVERLAY = False
        with patch('build.run') as mock_run:
            _dqd_compose_up(build=False)
        cmd = mock_run.call_args[0][0]
        assert cmd == ['docker', 'compose', 'up', '-d']

    def test_WHEN_no_overlay_build_true_SHOULD_still_run_plain_compose_up(self):
        build._USE_DEV_OVERLAY = False
        with patch('build.run') as mock_run:
            _dqd_compose_up(build=True)
        cmd = mock_run.call_args[0][0]
        assert cmd == ['docker', 'compose', 'up', '-d']

    def test_WHEN_dev_overlay_no_build_SHOULD_include_overlay_files_without_build_flag(self):
        build._USE_DEV_OVERLAY = True
        with patch('build.run') as mock_run:
            _dqd_compose_up(build=False)
        cmd = mock_run.call_args[0][0]
        assert 'docker-compose.dev.yml' in cmd
        assert '--build' not in cmd
        assert cmd[-1] == '-d'

    def test_WHEN_dev_overlay_with_build_SHOULD_include_overlay_files_and_build_flag(self):
        build._USE_DEV_OVERLAY = True
        with patch('build.run') as mock_run:
            _dqd_compose_up(build=True)
        cmd = mock_run.call_args[0][0]
        assert 'docker-compose.dev.yml' in cmd
        assert '--build' in cmd
        assert cmd[-1] == '-d'

    def test_WHEN_ig_source_upstream_SHOULD_pass_latest_matchbox_image_in_env(self):
        build._IG_SOURCE = 'upstream'
        build._USE_DEV_OVERLAY = False
        with patch('build.run') as mock_run:
            _dqd_compose_up()
        env = _env_from_compose_up_call(mock_run)
        assert env.get('MATCHBOX_IMAGE') == 'croeder/matchbox:latest'

    def test_WHEN_ig_source_branch_SHOULD_pass_branch_matchbox_image_in_env(self):
        build._IG_SOURCE = 'IDs_and_everything'
        build._USE_DEV_OVERLAY = False
        with patch('build.run') as mock_run:
            _dqd_compose_up()
        env = _env_from_compose_up_call(mock_run)
        assert env.get('MATCHBOX_IMAGE') == 'croeder/matchbox:IDs_and_everything'

    def test_WHEN_ig_source_local_SHOULD_pass_local_matchbox_image_in_env(self):
        build._IG_SOURCE = 'local'
        build._USE_DEV_OVERLAY = True
        with patch('build.run') as mock_run:
            _dqd_compose_up()
        env = _env_from_compose_up_call(mock_run)
        assert env.get('MATCHBOX_IMAGE') == 'croeder/matchbox:local'


class TestMainRouting:
    def _mock_step_fns(self):
        return {step: MagicMock() for step in build.STEP_FNS}

    def test_WHEN_run_alone_SHOULD_call_restart_and_etl_not_rebuild_steps(self):
        mocks = self._mock_step_fns()
        with patch.object(sys, 'argv', ['build.py', 'run']), \
             patch.dict('build.STEP_FNS', mocks), \
             patch('build._detect_dirty', return_value=False):
            build.main()
        assert mocks['restart'].called
        assert mocks['etl'].called
        assert not mocks['ig'].called
        assert not mocks['docker'].called
        assert not mocks['test'].called

    def test_WHEN_run_upstream_SHOULD_call_ig_docker_restart_etl(self):
        mocks = self._mock_step_fns()
        with patch.object(sys, 'argv', ['build.py', 'run', 'upstream']), \
             patch.dict('build.STEP_FNS', mocks):
            build.main()
        assert mocks['ig'].called
        assert mocks['docker'].called
        assert mocks['restart'].called
        assert mocks['etl'].called
        assert not mocks['test'].called

    def test_WHEN_run_local_nothing_dirty_SHOULD_call_restart_and_etl_only(self):
        mocks = self._mock_step_fns()
        with patch.object(sys, 'argv', ['build.py', 'run', 'local']), \
             patch.dict('build.STEP_FNS', mocks), \
             patch('build._detect_dirty', return_value=False):
            build.main()
        assert mocks['restart'].called
        assert mocks['etl'].called
        assert not mocks['ig'].called
        assert not mocks['mvn'].called

    def test_WHEN_run_branch_SHOULD_call_ig_docker_restart_etl_and_set_ig_source(self):
        mocks = self._mock_step_fns()
        with patch.object(sys, 'argv', ['build.py', 'run', 'my-branch']), \
             patch.dict('build.STEP_FNS', mocks):
            build.main()
        assert mocks['ig'].called
        assert mocks['docker'].called
        assert build._IG_SOURCE == 'my-branch'

    def test_WHEN_test_local_nothing_dirty_SHOULD_also_call_test_step(self):
        mocks = self._mock_step_fns()
        with patch.object(sys, 'argv', ['build.py', 'test', 'local']), \
             patch.dict('build.STEP_FNS', mocks), \
             patch('build._detect_dirty', return_value=False):
            build.main()
        assert mocks['restart'].called
        assert mocks['etl'].called
        assert mocks['test'].called

    def test_WHEN_run_with_too_many_args_SHOULD_exit(self):
        with patch.object(sys, 'argv', ['build.py', 'run', 'a', 'b']):
            with pytest.raises(SystemExit):
                build.main()

    def test_WHEN_granular_steps_used_SHOULD_not_route_as_task_command(self):
        mocks = self._mock_step_fns()
        with patch.object(sys, 'argv', ['build.py', 'ig', 'docker']), \
             patch.dict('build.STEP_FNS', mocks):
            build.main()
        assert mocks['ig'].called
        assert mocks['docker'].called
        assert not mocks['restart'].called
        assert not mocks['etl'].called
