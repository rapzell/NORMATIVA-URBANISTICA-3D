import cv2
from pyzbar.pyzbar import decode
import time
from typing import Optional
try:
    # Cuando se ejecuta como paquete: python -m src.scanner
    from .api import lookup_upc, pretty_print_item, open_image_url
except Exception:
    # Fallback cuando se ejecuta directamente: python src/scanner.py
    from api import lookup_upc, pretty_print_item, open_image_url


def is_valid_upc(upc: str) -> bool:
    """Validate UPC-A (12 digits)."""
    return upc.isdigit() and len(upc) == 12


def scan_barcode(timeout_seconds: int = 60) -> Optional[str]:
    """
    Open the default webcam and scan frames until a UPC is detected or timeout.
    Press 'q' to quit manually.
    Returns the UPC string if found, else None.
    """
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("No se pudo abrir la cámara. Prueba con otro índice (1, 2) o verifica permisos.")
        return None

    scanned_upc = None
    start = time.time()

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("Error al capturar frame.")
                break

            # Decodificar códigos en el frame
            barcodes = decode(frame)

            # Dibujar rectángulos para feedback visual
            for barcode in barcodes:
                (x, y, w, h) = barcode.rect
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                # Mostrar tipo
                try:
                    text = barcode.type
                except Exception:
                    text = "BARCODE"
                cv2.putText(frame, text, (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

            for barcode in barcodes:
                upc_raw = barcode.data.decode("utf-8").strip()
                if is_valid_upc(upc_raw):
                    scanned_upc = upc_raw
                    cv2.putText(frame, f"UPC: {upc_raw}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                    # Mostrar un frame con el UPC confirmado
                    cv2.imshow("Escáner de Funko", frame)
                    cv2.waitKey(500)
                    break

            # Mostrar frame
            cv2.imshow("Escáner de Funko", frame)

            if scanned_upc:
                break

            # Salir manualmente
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

            # Timeout
            if (time.time() - start) > timeout_seconds:
                print("Tiempo de espera agotado sin detectar UPC.")
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()

    return scanned_upc


def main():
    print("=== Escáner de Códigos de Barras - Funko Pops ===")
    print("Coloca el código de barras frente a la cámara. Presiona 'q' para salir.")

    upc = scan_barcode()

    if not upc:
        # Fallback: entrada manual
        manual = input("No se detectó UPC. ¿Deseas introducirlo manualmente? (deja vacío para salir): ").strip()
        if manual:
            if is_valid_upc(manual):
                upc = manual
            else:
                print("El UPC manual no es válido (deben ser 12 dígitos).")
                return
        else:
            print("Saliendo.")
            return

    print(f"UPC detectado: {upc}")
    print("Consultando API...")

    result = lookup_upc(upc)

    if not result or result.get("code") != "OK" or result.get("total", 0) == 0:
        print("No se encontró información para este UPC o hubo un error en la API.")
        return

    item = result["items"][0]
    pretty_print_item(item)

    # Mostrar imagen opcionalmente
    images = item.get("images") or []
    if images:
        choice = input("¿Abrir la imagen del producto? (s/n): ").strip().lower()
        if choice == 's':
            try:
                open_image_url(images[0])
            except Exception as ex:
                print(f"No se pudo abrir la imagen: {ex}")


if __name__ == "__main__":
    main()
