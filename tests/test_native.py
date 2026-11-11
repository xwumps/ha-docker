import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).parents[1] / 'compose_studio' / 'app'))
from server import Workspace
from native import Native, MANAGED, OWNER, normalize, parse_run


class RunParserTests(unittest.TestCase):
    def test_run_options_and_quoted_container_command(self):
        result = parse_run('docker run -d --name web -p8090:80 -e "MESSAGE=hello world" -v web-data:/data --restart=on-failure:5 busybox:1.37.0 sh -c "echo hello; sleep 30"')
        self.assertEqual(result['name'], 'web')
        config = result['config']
        self.assertEqual(config['ports'], ['8090:80'])
        self.assertEqual(config['env'], {'MESSAGE': 'hello world'})
        self.assertEqual(config['mounts'], ['web-data:/data'])
        self.assertEqual(config['command'], ['sh', '-c', 'echo hello; sleep 30'])
        self.assertEqual(config['restart'], 'on-failure:5')

    def test_shell_environment_is_not_expanded(self):
        result = parse_run('docker run -e VALUE="$HOME" busybox echo hello')
        self.assertEqual(result['config']['env']['VALUE'], '$HOME')

    def test_multiline_and_mount_readonly_false(self):
        result = parse_run('docker container run \\\n  --name app --mount type=volume,src=app-data,target=/data,readonly=false busybox')
        self.assertEqual(result['name'], 'app')
        self.assertEqual(result['config']['mounts'], ['app-data:/data'])
        with self.assertRaises(ValueError):
            parse_run('docker run --mount type=bind,src=data,target=/data busybox')

    def test_unsupported_flags_and_host_shell_are_rejected(self):
        for command in ('sudo docker run busybox', 'docker --context remote run busybox',
                        'docker run --rm busybox', 'docker run -it busybox',
                        'docker run --env-file .env busybox', 'docker run busybox && echo host',
                        'docker run --name web'):
            with self.subTest(command=command), self.assertRaises(ValueError):
                parse_run(command)

    def test_host_data_and_internal_labels_rejected(self):
        for config in ({'mounts': ['/host/data:/data']}, {'labels': {MANAGED: 'true'}},
                       {'labels': {'com.docker.compose.project': 'homeassistant'}},
                       {'network': 'host', 'ports': ['8090:80']},
                       {'mounts': ['one:/data', 'two:/data']}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                normalize('app', {'image': 'busybox', **config})


class NativeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Workspace(Path(self.temp.name))
        self.native = Native(self.workspace)
        self.native.save('app', {'image': 'busybox:1.37.0'})

    def tearDown(self):
        self.temp.cleanup()

    def test_dockerfile_archive_keeps_context_without_compose(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('source/Dockerfile', 'FROM busybox:1.37.0\nCOPY message /message\n')
            archive.writestr('source/message', 'hello')
        result = self.native.import_build('built', stream.getvalue())
        self.assertTrue(result['config']['build'])
        self.assertEqual(result['config']['image'], 'ha-docker/built:local')
        self.assertEqual((self.native.folder('built') / 'context/message').read_text(), 'hello')
        self.assertFalse((self.native.folder('built') / 'compose.yaml').exists())
        with self.assertRaises(ValueError):
            self.native.import_build('built', stream.getvalue())

    def test_context_upload_cannot_follow_symlink(self):
        context = self.native.folder('app') / 'context'
        (context / 'link').symlink_to(self.temp.name)
        with self.assertRaises(ValueError):
            self.native.upload('app', 'link/outside', b'data')

    def test_custom_dockerfile_path_and_executable_source_modes(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('source/docker/Dockerfile', 'FROM busybox:1.37.0\nCOPY entrypoint.sh /entrypoint.sh\n')
            script = zipfile.ZipInfo('source/entrypoint.sh')
            script.create_system = 3
            script.external_attr = 0o104755 << 16  # setuid bit must be removed.
            archive.writestr(script, '#!/bin/sh\necho hello\n')
        result = self.native.import_build('custom', stream.getvalue(), 'docker/Dockerfile')
        self.assertEqual(result['config']['dockerfile'], 'docker/Dockerfile')
        script = self.native.folder('custom') / 'context/entrypoint.sh'
        self.assertEqual(script.stat().st_mode & 0o7777, 0o755)
        self.native.upload('custom', 'entrypoint.sh', b'#!/bin/sh\necho updated\n')
        self.assertEqual(script.stat().st_mode & 0o777, 0o755)
        self.native.upload('custom', 'new-script.sh', b'#!/bin/sh\n', executable=True)
        self.assertEqual((script.parent / 'new-script.sh').stat().st_mode & 0o777, 0o755)

    def test_unowned_container_cannot_be_removed(self):
        def run(args, **kwargs):
            if args[:3] == ['docker', 'container', 'inspect']:
                return {'code': 0, 'output': json.dumps({'labels': None})}
            raise AssertionError('Unexpected mutation: ' + repr(args))
        with patch.object(self.workspace, 'run', side_effect=run):
            job = self.native.action('app', 'remove')
            self.assertTrue(self.workspace.lock.acquire(timeout=3))
            self.workspace.lock.release()
            result = self.workspace.job(job['id'])
        self.assertEqual(result['state'], 'failed')
        self.assertIn('gehört nicht', result['output'])

    def test_compile_uses_native_create_and_persists_implicit_volumes(self):
        image = {'Id': 'sha256:example', 'Config': {'Volumes': {'/data': {}}}, 'RepoDigests': ['busybox@sha256:example']}
        calls = []
        def run(args, **kwargs):
            calls.append(args)
            if args[:3] == ['docker', 'volume', 'inspect']:
                return {'code': 1, 'output': 'no such volume'}
            return {'code': 0, 'output': 'created'}
        with patch.object(self.workspace, 'run', side_effect=run):
            runtime, command = self.native.compile('app', normalize('app', {'image': 'busybox'}), image)
        self.assertEqual(command[:3], ['docker', 'container', 'create'])
        self.assertIn('/data', runtime['config']['mounts'])
        self.assertEqual(len(runtime['volumes']), 1)
        self.assertTrue(any('device=' + self.temp.name in arg for call in calls for arg in call))
        self.assertFalse(any('compose' in call for call in calls))

    def test_backup_inventory_excludes_foreign_name_collisions(self):
        with patch.object(self.workspace, 'run', return_value={'code': 0, 'output': json.dumps({'labels': None})}):
            self.assertEqual(self.native.containers(), [])

    def test_interrupted_create_does_not_block_backup_of_stopped_data(self):
        with patch.object(self.native, 'inspect', return_value={'running': False, 'mounts': []}):
            self.native.audit('app')

    def test_resume_uses_applied_config_not_edited_draft(self):
        runtime = {'config': {'image': 'busybox', 'env': {'VALUE': 'applied'}}, 'image_id': 'sha256:old'}
        self.workspace.write(self.native.folder('app') / '.studio-native-runtime.json', json.dumps(runtime))
        self.native.save('app', {'image': 'busybox', 'env': {'VALUE': 'draft'}})
        with patch.object(self.native, 'apply', return_value={'code': 0}) as apply:
            self.native.resume('app')
        self.assertEqual(apply.call_args.kwargs['pinned']['config']['env']['VALUE'], 'applied')

    def test_failed_image_archive_never_replaces_a_backup(self):
        with patch.object(self.workspace, 'run', return_value={'code': 1, 'output': 'disk full'}):
            with self.assertRaises(ValueError):
                self.native.save_image('sha256:example')
        self.assertFalse(self.native.image_archive('sha256:example').exists())
        self.assertEqual(list((Path(self.temp.name) / 'docker-images').iterdir()), [])


if __name__ == '__main__':
    unittest.main()
