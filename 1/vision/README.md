# Reconocimiento de monedas colombianas (9 clases) - etapa de identificacion

Instalacion (Python 3.10+):  pip install -r requirements.txt

Orden de uso
1. python 01_probar_camara.py --fuente <0 | URL del celular>
2. (bandeja VACIA) tecla f para guardar datos/fondo.png
3. python 02_capturar_dataset.py --fuente <...> --fondo datos/fondo.png --ventana <sugerida>
4. python 03_entrenar.py --datos datos --salida modelo
5. Sesion de prueba independiente: 02_capturar_dataset.py --salida datos_prueba ...
   luego: python 05_evaluar.py --datos datos_prueba --modelo modelo
6. python 04_reconocer_en_vivo.py --fuente <...> --fondo datos/fondo.png --ventana <la misma>

Fuentes de camara
- Webcam USB/integrada: --fuente 0 (o 1, 2...)
- Android, app IP Webcam: --fuente http://IP:8080/video
- App DroidCam:           --fuente http://IP:4747/video
Celular y PC en la MISMA red Wi-Fi, celular desbloqueado y app abierta.

Estado de prueba: comun.py (deteccion/recorte) probado con imagenes sinteticas.
Los scripts 01-05 con camara real, entrenamiento y reconocimiento en vivo NO se han
ejecutado aun con tus monedas: validalos con el primer lote de fotos.
