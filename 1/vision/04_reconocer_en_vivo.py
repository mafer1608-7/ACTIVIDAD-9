"""
04_reconocer_en_vivo.py - Reconoce las monedas en vivo desde la camara (PC o celular).

Aumenta la exactitud con tres mecanismos:
  1) Promedio de probabilidades en varios fotogramas por moneda (seguimiento simple).
  2) Umbral de confianza: por debajo de el se muestra '?' en vez de arriesgar un error.
  3) Verificacion de diametro (si pasas --mm_por_px): si el diametro medido no cuadra con la
     clase predicha, la moneda se marca 'inconsistente'.

Uso:
  python 04_reconocer_en_vivo.py --fuente http://192.168.1.67:8080/video --ventana 160 \
      --fondo datos/fondo.png --mm_por_px 0.15

Teclas: r = imprimir informe JSON de monedas confirmadas | q = salir
"""
import argparse
import json
from collections import deque
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn as nn
import torchvision
from PIL import Image
from torchvision import transforms as T

from comun import DIAMETRO_MM, TAM_CAPTURA, Camara, detectar_monedas, recortar


def cargar_modelo(carpeta, dispositivo):
    info = json.loads((Path(carpeta) / "clases.json").read_text(encoding="utf-8"))
    m = torchvision.models.mobilenet_v2(weights=None)
    m.classifier[1] = nn.Linear(m.last_channel, len(info["clases"]))
    m.load_state_dict(torch.load(Path(carpeta) / "modelo.pt", map_location=dispositivo))
    return m.to(dispositivo).eval(), info


def a_tensor(crop_bgr, tf):
    """Mismo preprocesado que en entrenamiento (Resize + Normalize)."""
    return tf(Image.fromarray(cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--fuente", default="0")
    ap.add_argument("--modelo", default="modelo")
    ap.add_argument("--fondo", default=None)
    ap.add_argument("--invertir", action="store_true")
    ap.add_argument("--ventana", type=int, default=160, help="DEBE ser igual a la usada al capturar")
    ap.add_argument("--area_min", type=int, default=300)
    ap.add_argument("--umbral", type=float, default=0.80)
    ap.add_argument("--frames", type=int, default=7, help="fotogramas a promediar por moneda")
    ap.add_argument("--min_frames", type=int, default=3)
    ap.add_argument("--mm_por_px", type=float, default=None)
    ap.add_argument("--tol_mm", type=float, default=1.2)
    ap.add_argument("--ancho", type=int, default=None)
    ap.add_argument("--alto", type=int, default=None)
    args = ap.parse_args()

    dispositivo = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    modelo, info = cargar_modelo(args.modelo, dispositivo)
    clases = info["clases"]
    tf = T.Compose([T.Resize((info["tam"], info["tam"])), T.ToTensor(),
                    T.Normalize(info["media"], info["std"])])
    fondo = cv2.imread(args.fondo) if args.fondo else None
    cam = Camara(args.fuente, args.ancho, args.alto)

    pistas = []  # cada pista: dict(cx, cy, r, hist(deque de probs), perdidas)
    confirmadas = []
    while True:
        frame = cam.leer()
        if frame is None:
            continue
        dets = [d for d in detectar_monedas(frame, fondo, args.invertir, args.area_min)]
        validas = [d for d in dets if d["ok"]]

        if validas:
            lote = torch.stack([a_tensor(recortar(frame, d, args.ventana, TAM_CAPTURA), tf)
                                for d in validas]).to(dispositivo)
            with torch.no_grad():
                probs = torch.softmax(modelo(lote), 1).cpu().numpy()
        else:
            probs = []

        for p in pistas:
            p["perdidas"] += 1
        for d, pr in zip(validas, probs):
            mejor, dmin = None, 1e9
            for p in pistas:
                dist = np.hypot(p["cx"] - d["cx"], p["cy"] - d["cy"])
                if dist < dmin and dist < 0.8 * d["diam_px"]:
                    mejor, dmin = p, dist
            if mejor is None:
                mejor = {"hist": deque(maxlen=args.frames), "perdidas": 0}
                pistas.append(mejor)
            mejor.update(cx=d["cx"], cy=d["cy"], diam_px=d["diam_px"], perdidas=0)
            mejor["hist"].append(pr)
        pistas = [p for p in pistas if p["perdidas"] <= 10]

        vista = frame.copy()
        confirmadas = []
        for d in dets:
            if not d["ok"]:
                cv2.circle(vista, (int(d["cx"]), int(d["cy"])), int(d["diam_px"] / 2), (0, 0, 255), 2)
                cv2.putText(vista, d["motivo"], (int(d["cx"]) - 40, int(d["cy"])),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
        for p in pistas:
            if p["perdidas"] > 0:
                continue
            media = np.mean(p["hist"], axis=0)
            i = int(media.argmax())
            conf = float(media[i])
            etiqueta, color = "?", (0, 165, 255)
            if len(p["hist"]) >= args.min_frames and conf >= args.umbral:
                etiqueta, color = clases[i], (0, 200, 0)
                if clases[i] == "otra":
                    color = (160, 160, 160)  # no es la moneda buscada: no se cuenta
                elif (args.mm_por_px and clases[i] in DIAMETRO_MM and
                      abs(p["diam_px"] * args.mm_por_px - DIAMETRO_MM[clases[i]]) > args.tol_mm):
                    etiqueta, color = f"{clases[i]}?diam", (0, 0, 255)
                else:
                    confirmadas.append({"clase": clases[i], "conf": round(conf, 3),
                                        "x": int(p["cx"]), "y": int(p["cy"])})
            cv2.circle(vista, (int(p["cx"]), int(p["cy"])), int(p["diam_px"] / 2), color, 2)
            cv2.putText(vista, f"{etiqueta} {conf * 100:.0f}%", (int(p["cx"]) - 45, int(p["cy"]) - int(p["diam_px"] / 2) - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
        cv2.putText(vista, f"confirmadas: {len(confirmadas)}", (10, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 0), 2)
        cv2.imshow("Reconocimiento (q = salir)", vista)
        k = cv2.waitKey(1) & 0xFF
        if k == ord("q"):
            break
        if k == ord("r"):
            print(json.dumps(confirmadas, ensure_ascii=False, indent=2))
    cam.cerrar()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
