# Guía rápida: Plantilla CSV municipal (Residencial Galicia)

Archivo de referencia: `documentacion/plan_municipal_residencial_template.csv`
Esquema: `documentacion/schema_normativa.yaml`
Proveedor que lo consume: `src/planes/csv_provider.py`

## Objetivo
Estandarizar parámetros municipales mínimos para que el backend aplique la normativa residencial a consultas y a la generación de volúmenes (altura/retranqueos/ocupación/edificabilidad).

## Columnas y significado
- municipio (obligatoria)
  - Nombre del municipio. Cotejado en minúsculas internamente.
- subzona (opcional)
  - Clave o denominación de subzona/ordenanza/ficha (p. ej. "R-1", "UC-1").
  - Si queda vacío, actúa como fila por defecto del municipio.
- altura_maxima_m (recomendada) [> 0]
  - Altura máxima genérica en metros para la subzona o el municipio.
- retranqueo_min_m (opcional) [>= 0]
  - Retranqueo mínimo general en metros (aplicable cuando no hay retranqueos direccionales).
- setback_front_m / setback_side_m / setback_back_m (opcionales) [>= 0]
  - Retranqueos direccionales en metros.
- front_direction_default (opcional) [north|east|south|west]
  - Dirección de frente por defecto. Requiere que al menos uno de los retranqueos direccionales esté definido.
- ocupacion_max (opcional) [0..1]
  - Fracción de ocupación de parcela (0.6 = 60%).
- edificabilidad_max_m2_m2 (opcional) [>= 0]
  - m² techo por m² suelo.
- parcela_min_m2 / frente_min_m (opcionales) [>= 0]
  - Tamaño mínimo de parcela, frente mínimo a vía.
- fuente / articulo / url / notas (opcionales)
  - Trazabilidad a la ordenanza, ficha o documento público.

## Reglas de selección de fila
- Si se consulta con `municipio` y `subzona`, se intenta match exacto.
- Si solo se aporta `municipio`, se busca primero una fila con `subzona` vacía (default); si no hay, se usa la primera específica disponible.

## Validaciones clave (rechazan fila)
- Faltan columnas requeridas: `municipio`.
- `altura_maxima_m` ausente o <= 0.
- `retranqueo_min_m` < 0.
- Cualquier `setback_*` < 0.
- `front_direction_default` definido pero sin ningún `setback_*`.
- `ocupacion_max` fuera de [0,1].
- `edificabilidad_max_m2_m2` < 0.

## Buenas prácticas
- Una fila por subzona. Añade otra con `subzona` vacía para defaults del municipio.
- Usa “.” como separador decimal (ej.: 1.5).
- Evita unidades en campos numéricos (todos son metros o fracciones).
- Completa `fuente`, `articulo` y `url` siempre que sea posible.

## Ejemplo mínimo
```csv
municipio,subzona,altura_maxima_m,retranqueo_min_m,setback_front_m,setback_side_m,setback_back_m,front_direction_default,ocupacion_max,edificabilidad_max_m2_m2,parcela_min_m2,frente_min_m,fuente,articulo,url,notas
Vigo,R-1,12,3,3,3,3,east,0.6,1.2,120,6,PGOM Vigo 2008,Art. XX,https://ejemplo.vigo.es/ordenanza,Régimen orientativo
```

## Cómo validar y cargar en el backend
- Validación vía API:
  - `POST /zoning/validate-plan-csv` con `{ "path": "documentacion/plan_municipal_residencial_template.csv" }`
- Recarga del plan (si `PLAN_PROVIDER=csv`):
  - `POST /admin/reload-plan` con `{ "path": "documentacion/plan_municipal_residencial_template.csv" }`
- Script de demo (PowerShell):
```powershell
.\scriptsun_viewer_demo.ps1 -PlanProvider csv -PlanCSVPath .
\documentacion\plan_municipal_residencial_template.csv -Present
```

## Tests incluidos
- `tests/test_plan_csv_template.py` valida ejemplos de la plantilla.

## Siguientes pasos
- Rellenar con datos reales para el municipio objetivo.
- Si hay campos adicionales relevantes, podemos extender el `csv_provider` y el esquema.
