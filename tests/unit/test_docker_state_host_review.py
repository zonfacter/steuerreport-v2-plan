"""Independent host lifecycle probes. No Docker, database, or provider access."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


TARGET = Path(__file__).resolve().parents[2] / 'scripts/docker_state_v2.py'
CID = 'a' * 64
RUN = 'review-host'


@pytest.fixture
def ops(monkeypatch):
    spec = importlib.util.spec_from_file_location('independent_host_review', TARGET)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    def forbidden(*args, **kwargs):
        raise AssertionError('Real subprocess forbidden in host lifecycle review')
    monkeypatch.setattr(module.subprocess, 'run', forbidden)
    monkeypatch.setattr(module.subprocess, 'Popen', forbidden)
    monkeypatch.setattr(module.time, 'sleep', lambda _: None)
    monkeypatch.setattr(module, 'RESTORE_CLEANUP_ATTEMPTS', 3)
    return module


def resource(ops, kind, owner=None):
    labels = {ops.RESOURCE_LABEL: RUN, ops.OWNER_LABEL: owner or ops.OWNER_NONCE}
    return {'Id': CID, 'Config': {'Labels': labels}} if kind == 'container' else {'Labels': labels}


@pytest.mark.parametrize('kind', ['container', 'volume'])
@pytest.mark.parametrize('late', [False, True])
def test_unknown_create_needs_observation(ops, monkeypatch, kind, late):
    reads, removed = [], []
    def inspect(k, ref):
        reads.append(ref)
        return resource(ops, kind) if late and len(reads) > 1 and not removed else None
    monkeypatch.setattr(ops, '_inspect_optional', inspect)
    monkeypatch.setattr(ops, '_docker', lambda cmd, **kw: removed.append(cmd) or '')
    outcome = ops._cleanup_restore_resource(kind, 'pending', RUN)
    assert outcome == (None if late else kind + '_create_state_unknown')
    assert len(removed) == int(late)
    if late and kind == 'container':
        assert removed == [['rm', '--force', CID]] and reads[-1] == CID
    if not late:
        assert len(reads) == 3


@pytest.mark.parametrize('kind', ['container', 'volume'])
@pytest.mark.parametrize('foreign_on_retry', [False, True])
def test_foreign_nonce_never_removed_even_after_remove_failure(ops, monkeypatch, kind, foreign_on_retry):
    removed = []
    def inspect(*args):
        return resource(ops, kind, 'foreign' if removed or not foreign_on_retry else None)
    def remove(cmd, **kw):
        removed.append(cmd)
        raise ops.OpsError('remove_timeout')
    monkeypatch.setattr(ops, '_inspect_optional', inspect)
    monkeypatch.setattr(ops, '_docker', remove)
    assert ops._cleanup_restore_resource(kind, 'name', RUN) == kind + '_ownership_unverified'
    assert len(removed) == int(foreign_on_retry)


def test_name_swap_and_remove_retry_keep_original_container_id(ops, monkeypatch):
    removed, inspected = [], []
    def inspect(kind, ref):
        inspected.append(ref)
        if len(inspected) > 1:
            assert ref == CID
        return None if len(removed) == 2 else resource(ops, kind)
    def remove(cmd, **kw):
        removed.append(cmd)
        if len(removed) == 1:
            raise ops.OpsError('remove_timeout')
        return ''
    monkeypatch.setattr(ops, '_inspect_optional', inspect)
    monkeypatch.setattr(ops, '_docker', remove)
    assert ops._cleanup_restore_resource('container', 'reassigned-name', RUN) is None
    assert removed == [['rm', '--force', CID]] * 2


def test_volume_creation_binds_both_labels_and_new_name_per_attempt(ops, monkeypatch):
    commands, volumes = [], {}
    def docker(cmd, **kw):
        commands.append(cmd)
        volumes[cmd[-1]] = resource(ops, 'volume')
        return cmd[-1]
    monkeypatch.setattr(ops, '_docker', docker)
    monkeypatch.setattr(ops, '_inspect_optional', lambda k, n: volumes.get(n))
    first, _ = ops._new_restore_volumes([{'id': 'm000'}], RUN)
    second, _ = ops._new_restore_volumes([{'id': 'm000'}], RUN)
    assert first != second
    for cmd in commands:
        assert ops.RESOURCE_LABEL + '=' + RUN in cmd
        assert ops.OWNER_LABEL + '=' + ops.OWNER_NONCE in cmd


@pytest.mark.parametrize('confirmed', [False, True])
def test_failed_volume_create_clears_stale_confirmation(ops, monkeypatch, confirmed):
    ops._CONFIRMED_RESOURCES.add(('volume', 'volume-name', RUN))
    def create(cmd, **kw):
        if not confirmed:
            raise ops.OpsError('create_timeout')
        return cmd[-1]
    monkeypatch.setattr(ops, '_docker', create)
    monkeypatch.setattr(ops, '_inspect_optional', lambda *a: None)
    if confirmed:
        ops._create_restore_volume('volume-name', RUN)
    else:
        with pytest.raises(ops.OpsError):
            ops._create_restore_volume('volume-name', RUN)
    assert ops._cleanup_restore_resource('volume', 'volume-name', RUN) == (
        None if confirmed else 'volume_create_state_unknown')


@pytest.mark.parametrize('mode', ['missing', 'foreign', 'owned', 'known-absent'])
def test_helper_cleanup_identity_and_dual_label_filter(ops, tmp_path, monkeypatch, mode):
    cidfile, commands = tmp_path / 'cid', []
    if mode == 'known-absent':
        cidfile.write_text(CID, encoding='ascii')
    def docker(cmd, **kw):
        commands.append(cmd)
        return CID if cmd[0] == 'ps' and mode != 'missing' else ''
    def inspect(*args):
        if mode == 'known-absent' or any(cmd[0] == 'rm' for cmd in commands):
            return None
        return resource(ops, 'container', 'foreign' if mode == 'foreign' else None)
    monkeypatch.setattr(ops, '_docker', docker)
    monkeypatch.setattr(ops, '_inspect_optional', inspect)
    assert ops._cleanup_helper_container(cidfile, RUN, require_observed=True) == (mode in {'owned', 'known-absent'})
    if mode != 'known-absent':
        assert 'label=' + ops.RESOURCE_LABEL + '=' + RUN in commands[0]
        assert 'label=' + ops.OWNER_LABEL + '=' + ops.OWNER_NONCE in commands[0]
    assert sum(cmd[0] == 'rm' for cmd in commands) == int(mode == 'owned')


@pytest.mark.parametrize('mode', ['success', 'timeout-late', 'timeout-missing', 'name-foreign'])
def test_restore_check_lifecycle(ops, tmp_path, monkeypatch, mode):
    image = {'image_id': 'sha256:' + 'b' * 64, 'revision': 'c' * 40, 'version': 'test'}
    manifest = {'source_image': image, 'mounts': [{'id': 'm000', 'kind': 'volume', 'target': '/state',
                'read_only': False}], 'archive_members': [], 'wal_files': [], 'schema_version': 3,
                'database_tables': {}, 'database_semantic_sha256': 'd' * 64}
    snapshot = {'database_present': True, 'required_private_files_present': True,
                'vault': {'decryptable': True, 'encrypted_rows': 0, 'unreadable_rows': 0},
                'schema_version': 3, 'tables': {}, 'database_semantic_sha256': 'd' * 64,
                'database_catalog_sha256': 'e' * 64, 'archive_members': [], 'wal_files': []}
    monkeypatch.setattr(ops, '_load_backup', lambda *a, **kw: (tmp_path / 'archive', manifest))
    monkeypatch.setattr(ops, '_image_info', lambda *a: image)
    monkeypatch.setattr(ops, '_stage_backup_archive', lambda *a: tmp_path / 'archive')
    monkeypatch.setattr(ops, '_run_helper_command', lambda *a, **kw: {})
    monkeypatch.setattr(ops, '_runtime_snapshot', lambda *a: snapshot)
    monkeypatch.setattr(ops, '_equal_after_start', lambda *a: True)
    reports, commands, volumes, container = [], [], {}, {}
    monkeypatch.setattr(ops, '_write_private_json', lambda p, value: reports.append(value))
    def inspect(kind, ref):
        if kind == 'volume':
            return volumes.get(ref)
        if not container:
            return None
        if mode == 'success':
            assert ref == CID, 'Name must not be used after successful create'
        return container
    monkeypatch.setattr(ops, '_inspect_optional', inspect)
    monkeypatch.setattr(ops, '_inspect', inspect)
    monkeypatch.setattr(ops, '_wait_health', lambda ref, version: {'id': ref} if ref == CID else pytest.fail(ref))
    def docker(cmd, **kw):
        commands.append(cmd)
        if cmd[:2] == ['volume', 'create']:
            volumes[cmd[-1]] = resource(ops, 'volume')
            return cmd[-1]
        if cmd[:2] == ['volume', 'rm']:
            volumes.pop(cmd[-1])
        elif cmd[0] == 'create':
            assert ops.OWNER_LABEL + '=' + ops.OWNER_NONCE in cmd
            if mode == 'timeout-missing':
                raise ops.OpsError('create_timeout')
            container.update(resource(ops, 'container', 'foreign' if mode == 'name-foreign' else None))
            container.update({'HostConfig': {'NetworkMode': 'none', 'ReadonlyRootfs': True},
                              'Mounts': [{'Name': next(iter(volumes)), 'Type': 'volume',
                                          'Destination': '/state', 'RW': True}]})
            if mode != 'success':
                raise ops.OpsError('create_timeout')
            return CID
        elif cmd[0] in {'start', 'stop', 'rm'}:
            assert cmd[-1] == CID
            if cmd[0] == 'rm':
                assert mode != 'name-foreign'
                container.clear()
        return ''
    monkeypatch.setattr(ops, '_docker', docker)
    args = SimpleNamespace(backup_dir=tmp_path, evidence_dir=tmp_path / 'evidence', run_id=RUN,
                           max_restore_bytes=1024, max_archive_bytes=1024,
                           max_expanded_archive_bytes=2048, image=None)
    if mode == 'success':
        result = ops.restore_check(args)
        assert result['status'] == 'passed' and result['cleanup']
    else:
        with pytest.raises(ops.OpsError, match='create_timeout'):
            ops.restore_check(args)
    assert not volumes
    assert reports[-1]['cleanup'] == (mode in {'success', 'timeout-late'})
    if mode == 'timeout-missing':
        assert reports[-1]['cleanup_failures'] == ['container_create_state_unknown']
    if mode == 'name-foreign':
        assert container and reports[-1]['cleanup_failures'] == ['container_ownership_unverified']
    else:
        assert not container
