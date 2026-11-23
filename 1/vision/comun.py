"""
comun.py - Utilidades compartidas: camara (PC/celular), deteccion y recorte de monedas.

Idea clave del diseno (dos pasos):
  1) DETECTAR: se localizan las monedas con OpenCV (umbral + contornos + circularidad).
  2) CLASIFICAR: cada moneda se recorta en una ventana de tamano FIJO (en pixeles) y se
     clasifica con una red neuronal pequena. El tamano fijo conserva la informacion de
     diametro real (la camara debe estar fija, a distancia constante).
"""
import threading
import time

import cv2
import numpy as np

CLASES = [
    "50_vieja", "50_nueva",
    "100_vieja", "100_nueva",
    "200_vieja", "200_nueva",
    "500_vieja", "500_nueva",
    "1000",
]

# Diametros segun catalogos (mm). REEMPLAZAR por TUS mediciones con calibrador.
DIAMETRO_MM = {
    "50_vieja": 21.8, "50_nueva": 17.0,
    "100_vieja": 23.0, "100_nueva": 20.3,
    "200_vieja": 24.4, "200_nueva": 22.4,
    "500_vieja": 23.5, "500_nueva": 23.7,
    "1000": 26.7,
}

AJUSTE_MIN = 0.88  # minimo de area/area(circulo minimo envolvente) para aceptar una moneda
TAM_CAPTURA = 224  # lado (px) con que se GUARDAN los recortes (alta resolucion)
TAM_ENTRADA = 128  # lado (px) por defecto de la entrada de la red (se cambia con --tam al entrenar)


def parsear_fuente(fuente):
    """'0' -> 0 (webcam USB); 'http://...' -> URL (celular / camara IP)."""
    texto = str(fuente).strip()
    return int(texto) if texto.isdigit() else texto


class Camara:
    """Lee la fuente en un hilo y conserva solo el ULTIMO fotograma.

    Evita el retraso acumulado tipico de los streams IP del celular.
    """

    def __init__(self, fuente=0, ancho=None, alto=None, espera_s=8.0):
        self.fuente = parsear_fuente(fuente)
        self.cap = cv2.VideoCapture(self.fuente)
        if not self.cap.isOpened():
            raise RuntimeError(f"No se pudo abrir la fuente de video: {self.fuente!r}")
        if ancho:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(ancho))
        if alto:
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(alto))
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._frame = None
        self._lock = threading.Lock()
        self._parar = False
        self._hilo = threading.Thread(target=self._bucle, daemon=True)
        self._hilo.start()
        t0 = time.time()
        while self._frame is None and time.time() - t0 < espera_s:
            time.sleep(0.05)
        if self._frame is None:
            self.cerrar()
            raise RuntimeError("La fuente se abrio pero no entrega imagenes "
                               "(celular bloqueado, otra red o URL incorrecta).")

    def _bucle(self):
        while not self._parar:
            ok, f = self.cap.read()
            if not ok:
                time.sleep(0.02)
                continue
            with self._lock:
                self._frame = f

    def leer(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def cerrar(self):
        self._parar = True
        time.sleep(0.05)
        self.cap.release()


def _analizar(frame, fondo=None, invertir=False, area_min=300, circ_min=0.82,
              margen_borde=2, ancho_proc=640, umbral_dif=None):
    """Nucleo de la deteccion. Devuelve (detecciones, mascara_a_escala_de_proceso).

    Mejoras de estabilidad frente a la version simple:
      - Se procesa una copia REDUCIDA (ancho_proc px): promedia ruido y es mas rapido.
      - Con fondo, el umbral de la diferencia nunca baja de un piso (evita ruido como objeto).
      - La circularidad y el diametro se calculan sobre el CASCO CONVEXO del contorno: un
        reflejo o una sombra que muerde el borde ya no hace rechazar una moneda real.
    """
    h, w = frame.shape[:2]
    esc = min(1.0, float(ancho_proc) / w) if ancho_proc else 1.0
    if esc < 1.0:
        pequeno = cv2.resize(frame, (int(round(w * esc)), int(round(h * esc))), interpolation=cv2.INTER_AREA)
    else:
        pequeno = frame
    hp, wp = pequeno.shape[:2]
    gris = cv2.GaussianBlur(cv2.cvtColor(pequeno, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    if fondo is not None:
        f0 = cv2.resize(fondo, (wp, hp), interpolation=cv2.INTER_AREA) if fondo.shape[:2] != (hp, wp) else fondo
        g0 = cv2.GaussianBlur(cv2.cvtColor(f0, cv2.COLOR_BGR2GRAY), (5, 5), 0)
        base = cv2.absdiff(gris, g0)
        if umbral_dif is not None:
            _, mascara = cv2.threshold(base, float(umbral_dif), 255, cv2.THRESH_BINARY)
        else:
            t_otsu, mascara = cv2.threshold(base, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            if t_otsu < 15:  # escena casi vacia: Otsu partiria el ruido; usar un piso
                _, mascara = cv2.threshold(base, 15, 255, cv2.THRESH_BINARY)
    else:
        tipo = cv2.THRESH_BINARY_INV if invertir else cv2.THRESH_BINARY
        _, mascara = cv2.threshold(gris, 0, 255, tipo + cv2.THRESH_OTSU)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mascara = cv2.morphologyEx(mascara, cv2.MORPH_OPEN, kernel)
    mascara = cv2.morphologyEx(mascara, cv2.MORPH_CLOSE, kernel, iterations=2)

    contornos, _ = cv2.findContours(mascara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    area_min_p = area_min * esc * esc
    mb = max(1, int(round(margen_borde * esc)))
    dets = []
    for c in contornos:
        if cv2.contourArea(c) < area_min_p:
            continue
        casco = cv2.convexHull(c)
        area = cv2.contourArea(casco)
        per = cv2.arcLength(casco, True)
        if area <= 0 or per == 0:
            continue
        circ = 4.0 * np.pi * area / (per * per)
        (cx, cy), r_min = cv2.minEnclosingCircle(casco)
        # Que tanto del circulo minimo que la envuelve ocupa la forma: ~1.0 en una moneda,
        # claramente menor si son dos monedas pegadas (el casco convexo solo no lo detecta).
        ajuste = area / (np.pi * r_min * r_min) if r_min > 0 else 0.0
        x, y, bw, bh = cv2.boundingRect(c)
        borde = x <= mb or y <= mb or x + bw >= wp - mb or y + bh >= hp - mb
        motivo = ""
        if borde:
            motivo = "borde"
        elif circ < circ_min or ajuste < AJUSTE_MIN:
            motivo = "forma (solapadas?)"
        dets.append({
            "cx": float(cx / esc), "cy": float(cy / esc),
            "diam_px": float(2.0 * np.sqrt(area / np.pi) / esc),
            "circ": float(circ), "ajuste": float(ajuste),
            "ok": motivo == "",
            "motivo": motivo,
        })
    return dets, mascara


def detectar_monedas(frame, fondo=None, invertir=False, area_min=300, circ_min=0.82,
                     margen_borde=2, ancho_proc=640, umbral_dif=None):
    """Devuelve una lista de detecciones (dict) para cada objeto candidato.

    - fondo: imagen de la bandeja VACIA (recomendado: es el metodo mas robusto).
      Sin fondo se usa umbral de Otsu (moneda clara sobre fondo oscuro; usar
      invertir=True si es al reves).
    - Cada deteccion trae ok=True solo si es circular y no toca el borde.
      Si ok=False (monedas pegadas/solapadas, moneda cortada) NO se clasifica:
      es mejor rechazar que equivocarse.
    """
    return _analizar(frame, fondo, invertir, area_min, circ_min, margen_borde, ancho_proc, umbral_dif)[0]


def detectar_con_mascara(frame, fondo=None, invertir=False, area_min=300, circ_min=0.82,
                         margen_borde=2, ancho_proc=640, umbral_dif=None):
    """Igual que detectar_monedas pero devuelve tambien la mascara (para diagnostico)."""
    return _analizar(frame, fondo, invertir, area_min, circ_min, margen_borde, ancho_proc, umbral_dif)


class Estabilizador:
    """Suaviza la deteccion en el tiempo SOLO PARA MOSTRAR (no para guardar/clasificar).

    - Una moneda se muestra tras `confirmar` cuadros seguidos (ignora destellos de 1 cuadro).
    - Si desaparece, se mantiene `retener` cuadros (tapa cortes breves de la deteccion).
    - Posicion y diametro se suavizan (promedio exponencial) para que el circulo no tiemble.
    """

    def __init__(self, confirmar=2, retener=6, alfa=0.5):
        self.confirmar, self.retener, self.alfa = confirmar, retener, alfa
        self.pistas = []

    def actualizar(self, dets):
        for p in self.pistas:
            p["perdidas"] += 1
        for d in (x for x in dets if x["ok"]):
            mejor, dmin = None, 1e9
            for p in self.pistas:
                dist = float(np.hypot(p["cx"] - d["cx"], p["cy"] - d["cy"]))
                if dist < dmin and dist < 0.6 * max(d["diam_px"], 1.0) and p["perdidas"] > 0:
                    mejor, dmin = p, dist
            if mejor is None:
                self.pistas.append({"cx": d["cx"], "cy": d["cy"], "diam_px": d["diam_px"],
                                    "hits": 1, "perdidas": 0})
            else:
                a = self.alfa
                mejor["cx"] = a * d["cx"] + (1 - a) * mejor["cx"]
                mejor["cy"] = a * d["cy"] + (1 - a) * mejor["cy"]
                mejor["diam_px"] = a * d["diam_px"] + (1 - a) * mejor["diam_px"]
                mejor["hits"] += 1
                mejor["perdidas"] = 0
        self.pistas = [p for p in self.pistas if p["perdidas"] <= self.retener]
        return [dict(p, retenida=p["perdidas"] > 0) for p in self.pistas if p["hits"] >= self.confirmar]


def recortar(frame, det, ventana=160, tam=TAM_CAPTURA):
    """Recorta una ventana CUADRADA de tamano fijo centrada en la moneda.

    El fondo fuera de la moneda se pone en negro (la red no aprende la bandeja)
    pero el tamano relativo de la moneda dentro de la ventana se conserva.
    """
    mitad = int(ventana) // 2
    cx, cy = int(round(det["cx"])), int(round(det["cy"]))
    marco = cv2.copyMakeBorder(frame, mitad, mitad, mitad, mitad,
                               cv2.BORDER_CONSTANT, value=(0, 0, 0))
    roi = marco[cy:cy + 2 * mitad, cx:cx + 2 * mitad]
    mascara = np.zeros(roi.shape[:2], np.uint8)
    radio = int(round(det["diam_px"] / 2.0 * 1.04))
    cv2.circle(mascara, (mitad, mitad), radio, 255, -1)
    roi = cv2.bitwise_and(roi, roi, mask=mascara)
    return cv2.resize(roi, (tam, tam), interpolation=cv2.INTER_AREA)


def ventana_sugerida(diam_px_max):
    """Ventana (px, par) para que la moneda mas grande quepa con ~20 % de margen."""
    return int(round(diam_px_max * 1.2 / 2.0)) * 2
