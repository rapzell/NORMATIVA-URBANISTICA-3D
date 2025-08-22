import json
import os
import sys

def cargar_base_de_datos(ruta_archivo):
    """Carga la base de datos JSON desde la ruta especificada."""
    if not os.path.exists(ruta_archivo):
        print(f"Error: El archivo de base de datos no se encuentra en '{ruta_archivo}'.")
        print("Por favor, asegúrese de haber ejecutado primero 'procesar_normativa.py'.")
        return None
    with open(ruta_archivo, 'r', encoding='utf-8') as f:
        return json.load(f)

def mostrar_informacion_categoria(datos, nombre_categoria):
    """Muestra de forma estructurada la información de una categoría de suelo."""
    categoria = datos.get(nombre_categoria)

    if not categoria:
        print(f"\nLo sentimos, la categoría '{nombre_categoria}' no fue encontrada.")
        print(f"Categorías disponibles: {', '.join(datos.keys())}")
        return

    print(f"\n--- INFORMACIÓN PARA: {nombre_categoria.upper()} ---")
    if 'titulo' in categoria:
        print(f"\n[+] Título principal: {categoria['titulo']}")
    if 'texto_completo' in categoria:
        print(f"\n[i] Texto completo:\n{categoria['texto_completo']}\n")

    if 'reglas_extraidas' in categoria and categoria['reglas_extraidas']:
        print("\n--- Reglas y Subcategorías ---")
        for sub_key, sub_value in categoria['reglas_extraidas'].items():
            print(f"\n  * {sub_key.replace('_', ' ').capitalize()}:")
            print(f"    - Título: {sub_value['titulo']}")
            if 'texto' in sub_value:
                print(f"    - Descripción: {sub_value['texto'][:200]}...")
            
            if 'subdivisiones' in sub_value:
                print("\n    --- Subdivisiones de Protección Especial ---")
                for div_key, div_value in sub_value['subdivisiones'].items():
                    print(f"      - {div_value['titulo']}:")
                    print(f"        {div_value['texto']}")

def main():
    """Función principal para la interfaz de usuario del sistema de consulta."""
    ruta_json = os.path.join('datos', 'normativa_estructurada.json')
    base_de_datos = cargar_base_de_datos(ruta_json)

    if base_de_datos is None:
        return

    # Modo no interactivo: procesar argumento de línea de comandos
    if len(sys.argv) > 1:
        categoria_consulta = sys.argv[1].lower().strip()
        if categoria_consulta in base_de_datos:
            mostrar_informacion_categoria(base_de_datos, categoria_consulta)
        else:
            print(f"Error: Categoría '{categoria_consulta}' no válida.")
            print(f"Categorías disponibles: {', '.join(base_de_datos.keys())}")
        return

    # Modo interactivo: si no hay argumentos
    print("--- Sistema de Consulta de Normativa Urbanística de Galicia ---")
    print("Bienvenido. Puede consultar información sobre las siguientes categorías de suelo:")
    print(f"-> {', '.join(base_de_datos.keys())}")
    print("Escriba 'salir' para terminar.")

    while True:
        try:
            categoria_consulta = input("\n¿Qué categoría de suelo desea consultar? > ").lower().strip()
            if categoria_consulta == 'salir':
                break
            if categoria_consulta in base_de_datos:
                mostrar_informacion_categoria(base_de_datos, categoria_consulta)
            else:
                print(f"Error: Categoría '{categoria_consulta}' no válida. Inténtelo de nuevo.")
        except (EOFError, KeyboardInterrupt):
            print("\nSaliendo del programa.")
            break

if __name__ == "__main__":
    main()
