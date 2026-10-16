"""Cross-platform student launcher. Run via platform-specific launch script."""
import getpass
import os
import pathlib
import platform
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.request
import venv

ROOT = pathlib.Path(__file__).resolve().parent
BIN = ROOT / 'tools'
SYSTEM = platform.system()
ARCH = platform.machine().lower()


def download_cloudflared():
    BIN.mkdir(exist_ok=True)
    executable = BIN / ('cloudflared.exe' if SYSTEM == 'Windows' else 'cloudflared')
    if executable.exists():
        return executable
    if SYSTEM == 'Windows':
        filename = 'cloudflared-windows-amd64.exe' if ARCH in ('amd64', 'x86_64') else 'cloudflared-windows-arm64.exe'
    elif SYSTEM == 'Darwin':
        filename = 'cloudflared-darwin-arm64.tgz' if ARCH in ('arm64', 'aarch64') else 'cloudflared-darwin-amd64.tgz'
    elif SYSTEM == 'Linux':
        filename = {'x86_64': 'cloudflared-linux-amd64', 'amd64': 'cloudflared-linux-amd64',
                    'aarch64': 'cloudflared-linux-arm64', 'arm64': 'cloudflared-linux-arm64',
                    'armv7l': 'cloudflared-linux-arm'}.get(ARCH)
        if not filename:
            raise RuntimeError(f'Unsupported Linux CPU architecture: {ARCH}')
    else:
        raise RuntimeError(f'Unsupported operating system: {SYSTEM}')
    url = 'https://github.com/cloudflare/cloudflared/releases/latest/download/' + filename
    print('Downloading Cloudflare Tunnel from its official GitHub release...')
    try:
        if filename.endswith('.tgz'):
            import tarfile
            archive = BIN / 'cloudflared.tgz'
            urllib.request.urlretrieve(url, archive)
            with tarfile.open(archive, 'r:gz') as tar:
                member = next((m for m in tar.getmembers() if m.isfile() and pathlib.PurePosixPath(m.name).name == 'cloudflared'), None)
                if not member:
                    raise RuntimeError('Cloudflared binary missing from archive')
                with tar.extractfile(member) as source, executable.open('wb') as dest:
                    shutil.copyfileobj(source, dest)
            archive.unlink()
        else:
            urllib.request.urlretrieve(url, executable)
        if SYSTEM != 'Windows':
            executable.chmod(0o755)
        subprocess.run([str(executable), '--version'], check=True, stdout=subprocess.DEVNULL)
    except Exception:
        executable.unlink(missing_ok=True)
        raise
    return executable


def main():
    if sys.version_info < (3, 9):
        raise RuntimeError('Python 3.9+ is required; install Python 3.11 and try again.')
    print(f'=== Peerbots Phone Microphone | {SYSTEM} / Python {sys.version.split()[0]} ===')
    envdir = ROOT / '.venv'
    py = envdir / ('Scripts/python.exe' if SYSTEM == 'Windows' else 'bin/python')
    if not py.exists():
        print('Creating Python virtual environment...')
        venv.EnvBuilder(with_pip=True).create(envdir)
    print('Installing Python dependencies...')
    subprocess.run([str(py), '-m', 'pip', 'install', '--upgrade', 'pip'], check=True)
    subprocess.run([str(py), '-m', 'pip', 'install', '-r', str(ROOT / 'requirements.txt')], check=True)
    tunnel = download_cloudflared()
    tokenfile = ROOT / '.peerbots_token'
    if not tokenfile.exists():
        tokenfile.write_text(secrets.token_urlsafe(32), encoding='utf-8')
        if SYSTEM != 'Windows':
            tokenfile.chmod(0o600)
    token = tokenfile.read_text(encoding='utf-8').strip()
    # Load optional local credentials without overriding explicitly supplied environment variables.
    dotenv = ROOT / '.env'
    if dotenv.is_file():
        for raw in dotenv.read_text(encoding='utf-8-sig').splitlines():
            line = raw.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            if key in ('OPENAI_API_KEY', 'PEERBOTS_API_KEY', 'PEERBOTS_USERNAME') and value:
                os.environ.setdefault(key, value)
    api_key = os.environ.get('OPENAI_API_KEY', '').strip()
    if not api_key:
        api_key = getpass.getpass('Paste your OpenAI API key (not saved to disk): ').strip()
    if not api_key:
        raise RuntimeError('An OpenAI API key is required.')
    peerbots_key = os.environ.get('PEERBOTS_API_KEY', '').strip()
    if not peerbots_key:
        peerbots_key = getpass.getpass('Paste your Peerbots API key (not saved to disk): ').strip()
    username = os.environ.get('PEERBOTS_USERNAME', '').strip()
    if not username:
        username = input('Peerbots face username or email: ').strip()
    if not peerbots_key or not username:
        raise RuntimeError('Peerbots API key and face username are required.')
    env = os.environ.copy()
    env.update(OPENAI_API_KEY=api_key, PEERBOTS_API_KEY=peerbots_key, PEERBOTS_USERNAME=username, PEERBOTS_TOKEN=token, PORT='8443')
    # Server deliberately listens on loopback only; cloudflared provides browser-trusted HTTPS.
    serverlog = (ROOT / 'peerbots_server.log').open('w', encoding='utf-8')
    tunnellog = (ROOT / 'peerbots_tunnel.log').open('w', encoding='utf-8')
    server = tunnelproc = None
    try:
        server = subprocess.Popen([str(py), '-u', str(ROOT / 'server.py')], cwd=ROOT,
                                  env=env, stdout=serverlog, stderr=subprocess.STDOUT)
        tunnelproc = subprocess.Popen([str(tunnel), 'tunnel', '--no-autoupdate', '--url',
                                       'http://127.0.0.1:8443'], cwd=ROOT,
                                      stdout=tunnellog, stderr=subprocess.STDOUT)
        print('Starting secure tunnel (may take up to 60 seconds)...')
        url = None
        for _ in range(60):
            if server.poll() is not None:
                raise RuntimeError('Python server stopped. See peerbots_server.log')
            if tunnelproc.poll() is not None:
                raise RuntimeError('Cloudflare Tunnel stopped. See peerbots_tunnel.log')
            tunnellog.flush()
            contents = (ROOT / 'peerbots_tunnel.log').read_text(encoding='utf-8', errors='replace')
            match = re.search(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', contents)
            if match:
                url = match.group(0)
                break
            time.sleep(1)
        if not url:
            raise RuntimeError('Tunnel URL not found. See peerbots_tunnel.log')
        print('\n' + '=' * 65)
        print('OPEN THIS URL ON THE PHONE:')
        print(f'{url}/?token={token}')
        print('=' * 65)
        print('Tap Enable microphone; Peerbots face remains visible.')
        print('Keep this window open. Press Ctrl+C to stop.')
        print('Audio traverses Cloudflare; Google ASR and OpenAI also use internet.')
        print('Keep the tokenized URL private. Do not share the logs or token.')
        while server.poll() is None and tunnelproc.poll() is None:
            time.sleep(1)
        raise RuntimeError('Server or tunnel stopped; check peerbots_server.log / peerbots_tunnel.log')
    except KeyboardInterrupt:
        print('\nStopping...')
    finally:
        for process in (tunnelproc, server):
            if process and process.poll() is None:
                process.terminate()
        for process in (tunnelproc, server):
            if process:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
        serverlog.close()
        tunnellog.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'\nSETUP ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
