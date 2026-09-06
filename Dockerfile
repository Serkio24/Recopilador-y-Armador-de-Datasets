# Recopilador y analizador de YouTube Shorts - imagen para el modo CLI.
#
# La interfaz Tkinter NO va aqui: se sigue abriendo nativa en Windows con
# recopilador.bat. Lo que el contenedor aporta es el entorno, que es la parte
# fragil del proyecto: Python 3.11, ffmpeg, un motor de JavaScript y las libs de
# CUDA colocadas donde CTranslate2 sabe buscarlas.
#
#   docker compose build
#   docker compose run --rm app --cli --tema "pesca artesanal" --n 50
#
# Con GPU la imagen ocupa 1,7 GB. Para una solo-CPU, sin cuBLAS ni cuDNN:
#   docker compose build --build-arg CON_GPU=0

# 3.11 es lo mismo que hay en el .venv del equipo. El minimo real es 3.10: en 3.9
# el yt-dlp mas nuevo instalable es de 2025 y YouTube ya lo rechaza.
FROM python:3.11-slim-bookworm

# No hace falta la imagen nvidia/cuda: las wheels de requirements-gpu.txt traen
# cuBLAS y cuDNN, y el NVIDIA Container Toolkit inyecta el driver del host.

# - ffmpeg es obligatorio: YouTube entrega los Shorts con video y audio en pistas
#   separadas y hay que unirlas. recopilador/config.py lo localiza por PATH.
# - nodejs resuelve el reto en JavaScript con el que YouTube protege las URLs de
#   sus formatos. Sin motor, yt-dlp cae a un solo cliente de reproduccion y falla
#   muy a menudo con "The page needs to be reloaded" o HTTP 403.
#   localizar_js_runtime() lo busca como `node`, asi que se asegura el enlace.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && if [ ! -x /usr/bin/node ]; then ln -s /usr/bin/nodejs /usr/bin/node; fi \
    && node --version && ffmpeg -version | head -1

WORKDIR /app

# Las dependencias antes que el codigo: editar un .py no debe invalidar la capa
# cara (la de cuDNN sola pasa de 700 MB).
ARG CON_GPU=1
COPY requirements.txt requirements-gpu.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$CON_GPU" = "1" ]; then \
         pip install --no-cache-dir -r requirements-gpu.txt; \
       fi

# El equivalente en Linux de analisis/config.py:registrar_dll_cuda(), que solo
# actua en Windows (os.name != "nt" devuelve []). pip deja los .so de cuBLAS y
# cuDNN dentro de site-packages/nvidia/*/lib, que no esta en la ruta de busqueda
# del enlazador: sin esto CTranslate2 no los encuentra, el respaldo a CPU salta y
# el lote entero se transcribe unas diez veces mas lento.
#
# Se recorre el glob en vez de fijar las dos rutas a mano, igual que hace
# registrar_dll_cuda(): los dos paquetes de requirements-gpu.txt arrastran un
# tercero (cuda_nvrtc), y esa lista cambia entre versiones.
RUN SP="$(python -c 'import site; print(site.getsitepackages()[0])')" \
    && find "$SP/nvidia" -maxdepth 2 -type d -name lib 2>/dev/null \
       > /etc/ld.so.conf.d/nvidia-pip.conf \
    && ldconfig \
    && cat /etc/ld.so.conf.d/nvidia-pip.conf

COPY . .

# El CLI informa video a video con print; sin esto la salida sale a bloques y en
# un lote de 200 no se ve el progreso.
ENV PYTHONUNBUFFERED=1

# Sin CMD: los argumentos de `docker compose run app ...` son los de main.py.
# _relanzar_en_venv() no estorba, al no existir /app/.venv se sigue de largo.
ENTRYPOINT ["python", "main.py"]
