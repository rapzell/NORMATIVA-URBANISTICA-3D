from __future__ import annotations
import csv
from typing import Optional
import logging
from pathlib import Path
from .base import PlanParams


class CSVPlanProvider:
    def __init__(self, csv_path: str | Path):
        self.path = Path(csv_path)
        self.rows: list[dict] = []
        if not self.path.exists():
            raise FileNotFoundError(f"CSV no encontrado: {self.path}")
        with open(self.path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            # Validate required headers
            required = {'municipio'}
            present = set((reader.fieldnames or []))
            missing = sorted(list(required - present))
            if missing:
                raise ValueError(f"CSV faltan columnas requeridas: {', '.join(missing)}")
            # Warn for unknown/unsupported columns
            allowed = {
                'municipio','subzona','altura_maxima_m','retranqueo_min_m',
                'setback_front_m','setback_side_m','setback_back_m',
                'front_direction_default','ocupacion_max','edificabilidad_max_m2_m2'
            }
            unknown = sorted(list(present - allowed))
            if unknown:
                logging.getLogger(__name__).warning(
                    "Columnas desconocidas en CSV %s: %s", str(self.path), ", ".join(unknown)
                )
            for r in reader:
                # normalizar claves mínimas
                r2 = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in r.items()}
                self.rows.append(r2)

    def get(self, municipio: str, subzona: Optional[str] = None) -> PlanParams:
        m = (municipio or '').strip().lower()
        s = (subzona or '').strip().lower() if subzona else None
        candidate_specific: dict | None = None
        candidate_default: dict | None = None
        # Recoger mejor fila específica y mejor fila por defecto (subzona vacía)
        for r in self.rows:
            rm = (r.get('municipio') or '').strip().lower()
            rs_raw = (r.get('subzona') or '').strip()
            rs = rs_raw.lower() if rs_raw else ''
            if rm != m:
                continue
            if s is not None:
                if rs and rs == s:
                    candidate_specific = r
                    break  # match exacto
            else:
                # Sin subzona solicitada: preferir subzona vacía
                if rs == '' and candidate_default is None:
                    candidate_default = r
                # Guardar una específica solo si no hay default; pero no sobrescribir default
                if rs and candidate_specific is None:
                    candidate_specific = r

        best = candidate_specific if s is not None else (candidate_default or candidate_specific)
        
        if best is None:
            return PlanParams(municipio=municipio, subzona=subzona)
        def _float(v):
            try:
                return float(v) if v not in (None, '') else None
            except Exception:
                return None
        # Validar y normalizar front_direction_default
        raw_fd = (best.get('front_direction_default') or '').strip()
        fd_norm: str | None
        if raw_fd == '':
            fd_norm = None
        else:
            fd_norm = raw_fd.lower()
            allowed = {'north', 'east', 'south', 'west'}
            if fd_norm not in allowed:
                raise ValueError(
                    f"front_direction_default inválido en CSV para {municipio}{' - ' + subzona if subzona else ''}: '{raw_fd}'. Valores permitidos: north|east|south|west"
                )

        # Parse directional setbacks first to allow consistency validation
        sf = _float(best.get('setback_front_m'))
        ss = _float(best.get('setback_side_m'))
        sb = _float(best.get('setback_back_m'))
        has_any_dir = any(v is not None for v in (sf, ss, sb))
        if fd_norm is not None and not has_any_dir:
            raise ValueError(
                f"CSV inconsistente para {municipio}{' - ' + subzona if subzona else ''}: front_direction_default definido ('{raw_fd}') pero no hay retranqueos direccionales (setback_front_m/setback_side_m/setback_back_m)."
            )

        # Range validations
        altura = _float(best.get('altura_maxima_m'))
        retranqueo_min = _float(best.get('retranqueo_min_m'))
        for name, val, cond, msg in (
            ('altura_maxima_m', altura, (altura is None) or (altura <= 0), "altura_maxima_m debe ser > 0"),
        ):
            if cond:
                if name == 'altura_maxima_m' and altura is None:
                    raise ValueError(f"altura_maxima_m requerida en CSV para {municipio}{' - ' + subzona if subzona else ''}")
                raise ValueError(f"Valor inválido en CSV para {municipio}{' - ' + subzona if subzona else ''}: {msg}")

        if retranqueo_min is not None and retranqueo_min < 0:
            raise ValueError(f"Valor inválido en CSV para {municipio}{' - ' + subzona if subzona else ''}: retranqueo_min_m debe ser >= 0")
        for label, val in (('setback_front_m', sf), ('setback_side_m', ss), ('setback_back_m', sb)):
            if val is not None and val < 0:
                raise ValueError(f"Valor inválido en CSV para {municipio}{' - ' + subzona if subzona else ''}: {label} debe ser >= 0")

        # Additional optional constraints
        ocupacion = _float(best.get('ocupacion_max'))
        if ocupacion is not None and not (0 <= ocupacion <= 1):
            raise ValueError(f"Valor inválido en CSV para {municipio}{' - ' + subzona if subzona else ''}: ocupacion_max debe estar en [0,1]")
        edificabilidad = _float(best.get('edificabilidad_max_m2_m2'))
        if edificabilidad is not None and edificabilidad < 0:
            raise ValueError(f"Valor inválido en CSV para {municipio}{' - ' + subzona if subzona else ''}: edificabilidad_max_m2_m2 debe ser >= 0")

        return PlanParams(
            municipio=municipio,
            subzona=subzona,
            altura_maxima_m=altura,
            retranqueo_min_m=retranqueo_min,
            setback_front_m=sf,
            setback_side_m=ss,
            setback_back_m=sb,
            front_direction_default=fd_norm,
            ocupacion_max=ocupacion,
            edificabilidad_max_m2_m2=edificabilidad,
            source='csv',
        )
