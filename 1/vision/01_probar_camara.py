"""
01_probar_camara.py - Verifica la camara, muestra la deteccion y DIAGNOSTICA su estabilidad.

Ejemplos:
  python 01_probar_camara.py --fuente 0                                # webcam USB / integrada
  python 01_probar_camara.py --fuente http://192.168.1.67:8080/video   # app IP Webcam (Android)
  python 01_probar_camara.py --fuente http://IP:8080/video --fondo datos/fondo.png

Que muestra:
  - Circulo VERDE = moneda estable; AMARILLO = retenida unos cuadros; ROJO = rechazada (con motivo).
  - 'estabilidad' = % de los ultimos 30 cuadros con una moneda valida. Objetivo: > 95 %.
  - 'fallos' = por que se rechazo en los ultimos 60 cuadros (borde / forma / nada).
  - 'ventana sugerida' = mediana de los ultimos 60 cuadros (no salta).

Teclas: s = guardar foto | f = guardar FONDO (bandeja vacia) | m = ver mascara | q = salir
"""
import argparse
import time
from collections import Counter, deque
from pathlib import Path

import cv2
import numpy as np

from comun import Camara, Estabilizador, detectar_con_mascara, ventana_sugerida


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--fuente", default="0")
    ap.add_argument("--ancho", type=int, default=None)
    ap.add_argument("--alto", type=int, default=None)
    ap.add_argument("--fondo", default=None, help="imagen de bandeja vacia (muy recomendado)")
    ap.add_argument("--invertir", action="store_true", help="monedas OSCURAS sobre fondo CLARO")
    ap.add_argument("--area_min", type=int, default=300)
    ap.add_argument("--circ_min", type=float, default=0.82)
    ap.add_argument("--ancho_proc", type=int, default=640, help="ancho al que se procesa la deteccion")
    ap.add_argument("--umbral_dif", type=float, default=None,
                    help="con fondo: umbral fijo (p.ej. 25) en vez de automatico")
    ap.add_argument("--sin_estabilizar", action="store_true")
    args = ap.parse_args()

    fondo = cv2.imread(args.fondo) if args.fondo else None
    if args.fondo and fondo is None:
        raise SystemExit(f"No se pudo leer el fondo: {args.fondo}")

    cam = Camara(args.fuente, args.ancho, args.alto)
    Path("datos").mkdir(exist_ok=True)
    est = Estabilizador()
    hist_ok, hist_fallos, hist_diam = deque(maxlen=30), deque(maxlen=60), deque(maxlen=60)
    ver_mascara = False
    t_fps, n, fps = time.time(), 0, 0.0
    print("Camara conectada. Teclas: s=foto | f=fondo | m=mascara | q=salir")
    while True:
        frame = cam.leer()
        if frame is None:
            continue
        n += 1
        if time.time() - t_fps >= 1.0:
            fps, n, t_fps = n / (time.time() - t_fps), 0, time.time()
        dets, mascara = detectar_con_mascara(frame, fondo, args.invertir, args.area_min,
                                             args.circ_min, ancho_proc=args.ancho_proc,
                                             umbral_dif=args.umbral_dif)
        h, w = frame.shape[:2]
        buenas = [d for d in dets if d["ok"]]
        hist_ok.append(len(buenas) > 0)
        if buenas:
            hist_diam.append(max(d["diam_px"] for d in buenas))
        if not dets:
            hist_fallos.append("nada")
        for d in dets:
            if not d["ok"]:
                hist_fallos.append(d["motivo"].split(" ")[0])

        vista = frame.copy()
        for d in dets:
            if not d["ok"]:
                cv2.circle(vista, (int(d["cx"]), int(d["cy"])), int(d["diam_px"] / 2), (0, 0, 255), 2)
                cv2.putText(vista, f"{d['motivo']} c={d['circ']:.2f} aj={d['ajuste']:.2f}",
                            (int(d["cx"]) - 90, int(d["cy"])), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
        if args.sin_estabilizar:
            visibles = [dict(d, retenida=False) for d in buenas]
        else:
            visibles = est.actualizar(dets)
        for p in visibles:
            color = (0, 255, 255) if p["retenida"] else (0, 200, 0)
            cv2.circle(vista, (int(p["cx"]), int(p["cy"])), int(p["diam_px"] / 2), color, 2)
            cv2.putText(vista, f"{p['diam_px']:.0f}px", (int(p["cx"]) - 25, int(p["cy"]) - int(p["diam_px"] / 2) - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

        pct = 100.0 * sum(hist_ok) / max(len(hist_ok), 1)
        resumen = ", ".join(f"{k} x{v}" for k, v in Counter(hist_fallos).most_common(3)) or "ninguno"
        lineas = [(f"{w}x{h}  {fps:.0f} fps  monedas: {len(visibles)}", (255, 255, 0)),
                  (f"estabilidad: {pct:.0f} %   fallos: {resumen}", (0, 255, 0) if pct >= 95 else (0, 165, 255))]
        if len(hist_diam) >= 10:
            mediana = float(np.median(hist_diam))
            lineas.append((f"ventana sugerida: {ventana_sugerida(mediana)} px (mediana, diam {mediana:.0f} px)",
                           (255, 255, 0)))
            if mediana > 0.45 * min(h, w):
                lineas.append(("MONEDA MUY GRANDE EN EL ENCUADRE: aleja la camara (se acerca al borde y "
                               "la deteccion parpadea)", (0, 0, 255)))
        for i, (txt, col) in enumerate(lineas):
            cv2.putText(vista, txt, (10, 24 + 24 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2)
        cv2.imshow("Prueba de camara (q = salir)", vista)
        if ver_mascara:
            cv2.imshow("Mascara (lo que el programa considera 'moneda')", mascara)

        k = cv2.waitKey(1) & 0xFF
        if k == ord("q"):
            break
        if k == ord("m"):
            ver_mascara = not ver_mascara
            if not ver_mascara:
                cv2.destroyWindow("Mascara (lo que el programa considera 'moneda')")
        if k == ord("s"):
            ruta = f"datos/prueba_{int(time.time())}.png"
            cv2.imwrite(ruta, frame)
            print("Guardada", ruta)
        if k == ord("f"):
            cv2.imwrite("datos/fondo.png", frame)
            fondo = frame.copy()
            print("Fondo guardado en datos/fondo.png (la bandeja debe estar VACIA)")
    cam.cerrar()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
