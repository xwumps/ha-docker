import base64
import io
import json
from pathlib import Path
import stat
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).parents[1] / 'compose_studio' / 'app'))
from server import Workspace
from importers import extract_archive, install_archive, install_jotion
from backups import Backup
from storage import OperationLock, prepare, rebase


def zipped(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        for path, contents in files.items():
            archive.writestr(path, contents)
    return stream.getvalue()


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Workspace(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def test_archive_import_retains_auxiliary_files_and_does_not_run_scripts(self):
        data = zipped({'package/compose.yml': 'services: {}', 'package/docker/Caddyfile': ':80 {}',
                       'package/.env.example': 'PORT=8080', 'package/install.sh': 'touch /SHOULD_NOT_RUN'})
        project = install_archive(self.workspace, 'example', data)
        self.assertEqual(project['env'], 'PORT=8080')
        self.assertEqual((self.workspace.project('example') / 'docker/Caddyfile').read_text(), ':80 {}')
        with self.assertRaises(ValueError):
            install_archive(self.workspace, 'example', data)

    def test_archive_rejects_traversal_symlinks_and_reserved_metadata(self):
        for name in ('../escaped', '/absolute', 'a\\b', '.studio-runtime.json'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                extract_archive(zipped({name: 'x'}), Path(self.temp.name))
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            info = zipfile.ZipInfo('link')
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, '../../escape')
        with self.assertRaises(ValueError):
            extract_archive(stream.getvalue(), Path(self.temp.name))
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w') as archive:
            item = tarfile.TarInfo('hardlink')
            item.type = tarfile.LNKTYPE
            item.linkname = '../../escape'
            archive.addfile(item)
        with self.assertRaises(ValueError):
            extract_archive(stream.getvalue(), Path(self.temp.name))

    def test_file_upload_rejects_parent_symlink(self):
        self.workspace.save('example', 'services: {}', '')
        (self.workspace.project('example') / 'link').symlink_to(self.temp.name)
        with self.assertRaises(ValueError):
            self.workspace.save_file('example', 'link/escape', base64.b64encode(b'content').decode())

    def test_tar_limit_checked_before_decompressing_member(self):
        item = tarfile.TarInfo('oversized')
        item.size = 33 * 1024 * 1024
        # Header only: a correct bounded parser rejects it before reading data.
        with self.assertRaisesRegex(ValueError, 'große'):
            extract_archive(item.tobuf() + b'\0' * 1024, Path(self.temp.name))

    def test_jotion_generates_unique_secrets_and_pins_images(self):
        package = zipped({'compose.yml': 'services: {}', '.env.example': 'POSTGRES_PASSWORD=change-me\nJOTION_MASTER_KEY=\n',
                          'docker/Caddyfile': ':80 {}'})
        release = json.dumps({'tag_name': 'v1.0.1', 'assets': [{'name': 'jotion-1.0.1.tar.gz'}]}).encode()
        with patch('importers.fetch', side_effect=[release, package, release, package]):
            a = install_jotion(self.workspace, 'jotion-a', '', 'http://192.168.1.20:8090', 8090)
            b = install_jotion(self.workspace, 'jotion-b', '1.0.1', 'http://192.168.1.20:8091', 8091)
        def env(project):
            return dict(line.split('=', 1) for line in project['env'].splitlines() if '=' in line)
        ea, eb = env(a), env(b)
        self.assertNotEqual(ea['POSTGRES_PASSWORD'], eb['POSTGRES_PASSWORD'])
        self.assertNotEqual(ea['JOTION_MASTER_KEY'], eb['JOTION_MASTER_KEY'])
        self.assertEqual(len(base64.b64decode(ea['JOTION_MASTER_KEY'])), 32)
        self.assertEqual(ea['JOTION_IMAGE_PREFIX'], 'ghcr.io/xwumps/jotion')
        self.assertEqual(ea['JOTION_VERSION'], '1.0.1')
        self.assertEqual(ea['JOTION_PUBLIC_URL'], 'http://192.168.1.20:8090')


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Workspace(Path(self.temp.name))
        self.workspace.save('example', 'services: {}', '')

    def tearDown(self):
        self.temp.cleanup()

    def prepare(self, config):
        def run(args, **kwargs):
            if args[:3] == ['docker', 'compose', '--ansi']:
                return {'code': 0, 'output': json.dumps(config)}
            return {'code': 1, 'output': 'no such volume'}
        with patch.object(self.workspace, 'run', side_effect=run), patch('storage.containers', return_value=[]):
            return prepare(self.workspace, 'example')

    def test_named_volumes_use_app_data_and_runtime_has_no_build(self):
        result = self.prepare({'services': {'db': {'image': 'postgres:16-alpine', 'build': '.',
            'volumes': [{'type': 'volume', 'source': 'db', 'target': '/data'}]}},
            'volumes': {'db': {'name': 'cs_example_db'}}})
        self.assertNotIn('build', result['services']['db'])
        self.assertTrue(result['volumes']['db']['driver_opts']['device'].startswith(self.temp.name + '/storage/'))
        self.assertEqual(result['volumes']['db']['driver_opts']['o'], 'bind')

    def test_external_data_and_anonymous_volumes_are_rejected(self):
        for mount in ({'type': 'bind', 'source': '/outside', 'target': '/data'},
                      {'type': 'volume', 'target': '/data'}):
            with self.subTest(mount=mount), self.assertRaises(ValueError):
                self.prepare({'services': {'app': {'image': 'busybox', 'volumes': [mount]}}})
        with self.assertRaises(ValueError):
            self.prepare({'services': {'app': {'image': 'busybox'}}, 'volumes': {'db': {'external': True}}})

    def test_partial_migration_is_rolled_back_before_original_containers_resume(self):
        calls = []
        def copy_volume(workspace, name, directory):
            calls.append(name)
            if len(calls) == 2:
                raise ValueError('Second volume failed')
            (directory / 'copied-data').write_text('snapshot')
            return True
        config = {'services': {'app': {'image': 'busybox'}},
                  'volumes': {'one': {'name': 'old_one'}, 'two': {'name': 'old_two'}}}
        with patch('storage.copy_legacy_volume', side_effect=copy_volume), self.assertRaises(ValueError):
            self.prepare(config)
        self.assertFalse((self.workspace.project('example') / '.studio-runtime.json').exists())
        self.assertEqual(list((Path(self.temp.name) / 'storage' / 'example').iterdir()), [])

    def test_rebase_changes_host_paths_and_wrapper_name(self):
        self.prepare({'services': {'app': {'image': 'busybox'}}, 'volumes': {'db': {'name': 'cs_example_db'}}})
        original = json.loads((self.workspace.project('example') / '.studio-runtime.json').read_text())
        with tempfile.TemporaryDirectory() as restored:
            import shutil
            shutil.copytree(self.workspace.root, Path(restored) / 'stacks')
            workspace = Workspace(Path(restored))
            result = rebase(workspace, 'example')
            self.assertNotEqual(original['volumes']['db']['name'], result['volumes']['db']['name'])
            self.assertTrue(result['volumes']['db']['driver_opts']['device'].startswith(restored + '/storage/'))

    def test_cross_process_lock_and_backup_marker_block_mutations(self):
        second = OperationLock(Path(self.temp.name) / '.studio-operation.lock')
        self.workspace.lock.acquire()
        try:
            self.assertFalse(second.acquire(blocking=False))
        finally:
            self.workspace.lock.release()
        (Path(self.temp.name) / '.studio-backup-state.json').write_text('{}')
        with self.assertRaises(BlockingIOError):
            self.workspace.save('another', 'services: {}', '')

    def test_backup_preserves_resume_intent_and_post_clears_it(self):
        backup = Backup(self.workspace)
        with patch('backups.containers', return_value=[]), patch('backups.legacy_volumes', return_value=[]):
            backup.pre()
        self.assertTrue(backup.state.exists())
        self.assertTrue(json.loads(backup.state.read_text())['ready'])
        backup.post()
        self.assertFalse(backup.state.exists())


if __name__ == '__main__':
    unittest.main()
