"""Descarga los datos mínimos de la beta desde el dataset público HF.

Los datos no van en git (170 MB): viven en el dataset
`DavidVRM/normativa-galicia-data` y este script los baja a `datos/`
al arrancar el contenedor (Render/Space). Idempotente: si ya existen,
no descarga nada salvo que se pase --forzar.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = os.getenv('BETA_DATA_REPO', 'DavidVRM/normativa-galicia-data')
DATOS = Path('datos')

# Marca de datos completos: el índice de ordenanzas extraído y el
# índice de ámbitos son lo último que se necesita en runtime.
_MARKERS = [
    DATOS / 'normativa/36057/_ordenanzas.json',
    DATOS / 'normativa/36057/ambitos.json',
    DATOS / 'corpus/_corpus_index.json',
    DATOS / 'inventario_planeamento.csv',
    DATOS / 'subzonas_piloto.geojson',
]


def main() -> int:
    forzar = '--forzar' in sys.argv
    if not forzar and all(m.exists() for m in _MARKERS):
        print('[beta-data] datos ya presentes — sin descarga')
        return 0
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print('[beta-data] huggingface_hub no instalado — sin datos')
        return 1
    print(f'[beta-data] descargando dataset {REPO} → datos/')
    snapshot_download(REPO, repo_type='dataset', local_dir=str(DATOS))
    ok = all(m.exists() for m in _MARKERS)
    print('[beta-data] descarga', 'completa' if ok else 'INCOMPLETA')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
