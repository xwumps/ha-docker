import http.client
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

APP = Path(__file__).parents[1] / 'compose_studio' / 'app' / 'server.py'
spec = importlib.util.spec_from_file_location('compose_studio', APP)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = module.Workspace(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def test_invalid_names_cannot_escape_workspace(self):
        for name in ('../host', '/data', '', 'a/b', '..', 'HA', 'a' * 41, None):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.workspace.save(name, 'services: {}', '')

    def test_symlinked_projects_and_files_are_rejected(self):
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        (self.workspace.root / 'linked').symlink_to(outside)
        with self.assertRaises(ValueError):
            self.workspace.save('linked', 'services: {}', '')
        self.workspace.save('normal', 'services: {}', '')
        config = self.workspace.root / 'normal' / 'compose.yaml'
        config.unlink()
        config.symlink_to(outside / 'secret')
        with self.assertRaises(ValueError):
            self.workspace.save('normal', 'services: {}', '')

    def test_busy_workspace_rejects_saves(self):
        self.workspace.lock.acquire()
        try:
            with self.assertRaises(BlockingIOError):
                self.workspace.save('test', 'services: {}', '')
        finally:
            self.workspace.lock.release()

    def test_project_directory_keeps_host_path_spelling(self):
        source = Path(self.temp.name) / 'host-path'
        source.symlink_to(self.workspace.root.parent)
        workspace = module.Workspace(source)
        workspace.save('test', 'services: {}', 'KEY=value\n')
        command = workspace.command('test', 'up', '-d')
        self.assertIn(str(source / 'stacks' / 'test'), command)
        self.assertEqual(command[command.index('--project-name') + 1], 'cs_test')
        self.assertNotIn('SUPERVISOR_TOKEN', module.DOCKER_ENV)

    def test_invalid_compose_prevents_up(self):
        self.workspace.save('test', 'broken', '')
        with patch.object(module, 'run_command', return_value={'code': 1, 'output': 'invalid'}) as run:
            job = self.workspace.start('test', 'up')
            self.workspace.lock.acquire(timeout=3)
            self.workspace.lock.release()
            self.assertEqual(self.workspace.job(job['id'])['state'], 'failed')
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[0][-2:], ['config', '--quiet'])


class IngressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = module.ThreadingHTTPServer(('127.0.0.1', 0), module.Handler)
        self.server.workspace = module.Workspace(Path(self.temp.name))
        self.server.compose_version = '2.test'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.temp.cleanup()

    def request(self, method, path, data=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        conn.request(method, path, body=None if data is None else json.dumps(data), headers=headers or {})
        response = conn.getresponse()
        result = (response.status, response.read())
        conn.close()
        return result

    def test_untrusted_ip_denied_even_with_forged_forwarded_header(self):
        code, _ = self.request('GET', '/', headers={'X-Forwarded-For': module.INGRESS_IP})
        self.assertEqual(code, 403)

    def test_tokens_and_cross_site_protection(self):
        with patch.object(module, 'INGRESS_IP', '127.0.0.1'):
            code, body = self.request('GET', '/')
            self.assertEqual(code, 200)
            self.assertIn(module.TOKEN.encode(), body)
            code, _ = self.request('GET', '/api/projects')
            self.assertEqual(code, 403)
            auth = {'X-Compose-Token': module.TOKEN, 'Content-Type': 'application/json'}
            code, _ = self.request('POST', '/api/projects/example', {'compose': 'services: {}', 'env': ''}, auth)
            self.assertEqual(code, 200)
            code, body = self.request('GET', '/api/projects/example', headers=auth)
            self.assertEqual(code, 200)
            self.assertEqual(json.loads(body)['compose'], 'services: {}')
            code, _ = self.request('GET', '/api/projects', headers={**auth, 'Sec-Fetch-Site': 'cross-site'})
            self.assertEqual(code, 403)


if __name__ == '__main__':
    unittest.main()
