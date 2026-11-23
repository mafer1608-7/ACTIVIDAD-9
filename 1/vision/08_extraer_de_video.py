"""
08_extraer_de_video.py - Convierte videos de monedas en recortes ETIQUETADOS para entrenar.

La clase se toma del NOMBRE del archivo: 100_vieja.mp4, 100_vieja_2.mp4, 1000.avi ...
Nombre especial  otra.mp4 / otra_2.mp4 : video con VARIAS monedas distintas a la vez
(todas las que NO son la buscada). Se guardan todas las monedas aisladas de cada cuadro como
clase 'otra'. NUNCA pongas la moneda buscada en un video 'otra'.

Muestra una ventana emergente con la deteccion (verde = aceptada, rojo = rechazada).

Reglas de seguridad para no ensuciar el dataset:
  - Video de UNA clase: solo se guarda un cuadro si hay EXACTAMENTE un objeto y es valido
    (si aparece la mano, otra moneda o la moneda esta cortada, ese cuadro se ignora).
  - Video 'otra': se guardan solo las monedas validas (circulares, completas y separadas);
    lo cortado, pegado o la mano se ignora.
  - Solo se guarda lo que se ve DISTINTO a lo guardado hace poco (otro giro / otra cara) y
    con al menos --min_cuadros entre capturas: evita copias casi identicas.
    Si salen pocos recortes, baja --dif; si salen demasiadas copias, sube --dif.

Uso:
  python 08_extraer_de_video.py --carpeta videos --fondo datos/fondo.png --ventana 160
Teclas en la ventana: n = siguiente video | q = salir
"""
import argparse
import csv
from collections import deque
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from comun import CLASES, detectar_monedas, recortar

EXTENSIONES = {".mp4", ".avi", ".mov", ".mkv", ".m4v"}
TODAS = CLASES + ["otra"]


def clase_de_archivo(ruta):
    stem = ruta.stem
    for c in TODAS:
        if stem == c or stem.startswith(c + "_"):
            return c
    return None


def firma(crop):
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    return cv2.resize(g, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--carpeta", default="videos")
    ap.add_argument("--video", default=None, help="procesar un solo archivo")
    ap.add_argument("--salida", default="datos")
    ap.add_argument("--fondo", default=None)
    ap.add_argument("--invertir", action="store_true")
    ap.add_argument("--ventana", type=int, default=160, help="DEBE ser la misma en todo el proyecto")
    ap.add_argument("--area_min", type=int, default=300)
    ap.add_argument("--dif", type=float, default=2.5, help="cambio minimo (0-255) respecto a lo guardado")
    ap.add_argument("--min_cuadros", type=int, default=3, help="cuadros minimos entre dos capturas")
    ap.add_argument("--bloques", type=int, default=5, help="trozos del video tratados como 'sesiones'")
    ap.add_argument("--max_por_video", type=int, default=600)
    ap.add_argument("--max_otra", type=int, default=1500, help="tope para videos 'otra'")
    ap.add_argument("--demora", type=int, default=1, help="ms por cuadro en la ventana (sube para ver mas lento)")
    ap.add_argument("--sin_ventana", action="store_true")
    args = ap.parse_args()

    if args.video:
        videos = [Path(args.video)]
    else:
        videos = sorted(p for p in Path(args.carpeta).glob("*") if p.suffix.lower() in EXTENSIONES)
    if not videos:
        raise SystemExit("No se encontraron videos.")
    fondo = cv2.imread(args.fondo) if args.fondo else None
    if args.fondo and fondo is None:
        raise SystemExit(f"No se pudo leer el fondo: {args.fondo}")

    salida = Path(args.salida)
    (salida / "crops").mkdir(parents=True, exist_ok=True)
    ruta_csv = salida / "metadatos.csv"
    nuevo = not ruta_csv.exists()
    f_csv = open(ruta_csv, "a", newline="", encoding="utf-8")
    escritor = csv.writer(f_csv)
    if nuevo:
        escritor.writerow(["archivo", "clase", "sesion", "diam_px", "circularidad", "ventana"])

    sello = datetime.now().strftime("%Y%m%d-%H%M%S")
    n_seq, nuevos, salir = 0, {c: 0 for c in TODAS}, False

    for vi, ruta_video in enumerate(videos):
        clase = clase_de_archivo(ruta_video)
        if clase is None:
            print(f"OMITIDO (el nombre no empieza con una clase valida): {ruta_video.name}")
            continue
        cap = cv2.VideoCapture(str(ruta_video))
        if not cap.isOpened():
            print(f"OMITIDO (no se pudo abrir): {ruta_video.name}")
            continue
        es_otra = clase == "otra"
        tope = args.max_otra if es_otra else args.max_por_video
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        blk = max(1, total // args.bloques) if total > 0 else 300
        carpeta = salida / "crops" / clase
        carpeta.mkdir(parents=True, exist_ok=True)
        recientes = deque(maxlen=40 if es_otra else 1)  # firmas de lo guardado hace poco
        ultimo_idx, guardados, idx, avisado = 0, 0, 0, False
        print(f"[{vi + 1}/{len(videos)}] {ruta_video.name} -> clase {clase}")

        while True:
            ok, frame = cap.read()
            if not ok:
                break
            idx += 1
            dets = detectar_monedas(frame, fondo, args.invertir, args.area_min)
            candidatas = []
            if guardados < tope and (not recientes or idx - ultimo_idx >= args.min_cuadros):
                if es_otra:
                    pool = [d for d in dets if d["ok"]]
                else:
                    pool = [dets[0]] if len(dets) == 1 and dets[0]["ok"] else []
                for d in pool:
                    if d["diam_px"] > 0.9 * args.ventana:
                        if not avisado:
                            print("  AVISO: una moneda no cabe en --ventana; sube el valor.")
                            avisado = True
                        continue
                    crop = recortar(frame, d, args.ventana)
                    f = firma(crop)
                    if all(float(np.mean(np.abs(f - r))) > args.dif for r in recientes):
                        candidatas.append((d, crop))
                        recientes.append(f)
            if candidatas:
                ultimo_idx = idx
                bloque = idx // blk if total <= 0 else min(args.bloques - 1, idx // blk)
                sesion = f"{sello}v{vi}b{bloque}"  # sin guion bajo: 03_entrenar la usa para separar
                for d, crop in candidatas:
                    n_seq += 1
                    nombre = f"{sesion}_{n_seq:05d}.png"
                    cv2.imwrite(str(carpeta / nombre), crop)
                    escritor.writerow([f"{clase}/{nombre}", clase, sesion,
                                       f"{d['diam_px']:.1f}", f"{d['circ']:.3f}", args.ventana])
                    guardados += 1
                    nuevos[clase] += 1

            if not args.sin_ventana:
                vista = frame.copy()
                for d in dets:
                    color = (0, 200, 0) if d["ok"] else (0, 0, 255)
                    cv2.circle(vista, (int(d["cx"]), int(d["cy"])), int(d["diam_px"] / 2), color, 2)
                    if not d["ok"]:
                        cv2.putText(vista, d["motivo"], (int(d["cx"]) - 40, int(d["cy"])),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
                cv2.putText(vista, f"{clase}  video {vi + 1}/{len(videos)}  cuadro {idx}/{max(total, 0)}"
                            f"  guardados: {guardados}", (10, 26),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
                cv2.imshow("Extraccion desde video (n = siguiente, q = salir)", vista)
                k = cv2.waitKey(max(1, args.demora)) & 0xFF
                if k == ord("q"):
                    salir = True
                    break
                if k == ord("n"):
                    break
        cap.release()
        f_csv.flush()
        print(f"  guardados: {guardados}")
        if guardados < 100:
            print("  AVISO: pocos recortes. Graba un video mas largo o con mas giros/vueltas "
                  "(o baja --dif).")
        if salir:
            break

    f_csv.close()
    cv2.destroyAllWindows()
    print("\nRecortes nuevos por clase en esta ejecucion / total en carpeta:")
    for c in TODAS:
        total_c = len(list((salida / "crops" / c).glob("*.png")))
        if nuevos[c] or total_c:
            print(f"  {c:10s} +{nuevos[c]:4d}   total {total_c}")


if __name__ == "__main__":
    main()
