import time
from typing import Optional

import cv2
from pyzbar.pyzbar import decode
try:
    # Cuando se ejecuta como paquete: python -m src.funko_scanner
    from .funko_api import lookup_upc, pretty_print_item, open_image_url
except Exception:
    # Fallback cuando se ejecuta directamente: python src/funko_scanner.py
    from funko_api import lookup_upc, pretty_print_item, open_image_url


def is_valid_upc(upc: str) -> bool:
    """Valida UPC-A (12 dígitos)."""
    return upc.isdigit() and len(upc) == 12


def scan_barcode(timeout_seconds: int = 60) -> Optional[str]:
    """
    Abre la webcam por defecto y escanea frames hasta detectar un UPC o agotar el tiempo.
    Pulsa 'q' para salir manualmente. Devuelve el UPC si lo encuentra, None en otro caso.
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

            barcodes = decode(frame)

            # Dibujar rectángulos para feedback visual
            for barcode in barcodes:
                (x, y, w, h) = barcode.rect
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                label = getattr(barcode, "type", "BARCODE")
                cv2.putText(frame, label, (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

            for barcode in barcodes:
                upc_raw = barcode.data.decode("utf-8").strip()
                if is_valid_upc(upc_raw):
                    scanned_upc = upc_raw
                    cv2.putText(frame, f"UPC: {upc_raw}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                    cv2.imshow("Escáner de Funko", frame)
                    cv2.waitKey(500)
                    break

            cv2.imshow("Escáner de Funko", frame)

            if scanned_upc:
                break

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

            if (time.time() - start) > timeout_seconds:
                print("Tiempo de espera agotado sin detectar UPC.")
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()

    return scanned_upc


message = (
    "=== Escáner de Códigos de Barras - Funko Pops ===\n"
    "Coloca el código de barras frente a la cámara. Presiona 'q' para salir."
)


def main():
    print(message)

    upc = scan_barcode()

    if not upc:
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
