# Despliegue con Alembic

Desde este commit el esquema de la base lo versiona **Alembic**, no
`Base.metadata.create_all()`. El lifespan de `app/main.py` ya no crea tablas;
`alembic upgrade head` corre en el arranque del servicio, antes de uvicorn
(ver `Procfile` y `Dockerfile`).

Todos los comandos se ejecutan **desde `intelligence-backend/`**, que es donde
vive `alembic.ini`. La URL de la base sale de `DATABASE_URL` a través de
`app/core/config.py`; no hay que pasarla por línea de comandos.

Revisiones:

| Revisión | Qué contiene |
|---|---|
| `0001` | Esquema base: `organizations`, `users`, `clients`, `ad_accounts`, `facebook_connections`, `meta_central_tokens` |
| `0002` | Módulo de leads: `client_pages`, `leads`, `lead_audits`, `orphan_leads` |

---

## ⚠️ Lo único que no se puede equivocar

La base de **producción ya tiene** las tablas de `0001`, con datos de clientes
que pagan. Si se despliega este código sin marcarla antes, el arranque
ejecutará `0001`, intentará crear tablas que ya existen y **el despliegue
fallará en bucle**.

El `alembic stamp 0001` de producción va **ANTES** del primer despliegue con
este código. No es un paso opcional ni se puede hacer después.

---

## Caso 1 — Producción / cualquier base que ya tenga datos

La base tiene las seis tablas del esquema base y ninguna de las de leads.

```bash
# 1) Respaldo. Primero. Siempre.
pg_dump "$DATABASE_URL" > respaldo-pre-alembic-$(date +%F).sql

# 2) Confirmar el punto de partida: deben aparecer las 6 tablas base,
#    NINGUNA tabla de leads, y NINGUNA tabla alembic_version.
psql "$DATABASE_URL" -c "\dt"

# 3) Marcar la base como si 0001 ya se hubiera aplicado.
#    Esto NO toca ninguna tabla: sólo escribe la fila '0001' en
#    alembic_version, que Alembic crea en este momento.
alembic stamp 0001

# 4) Comprobar que quedó marcada.
alembic current          # -> 0001 (head aún no)

# 5) Recién ahora, desplegar el código. El arranque del servicio corre
#    `alembic upgrade head`, que aplica sólo 0002 y crea las tablas de leads.
```

Si se prefiere aplicar `0002` a mano antes de desplegar (para separar el
cambio de esquema del cambio de código), entre el paso 4 y el 5:

```bash
alembic upgrade head
alembic current          # -> 0002 (head)
psql "$DATABASE_URL" -c "\dt"   # ya aparecen leads, lead_audits, client_pages, orphan_leads
```

Las seis tablas del esquema base no se tocan en ningún momento: `0001` no se
ejecuta (está stampeada) y `0002` sólo crea tablas nuevas.

## Caso 2 — Base nueva y vacía (CI, un desarrollador que empieza de cero)

Sin `stamp`. Se aplica todo desde cero:

```bash
alembic upgrade head
alembic current          # -> 0002 (head)
```

## Caso 3 — Máquina de desarrollo con tablas creadas por `create_all`

La base tiene el esquema base y, además, algunas o todas las tablas de leads,
creadas por el `create_all` que había en el lifespan — posiblemente con
`lead_audits.user_id` NOT NULL, que es el estado viejo del modelo.

```bash
# 1) Marcar el esquema base como ya aplicado (igual que en producción).
alembic stamp 0001

# 2) Subir a head. La revisión 0002 comprueba tabla por tabla: crea las que
#    falten y, si `lead_audits` ya estaba, pone `user_id` en NULL-able.
alembic upgrade head
alembic current          # -> 0002 (head)

# 3) Verificar que no queda ninguna diferencia contra los modelos.
alembic check            # -> "No new upgrade operations detected."
```

Si la base de desarrollo no importa, la alternativa siempre válida es
borrarla y hacer el Caso 2.

---

## Comandos del día a día

```bash
alembic current                              # en qué revisión está la base
alembic history                              # las revisiones y su orden
alembic check                                # ¿los modelos y la base coinciden?
alembic revision --autogenerate -m "mensaje" # nueva revisión desde los modelos
alembic upgrade head                         # aplicar lo pendiente
alembic downgrade -1                         # deshacer la última
```

Una revisión autogenerada **siempre** se lee antes de commitearla: Alembic
detecta bien las tablas y columnas nuevas, y mal los renombres (los ve como
un DROP más un ADD, o sea, pérdida de datos).

## Si alguien quiere revisar el SQL antes de aplicarlo

```bash
# Lo que se ejecutaria en produccion (que esta stampeada en 0001):
alembic upgrade 0001:head --sql
```

En modo `--sql` Alembic no abre conexión, así que `0002` no puede
inspeccionar la base: emite el `CREATE TABLE` de las cuatro tablas sin
comprobar nada. Es lo correcto para el escenario en que se usa el modo
offline —el despliegue a producción, donde ninguna existe—, pero significa
que el `.sql` generado **no sirve** para una base de desarrollo a medio
camino. Ésas se migran conectándose (Caso 3).

## Nota sobre el arranque del servicio

`Procfile` y `Dockerfile` traen los dos el mismo comando encadenado:

```
alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Están los dos porque el repo tiene `Procfile` y `Dockerfile` y cuál de ellos
lee Railway depende de qué builder tenga configurado el servicio (con
Dockerfile presente suele usar Docker e ignorar el `Procfile`). No hay ni
`railway.json` ni `nixpacks.toml` en el repo que lo resuelva, así que se
cubren ambos caminos. **Si el servicio tiene un Start Command puesto a mano en
el panel de Railway, ése gana sobre los dos** y hay que agregarle allí el
`alembic upgrade head &&`.

El `&&` es intencional: si la migración falla, uvicorn no arranca, el
contenedor muere y Railway no promueve el despliegue. Es preferible a servir
la API contra un esquema que no es el que el código espera.
