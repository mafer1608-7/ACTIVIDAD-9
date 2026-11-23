"""
07_grabar_video.py - Graba un video corto de UNA SOLA moneda con la MISMA camara del proyecto.

Por que grabar con este script y no con la app de camara del celular: el video queda con la
misma resolucion, luz y encuadre que veran los demas scripts. Ademas el video crudo se guarda,
asi puedes reprocesarlo (otra --ventana, otro fondo) sin volver a mover monedas.

Uso (una moneda por video; el NOMBRE del archivo define la clase):
  python 07_grabar_video.py --fuente http://TU_IP:8080/video --clase 100_nueva --segundos 40

Teclas: ESPACIO = empezar a grabar | q = salir
Durante la grabacion: empuja la moneda con el dedo, giratela y voltéala; retira la mano y
espera ~1 s con la moneda quieta. Usa ambas caras (mitad y mitad).
"""
import argparse
import time
from pathlib import Path

import cv2

from comun import CLASES, Camara


def nombre_libre(carpeta, clase, ext):
    n = 1
    while True:
        sufijo = "" if n == 1 else f"_{n}"
        ruta = carpeta / f"{clase}{sufijo}.{ext}"
        if not ruta.exists():
            return ruta
        n += 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--fuente", default="0")
    ap.add_argument("--clase", required=True, choices=CLASES + ["otra"],
                    help="otra = video con VARIAS monedas distintas a la buscada (nunca la buscada)")
    ap.add_argument("--segundos", type=float, default=40.0)
    ap.add_argument("--fps", type=float, default=20.0)
    ap.add_argument("--salida", default="videos")
    ap.add_argument("--ancho", type=int, default=None)
    ap.add_argument("--alto", type=int, default=None)
    ap.add_argument("--auto", action="store_true", help="empezar sin esperar la tecla ESPACIO")
    ap.add_argument("--sin_ventana", action="store_true")
    args = ap.parse_args()

    carpeta = Path(args.salida)
    carpeta.mkdir(parents=True, exist_ok=True)
    cam = Camara(args.fuente, args.ancho, args.alto)
    primero = cam.leer()
    h, w = primero.shape[:2]

    def abrir_escritor():
        for ext, codec in (("mp4", "mp4v"), ("avi", "MJPG")):
            ruta = nombre_libre(carpeta, args.clase, ext)
            esc = cv2.VideoWriter(str(ruta), cv2.VideoWriter_fourcc(*codec), args.fps, (w, h))
            if esc.isOpened():
                return esc, ruta
        raise SystemExit("No se pudo crear el archivo de video (codec no disponible).")

    grabando, escritor, ruta, t0, siguiente, dt = args.auto, None, None, 0.0, 0.0, 1.0 / args.fps
    n_cuadros = 0
    print(f"Clase: {args.clase}  |  {w}x{h}  |  ESPACIO para grabar {args.segundos:.0f} s, q para salir")
    while True:
        frame = cam.leer()
        if frame is None:
            continue
        if frame.shape[1] != w or frame.shape[0] != h:
            frame = cv2.resize(frame, (w, h))
        ahora = time.time()
        if grabando and escritor is None:
            escritor, ruta = abrir_escritor()
            t0 = siguiente = ahora
        if grabando:
            if ahora >= siguiente:
                escritor.write(frame)
                n_cuadros += 1
                siguiente = max(siguiente + dt, ahora)
            if ahora - t0 >= args.segundos:
                break

        tecla = 255
        if not args.sin_ventana:
            vista = frame.copy()
            if grabando:
                texto = f"REC {args.clase}  {max(0.0, args.segundos - (ahora - t0)):.0f} s"
                color = (0, 0, 255)
            else:
                texto = f"{args.clase}: ESPACIO para grabar"
                color = (0, 255, 255)
            cv2.putText(vista, texto, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
            cv2.imshow("Grabar video (q = salir)", vista)
            tecla = cv2.waitKey(1) & 0xFF
        else:
            time.sleep(0.005)
        if tecla == ord("q"):
            break
        if tecla == ord(" "):
            grabando = True

    if escritor is not None:
        escritor.release()
        print(f"Video guardado: {ruta}  ({n_cuadros} cuadros)")
    else:
        print("No se grabo nada.")
    cam.cerrar()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
