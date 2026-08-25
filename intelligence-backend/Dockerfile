FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Chromium + sus dependencias de sistema, en la misma imagen (build == runtime,
# así no hay que sincronizar paquetes apt entre etapas de build y deploy).
RUN playwright install --with-deps chromium

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
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
