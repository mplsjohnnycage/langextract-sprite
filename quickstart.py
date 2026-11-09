#!/usr/bin/env python3
"""Local installer and personalized ChatGPT plugin bundle generator."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import shutil
import sys
import venv
import zipfile

ROOT = Path(__file__).resolve().parent


def build_bundle(sprite, project_dir, output):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', sprite):
        raise ValueError('Sprite name must use letters, numbers, dot, underscore or hyphen')
    if not project_dir.startswith('/') or '\n' in project_dir or '\r' in project_dir:
        raise ValueError('Sprite project directory must be an absolute Unix path')
    output = Path(output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((ROOT / 'plugin').rglob('*')):
            if not path.is_file():
                continue
            data = path.read_text(encoding='utf-8')
            data = data.replace('YOUR_AUTHORIZED_SPRITE', sprite)
            data = data.replace('/path/to/langextract-sprite', project_dir.rstrip('/'))
            archive.writestr(path.relative_to(ROOT / 'plugin').as_posix(), data)
    return output


def install_runtime():
    env = ROOT / '.venv'
    if not env.exists():
        venv.EnvBuilder(with_pip=True).create(env)
    python = env / 'bin' / 'python'
    if shutil.which('uv'):
        subprocess.run(['uv', 'pip', 'install', '--python', str(python), '-e', str(ROOT)], check=True)
    else:
        subprocess.run([str(python), '-m', 'ensurepip', '--upgrade'], check=True)
        subprocess.run([str(python), '-m', 'pip', 'install', '-e', str(ROOT)], check=True)
    return python


def doctor(python):
    cmd = [str(python), '-m', 'bridge.tools', json.dumps({'tool': 'tools.list', 'arguments': {}})]
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    payload = json.loads(result.stdout)
    if not payload.get('ok') or len(payload.get('tools', [])) != 8:
        raise RuntimeError('Dispatcher health check failed')
    print('PASS: eight Sprite-side operations available')


def main():
    parser = argparse.ArgumentParser(description='Install LangExtract Sprite and generate a personalized ChatGPT plugin ZIP')
    parser.add_argument('--sprite', help='Existing authenticated Fly Sprite name')
    parser.add_argument('--project-dir', default=str(ROOT), help='Absolute path of checkout ON the Sprite')
    parser.add_argument('--output', default='dist/langextract-sprite-chatgpt-plugin.zip')
    parser.add_argument('--bundle-only', action='store_true', help='Generate plugin without installing Python dependencies')
    args = parser.parse_args()
    sprite = args.sprite
    if not sprite:
        if not sys.stdin.isatty():
            parser.error('--sprite is required for noninteractive use')
        sprite = input('Existing authorized Sprite name: ').strip()
    try:
        if not args.bundle_only:
            python = install_runtime()
            doctor(python)
        output = build_bundle(sprite, args.project_dir, args.output)
    except (ValueError, RuntimeError, subprocess.CalledProcessError, OSError) as exc:
        parser.exit(1, f'ERROR: {exc}\n')
    print(f'Plugin ZIP: {output}')
    print('Next: upload the ZIP as a ChatGPT plugin, connect/authorize Fly Sprites, and run an extraction.')
    print('Note: the bundle does not automatically install or authorize a ChatGPT plugin.')


if __name__ == '__main__':
    main()
