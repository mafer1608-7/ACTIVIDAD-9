"""
02_capturar_dataset.py - Crea el dataset con ETIQUETADO AUTOMATICO.

Truco: se pone en la bandeja SOLO monedas de UN tipo, se elige la clase con una tecla
y todas las monedas detectadas se guardan ya etiquetadas (sin etiquetar a mano).

Teclas:
  1..9   elegir clase (1=50_vieja 2=50_nueva 3=100_vieja 4=100_nueva 5=200_vieja
         6=200_nueva 7=500_vieja 8=500_nueva 9=1000)
  ESPACIO guardar una captura | c = captura continua (on/off) | f = guardar fondo vacio
  q       salir

Reglas para que el modelo sea exacto (importante):
  - Solo monedas de la clase elegida en la bandeja.
  - Entre capturas MUEVE, GIRA y VOLTEA las monedas (ambas caras; rotacion aleatoria).
  - Usa muchas monedas FISICAS distintas por clase (desgaste, anos distintos).
  - Varia un poco la posicion en la bandeja. No cambies la camara ni la luz entre
    "entrenar" y "usar": si cambian, captura de nuevo en las nuevas condiciones.
"""
import argparse
import csv
import time
from datetime import datetime
from pathlib import Path

import cv2

from comun import CLASES, Camara, detectar_monedas, recortar


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--fuente", default="0")
    ap.add_argument("--salida", default="datos")
    ap.add_argument("--fondo", default=None)
    ap.add_argument("--invertir", action="store_true")
    ap.add_argument("--ventana", type=int, default=160,
                    help="lado (px) de la ventana de recorte; ver 'ventana sugerida' en el paso 1")
    ap.add_argument("--area_min", type=int, default=300)
    ap.add_argument("--intervalo", type=float, default=0.7, help="seg entre capturas en modo continuo")
    ap.add_argument("--ancho", type=int, default=None)
    ap.add_argument("--alto", type=int, default=None)
    args = ap.parse_args()

    salida = Path(args.salida)
    (salida / "crops").mkdir(parents=True, exist_ok=True)
    fondo = cv2.imread(args.fondo) if args.fondo else None
    if args.fondo and fondo is None:
        raise SystemExit(f"No se pudo leer el fondo: {args.fondo}")

    sesion = datetime.now().strftime("%Y%m%d-%H%M%S")  # la sesion se usa para separar train/val
    ruta_csv = salida / "metadatos.csv"
    nuevo = not ruta_csv.exists()
    f_csv = open(ruta_csv, "a", newline="", encoding="utf-8")
    escritor = csv.writer(f_csv)
    if nuevo:
        escritor.writerow(["archivo", "clase", "sesion", "diam_px", "circularidad", "ventana"])

    contadores = {c: len(list((salida / "crops" / c).glob("*.png"))) for c in CLASES}
    clase_idx, continuo, t_ult, n_seq = 0, False, 0.0, 0

    cam = Camara(args.fuente, args.ancho, args.alto)
    print(__doc__)
    while True:
        frame = cam.leer()
        if frame is None:
            continue
        dets = detectar_monedas(frame, fondo, args.invertir, args.area_min)
        vista = frame.copy()
        demasiado_grande = False
        for d in dets:
            color = (0, 200, 0) if d["ok"] else (0, 0, 255)
            cv2.circle(vista, (int(d["cx"]), int(d["cy"])), int(d["diam_px"] / 2), color, 2)
            if d["diam_px"] > 0.9 * args.ventana:
                demasiado_grande = True
        clase = CLASES[clase_idx]
        cv2.putText(vista, f"CLASE [{clase_idx + 1}]: {clase}   guardadas: {contadores[clase]}"
                    f"   {'CONTINUO' if continuo else ''}", (10, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)
        if demasiado_grande:
            cv2.putText(vista, "VENTANA PEQUENA: sube --ventana", (10, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        cv2.imshow("Captura de dataset (q = salir)", vista)

        k = cv2.waitKey(1) & 0xFF
        guardar = False
        if k == ord("q"):
            break
        elif ord("1") <= k <= ord("9"):
            clase_idx = k - ord("1")
        elif k == ord(" "):
            guardar = True
        elif k == ord("c"):
            continuo = not continuo
        elif k == ord("f"):
            cv2.imwrite(str(salida / "fondo.png"), frame)
            fondo = frame.copy()
            print("Fondo guardado (la bandeja debia estar VACIA).")
        if continuo and time.time() - t_ult >= args.intervalo:
            guardar = True

        if guardar:
            validas = [d for d in dets if d["ok"]]
            if not validas or demasiado_grande:
                continue
            carpeta = salida / "crops" / clase
            carpeta.mkdir(parents=True, exist_ok=True)
            for d in validas:
                n_seq += 1
                nombre = f"{sesion}_{n_seq:05d}.png"
                cv2.imwrite(str(carpeta / nombre), recortar(frame, d, args.ventana))
                escritor.writerow([f"{clase}/{nombre}", clase, sesion,
                                   f"{d['diam_px']:.1f}", f"{d['circ']:.3f}", args.ventana])
                contadores[clase] += 1
            f_csv.flush()
            t_ult = time.time()

    f_csv.close()
    cam.cerrar()
    cv2.destroyAllWindows()
    print("Resumen de recortes por clase:")
    for c in CLASES:
        print(f"  {c:10s} {contadores[c]}")


if __name__ == "__main__":
    main()
