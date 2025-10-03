# Esquema de anotaciones (Residencial Galicia)

Este esquema define los campos mínimos para anotar parámetros residenciales por municipio/subzona con trazabilidad.

- `municipio` (string) — Nombre del municipio, p. ej. "Vigo".
- `subzona` (string|null) — Identificador de subzona (puede estar vacío si aplica a todo el municipio).
- `altura_maxima_m` (number|null) — Altura máxima permitida (m). Debe ser > 0 si se proporciona.
- `retranqueo_min_m` (number|null) — Retanqueo uniforme mínimo (m). Debe ser ≥ 0 si se proporciona.
- `setback_front_m` (number|null)
- `setback_side_m` (number|null)
- `setback_back_m` (number|null)
- `front_direction_default` ("north"|"east"|"south"|"west"|null) — Dirección por defecto del frente si aplica.
- `ocupacion_max` (number|null) — Proporción [0,1].
- `edificabilidad_max_m2_m2` (number|null) — ≥ 0.
- `source_refs` (array<string>) — Referencias de trazabilidad (artículo, página, cita breve).
- `notes` (string|null) — Comentarios libres.

Formato de archivo: JSON Lines (JSONL), una anotación por línea.

Ejemplo:

```json
{
  "municipio": "Vigo",
  "subzona": "RZ-2",
  "altura_maxima_m": 12,
  "retranqueo_min_m": 3,
  "setback_front_m": 2.0,
  "setback_side_m": 1.0,
  "setback_back_m": 0.5,
  "front_direction_default": "north",
  "ocupacion_max": 0.35,
  "edificabilidad_max_m2_m2": 0.90,
  "source_refs": ["Art. 5.2 (pág. 42)", "Fig. 3 (pág. 44)"],
  "notes": "Aplicable a RZ-2; revisar excepciones en esquinas."
}
```

Validaciones recomendadas (ya soportadas por la API):
- `altura_maxima_m` > 0
- `retranqueo_min_m` ≥ 0; si no hay contexto direccional, opera como retranqueo uniforme.
- `setback_*_m` ≥ 0; se aplican automáticamente cuando la petición tiene contexto direccional (`front_direction` o `street_axis`).
- `ocupacion_max` ∈ [0,1]
- `edificabilidad_max_m2_m2` ≥ 0
