import os
import json
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer

def crear_y_guardar_indice():
    """Carga los chunks, crea los embeddings y guarda el índice FAISS."""
    print("Iniciando la creación del índice vectorial...")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # --- 1. Cargar los documentos fragmentados ---
    ruta_chunks = os.path.join(script_dir, '..', 'datos', 'normativa_chunks.json')
    if not os.path.exists(ruta_chunks):
        print(f"Error: No se encuentra el archivo '{ruta_chunks}'. Ejecuta primero 'procesar_normativa.py'.")
        return

    with open(ruta_chunks, 'r', encoding='utf-8') as f:
        documentos = json.load(f)
    
    contenidos = [doc['contenido'] for doc in documentos]
    print(f"Se han cargado {len(contenidos)} fragmentos de texto.")

    # --- 2. Cargar el modelo de Sentence Transformers ---
    # Este modelo es potente y multilingüe, ideal para textos en español.
    print("Cargando el modelo de Sentence Transformers... (puede tardar un poco la primera vez)")
    modelo_nombre = 'sentence-transformers/paraphrase-multilingual-mpnet-base-v2'
    modelo = SentenceTransformer(modelo_nombre)

    # --- 3. Generar los embeddings para cada fragmento ---
    print("Generando embeddings para los fragmentos de texto...")
    embeddings = modelo.encode(contenidos, show_progress_bar=True)
    print(f"Se han generado {len(embeddings)} vectores con una dimensión de {embeddings.shape[1]}.")

    # --- 4. Crear y poblar el índice FAISS ---
    dimension = embeddings.shape[1]
    index = faiss.IndexFlatL2(dimension)
    index.add(np.array(embeddings))

    print(f"Índice FAISS creado. Total de vectores en el índice: {index.ntotal}")

    # --- 5. Guardar el índice en disco ---
    ruta_indice = os.path.join(script_dir, '..', 'datos', 'normativa.index')
    faiss.write_index(index, ruta_indice)
    
    print(f"\n¡Éxito! El índice ha sido guardado en '{ruta_indice}'.")
    print("El sistema está listo para la nueva versión del asistente.")

if __name__ == "__main__":
    crear_y_guardar_indice()
