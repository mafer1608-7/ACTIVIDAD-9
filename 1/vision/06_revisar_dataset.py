"""
06_revisar_dataset.py - Control de calidad del dataset ANTES de entrenar.

Genera una imagen-mosaico por clase (datos/revision/<clase>.jpg) con recortes al azar y
muestra el conteo por clase y por sesion. Mira los mosaicos: cada moneda debe verse
centrada, completa, sin manos ni sombras raras y con la etiqueta correcta.

Uso:  python 06_revisar_dataset.py --datos datos
"""
import argparse
import random
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from comun import CLASES


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--datos", default="datos")
    ap.add_argument("--n", type=int, default=48, help="recortes por mosaico")
    ap.add_argument("--columnas", type=int, default=8)
    args = ap.parse_args()

    raiz = Path(args.datos)
    (raiz / "revision").mkdir(parents=True, exist_ok=True)
    rng = random.Random(0)
    print(f"{'clase':10s} {'recortes':>8s} {'sesiones':>9s}")
    problemas = []
    for c in CLASES + ["otra"]:
        archivos = sorted((raiz / "crops" / c).glob("*.png"))
        sesiones = Counter(a.stem.split("_")[0] for a in archivos)
        print(f"{c:10s} {len(archivos):8d} {len(sesiones):9d}")
        if not archivos:
            continue  # clase sin datos: simplemente no entra al modelo
        if len(sesiones) < 5:
            problemas.append(f"{c}: {len(sesiones)} sesiones (recomendado: 5; con menos la validacion es optimista)")
        if len(archivos) < 150:
            problemas.append(f"{c}: {len(archivos)} recortes (pocos)")
        muestra = rng.sample(archivos, min(args.n, len(archivos)))
        celdas = [cv2.resize(cv2.imread(str(a)), (112, 112)) for a in muestra]
        while len(celdas) % args.columnas:
            celdas.append(np.zeros((112, 112, 3), np.uint8))
        filas = [np.hstack(celdas[i:i + args.columnas]) for i in range(0, len(celdas), args.columnas)]
        mosaico = np.vstack(filas)
        cv2.putText(mosaico, c, (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        cv2.imwrite(str(raiz / "revision" / f"{c}.jpg"), mosaico)
    print("\nMosaicos en", raiz / "revision")
    if problemas:
        print("\nAVISOS:")
        for p in problemas:
            print(" -", p)
    else:
        print("\nConteos suficientes. Revisa los mosaicos visualmente.")


if __name__ == "__main__":
    main()
