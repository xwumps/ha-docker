"""Native Docker checks included in integration.py (reserved test names only)."""
import base64
import io
import json
import shlex
import time
import urllib.request
import zipfile

BASIC = 'native-integration'
BUILT = 'native-built'
DOCKERFILE = '''FROM busybox:1.37.0
COPY entrypoint.sh /entrypoint.sh
RUN /entrypoint.sh
COPY marker /marker
VOLUME /persistent
CMD ["sh", "-c", "echo built-log-ok; exec sleep 300"]
'''


class NativeChecks:
    def __init__(self, request, docker, app_name):
        self.request, self.docker, self.app_name = request, docker, app_name
        self.image_id = None

    def action(self, name, action, command=''):
        job = self.request('api/docker/containers/' + name + '/actions', {'action': action, 'command': command})
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            result = self.request('api/jobs/' + job['id'])
            if result['state'] != 'running':
                assert result['code'] == 0, result.get('output', '')[-4000:]
                return result['output']
            time.sleep(0.3)
        raise AssertionError('Native Docker operation timed out: ' + action)

    def setup(self):
        script = 'mkdir -p /www; printf "%s" "$NOTE" > /www/index.html; echo native-log-ok; exec httpd -f -p 8080 -h /www'
        command = ['docker', 'run', '-d', '--init', '--name', BASIC, '-p', '127.0.0.1:18091:8080',
                   '-e', 'NOTE=native-ok', '-v', 'native-integration-data:/data',
                   'busybox:1.37.0', 'sh', '-c', script]
        parsed = self.request('api/docker/parse', {'command': shlex.join(command)})
        self.request('api/docker/containers/' + BASIC, {'config': parsed['config']})
        self.action(BASIC, 'up')
        with urllib.request.urlopen('http://127.0.0.1:18091', timeout=10) as response:
            assert response.read().decode() == 'native-ok'
        assert 'native-log-ok' in self.action(BASIC, 'logs')
        self.action(BASIC, 'exec', "sh -c 'echo snapshot-data > /data/durable'")
        self.action(BASIC, 'stop')
        self.action(BASIC, 'restart')
        self.action(BASIC, 'status')
        desired = parsed['config']
        desired['env']['NOTE'] = 'draft-not-applied'
        self.request('api/docker/containers/' + BASIC, {'config': desired})
        print('PASS native docker run import, HTTP port, env, named volume, logs, exec, stop/restart', flush=True)
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('source/Dockerfile', DOCKERFILE)
            z.writestr('source/marker', 'source-context-ok')
            script = zipfile.ZipInfo('source/entrypoint.sh')
            script.create_system = 3
            script.external_attr = 0o100755 << 16
            z.writestr(script, '#!/bin/sh\nprintf build-ran > /built-proof\n')
        imported = self.request('api/docker/import', {'name': BUILT, 'archive': base64.b64encode(archive.getvalue()).decode()})
        config = imported['config']
        config['init'] = True
        self.request('api/docker/containers/' + BUILT, {'config': config})
        self.action(BUILT, 'up')
        assert self.action(BUILT, 'exec', 'cat /built-proof').strip() == 'build-ran'
        assert self.action(BUILT, 'exec', 'cat /marker').strip() == 'source-context-ok'
        self.action(BUILT, 'exec', "sh -c 'echo image-volume-data > /persistent/record'")
        runtime = json.loads(self.docker('exec', self.app_name, 'cat', '/data/containers/' + BUILT + '/.studio-native-runtime.json'))
        self.image_id = runtime['image_id']
        assert runtime['archive_image'] and len(runtime['volumes']) == 1
        print('PASS Dockerfile build with RUN/COPY, implicit VOLUME persistence and local image archive', flush=True)

    def assert_stopped(self):
        for name in (BASIC, BUILT):
            assert self.docker('inspect', 'hd_' + name, '--format', '{{.State.Running}}') == 'false'

    def after_backup(self):
        assert self.action(BASIC, 'exec', 'printenv NOTE').strip() == 'native-ok'
        self.action(BASIC, 'exec', "sh -c 'echo later-data > /data/durable'")
        self.action(BUILT, 'exec', "sh -c 'echo later-data > /persistent/record'")
        self.action(BASIC, 'remove')
        self.action(BUILT, 'remove')
        self.docker('image', 'rm', 'ha-docker/' + BUILT + ':local')
        missing = self.docker('image', 'inspect', self.image_id, check=False)
        assert 'no such' in missing.lower(), missing
        print('PASS native removal retains data; custom image removed to exercise backup image load', flush=True)

    def after_restore(self):
        assert self.action(BASIC, 'exec', 'cat /data/durable').strip() == 'snapshot-data'
        assert self.action(BASIC, 'exec', 'printenv NOTE').strip() == 'native-ok'
        assert self.request('api/docker/containers/' + BASIC)['config']['env']['NOTE'] == 'draft-not-applied'
        assert self.action(BUILT, 'exec', 'cat /persistent/record').strip() == 'image-volume-data'
        assert self.action(BUILT, 'exec', 'cat /built-proof').strip() == 'build-ran'
        assert self.docker('inspect', 'hd_' + BUILT, '--format', '{{.Image}}') == self.image_id
        self.request('api/docker/containers/' + BUILT + '/files', {'path': 'Dockerfile', 'content': base64.b64encode(DOCKERFILE.encode()).decode()})
        print('PASS native restore: data, last applied env, automatic image volumes, exact local image without rebuild', flush=True)
