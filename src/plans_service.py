import logging
import os
from typing import Optional

_PLAN_PROVIDER_CACHE = {
    "provider": None,
    "kind": None,
}


def get_plan_provider():
    """Devuelve una instancia de proveedor de planes según variables de entorno."""
    kind = (os.getenv("PLAN_PROVIDER", "") or "").strip().lower() or "csv"
    cached = _PLAN_PROVIDER_CACHE.get("provider")
    if cached is not None and _PLAN_PROVIDER_CACHE.get("kind") == kind:
        return cached

    if kind == "csv":
        try:
            from src.planes.csv_provider import CSVPlanProvider
            csv_path = os.getenv("PLAN_CSV_PATH") or os.path.join("datos", "plan_uploaded.csv")
            prov = CSVPlanProvider(csv_path)
            _PLAN_PROVIDER_CACHE.update({"provider": prov, "kind": kind})
            logging.getLogger(__name__).info("PLAN_PROVIDER=csv usando %s", csv_path)
            return prov
        except Exception as e:
            logging.getLogger(__name__).warning("Fallo iniciando CSVPlanProvider: %s. Cayendo a mock.", e)
            kind = "mock"

    try:
        from src.planes import mock_provider as _mp

        class _MockProvider:
            def get(self, municipio: str, subzona: str | None = None):
                return _mp.get_plan_params(municipio, subzona)

        prov = _MockProvider()
    except Exception:
        class _EmptyProvider:
            def get(self, municipio: str, subzona: str | None = None):
                from src.planes.base import PlanParams
                return PlanParams(municipio=municipio, subzona=subzona)

        prov = _EmptyProvider()

    _PLAN_PROVIDER_CACHE.update({"provider": prov, "kind": "mock"})
    logging.getLogger(__name__).info("PLAN_PROVIDER=mock (fallback)")
    return prov


def get_plan_provider_kind() -> str:
    return _PLAN_PROVIDER_CACHE.get("kind") or "unknown"


def get_plan_params_dynamic(municipio: Optional[str], subzona: Optional[str]):
    """Obtiene parámetros del plan de manera dinámica usando el proveedor activo."""
    from src.planes.base import PlanParams

    muni = (municipio or "").strip()
    subz = (subzona or None)
    prov = get_plan_provider()
    try:
        params = prov.get(muni, subz)
        if not isinstance(params, PlanParams):
            if hasattr(params, 'model_dump'):
                params = PlanParams(**params.model_dump())
            else:
                params = PlanParams(**(params or {}))

        def _has_core_values(p: PlanParams) -> bool:
            return (getattr(p, "altura_maxima_m", None) is not None) or (getattr(p, "retranqueo_min_m", None) is not None)

        mlow = muni.lower()
        if not _has_core_values(params) and ("vigo" in mlow):
            try:
                from src.planes.csv_provider import CSVPlanProvider
                for alt_csv in (
                    os.path.join("datos", "planes_Vigo_residencial_clean.csv"),
                    os.path.join("datos", "planes_Vigo_residencial.csv"),
                    os.path.join("datos", "planes_vigo_boiro.csv"),
                ):
                    try:
                        if os.path.isfile(alt_csv):
                            altp = CSVPlanProvider(alt_csv).get(muni, subz)
                            if not isinstance(altp, PlanParams):
                                if hasattr(altp, 'model_dump'):
                                    altp = PlanParams(**altp.model_dump())
                                else:
                                    altp = PlanParams(**(altp or {}))
                            if _has_core_values(altp):
                                logging.getLogger(__name__).info("Proveedor CSV alternativo aplicado: %s", alt_csv)
                                return altp
                    except Exception:
                        continue
            except Exception:
                pass
        return params
    except Exception as e:
        logging.getLogger(__name__).warning("get_plan_params_dynamic error: %s", e)
        return PlanParams(municipio=muni, subzona=subz)
