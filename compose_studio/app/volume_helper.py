"""Fixed-purpose helper: copy a stopped legacy Docker volume with ownership."""
import subprocess

producer = subprocess.Popen(['tar', '-cpf', '-', '-C', '/from', '.'], stdout=subprocess.PIPE)
try:
    consumer = subprocess.run(['tar', '-xpf', '-', '-C', '/to'], stdin=producer.stdout)
    producer.stdout.close()
    code = producer.wait()
    if code or consumer.returncode:
        raise SystemExit(1)
finally:
    if producer.poll() is None:
        producer.kill()
        producer.wait()
