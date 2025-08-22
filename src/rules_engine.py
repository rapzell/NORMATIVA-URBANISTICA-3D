from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field
import os


class ZoneInput(BaseModel):
    # Datos básicos + geometría GeoJSON (opcional)
    zona: str = Field(..., description="Tipo de zona: urbano, nucleo, urbanizable, rustico")
    uso_previsto: Optional[str] = Field(None, description="Uso previsto principal: residencial, dotacional, industrial, etc.")
    area_m2: Optional[float] = Field(None, ge=0)
    num_frentes: Optional[int] = Field(None, ge=0)
    geometry: Optional[dict] = Field(None, description="GeoJSON Geometry (Polygon/MultiPolygon)")
    crs: Optional[str] = Field(None, description="CRS de la geometría, p.ej. EPSG:3857")
    municipio: Optional[str] = Field(None, description="Municipio al que pertenece la parcela")
    subzona: Optional[str] = Field(None, description="Clave o subzona del planeamiento municipal")


class Restriccion(BaseModel):
    codigo: str
    descripcion: str
    fuente: str


class ZoningResult(BaseModel):
    zona_normalizada: str
    apto_residencial: Optional[bool]
    altura_maxima_m: Optional[float]
    retranqueo_min_m: Optional[float]
    observaciones: List[str] = []
    restricciones: List[Restriccion] = []


class GeometryReport(BaseModel):
    area: float
    perimeter: float
    bbox: tuple
    is_valid: bool
    is_simple: bool
    convex_hull_area: float
    convexity_ratio: float


def _norm_zona(z: str) -> str:
    zl = (z or '').strip().lower()
    if 'urbano' in zl and 'consolid' in zl:
        return 'urbano_consolidado'
    if 'urbano' in zl:
        return 'urbano'
    if 'nucleo' in zl or 'núcleo' in zl:
        return 'nucleo_rural'
    if 'urbanizable' in zl:
        return 'urbanizable'
    return 'rustico' if ('rustic' in zl or 'rústic' in zl or zl == 'rustico') else zl


def analizar_zonificacion(inp: ZoneInput) -> ZoningResult:
    """
    Lógica muy básica (MVP) apoyada en artículos clave:
    - Art. 27: Urbanizable orientado al crecimiento urbano (no fija alturas genéricas aquí)
    - Art. 31-32: Rústico restringe a usos compatibles; permite infraestructuras (Art. 32)
    - Art. 13 / 17: Definiciones de núcleo rural / urbano (consolidado)
    NOTA: Las alturas, retranqueos y parámetros finos dependen del planeamiento municipal.
    Este MVP devuelve valores placeholder conservadores más observaciones y fuentes.
    """
    z = _norm_zona(inp.zona)

    res = ZoningResult(
        zona_normalizada=z,
        apto_residencial=None,
        altura_maxima_m=None,
        retranqueo_min_m=None,
        observaciones=[],
        restricciones=[],
    )

    if z == 'urbanizable':
        # Requiere planeamiento que delimite sectores y programe actuaciones (Art. 27)
        res.apto_residencial = True if (inp.uso_previsto or '').lower().startswith('residen') else None
        res.observaciones.append(
            'El suelo urbanizable se destina al crecimiento urbano mediante planeamiento que delimita sectores y programa actuaciones (Art. 27).'
        )
        res.restricciones.append(Restriccion(
            codigo='ART27',
            descripcion='Transformación sujeta a planeamiento sectorizado/programado',
            fuente='Ley 2/2016 - Art. 27'
        ))
    elif z == 'nucleo_rural':
        # Asentamiento tradicional rural. Residencial posible, parámetros dependen de planeamiento
        res.apto_residencial = True if (inp.uso_previsto or '').lower().startswith('residen') else None
        res.observaciones.append('Suelo de núcleo rural: asentamiento tradicional rural con unidad funcional (Art. 13).')
        res.restricciones.append(Restriccion(
            codigo='ART13',
            descripcion='Condiciones específicas de núcleo rural según planeamiento municipal',
            fuente='Ley 2/2016 - Art. 13'
        ))
    elif z.startswith('urbano'):
        # Urbano / urbano consolidado. Parametrización fina por planeamiento
        res.apto_residencial = True if (inp.uso_previsto or '').lower().startswith('residen') else None
        if z == 'urbano_consolidado':
            res.observaciones.append('Suelo urbano consolidado: reúne o puede adquirir condición de solar (Art. 17).')
        else:
            res.observaciones.append('Suelo urbano: integrado en malla urbana y con servicios urbanísticos (Art. 17).')
        res.restricciones.append(Restriccion(
            codigo='ART17',
            descripcion='Condición de solar y servicios urbanísticos; parámetros por planeamiento',
            fuente='Ley 2/2016 - Art. 17'
        ))
    else:
        # Rústico (31-32): usos compatibles; residencial por regla general no es objetivo del rústico
        res.apto_residencial = False if (inp.uso_previsto or '').lower().startswith('residen') else None
        res.observaciones.append(
            'El suelo rústico se reserva a usos compatibles con su naturaleza; infraestructuras permitidas evitando transformaciones urbanísticas (Arts. 31-32).'
        )
        res.restricciones.append(Restriccion(
            codigo='ART31_32',
            descripcion='Usos compatibles: agrícolas, ganaderos, forestales, protección ambiental e infraestructuras',
            fuente='Ley 2/2016 - Arts. 31-32'
        ))

    # Integración con planeamiento municipal: si hay municipio/subzona, priorizar parámetros del plan
    try:
        if inp.municipio:
            plan = get_plan_params_dynamic(inp.municipio, inp.subzona)
            if plan.altura_maxima_m is not None:
                res.altura_maxima_m = plan.altura_maxima_m
            if plan.retranqueo_min_m is not None:
                res.retranqueo_min_m = plan.retranqueo_min_m
            # Añadir observaciones informativas
            detalle = []
            if plan.ocupacion_max is not None:
                detalle.append(f"ocupación máx {plan.ocupacion_max:.2f}")
            if plan.edificabilidad_max_m2_m2 is not None:
                detalle.append(f"edificabilidad máx {plan.edificabilidad_max_m2_m2:.2f} m2/m2")
            if detalle:
                res.observaciones.append(
                    f"Parámetros municipales ({inp.municipio}{' - ' + inp.subzona if inp.subzona else ''}): " + ", ".join(detalle)
                )
    except Exception as e:
        # No bloquear si el proveedor falla
        res.observaciones.append(f'Aviso: no fue posible cargar parámetros municipales ({e}).')

    return res


def get_plan_params_dynamic(municipio: str, subzona: str | None):
    """Selecciona proveedor de parámetros municipales por variables de entorno.
    PLAN_PROVIDER=csv|mock (por defecto: mock)
    PLAN_CSV_PATH=Ruta al CSV si PLAN_PROVIDER=csv
    """
    provider = os.getenv('PLAN_PROVIDER', 'mock').strip().lower()
    if provider == 'csv':
        from src.planes.csv_provider import CSVPlanProvider
        csv_path = os.getenv('PLAN_CSV_PATH')
        if not csv_path:
            raise ValueError('PLAN_CSV_PATH no definido para proveedor csv')
        prov = CSVPlanProvider(csv_path)
        return prov.get(municipio, subzona)
    else:
        from src.planes.mock_provider import get_plan_params
        return get_plan_params(municipio, subzona)


def geometry_checks(geometry: dict) -> GeometryReport:
    """Calcula métricas geométricas básicas con Shapely a partir de una geometría GeoJSON.
    No reproyecta: se asume geometría en un sistema plano adecuado si se quieren metros reales.
    """
    from shapely.geometry import shape
    if not geometry:
        raise ValueError("Se requiere 'geometry' (GeoJSON)")
    geom = shape(geometry)
    if geom.is_empty:
        raise ValueError("Geometría vacía")
    area = float(geom.area)
    perimeter = float(geom.length)
    bbox = tuple(geom.bounds)
    is_valid = bool(geom.is_valid)
    is_simple = bool(geom.is_simple)
    hull = geom.convex_hull
    hull_area = float(hull.area)
    convexity_ratio = float(area / hull_area) if hull_area > 0 else 0.0
    return GeometryReport(
        area=area,
        perimeter=perimeter,
        bbox=bbox,
        is_valid=is_valid,
        is_simple=is_simple,
        convex_hull_area=hull_area,
        convexity_ratio=convexity_ratio,
    )


def geometry_checks_with_crs(geometry: dict, crs: str | None = None, target_crs: str | None = None) -> GeometryReport:
    """Wrapper de geometry_checks que permite reproyección opcional de CRS.
    - Si sólo se proporciona `crs` y es geográfico, reproyecta automáticamente a un CRS métrico idóneo para Galicia (ETRS89/UTM 29N o 30N) según el centroide.
    - Si `crs` y `target_crs` están definidos y difieren, reproyecta con pyproj antes de calcular métricas.
    """
    if crs and not target_crs:
        try:
            from src.geo import auto_reproject_to_metric
            geometry, target = auto_reproject_to_metric(geometry, crs)
        except Exception as e:
            print(f"[geometry] auto metric reprojection failed from {crs}:", e)
    elif crs and target_crs and crs != target_crs:
        try:
            from src.geo import reproject_geojson
            geometry = reproject_geojson(geometry, crs, target_crs)
        except Exception as e:
            # En caso de fallo, seguimos con la geometría original y anotamos en logs
            print(f"[geometry] reprojection failed ({crs}->{target_crs}):", e)
    return geometry_checks(geometry)
