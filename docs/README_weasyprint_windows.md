# WeasyPrint en Windows (Guía rápida)

Esta guía explica cómo habilitar la generación de PDF en servidor para los informes del visor utilizando WeasyPrint en Windows.

## ¿Qué es WeasyPrint?
WeasyPrint convierte HTML+CSS en PDF de forma programática en el servidor. Nuestro backend expone el endpoint `GET /zoning/assess-report.pdf` que reutiliza el HTML del informe y lo convierte a PDF con WeasyPrint.

Ventajas:
- Generación automática y en lote (sin abrir el navegador).
- Resultado reproducible en distintos equipos/servidores.
- Flujo profesional de entrega (p. ej., enviar PDF por email o empaquetarlo).

No es obligatorio: el sistema funciona también con “Imprimir → Guardar como PDF” desde el navegador.

---

## Requisitos
WeasyPrint necesita librerías de renderizado: Cairo, Pango y GDK-PixBuf.

Hay dos caminos habituales para Windows:

### Opción A: MSYS2 (recomendado para desarrolladores)
1. Instala MSYS2: https://www.msys2.org/
2. Abre la consola "MSYS2 UCRT64" y actualiza paquetes:
   ```bash
   pacman -Syu
   # cuando finalice, cierra y vuelve a abrir la consola UCRT64
   pacman -Syu
   ```
3. Instala dependencias de WeasyPrint (toolchain de render):
   ```bash
   pacman -S --needed \
     mingw-w64-ucrt-x86_64-cairo \
     mingw-w64-ucrt-x86_64-pango \
     mingw-w64-ucrt-x86_64-gdk-pixbuf
   ```
4. Añade al `PATH` de Windows la carpeta `C:\msys64\ucrt64\bin` (ajusta si tu instalación difiere).
5. Instala la librería Python (en tu venv o entorno actual de Python):
   ```powershell
   pip install weasyprint
   ```

### Opción B: GTK Runtime (más simple, menos flexible)
1. Instala un runtime de GTK para Windows que incluya Cairo, Pango y GDK-PixBuf (por ejemplo GTK3). Puedes usar:
   - https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer
2. Añade las carpetas `bin` del runtime al `PATH` de Windows (p. ej., `C:\Program Files\GTK3-Runtime Win64\bin`).
3. Instala WeasyPrint en tu entorno Python:
   ```powershell
   pip install weasyprint
   ```

---

## Verificación
1. Prueba rápida en consola:
   ```powershell
   python -c "from weasyprint import HTML; print('weasyprint ok')"
   ```
   Debe imprimir `weasyprint ok`.

2. Desde el navegador, prueba el endpoint del backend:
   - Abre el visor, ve a "Normativa" → pulsa “PDF (servidor)”.
   - O manualmente construye la URL (ejemplo mínimo):
     ```
     http://127.0.0.1:8002/zoning/assess-report.pdf?body_b64=...&title=Informe&brand_color=%230044aa&signature=true&sign_by=AC8&sign_place=Vigo
     ```

Si WeasyPrint no está disponible, el endpoint devuelve HTTP 501 con un mensaje explicativo.

---

## Uso en el visor
- En “Prefs informe” puedes definir:
  - `logo` (URL), `title`, `client`, `project`
  - `brand_color` (hex, p. ej. `#0044aa`)
  - `signature` (on/off), `sign_by`, `sign_place`
- Botones:
  - “Informe”: abre el HTML (puedes imprimir a PDF desde el navegador).
  - “PDF (servidor)”: genera el PDF en el backend usando WeasyPrint (si está instalado).

---

## Problemas frecuentes
- No encuentra `cairo/pango/gdk-pixbuf`:
  - Revisa que las rutas a `bin` estén en el `PATH` del sistema (reinicia la consola/IDE tras cambiarlas).
- El PDF sale sin imágenes remotas:
  - Verifica conectividad y que las URLs de imágenes sean accesibles desde el servidor.
- Tipografías:
  - WeasyPrint usa fuentes disponibles en el sistema. Para garantizar una fuente concreta, instálala en Windows o referencia una `@font-face` accesible.

---

## Desinstalar
```powershell
pip uninstall weasyprint
```
Elimina también las rutas añadidas al `PATH` si no las necesitas.

---

## Referencias
- WeasyPrint: https://weasyprint.org/
- Documentación: https://doc.courtbouillon.org/weasyprint/latest/
- MSYS2: https://www.msys2.org/
