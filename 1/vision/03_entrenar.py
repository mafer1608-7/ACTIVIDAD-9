"""
03_entrenar.py - Entrena un clasificador MobileNetV2 (transfer learning) con los recortes.

Por que MobileNetV2: es una arquitectura pequena con ruta documentada para cuantizarla y
desplegarla en ESP32-S3 (ESP-PPQ + ESP-DL), asi el modelo entrenado en PC no es un callejon
sin salida.

Uso:
  python 03_entrenar.py --datos datos --salida modelo --epocas 20
  python 03_entrenar.py --datos datos --clases 50_vieja,50_nueva,100_vieja,1000   # clases explicitas
  python 03_entrenar.py --datos datos --positiva 100_vieja --salida modelo_100v    # UNA moneda vs "otra"

Modo --positiva: modelo binario ("100_vieja" contra "otra"). Las "otras" son TODAS las demas
clases que tengan recortes: el modelo solo sabra rechazar las monedas que haya visto como negativas.

Por defecto (--clases auto) entrena SOLO con las clases que tengan al menos --min_imagenes
recortes. El modelo resultante unicamente conoce esas clases: cualquier otra moneda sera
asignada (mal) a una de ellas salvo que la confianza quede por debajo del umbral.

Separacion train/val POR SESION de captura (no por imagen): evita que fotogramas casi
identicos de la misma sesion aparezcan en entrenamiento y validacion (eso infla la
precision de forma enganosa). Para una medida honesta, captura una sesion de PRUEBA en otro
momento/luz y evaluala con 05_evaluar (ver README).
"""
import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torchvision
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms as T

from comun import CLASES, TAM_ENTRADA

TODAS = CLASES + ["otra"]  # "otra" = monedas que no son la buscada (clase de rechazo)

MEDIA, STD = [0.485, 0.456, 0.406], [0.229, 0.224, 0.225]


class DatasetMonedas(Dataset):
    def __init__(self, items, transform):
        self.items, self.transform = items, transform

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        ruta, y = self.items[i]
        img = Image.open(ruta).convert("RGB")
        return self.transform(img), y


def dividir_por_sesion(raiz, clases, frac_val=0.2, semilla=42):
    rng = random.Random(semilla)
    train, val = [], []
    for ci, clase in enumerate(clases):
        archivos = sorted((raiz / "crops" / clase).glob("*.png"))
        por_sesion = defaultdict(list)
        for a in archivos:
            por_sesion[a.stem.split("_")[0]].append(a)
        sesiones = sorted(por_sesion)
        rng.shuffle(sesiones)
        if len(sesiones) >= 2:
            n_val = max(1, round(frac_val * len(sesiones)))
            s_val = set(sesiones[:n_val])
            for s in sesiones:
                destino = val if s in s_val else train
                destino += [(str(a), ci) for a in por_sesion[s]]
        else:
            print(f"AVISO: '{clase}' tiene 1 sola sesion; se separa el ultimo {int(frac_val*100)} % "
                  f"(la validacion sera optimista). Captura mas sesiones.")
            cut = int(len(archivos) * (1 - frac_val))
            train += [(str(a), ci) for a in archivos[:cut]]
            val += [(str(a), ci) for a in archivos[cut:]]
    return train, val


def elegir_clases(raiz, texto, min_imagenes):
    cuentas = {c: len(list((raiz / "crops" / c).glob("*.png"))) for c in TODAS}
    if texto.strip().lower() == "auto":
        elegidas = [c for c in TODAS if cuentas[c] >= min_imagenes]
    else:
        elegidas = [c.strip() for c in texto.split(",") if c.strip()]
        malas = [c for c in elegidas if c not in TODAS]
        if malas:
            raise SystemExit(f"Clases desconocidas: {malas}. Validas: {TODAS}")
        pocas = [c for c in elegidas if cuentas[c] < min_imagenes]
        if pocas:
            raise SystemExit(f"Clases con menos de {min_imagenes} recortes: {pocas}")
    print("Clases del modelo:")
    for c in TODAS:
        if cuentas[c] == 0 and c == "otra":
            continue
        estado = "INCLUIDA" if c in elegidas else "fuera del modelo"
        print(f"  {c:10s} {cuentas[c]:5d} recortes  {estado}")
    if len(elegidas) < 2:
        raise SystemExit("Se necesitan al menos 2 clases con datos.")
    return elegidas


def a_binario(items, fuentes, positiva):
    """Convierte etiquetas multiclase a binarias: 0 = positiva, 1 = 'otra'."""
    return [(ruta, 0 if fuentes[y] == positiva else 1) for ruta, y in items]


def crear_modelo(n_clases, preentrenado=True):
    pesos = torchvision.models.MobileNet_V2_Weights.IMAGENET1K_V1 if preentrenado else None
    m = torchvision.models.mobilenet_v2(weights=pesos)
    m.classifier[1] = nn.Linear(m.last_channel, n_clases)
    return m


@torch.no_grad()
def evaluar(modelo, cargador, dispositivo):
    modelo.eval()
    todos_y, todos_p, todos_c = [], [], []
    for x, y in cargador:
        pr = torch.softmax(modelo(x.to(dispositivo)), 1).cpu()
        conf, pred = pr.max(1)
        todos_y += y.tolist()
        todos_p += pred.tolist()
        todos_c += conf.tolist()
    return np.array(todos_y), np.array(todos_p), np.array(todos_c)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--datos", default="datos")
    ap.add_argument("--salida", default="modelo")
    ap.add_argument("--epocas", type=int, default=30)
    ap.add_argument("--epocas_cabeza", type=int, default=3, help="epocas con el backbone congelado")
    ap.add_argument("--lote", type=int, default=32)
    ap.add_argument("--clases", default="auto", help="auto = las que tengan datos, o lista separada por comas")
    ap.add_argument("--min_imagenes", type=int, default=30)
    ap.add_argument("--positiva", default=None, help="modelo binario: esta clase contra 'otra'")
    ap.add_argument("--tam", type=int, default=TAM_ENTRADA,
                    help="lado de entrada de la red: 128 (rapido) o 192 (mas detalle)")
    ap.add_argument("--workers", type=int, default=0, help="0 = seguro en Windows")
    ap.add_argument("--sin_preentrenado", action="store_true", help="solo para pruebas sin internet")
    args = ap.parse_args()

    torch.manual_seed(42)
    raiz, salida = Path(args.datos), Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)
    dispositivo = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print("Dispositivo:", dispositivo)

    fuentes = elegir_clases(raiz, "auto" if args.positiva else args.clases, args.min_imagenes)
    train, val = dividir_por_sesion(raiz, fuentes)
    if args.positiva:
        if args.positiva not in fuentes:
            raise SystemExit(f"La clase '{args.positiva}' no tiene recortes suficientes.")
        clases = [args.positiva, "otra"]
        train, val = a_binario(train, fuentes, args.positiva), a_binario(val, fuentes, args.positiva)
        print(f"Modo binario: '{args.positiva}' ({sum(1 for _, y in train if y == 0)} train) contra "
              f"'otra' ({sum(1 for _, y in train if y == 1)} train, de: "
              f"{', '.join(c for c in fuentes if c != args.positiva)})")
    else:
        clases = fuentes
    print(f"Train: {len(train)}  Val: {len(val)}")
    if not val:
        raise SystemExit("Validacion vacia: captura mas sesiones.")

    # Sin flips (una moneda espejada no existe). Rotacion completa: la moneda es circular
    # y cae con cualquier orientacion. Escala casi fija para conservar la pista de tamano.
    t_train = T.Compose([
        T.Resize((args.tam, args.tam)),
        T.RandomRotation(180, interpolation=T.InterpolationMode.BILINEAR, fill=0),
        T.RandomAffine(degrees=0, translate=(0.04, 0.04), scale=(0.97, 1.03)),
        T.ColorJitter(brightness=0.3, contrast=0.3, saturation=0.2, hue=0.02),
        T.RandomApply([T.GaussianBlur(3, (0.1, 1.5))], p=0.3),
        T.ToTensor(), T.Normalize(MEDIA, STD),
    ])
    t_val = T.Compose([T.Resize((args.tam, args.tam)), T.ToTensor(), T.Normalize(MEDIA, STD)])

    c_train = DataLoader(DatasetMonedas(train, t_train), batch_size=args.lote, shuffle=True,
                         num_workers=args.workers)
    c_val = DataLoader(DatasetMonedas(val, t_val), batch_size=args.lote, num_workers=args.workers)

    cuentas = np.bincount([y for _, y in train], minlength=len(clases)).astype(float)
    pesos_clase = torch.tensor(cuentas.sum() / (len(clases) * np.maximum(cuentas, 1)),
                               dtype=torch.float32, device=dispositivo)
    criterio = nn.CrossEntropyLoss(weight=pesos_clase, label_smoothing=0.1)

    modelo = crear_modelo(len(clases), not args.sin_preentrenado).to(dispositivo)
    mejor, ruta_mejor = 0.0, salida / "modelo.pt"

    for epoca in range(args.epocas):
        congelar = epoca < args.epocas_cabeza
        for p in modelo.features.parameters():
            p.requires_grad = not congelar
        if epoca in (0, args.epocas_cabeza):
            params = [p for p in modelo.parameters() if p.requires_grad]
            opt = torch.optim.AdamW(params, lr=1e-3 if congelar else 3e-4, weight_decay=1e-4)
            restantes = max(1, args.epocas - epoca)
            sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=restantes)
        modelo.train()
        perdida_total = 0.0
        for x, y in c_train:
            x, y = x.to(dispositivo), y.to(dispositivo)
            opt.zero_grad()
            perdida = criterio(modelo(x), y)
            perdida.backward()
            opt.step()
            perdida_total += perdida.item() * len(y)
        sched.step()
        yv, pv, _ = evaluar(modelo, c_val, dispositivo)
        acc = float((yv == pv).mean())
        print(f"Epoca {epoca + 1:02d}/{args.epocas}  perdida {perdida_total / len(train):.4f}  "
              f"val_acc {acc * 100:.2f} %" + ("  [congelado]" if congelar else ""))
        if acc >= mejor:
            mejor = acc
            torch.save(modelo.state_dict(), ruta_mejor)

    modelo.load_state_dict(torch.load(ruta_mejor, map_location=dispositivo))
    yv, pv, cv_ = evaluar(modelo, c_val, dispositivo)
    print(f"\nMejor val_acc: {mejor * 100:.2f} %")

    n = len(clases)
    conf_mat = np.zeros((n, n), int)
    for a, b in zip(yv, pv):
        conf_mat[a, b] += 1
    print("\nExactitud por clase y confusiones principales:")
    for i, c in enumerate(clases):
        tot = conf_mat[i].sum()
        fila = conf_mat[i].copy()
        fila[i] = 0
        peor = int(fila.argmax())
        extra = f"  (se confunde con {clases[peor]}: {fila[peor]})" if fila[peor] else ""
        print(f"  {c:10s} {100 * conf_mat[i, i] / max(tot, 1):6.2f} %  n={tot}{extra}")

    if args.positiva:
        tp, fn, fp, tn = conf_mat[0, 0], conf_mat[0, 1], conf_mat[1, 0], conf_mat[1, 1]
        print(f"\nBinario en validacion: {args.positiva} reconocida {tp}/{tp + fn}; "
              f"falsos positivos (otra moneda tomada por {args.positiva}): {fp}/{fp + tn}")

    print("\nUmbral de confianza -> cobertura / exactitud (lo que se acepta):")
    for u in (0.5, 0.7, 0.8, 0.9, 0.95, 0.99):
        m = cv_ >= u
        if m.sum():
            print(f"  >= {u:.2f}: acepta {100 * m.mean():5.1f} %  exactitud {100 * (yv[m] == pv[m]).mean():6.2f} %")

    with open(salida / "clases.json", "w", encoding="utf-8") as f:
        json.dump({"clases": clases, "tam": args.tam, "media": MEDIA, "std": STD}, f, indent=2)

    # Exportar ONNX (paso previo para cuantizar con ESP-PPQ hacia ESP32-S3).
    modelo.eval().cpu()
    ficticio = torch.zeros(1, 3, args.tam, args.tam)
    ruta_onnx = salida / "modelo.onnx"
    try:
        try:
            torch.onnx.export(modelo, ficticio, str(ruta_onnx), input_names=["input"],
                              output_names=["logits"], opset_version=13, dynamo=False)
        except TypeError:
            torch.onnx.export(modelo, ficticio, str(ruta_onnx), input_names=["input"],
                              output_names=["logits"], opset_version=13)
        print("ONNX guardado en", ruta_onnx)
    except Exception as e:  # no es critico para el uso en PC
        print("AVISO: no se pudo exportar ONNX:", e)


if __name__ == "__main__":
    main()
