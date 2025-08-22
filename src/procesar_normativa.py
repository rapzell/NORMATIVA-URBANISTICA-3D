import os
import re
import json
import unicodedata
import pdfplumber
from bs4 import BeautifulSoup
from langchain.text_splitter import RecursiveCharacterTextSplitter

def limpiar_texto(texto):
    """Limpia el texto eliminando saltos de línea anómalos y patrones no deseados."""
    texto = re.sub(r'(?<!\n\n)(?<![.\?!])\n(?!\n)', ' ', texto)
    texto = re.sub(r'\n{2,}', '\n\n', texto)
    texto = re.sub(r'DOG Núm\. \d+.*', '', texto, flags=re.IGNORECASE)
    texto = re.sub(r'Viernes, \d+ de \w+ de \d+.*', '', texto, flags=re.IGNORECASE)
    texto = re.sub(r'Página \d+.*', '', texto, flags=re.IGNORECASE)
    texto = re.sub(r'CVE-DOG:.*', '', texto, flags=re.IGNORECASE)
    return texto.strip()

def extraer_texto_pdf(ruta_pdf):
    """Extrae el texto completo de un archivo PDF."""
    print(f"Procesando PDF: {os.path.basename(ruta_pdf)}")
    texto_completo = ""
    try:
        with pdfplumber.open(ruta_pdf) as pdf:
            for page in pdf.pages:
                texto_completo += page.extract_text() or ''
    except Exception as e:
        print(f"ERROR al procesar {os.path.basename(ruta_pdf)}: {e}")
    return texto_completo

def extraer_texto_html(ruta_html):
    """Extrae el texto de un archivo HTML usando BeautifulSoup."""
    print(f"Procesando HTML: {os.path.basename(ruta_html)}")
    texto_completo = ""
    try:
        with open(ruta_html, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'lxml')
            for script_or_style in soup(['script', 'style']):
                script_or_style.decompose()
            texto_completo = soup.get_text(separator='\n', strip=True)
    except Exception as e:
        print(f"ERROR al procesar {os.path.basename(ruta_html)}: {e}")
    return texto_completo

def extraer_texto_txt(ruta_txt):
    """Extrae el texto de un archivo de texto plano."""
    print(f"Procesando TXT: {os.path.basename(ruta_txt)}")
    texto_completo = ""
    try:
        with open(ruta_txt, 'r', encoding='utf-8') as f:
            texto_completo = f.read()
    except Exception as e:
        print(f"ERROR al procesar {os.path.basename(ruta_txt)}: {e}")
    return texto_completo

def limpiar_errores_ocr(texto):
    """Corrige errores comunes de OCR y artefactos textuales."""
    # Normalización Unicode para estabilizar tildes/ñ
    try:
        texto = unicodedata.normalize('NFC', texto)
    except Exception:
        pass

    correcciones = {
        r'sueol': 'suelo',
        r'sueño': 'suelo',
        r'sueo': 'suelo',
        r'urbanstica': 'urbanística',
        r'planeamiente': 'planeamiento',
        r'pro- tección': 'protección',
        r'ordena- ción': 'ordenación',
        r'articulo': 'artículo',
        r'publica- ción': 'publicación',
        r'consolida- do': 'consolidado',
        r'urbanis- tica': 'urbanística',
        r'urbanis- tico': 'urbanístico',
        r'ámbitoo': 'ámbito',
        r' su e l o ': ' suelo ',
        r's u e l o': 'suelo',
        # Mojibake frecuentes de encabezados/artículos
        r'Art[�\?]culo': 'Artículo',
        r'T[�\?]TULO': 'TÍTULO',
        r'CAP[�\?]TULO': 'CAPÍTULO',
        r'SECCI[�\?]N': 'SECCIÓN',
        r'AP[�\?]NDICE': 'APÉNDICE',
        r'CAP[ÍI]TULO': 'CAPÍTULO',
        r'T[ÍI]TULO': 'TÍTULO',
        r'\s{2,}': ' ',
    }
    for error, correccion in correcciones.items():
        texto = re.sub(error, correccion, texto, flags=re.IGNORECASE)
    return texto

def fragmentar_texto(texto, nombre_fuente):
    """Fragmenta un texto largo en chunks más pequeños usando un método recursivo y robusto."""
    if not texto:
        return []

    texto_corregido_ocr = limpiar_errores_ocr(texto)
    texto_limpio = limpiar_texto(texto_corregido_ocr)

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=320,  # Tamaño mayor para capturar definiciones completas
        chunk_overlap=40,  # Solapamiento suficiente para contexto
        length_function=len,
        separators=["\n\n", "\n", ". ", ", ", " "]
    )

    fragmentos_texto = text_splitter.split_text(texto_limpio)

    # Inferir tipo de fuente
    fuente_lower = (nombre_fuente or "").lower()
    tipo_fuente = 'ley' if 'ley 2/2016' in fuente_lower else ('decreto' if 'decreto 143/2016' in fuente_lower else 'otro')

    # Detectar artículo actual por fragmento
    import re
    patron_art = re.compile(r"art[íi]culo\s+(\d+)", flags=re.IGNORECASE)
    articulo_actual = None
    chunks = []
    for fragmento in fragmentos_texto:
        m = patron_art.search(fragmento)
        if m:
            articulo_actual = f"Artículo {m.group(1)}"
        chunks.append({
            'contenido': fragmento,
            'metadata': {
                'fuente': nombre_fuente,
                'tipo_fuente': tipo_fuente,
                'articulo': articulo_actual or ''
            }
        })

    print(f" -> Generados {len(chunks)} chunks.")
    return chunks

def main():
    """Función principal para procesar todos los documentos y guardar los chunks."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    datos_dir = os.path.join(script_dir, '..', 'datos')
    ruta_salida_json = os.path.join(datos_dir, 'normativa_chunks.json')

    # Mapeo de nombres de archivo a fuentes legibles y sus funciones de extracción
    fuentes_map = {
        "AnuncioC3B0-150216-0001_es.pdf": {
            "fuente_legible": "Ley 2/2016 del Suelo de Galicia",
            "extractor": extraer_texto_pdf
        },
        "DOG 213 del 9_11_2016 - DECRETO 143_2016, de 22 de septiembre, por el que se aprueba el Reglamento de la Ley 2_2016, de 10 de febrero, del suelo de Galicia..html": {
            "fuente_legible": "Reglamento de la Ley (Decreto 143/2016)",
            "extractor": extraer_texto_html
        },
        "Modificaciones Leyes.txt": {
            "fuente_legible": "Modificaciones y Leyes Complementarias",
            "extractor": extraer_texto_txt
        }
    }

    chunks_totales = []
    print("Iniciando el procesamiento unificado de la normativa...")

    for nombre_archivo, data in fuentes_map.items():
        ruta_completa = os.path.join(datos_dir, nombre_archivo)
        fuente_legible = data["fuente_legible"]
        extractor = data["extractor"]

        if os.path.isfile(ruta_completa):
            contenido = extractor(ruta_completa)
            if contenido:
                nuevos_chunks = fragmentar_texto(contenido, fuente_legible)
                chunks_totales.extend(nuevos_chunks)
        else:
            print(f"ADVERTENCIA: No se encontró el archivo {nombre_archivo} en {datos_dir}")

    # Guardar todos los chunks en un único archivo JSON
    with open(ruta_salida_json, 'w', encoding='utf-8') as f:
        json.dump(chunks_totales, f, ensure_ascii=False, indent=4)
    
    print(f"\n¡Éxito! Se han guardado un total de {len(chunks_totales)} fragmentos en '{ruta_salida_json}'.")

if __name__ == "__main__":
    main()
