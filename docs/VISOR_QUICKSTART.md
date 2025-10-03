# Visor Three.js + Normativa Galicia: Guía rápida

Esta guía resume cómo abrir el visor, consultar normativa y generar informes HTML/PDF con branding y firma.

## Arranque del servidor
- Requisitos: Python 3.10+ y dependencias del proyecto.
- Arranque recomendado en Windows:
  - Doble clic a `scripts/launch_server.cmd` o ejecútalo desde PowerShell/CMD.
  - El servidor expone la API en `http://127.0.0.1:8002/`.

## Abrir el visor
- URL principal (redirige al visor):
  - `http://127.0.0.1:8002/`
- Visor directo:
  - `http://127.0.0.1:8002/web/examples/threejs-viewer/index.html`
- Si no ves cambios, usa recarga dura: Ctrl+F5.

## Flujo básico
1) Mueve el mapa para centrar el área de interés (o activa una parcela si la hay).
2) Pulsa el botón `Normativa` para abrir el panel.
3) Usa los botones del panel:
   - `Evaluar viabilidad`: consulta `/zoning/assess` con la geometría activa (o el viewport si no hay parcela) y muestra el badge (APTO/COND./NO APTO).
   - `Informe`: abre `/zoning/assess-report` (HTML) con tus preferencias de informe.
   - `Prefs informe`: ajusta logo, título, cliente, proyecto, color corporativo, firma, “firmado por”, “lugar/fecha”, Observaciones y Fuente normativa.
   - `Descargar PDF`: abre `/zoning/assess-report.pdf` con las mismas preferencias.

Notas:
- Si no hay parcela activa, el visor usará un polígono del rectángulo visible (viewport) para las consultas de volumen/viabilidad/informe.
- SIOSE (ocupación del suelo) está apagado por defecto para reducir ruido; puedes activarlo con su interruptor en el visor (si está presente) o vía `localStorage`.

## Preferencias de informe (persisten en localStorage)
- `report_logo_url`
- `report_title`
- `report_client`
- `report_project`
- `report_brand_color` (hex, ej. `#0044aa`)
- `report_signature_on` (`on`/`off`)
- `report_sign_by` (ej. `DVR`)
- `report_sign_place` (texto libre)
- `report_notes` (Observaciones)
- `report_source_ref` (Fuente normativa; texto o URL)

## Modo debug (opcional)
- El texto técnico “dens/umbral” del panel solo se muestra si activas el modo debug:
  - Activar: `localStorage.setItem('viewer_debug','on'); location.reload();`
  - Desactivar: `localStorage.removeItem('viewer_debug'); location.reload();`

## Rutas backend clave
- `POST /zoning/analyze` — Análisis de normativa (sustituye a cualquier `/normativa/consulta` previo).
- `POST /zoning/assess` — Viabilidad (APTO/COND./NO APTO) y razones.
- `GET /zoning/assess-report` — Informe HTML con branding/firma/observaciones/fuente.
- `GET /zoning/assess-report.pdf` — Informe PDF (mismos parámetros que el HTML).

## Pruebas rápidas (opcionales)
- Script Windows: `scripts/run_tests.cmd`
  - Crea `.venv`, instala `pytest` y ejecuta los tests del directorio `tests/`.
  - Para un test concreto: `scripts/run_tests.cmd tests/test_assess_report_branding.py`

## Solución de problemas
- Pop-up bloqueado: si al abrir informe/PDF el navegador bloquea pestañas, permite la ventana emergente o abre el enlace en la misma pestaña.
- 404 `/normativa/consulta`: el visor usa `POST /zoning/analyze` (actual); no existe `/normativa/consulta`.
- Sin tiles vectoriales: el visor puede añadir raster Esri como base automáticamente si está habilitado el fallback.
- SIOSE ruidoso: se deja apagado por defecto (`viewer_siose_enabled='off'`).

## Contacto y notas
- Este visor está enfocado a Residencial y pensado para minimizar errores y acelerar la viabilidad preliminar.
- Para dudas o mejoras, consulta el archivo `web/examples/threejs-viewer/index.html` y la API en `app/main.py`.
