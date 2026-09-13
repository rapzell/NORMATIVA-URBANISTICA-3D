# Propuesta de integración de GeoLibre en NORMATIVA GALICIA 3D

## 1. Objetivo

Este documento describe una integración progresiva de **GeoLibre** dentro de NORMATIVA GALICIA 3D, manteniendo el proyecto en una línea **100% gratuita** y evitando dependencias de pago.

La idea central es simple:

- **no sustituir el backend actual**;
- **no perder el visor 3D especializado**;
- y **usar GeoLibre como capa GIS principal** para visualización, consulta espacial y trabajo cartográfico.

---

## 2. Principio de diseño

La separación recomendada es:

### FastAPI
Responsable de:
- reglas normativas oficiales;
- cálculo de viabilidad;
- cálculo geométrico de la envolvente;
- exportaciones 3D;
- informes y trazabilidad.

### GeoLibre
Responsable de:
- mapa principal;
- gestión de capas;
- visualización de subzonas;
- consultas espaciales;
- estilo y análisis exploratorio;
- composición cartográfica.

### Three.js actual
Responsable de:
- revisión 3D especializada;
- visualización GLTF/GLB;
- prototipos y demos de volumen edificable.

---

## 3. Por qué GeoLibre encaja

GeoLibre aporta capacidades que complementan muy bien al proyecto actual:

- frontend GIS moderno con MapLibre;
- soporte para múltiples fuentes (`GeoJSON`, `GeoParquet`, `GeoPackage`, `WMS`, `WFS`, `WMTS`, `ArcGIS`, `STAC`);
- tabla de atributos y estilos;
- SQL espacial con DuckDB-WASM;
- herramientas de análisis vectorial y ráster;
- ejecución en navegador sin exigir infraestructura pesada para muchas tareas.

Eso lo convierte en una base muy buena para:

- ver subzonas de planeamiento;
- explorar parcelas;
- hacer joins espaciales y overlays;
- y mejorar mucho la parte 2D del producto.

---

## 4. Qué no debe hacerse

No recomiendo:

- mover la lógica normativa al cliente;
- duplicar en GeoLibre la lógica oficial de viabilidad;
- abandonar el backend actual;
- ni reemplazar de golpe el visor existente.

La razón es de consistencia y auditabilidad: la decisión oficial debe seguir viniendo del backend.

---

## 5. Arquitectura objetivo

## 5.1 Capa de datos

### Datos alfanuméricos
Mantener CSV para:
- altura;
- retranqueos;
- ocupación;
- edificabilidad;
- precedencia;
- referencias.

### Datos espaciales
Añadir una capa geoespacial de subzonas con:
- `municipio`
- `subzona`
- `fuente`
- `version`
- `geometry`

Formatos sugeridos:
1. GeoJSON
2. GeoPackage
3. GeoParquet

## 5.2 Capa de servicios

FastAPI debe exponer o consolidar:

- `GET /planeamento/inventario`
- `GET /planeamento/subzonas` o rutas equivalentes futuras
- `POST /zoning/analyze`
- `POST /zoning/assess`
- `POST /zoning/volume`
- `POST /zoning/volume-export`

## 5.3 Capa frontend

Añadir una experiencia GeoLibre para:

- mostrar subzonas y normativa visible por mapa;
- consultar atributos;
- lanzar evaluación sobre la parcela seleccionada;
- superponer resultados devueltos por FastAPI;
- preparar composición cartográfica.

---

## 6. Fases de implementación

## Fase 1 — Vista GIS adicional

Objetivo:
- incorporar GeoLibre como vista paralela.

Entregables:
- nueva ruta de acceso desde la app;
- carga de GeoJSON de ejemplo;
- consumo del inventario y de capas simples desde el backend.

## Fase 2 — Subzonas geoespaciales reales

Objetivo:
- representar espacialmente el planeamiento.

Entregables:
- primer dataset espacial de subzonas;
- unión estable por `municipio` y `subzona`;
- visualización temática en GeoLibre.

## Fase 3 — Flujo híbrido de análisis

Objetivo:
- usar GeoLibre para explorar y FastAPI para decidir.

Entregables:
- selección de parcela o subzona en GeoLibre;
- envío de geometría a `/zoning/assess`;
- devolución y renderizado del resultado sobre el mapa.

## Fase 4 — Informes mejorados

Objetivo:
- enriquecer la salida visual.

Entregables:
- mapa compuesto con subzonas, parcela y resultado;
- plantilla visual exportable;
- integración con el flujo de informe normativo.

## Fase 5 — Consolidación

Objetivo:
- definir roles finales de cada frontend.

Resultado deseado:
- GeoLibre como GIS principal;
- Three.js como módulo 3D especializado;
- FastAPI como backend normativo oficial.

---

## 7. Requisitos técnicos previos

Antes de una integración seria con GeoLibre, conviene resolver primero:

1. refactor parcial de `app/main.py`;
2. servicio unificado de resolución de parámetros efectivos;
3. contrato claro entre datos normativos y datos espaciales;
4. primer dataset espacial de subzonas.

Sin esas piezas, GeoLibre aportará valor visual, pero no quedará bien acoplado al dominio del proyecto.

---

## 8. Impacto esperado

Si se integra bien, GeoLibre debería mejorar especialmente:

- la experiencia de usuario 2D;
- la consulta de planeamiento por mapa;
- la capacidad de análisis espacial exploratorio;
- la calidad visual de informes;
- y la escalabilidad de la parte cartográfica.

El backend actual seguiría aportando el valor diferencial: normativa, viabilidad, geometría y exportación reproducible.

---

## 9. Recomendación final

La integración de GeoLibre sí tiene sentido, pero la estrategia correcta es:

- **complementar**, no reemplazar;
- **reforzar la cartografía**, no mover la lógica normativa al cliente;
- **adoptar por fases**, no hacer migración brusca.

Con esa estrategia, la integración puede mejorar mucho el producto sin perder la inversión ya hecha en FastAPI, CSV, Shapely y el visor 3D actual.
