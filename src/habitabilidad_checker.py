from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


DOG_URL = "https://www.xunta.gal/dog/Publicados/2023/20230915/AnuncioG0691-120923-0003_es.html"
CORRECTION_URL = "https://www.xunta.gal/dog/Publicados/2024/20240418/AnuncioG0691-160424-0001_es.html"
CONSOLIDATED_URL = "https://igvs.xunta.gal/sites/default/files/auxiliar/20240912_TEXTO_CONSOLIDADO_COMENTADO_NHV_version1-2.pdf"

CheckStatus = Literal["cumple", "no_cumple", "no_verificable"]
RoomType = Literal[
    "estancia_mayor",
    "estancia",
    "cocina",
    "bano",
    "aseo",
    "lavadero",
    "tendedero",
    "almacenamiento",
]


class HabitabilityRoom(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)
    tipo: RoomType
    superficie_util_m2: float | None = Field(default=None, gt=0)
    ancho_minimo_m: float | None = Field(default=None, gt=0)
    lado_cuadrado_inscribible_m: float | None = Field(default=None, gt=0)
    superficie_acristalada_m2: float | None = Field(default=None, ge=0)
    superficie_ventilacion_m2: float | None = Field(default=None, ge=0)
    relacion_exterior: bool | None = None


class HabitabilityInput(BaseModel):
    municipio: str | None = None
    tipo_operacion: Literal["cambio_uso_local_a_vivienda", "rehabilitacion", "nueva_construccion"] = "cambio_uso_local_a_vivienda"
    altura_libre_m: float | None = Field(default=None, gt=0)
    piezas: list[HabitabilityRoom] = Field(default_factory=list)
    programa_declarado_completo: bool = False
    geometria_local: dict[str, Any] | None = None


class HabitabilityCheck(BaseModel):
    codigo: str
    parametro: str
    estado: CheckStatus
    valor_observado: str
    requisito: str
    referencia: str
    fuente_url: str = DOG_URL
    detalle: str


class HabitabilityResult(BaseModel):
    estado_global: CheckStatus
    cumple: bool | None
    comprobaciones: list[HabitabilityCheck]
    incumplimientos: list[str]
    advertencias: list[str]
    no_verificables: list[str]
    fuentes: list[dict[str, str]]
    normativa: str = "NHV-2010, redacción dada por el Decreto 128/2023"
    version_reglas: str = "2024-09-12"


_E1_MIN = {1: 25.0, 2: 16.0, 3: 18.0, 4: 20.0, 5: 22.0, 6: 25.0}
_OTHER_MIN = {
    2: [12.0],
    3: [12.0, 8.0],
    4: [12.0, 8.0, 8.0],
    5: [12.0, 8.0, 8.0, 6.0],
    6: [12.0, 8.0, 8.0, 8.0, 6.0],
}
_KITCHEN_MIN = {1: 5.0, 2: 7.0, 3: 7.0, 4: 9.0, 5: 9.0, 6: 10.0}


def _bucket(count: int) -> int:
    return min(max(count, 1), 6)


def _check(
    codigo: str,
    parametro: str,
    observed: float | bool | None,
    required: float | bool,
    unit: str,
    referencia: str,
    *,
    minimum: bool = True,
    missing_detail: str,
) -> HabitabilityCheck:
    req_text = f"≥ {required:g} {unit}" if isinstance(required, (int, float)) and minimum else str(required)
    if observed is None:
        return HabitabilityCheck(
            codigo=codigo,
            parametro=parametro,
            estado="no_verificable",
            valor_observado="No aportado",
            requisito=req_text,
            referencia=referencia,
            detalle=missing_detail,
        )
    if isinstance(required, bool):
        passed = observed is required
        observed_text = "Sí" if observed else "No"
        req_text = "Sí"
    else:
        observed_value = float(observed)
        passed = observed_value >= float(required) if minimum else observed_value <= float(required)
        observed_text = f"{observed_value:g} {unit}"
    return HabitabilityCheck(
        codigo=codigo,
        parametro=parametro,
        estado="cumple" if passed else "no_cumple",
        valor_observado=observed_text,
        requisito=req_text,
        referencia=referencia,
        detalle="Valor dentro del umbral comprobado." if passed else "El valor aportado no alcanza el mínimo exigido.",
    )


def _missing_check(tipo: str, complete: bool) -> HabitabilityCheck:
    status: CheckStatus = "no_cumple" if complete else "no_verificable"
    return HabitabilityCheck(
        codigo=f"programa_{tipo}",
        parametro=f"Presencia de {tipo}",
        estado=status,
        valor_observado="No incluido",
        requisito="Pieza o espacio obligatorio",
        referencia="Anexo I, A.2.3 y tabla 2",
        detalle="El programa se declaró completo y falta este elemento." if complete else "Confirme si el programa aportado está completo.",
    )


def check_habitability(data: HabitabilityInput | dict[str, Any]) -> HabitabilityResult:
    """Realiza un prechequeo trazable de las NHV; no sustituye la revisión técnica del proyecto."""
    request = data if isinstance(data, HabitabilityInput) else HabitabilityInput.model_validate(data)
    checks: list[HabitabilityCheck] = []
    warnings: list[str] = []

    height_min = 2.4 if request.tipo_operacion == "cambio_uso_local_a_vivienda" else 2.5
    height_ref = "Anexo I, A.3.1.1.d" if request.tipo_operacion == "cambio_uso_local_a_vivienda" else "Anexo I, A.3.1.1.a"
    checks.append(_check(
        "altura_libre",
        "Altura libre mínima",
        request.altura_libre_m,
        height_min,
        "m",
        height_ref,
        missing_detail="Aporte la altura entre pavimento terminado y techo acabado.",
    ))

    major_rooms = [room for room in request.piezas if room.tipo == "estancia_mayor"]
    other_rooms = [room for room in request.piezas if room.tipo == "estancia"]
    room_count = len(major_rooms) + len(other_rooms)
    if not major_rooms:
        checks.append(_missing_check("estancia_mayor", request.programa_declarado_completo))
    if len(major_rooms) > 1:
        checks.append(HabitabilityCheck(
            codigo="estancia_mayor_unica",
            parametro="Identificación de estancia mayor",
            estado="no_cumple",
            valor_observado=str(len(major_rooms)),
            requisito="Una estancia mayor",
            referencia="Anexo I, A.3.2.1.a",
            detalle="Debe identificarse una única estancia mayor.",
        ))

    bucket = _bucket(room_count)
    if major_rooms:
        major = major_rooms[0]
        checks.append(_check("superficie_e1", f"Superficie de {major.nombre}", major.superficie_util_m2, _E1_MIN[bucket], "m²", "Anexo I, A.3.2.1, tabla 1", missing_detail="Aporte la superficie útil computable de la estancia mayor."))
        checks.append(_check("ancho_e1", f"Ancho de {major.nombre}", major.ancho_minimo_m, 2.7, "m", "Anexo I, A.3.2.1.b", missing_detail="Aporte el ancho mínimo entre paramentos enfrentados."))
        checks.append(_check("cuadrado_e1", f"Cuadrado inscribible en {major.nombre}", major.lado_cuadrado_inscribible_m, 3.3, "m", "Anexo I, A.3.2.1.a", missing_detail="Confirme el lado del cuadrado libre inscribible."))

    expected_other = _OTHER_MIN.get(bucket, [])
    sorted_other = sorted(other_rooms, key=lambda room: room.superficie_util_m2 or 0, reverse=True)
    for index, minimum_area in enumerate(expected_other):
        if index >= len(sorted_other):
            checks.append(_missing_check(f"estancia_E{index + 2}", request.programa_declarado_completo))
            continue
        room = sorted_other[index]
        checks.append(_check(f"superficie_e{index + 2}", f"Superficie de {room.nombre}", room.superficie_util_m2, minimum_area, "m²", "Anexo I, A.3.2.1, tabla 1", missing_detail="Aporte la superficie útil computable de la estancia."))
        min_width = 2.6 if minimum_area >= 12 else 2.0
        min_square = 2.6 if minimum_area >= 12 else 2.2
        checks.append(_check(f"ancho_e{index + 2}", f"Ancho de {room.nombre}", room.ancho_minimo_m, min_width, "m", "Anexo I, A.3.2.1.e-h", missing_detail="Aporte el ancho mínimo entre paramentos enfrentados."))
        checks.append(_check(f"cuadrado_e{index + 2}", f"Cuadrado inscribible en {room.nombre}", room.lado_cuadrado_inscribible_m, min_square, "m", "Anexo I, A.3.2.1.e-h", missing_detail="Confirme el lado del cuadrado libre inscribible."))

    service_specs = {
        "cocina": (_KITCHEN_MIN[bucket], 1.8, "Anexo I, A.3.2.2, tabla 2 y Cocina a"),
        "bano": (5.0, 1.6, "Anexo I, A.3.2.2, tabla 2 y Cuarto de baño a"),
        "lavadero": (1.5, None, "Anexo I, A.3.2.2, tabla 2"),
        "tendedero": (1.5, None, "Anexo I, A.3.2.2, tabla 2"),
        "almacenamiento": (float(bucket), None, "Anexo I, A.3.2.2, tabla 2"),
    }
    if bucket >= 4:
        service_specs["aseo"] = (1.5, 1.2, "Anexo I, A.3.2.2, tabla 2 y Cuarto de aseo a")
    for room_type, (area_min, width_min, reference) in service_specs.items():
        matches = [room for room in request.piezas if room.tipo == room_type]
        if not matches:
            checks.append(_missing_check(room_type, request.programa_declarado_completo))
            continue
        room = matches[0]
        checks.append(_check(f"superficie_{room_type}", f"Superficie de {room.nombre}", room.superficie_util_m2, area_min, "m²", reference, missing_detail="Aporte la superficie útil computable."))
        if width_min is not None:
            checks.append(_check(f"ancho_{room_type}", f"Ancho de {room.nombre}", room.ancho_minimo_m, width_min, "m", reference, missing_detail="Aporte el ancho mínimo entre paramentos enfrentados."))

    habitable = major_rooms + other_rooms + [room for room in request.piezas if room.tipo == "cocina"]
    for room in habitable:
        if room.superficie_util_m2 is None:
            continue
        glazing_min = room.superficie_util_m2 / 8.0
        ventilation_min = glazing_min / 3.0
        checks.append(_check(f"iluminacion_{room.nombre}", f"Acristalamiento de {room.nombre}", room.superficie_acristalada_m2, glazing_min, "m²", "Anexo I, A.1.2.a", missing_detail="Aporte la superficie efectiva de acristalamiento al exterior."))
        checks.append(_check(f"ventilacion_{room.nombre}", f"Ventilación de {room.nombre}", room.superficie_ventilacion_m2, ventilation_min, "m²", "Anexo I, A.1.2.i", missing_detail="Aporte la superficie real practicable de ventilación."))

    if major_rooms:
        checks.append(_check("exterior_e1", "Relación exterior de la estancia mayor", major_rooms[0].relacion_exterior, True, "", "Anexo I, A.1.1 y A.1.2", missing_detail="Confirme si ilumina y ventila directamente a un espacio exterior admisible."))
    if room_count > 1:
        secondary_exterior = any(room.relacion_exterior is True for room in other_rooms + [room for room in request.piezas if room.tipo == "cocina"])
        secondary_known = any(room.relacion_exterior is not None for room in other_rooms + [room for room in request.piezas if room.tipo == "cocina"])
        checks.append(_check("exterior_secundaria", "Segunda pieza con relación exterior", secondary_exterior if secondary_known else None, True, "", "Anexo I, A.1.1.b", missing_detail="Confirme la relación exterior de otra estancia o de la cocina no integrada."))

    if room_count == 0:
        warnings.append("No se pudo determinar el número de estancias; las tablas dimensionales no son verificables.")
    if room_count > 6:
        warnings.append("Para más de seis estancias se aplicó la columna >5 de las tablas 1 y 2.")
    warnings.append("La vivienda exterior puede depender del planeamiento municipal o de un anexo de habitabilidad.")
    warnings.append("Accesibilidad, seguridad contra incendios, salubridad CTE y condiciones municipales requieren comprobaciones independientes.")

    failures = [check.parametro for check in checks if check.estado == "no_cumple"]
    unknowns = [check.parametro for check in checks if check.estado == "no_verificable"]
    global_status: CheckStatus = "no_cumple" if failures else ("no_verificable" if unknowns else "cumple")
    return HabitabilityResult(
        estado_global=global_status,
        cumple=True if global_status == "cumple" else (False if global_status == "no_cumple" else None),
        comprobaciones=checks,
        incumplimientos=failures,
        advertencias=warnings,
        no_verificables=unknowns,
        fuentes=[
            {"nombre": "Decreto 128/2023 (DOG 176, 15/09/2023)", "url": DOG_URL},
            {"nombre": "Corrección de errores (DOG 77, 18/04/2024)", "url": CORRECTION_URL},
            {"nombre": "Texto consolidado comentado NHV (IGVS, versión 1.2)", "url": CONSOLIDATED_URL},
        ],
    )
