"""Sube la beta a un Hugging Face Space (SDK docker).

Uso:
    pip install huggingface_hub
    set HF_TOKEN=hf_xxx          # token con permiso write
    set BETA_PASSWORD=tu-clave   # contraseña única de la beta
    set OPENROUTER_API_KEY=sk-or-xxx   # opcional: activa el asistente LLM
    venv\\Scripts\\python.exe deploy\\hf\\upload_space.py <usuario>/<nombre-space>

Sube: código (app/, src/, web/, scripts/, Dockerfile) + datos mínimos
(corpus RAG, normativa 36057, inventario, subzonas piloto, esquema de
ordenanzas). La caché de capas se regenera sola en el Space.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

CODE_IGNORE = [
    '.git', '.gitignore', 'venv*', 'tests', 'docs', 'deploy',
    '__pycache__', '*.pyc', 'api.txt', 'datos', 'node_modules',
    '.vscode', '.idea', 'README.md',
]

DATA_UPLOADS = [
    ('datos/corpus', 'datos/corpus'),
    ('datos/normativa/36057', 'datos/normativa/36057'),
    ('datos/ordenanzas', 'datos/ordenanzas'),
]

DATA_FILES = [
    'datos/inventario_planeamento.csv',
    'datos/subzonas_piloto.geojson',
]


def main() -> int:
    if len(sys.argv) != 2 or '/' not in sys.argv[1]:
        print('uso: upload_space.py <usuario>/<nombre-space>')
        return 2
    space_id = sys.argv[1]
    token = os.getenv('HF_TOKEN', '').strip()
    if not token:
        print('Falta HF_TOKEN (token de Hugging Face con permiso write).')
        return 2

    from huggingface_hub import HfApi
    api = HfApi(token=token)

    print(f'== Creando Space {space_id} (docker, privado)')
    api.create_repo(space_id, repo_type='space', space_sdk='docker',
                    private=True, exist_ok=True)

    print('== Subiendo código')
    api.upload_folder(repo_id=space_id, repo_type='space',
                      folder_path=str(ROOT), path_in_repo='',
                      ignore_patterns=CODE_IGNORE)

    for local, remote in DATA_UPLOADS:
        src = ROOT / local
        if src.is_dir():
            print(f'== Subiendo {local}')
            api.upload_folder(repo_id=space_id, repo_type='space',
                              folder_path=str(src), path_in_repo=remote)
    for rel in DATA_FILES:
        src = ROOT / rel
        if src.is_file():
            print(f'== Subiendo {rel}')
            api.upload_file(repo_id=space_id, repo_type='space',
                            path_or_fileobj=str(src), path_in_repo=rel)

    print('== Subiendo README del Space')
    api.upload_file(repo_id=space_id, repo_type='space',
                    path_or_fileobj=str(ROOT / 'deploy/hf/README_SPACE.md'),
                    path_in_repo='README.md')

    beta_pw = os.getenv('BETA_PASSWORD', '').strip()
    if beta_pw:
        api.add_space_secret(space_id, 'BETA_PASSWORD', beta_pw)
        print('== Secret BETA_PASSWORD configurado')
    else:
        print('!! Sin BETA_PASSWORD — el Space quedará abierto')

    orkey = os.getenv('OPENROUTER_API_KEY', '').strip()
    if orkey:
        api.add_space_secret(space_id, 'OPENROUTER_API_KEY', orkey)
        api.add_space_variable(space_id, 'MODEL_PROVIDER', 'openrouter')
        print('== Secret OPENROUTER_API_KEY + MODEL_PROVIDER=openrouter')
    else:
        print('!! Sin OPENROUTER_API_KEY — el asistente responderá sin LLM')

    print(f'\nSpace: https://huggingface.co/spaces/{space_id}')
    print('La primera build tarda varios minutos. Cuando esté "Running",')
    print('la URL pública será https://<usuario>-<nombre>.hf.space/geolibre/')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
