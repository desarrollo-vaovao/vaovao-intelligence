FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Chromium + sus dependencias de sistema, en la misma imagen (build == runtime,
# así no hay que sincronizar paquetes apt entre etapas de build y deploy).
#
# "chromium-headless-shell" además de "chromium": desde que Playwright
# separó los dos binarios, chromium.launch() sin channel= explícito resuelve
# por defecto al headless-shell (más liviano) en vez del chromium completo,
# aunque el código nunca lo pida por nombre. requirements.txt fija
# `playwright>=1.40` sin techo, así que un build en fecha distinta puede
# traer una versión que ya hizo ese cambio - instalar ambos binarios cubre
# cualquiera de los dos sin tener que fijar la versión exacta de playwright
# ni tocar el .launch() de app/services/browser_pool.py.
RUN playwright install --with-deps chromium chromium-headless-shell

COPY . .

# Las migraciones corren ANTES de servir, en el mismo comando: si `alembic
# upgrade head` falla, el contenedor muere y Railway no promueve el despliegue
# — mejor eso que servir una API contra un esquema que no es el que el código
# espera. `app/main.py` ya no crea tablas; ésta es la única vía.
#
# OJO en el PRIMER despliegue con Alembic: la base de producción ya tiene las
# tablas del esquema base y hay que marcarla con `alembic stamp 0001` ANTES de
# desplegar, o esta línea intentará crearlas de nuevo y fallará. Ver
# docs/DEPLOY_ALEMBIC.md.
#
# NO COPIAR ESTA LÍNEA AL CAMPO "Start Command" DE RAILWAY
# --------------------------------------------------------
# El `sh -c` de aquí es lo que hace que `&&` encadene los dos comandos y que
# `${PORT:-8000}` se expanda. Railway NO mete el Start Command en un shell:
# lo trata como ejecutable + argumentos. Pegado ahí, este comando arranca
# `alembic` pasándole "&&", "uvicorn", "--port", "${PORT:-8000}"… como
# argumentos sueltos, uvicorn nunca corre y el contenedor se queda vivo pero
# sin escuchar. Da 502 con el healthcheck fallando y sin un solo error en los
# logs — costó una mañana entera de depuración en staging, donde alguien lo
# había pegado en ese campo.
#
# Si un entorno necesita un arranque distinto, se deja el Start Command VACÍO
# (para que mande este CMD) o se invoca el shell explícitamente:
#   sh -c "alembic upgrade head && uvicorn ..."
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
