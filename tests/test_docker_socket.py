import importlib.util
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

APP = Path(__file__).parents[1] / 'compose_studio' / 'app' / 'server.py'
sys.path.insert(0, str(APP.parent))
spec = importlib.util.spec_from_file_location('socket_server_test', APP)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class DockerSocketTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.primary = self.root / 'run/docker.sock'
        self.legacy = self.root / 'var/run/docker.sock'
        for path in (self.primary, self.legacy):
            path.parent.mkdir(parents=True)
        self.paths = patch.object(server, 'DOCKER_SOCKET_PATHS', (self.primary, self.legacy))
        self.paths.start()
        self.environment = patch.dict(server.DOCKER_ENV)
        self.environment.start()
        self.sockets = []

    def tearDown(self):
        for sock in self.sockets:
            sock.close()
        self.environment.stop()
        self.paths.stop()
        self.temp.cleanup()

    def bind(self, path):
        sock = socket.socket(socket.AF_UNIX)
        sock.bind(str(path))
        self.sockets.append(sock)

    def test_supervisor_run_socket_does_not_require_var_run_alias(self):
        self.bind(self.primary)
        server.require_docker_socket()
        self.assertEqual(server.DOCKER_ENV['DOCKER_HOST'], 'unix://' + str(self.primary))
        self.assertFalse(self.legacy.exists())

    def test_legacy_socket_is_supported(self):
        self.bind(self.legacy)
        server.require_docker_socket()
        self.assertEqual(server.DOCKER_ENV['DOCKER_HOST'], 'unix://' + str(self.legacy))

    def test_regular_file_is_not_a_docker_socket(self):
        self.primary.touch()
        self.bind(self.legacy)
        self.assertEqual(server.require_docker_socket(), self.legacy)

    def test_missing_mount_has_actionable_message_without_running_docker(self):
        with patch.object(server, 'run_command') as run:
            with self.assertRaisesRegex(server.DockerConnectionError, 'Schutzmodus'):
                server.discover_data_source()
        run.assert_not_called()

    def test_present_but_unreachable_socket_has_distinct_diagnostic(self):
        self.bind(self.primary)
        with patch.object(server, 'run_command', return_value={'code': 1, 'output': 'permission denied'}):
            with self.assertRaises(server.DockerConnectionError) as error:
                server.discover_data_source()
        self.assertIn('eingebunden', str(error.exception))
        self.assertIn('permission denied', str(error.exception))
        self.assertNotIn('kein Docker-Socket', str(error.exception))


if __name__ == '__main__':
    unittest.main()
