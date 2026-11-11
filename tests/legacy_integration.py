"""Run against tests/integration.py's retained deployment to test 0.1 volume migration."""
import json
import re
import time
import integration as it

NAME = 'legacy-volume-probe'
OLD = 'cs_' + NAME + '_db'


def main():
    it.token = re.search(r'name="compose-token" content="([^"]+)"', it.request(authenticated=False))[1]
    config = {'services': {'db': {'image': 'busybox:1.37.0', 'command': ['sleep', '300'],
        'volumes': ['db:/data']}}, 'volumes': {'db': {}}}
    project = it.request('api/projects/' + NAME, {'compose': json.dumps(config), 'env': ''})
    it.docker('volume', 'create', '--label', 'com.docker.compose.project=cs_' + NAME, OLD)
    it.docker('run', '--rm', '--mount', f'type=volume,src={OLD},dst=/data', 'busybox:1.37.0',
              'sh', '-c', 'echo original > /data/important.db; chown 123:456 /data/important.db; chmod 640 /data/important.db')
    it.docker('exec', it.APP_NAME, 'docker', 'compose', '-p', 'cs_' + NAME,
              '--project-directory', project['host_path'], '--env-file', project['host_path'] + '/.env',
              '-f', project['host_path'] + '/compose.yaml', 'up', '-d')
    job = it.request('api/projects/' + NAME + '/actions', {'action': 'up'})
    for attempt in range(600):
        result = it.request('api/jobs/' + job['id'])
        if result['state'] != 'running':
            assert result['code'] == 0, result['output'][-2000:]
            break
        time.sleep(0.2)
    else:
        raise AssertionError('Migration timed out')
    container = 'cs_' + NAME + '-db-1'
    assert it.docker('exec', container, 'cat', '/data/important.db') == 'original'
    assert it.docker('exec', container, 'stat', '-c', '%u:%g %a', '/data/important.db') == '123:456 640'
    it.docker('exec', container, 'sh', '-c', 'echo updated > /data/important.db')
    assert it.docker('run', '--rm', '--mount', f'type=volume,src={OLD},dst=/data,readonly',
                     'busybox:1.37.0', 'cat', '/data/important.db') == 'original'
    print('PASS legacy migration: data copied, UID/GID/mode preserved, original volume retained unchanged', flush=True)
    ids = it.docker('ps', '-aq', '--filter', 'label=com.docker.compose.project=cs_' + NAME).split()
    if ids:
        it.docker('rm', '-f', *ids)
    volumes = it.docker('volume', 'ls', '-q', '--filter', 'label=com.docker.compose.project=cs_' + NAME).split()
    if volumes:
        it.docker('volume', 'rm', *volumes)
    it.docker('network', 'rm', 'cs_' + NAME + '_default', check=False)


if __name__ == '__main__':
    main()
