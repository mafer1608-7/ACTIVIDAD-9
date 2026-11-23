"""
05_evaluar.py - Mide la exactitud REAL con una sesion de prueba independiente.

Captura una sesion nueva (otro momento, otra luz, monedas distintas si es posible) con
02_capturar_dataset.py --salida datos_prueba  y evaluala aqui. Esa cifra es la que
refleja lo que pasara el dia de la demostracion; la de validacion de 03_entrenar es optimista.

Uso:
  python 05_evaluar.py --datos datos_prueba --modelo modelo
"""
import argparse
import json
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torchvision
from PIL import Image
from torchvision import transforms as T

from comun import CLASES


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--datos", default="datos_prueba")
    ap.add_argument("--modelo", default="modelo")
    args = ap.parse_args()

    dispositivo = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    info = json.loads((Path(args.modelo) / "clases.json").read_text(encoding="utf-8"))
    clases = info["clases"]
    m = torchvision.models.mobilenet_v2(weights=None)
    m.classifier[1] = nn.Linear(m.last_channel, len(clases))
    m.load_state_dict(torch.load(Path(args.modelo) / "modelo.pt", map_location=dispositivo))
    m = m.to(dispositivo).eval()
    tf = T.Compose([T.Resize((info["tam"], info["tam"])), T.ToTensor(),
                    T.Normalize(info["media"], info["std"])])

    ys, ps, cs = [], [], []
    for c in CLASES + ["otra"]:  # carpetas de prueba; las clases que el modelo no conoce cuentan como 'otra'
        if c in clases:
            ci = clases.index(c)
        elif "otra" in clases:
            ci = clases.index("otra")
        else:
            continue
        for ruta in sorted((Path(args.datos) / "crops" / c).glob("*.png")):
            x = tf(Image.open(ruta).convert("RGB")).unsqueeze(0).to(dispositivo)
            with torch.no_grad():
                pr = torch.softmax(m(x), 1)[0].cpu()
            conf, pred = pr.max(0)
            ys.append(ci)
            ps.append(int(pred))
            cs.append(float(conf))
    if not ys:
        raise SystemExit("No se encontraron imagenes de prueba.")
    ys, ps, cs = np.array(ys), np.array(ps), np.array(cs)
    print(f"Imagenes: {len(ys)}   Exactitud global: {100 * (ys == ps).mean():.2f} %\n")
    n = len(clases)
    cm = np.zeros((n, n), int)
    for a, b in zip(ys, ps):
        cm[a, b] += 1
    print("Matriz de confusion (filas = real, columnas = predicho):")
    print(" " * 11 + " ".join(f"{c[:6]:>6s}" for c in clases))
    for i, c in enumerate(clases):
        print(f"{c:10s} " + " ".join(f"{v:6d}" for v in cm[i]))
    print("\nUmbral -> cobertura / exactitud:")
    for u in (0.5, 0.7, 0.8, 0.9, 0.95, 0.99):
        mk = cs >= u
        if mk.sum():
            print(f"  >= {u:.2f}: acepta {100 * mk.mean():5.1f} %  exactitud {100 * (ys[mk] == ps[mk]).mean():6.2f} %")


if __name__ == "__main__":
    main()
