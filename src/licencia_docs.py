"""Generación de plantillas de documentación de licencia para cambio de uso.

Produce plantillas rellenables a partir de los datos de análisis ya disponibles
(Catastro, SIOTUGA, habitabilidad, geometría). No inventa requisitos
normativos municipales: donde no hay fuente, lo indica explícitamente.
"""
from __future__ import annotations

import datetime as _dt
import html as _html
from typing import Any, Optional

from src.habitabilidad_checker import HabitabilityResult, check_habitability


def _esc(x: Any) -> str:
    try:
        return _html.escape(x if isinstance(x, str) else str(x))
    except Exception:
        return str(x)


def _fmt(x: Any, *, unit: str = "") -> str:
    if x is None or x == "":
        return "—"
    try:
        v = float(x)
        return f"{round(v, 2):g}{unit}"
    except (TypeError, ValueError):
        return f"{_esc(x)}{unit}"


class LicenciaInput:
    """Datos de entrada para generar la documentación de licencia.

    Todos los campos son opcionales; los ausentes se marcan como pendientes.
    No se infieren requisitos municipales sin fuente.
    """

    def __init__(
        self,
        *,
        municipio: str | None = None,
        ref_catastral: str | None = None,
        direccion_catastral: str | None = None,
        superficie_parcela_m2: float | None = None,
        parcela_label: str | None = None,
        clasificacion_suelo: str | None = None,
        instrumento_planeamiento: str | None = None,
        fecha_aprobacion: str | None = None,
        params_urbanisticos: dict[str, Any] | None = None,
        habitabilidad: dict[str, Any] | HabitabilityResult | None = None,
        superficies: dict[str, float] | None = None,
        tipo_operacion: str = "cambio_uso_local_a_vivienda",
        fuente_ordenanza_municipal: str | None = None,
    ) -> None:
        self.municipio = municipio
        self.ref_catastral = ref_catastral
        self.direccion_catastral = direccion_catastral
        self.superficie_parcela_m2 = superficie_parcela_m2
        self.parcela_label = parcela_label
        self.clasificacion_suelo = clasificacion_suelo
        self.instrumento_planeamiento = instrumento_planeamiento
        self.fecha_aprobacion = fecha_aprobacion
        self.params_urbanisticos = params_urbanisticos or {}
        self.habitabilidad = habitabilidad
        self.superficies = superficies or {}
        self.tipo_operacion = tipo_operacion
        self.fuente_ordenanza_municipal = fuente_ordenanza_municipal


def _habitabilidad_section(hab: HabitabilityResult) -> tuple[str, str]:
    """Devuelve (resumen_estado, tabla_html) para la justificación normativa."""
    status_label = {
        "cumple": "Cumple las reglas comprobables del Decreto 128/2023",
        "no_cumple": "No cumple todas las reglas comprobables",
        "no_verificable": "No verificable con los datos aportados",
    }.get(hab.estado_global, hab.estado_global)
    rows = "".join(
        f"<tr><td>{_esc(c.parametro)}</td><td>{_esc(c.valor_observado)}</td>"
        f"<td>{_esc(c.requisito)}</td><td>{_esc(c.estado)}</td>"
        f"<td>{_esc(c.referencia)}</td></tr>"
        for c in hab.comprobaciones
    )
    fuentes = "".join(
        f"<li><a href='{_esc(s['url'])}' target='_blank' rel='noopener'>{_esc(s['nombre'])}</a></li>"
        for s in hab.fuentes
    )
    tabla = (
        f"<p><b>Estado:</b> {_esc(status_label)}</p>"
        f"<p class='muted'>{_esc(hab.normativa)} · versión de reglas {_esc(hab.version_reglas)}</p>"
        "<table><thead><tr><th>Parámetro</th><th>Observado</th><th>Requisito</th>"
        "<th>Estado</th><th>Referencia</th></tr></thead><tbody>"
        f"{rows}</tbody></table>"
        f"<h4>Fuentes oficiales</h4><ul>{fuentes}</ul>"
    )
    return status_label, tabla


def _superficies_table(superficies: dict[str, float]) -> str:
    if not superficies:
        return "<p class='muted'>Sin datos de superficie aportados.</p>"
    labels = {
        "superficie_util_m2": "Superficie útil",
        "superficie_construida_m2": "Superficie construida",
        "superficie_ocupada_m2": "Superficie ocupada",
        "superficie_libre_m2": "Superficie libre",
        "superficie_parcela_m2": "Superficie de parcela",
    }
    rows = "".join(
        f"<tr><td>{_esc(labels.get(k, k))}</td><td>{_fmt(v, unit=' m²')}</td></tr>"
        for k, v in superficies.items()
        if v is not None
    )
    return (
        "<table><thead><tr><th>Concepto</th><th>Valor</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def _documentacion_exigida(municipio: str | None, fuente: str | None, *,
                           ref_catastral: str | None = None,
                           tiene_habitabilidad: bool = False,
                           tiene_planos: bool = False) -> str:
    """Lista la documentación típica marcando qué datos ya están incluidos."""
    base_docs = [
        ("Memoria del proyecto", False),
        ("Planos (planta, secciones, alzados)", False),
        ("Plano de situación y emplazamiento", tiene_planos),
        ("Justificación del cumplimiento del Decreto 128/2023 (incluida más abajo)", tiene_habitabilidad),
        ("Referencia catastral del inmueble", ref_catastral is not None),
    ]
    items = ""
    for doc, disponible in base_docs:
        if disponible:
            items += f"<li>✓ {_esc(doc)} <span class='muted' style='color:#2e7d32'>(incluido en este documento)</span></li>"
        else:
            items += f"<li>○ {_esc(doc)} <span class='muted'>(pendiente de aportar)</span></li>"
    nota = ""
    if not fuente:
        nota = (
            "<p class='muted'><b>Pendiente:</b> la documentación específica exigida por el "
            f"ayuntamiento de {_esc(municipio or '—')} no está disponible en el sistema. "
            "Consúltese la ordenanza municipal de cambio de uso correspondiente.</p>"
        )
    else:
        nota = f"<p class='muted'>Fuente de requisitos municipales: {_esc(fuente)}</p>"
    return f"<ul>{items}</ul>{nota}"


def render_licencia_html(data: LicenciaInput | dict[str, Any]) -> str:
    """Genera el HTML de la documentación de licencia rellenable.

    No sustituye el proyecto técnico ni la interpretación jurídica profesional.
    """
    if isinstance(data, dict):
        data = LicenciaInput(**data)

    hab_result: HabitabilityResult | None = None
    if data.habitabilidad is not None:
        if isinstance(data.habitabilidad, HabitabilityResult):
            hab_result = data.habitabilidad
        elif isinstance(data.habitabilidad, dict):
            hab_result = check_habitability(data.habitabilidad)

    gen_date = _dt.datetime.now().strftime("%Y-%m-%d")
    op_label = {
        "cambio_uso_local_a_vivienda": "Cambio de uso de local a vivienda",
        "rehabilitacion": "Rehabilitación",
        "nueva_construccion": "Nueva construcción",
    }.get(data.tipo_operacion, data.tipo_operacion)

    pe = data.params_urbanisticos
    params_rows = "".join(
        f"<tr><td>{_esc(k)}</td><td>{_fmt(v)}</td></tr>"
        for k, v in pe.items()
    ) if pe else "<tr><td colspan='2' class='muted'>Sin parámetros urbanísticos aportados.</td></tr>"

    hab_html = ""
    hab_estado = ""
    if hab_result is not None:
        hab_estado, hab_tabla = _habitabilidad_section(hab_result)
        hab_html = (
            "<section id='memoria-normativa'>"
            "<h2>2. Justificación del cumplimiento del Decreto 128/2023</h2>"
            f"{hab_tabla}"
            "<p class='muted'>Prechequeo técnico realizado con las reglas comprobables de las "
            "NHV (Decreto 29/2010, redacción dada por el Decreto 128/2023). "
            "No cubre accesibilidad, seguridad contra incendios, CTE ni ordenanzas municipales, "
            "que requieren comprobación independiente.</p>"
            "</section>"
        )

    sup_html = _superficies_table({**data.superficies, **({"superficie_parcela_m2": data.superficie_parcela_m2} if data.superficie_parcela_m2 else {})})

    catastro_link = ""
    if data.ref_catastral:
        rc = _esc(data.ref_catastral)
        catastro_link = (
            f"<a href='https://www1.sedecatastro.es/ConsultaInmueble/ConsultaDatoRegistro.aspx?rc={rc}' "
            "target='_blank' rel='noopener'>Consulta en la Sede Electrónica del Catastro</a>"
        )

    return f"""<!DOCTYPE html>
<html lang='gl'>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<title>Documentación de licencia — {_esc(data.municipio or '—')}</title>
<style>
  body {{ font-family: -apple-system, 'Segoe UI', Roboto, sans-serif; max-width: 900px;
         margin: 0 auto; padding: 24px; color: #1a1a1a; line-height: 1.5; }}
  h1 {{ font-size: 22px; border-bottom: 2px solid #2e7d32; padding-bottom: 8px; }}
  h2 {{ font-size: 18px; margin-top: 28px; border-left: 4px solid #2e7d32; padding-left: 8px; }}
  h3, h4 {{ font-size: 15px; }}
  table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
  th, td {{ border: 1px solid #ccc; padding: 6px 10px; text-align: left; font-size: 13px; }}
  th {{ background: #f5f5f5; }}
  .muted {{ color: #666; font-size: 13px; }}
  .header {{ display: flex; justify-content: space-between; flex-wrap: wrap; }}
  .placeholder {{ background: #fffbe6; border: 1px dashed #d4a017; padding: 8px 12px;
                 border-radius: 4px; margin: 8px 0; font-size: 13px; }}
  @media print {{ body {{ padding: 12px; }} .placeholder {{ background: #fffef0; }} }}
</style>
</head>
<body>
<div class='header'>
  <div>
    <h1>Documentación de licencia</h1>
    <p class='muted'>{_esc(op_label)} · {_esc(data.municipio or '—')}</p>
  </div>
  <div class='muted'>Generado: {_esc(gen_date)}</div>
</div>

<div class='placeholder'>
  <b>Plantilla rellenable.</b> Este documento se ha generado a partir de los datos del análisis
  y debe ser completado, revisado y firmado por el técnico competente. No constituye por sí mismo
  una solicitud de licencia ni un certificado.
</div>

<section id='datos-inmueble'>
<h2>1. Datos del inmueble</h2>
<table>
  <tr><td>Municipio</td><td>{_esc(data.municipio or '—')}</td></tr>
  <tr><td>Referencia catastral</td><td>{_esc(data.ref_catastral or '—')}{(' · ' + catastro_link) if catastro_link else ''}</td></tr>
  <tr><td>Número de parcela</td><td>{_esc(data.parcela_label or '—')}</td></tr>
  <tr><td>Dirección catastral</td><td>{_esc(data.direccion_catastral or '—')}</td></tr>
  <tr><td>Superficie de parcela</td><td>{_fmt(data.superficie_parcela_m2, unit=' m²')}</td></tr>
  <tr><td>Clasificación del suelo (SIOTUGA)</td><td>{_esc(data.clasificacion_suelo or '—')}</td></tr>
  <tr><td>Instrumento de planeamiento</td><td>{_esc(data.instrumento_planeamiento or '—')}{(' · aprobación: ' + _esc(data.fecha_aprobacion)) if data.fecha_aprobacion else ''}</td></tr>
  <tr><td>Tipo de operación</td><td>{_esc(op_label)}</td></tr>
</table>
</section>

{hab_html}

<section id='parametros-urbanisticos'>
<h2>{'3' if hab_html else '2'}. Parámetros urbanísticos aplicables</h2>
<table><thead><tr><th>Parámetro</th><th>Valor</th></tr></thead><tbody>{params_rows}</tbody></table>
<p class='muted'>Indique la fuente de cada parámetro (planeamiento vigente, ordenanza municipal, etc.).</p>
</section>

<section id='cuadro-superficies'>
<h2>{'4' if hab_html else '3'}. Cuadro de superficies</h2>
{sup_html}
</section>

<section id='documentacion-exigida'>
<h2>{'5' if hab_html else '4'}. Documentación a aportar</h2>
{_documentacion_exigida(data.municipio, data.fuente_ordenanza_municipal, ref_catastral=data.ref_catastral, tiene_habitabilidad=hab_result is not None)}
</section>

<section id='observaciones'>
<h2>{'6' if hab_html else '5'}. Observaciones y firmas</h2>
<div class='placeholder'>Espacio para observaciones del técnico, fecha de presentación y firma.</div>
</section>

<footer>
<p class='muted'>Generado por NORMATIVA URBANISTICA 3D · {_esc(gen_date)} ·
  Plantilla de apoyo; no sustituye el proyecto técnico ni la interpretación jurídica profesional.</p>
</footer>
</body>
</html>"""
