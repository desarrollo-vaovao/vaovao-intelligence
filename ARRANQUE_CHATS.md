# Mensajes de arranque por chat

Copiar el bloque correspondiente al abrir cada chat nuevo.
Estado al 26 de agosto de 2026: el backend del módulo de leads está completo y
fusionado en `dev`, con 50 pruebas. `main` (producción) sigue en `dfff208`.

---

## Chat 1 — Panel de leads (frontend)

```
Trabajo en VaoVao Intelligence: C:\Users\vfgut_7pxhpv9\Documents\vaovao inteligence

Necesito construir el panel de leads del frontend. Hoy `intelligence-web/app/leads/page.jsx`
es un placeholder de 5 líneas con <ComingSoon />.

CONTEXTO
El backend del módulo ya está terminado, probado y fusionado en `dev`. La API está lista;
no hay que tocar backend salvo que falte algo, y si falta hay que decirlo antes de inventarlo.

Stack: Next.js 14.2.5 (app router) + React 18. El cliente HTTP es `intelligence-web/lib/api.js`
—seguir ese patrón, no crear otro—. El token vive en localStorage como `vv_token`.
Como referencia de estilo y estructura, ver `app/clientes/page.jsx` (446 líneas) y
`app/reportes/page.jsx`.

ENDPOINTS DISPONIBLES
  GET   /leads?page=&size=&client_id=&status=&search=   listado paginado (size máx 500)
  GET   /leads/{id}                                     detalle + bitácora
  PATCH /leads/{id}                                     etapa, responsable, notas
  GET   /leads/export/csv?client_id=                    descarga CSV
  GET   /leads/status                                   estado + huérfanos pendientes
  POST  /leads/orphans/{page_id}/reconcile              reconciliar (solo admin/owner)

DECISIONES YA TOMADAS — no reabrir
- Pipeline de 6 etapas: nuevo → contactado → calificado → propuesta → ganado,
  y `perdido`, terminal, alcanzable desde cualquier etapa.
- Roles: `member` ve solo los leads asignados a él y solo puede editar esos.
  `admin`/`owner` ven toda la organización y pueden asignar y reconciliar.
  El backend ya lo impone; el frontend debe reflejarlo, no reimplementarlo.
- El CSV es para entregar al cliente; el panel es interno de VaoVao.

DISEÑO
Hay un mockup aprobado: vista Kanban con las 5 columnas del pipeline, vista Lista con
buscador por nombre/teléfono/correo, tarjetas de métricas arriba (leads del período,
costo por lead, tasa de contacto, cierre), y gráficas de leads por día y origen.
Se lo puedo pasar como imagen.

PENDIENTE CONOCIDO QUE TE TOCA
`DELETE /clients/{id}` ahora responde 409 cuando el cliente tiene leads, con un mensaje
que dice cuántos se perderían. `app/clientes/page.jsx` no contempla ese código y muestra
un error genérico, perdiendo justo la explicación útil. Hay que manejarlo.

Empecemos por entender qué hay y proponerme un plan antes de escribir código.
```

---

## Chat 2 — Postgres en pruebas + integración continua

```
Trabajo en VaoVao Intelligence: C:\Users\vfgut_7pxhpv9\Documents\vaovao inteligence

Necesito montar Postgres en la suite de pruebas y dejarla corriendo en integración continua.

CONTEXTO
En `dev` hay 50 pruebas que pasan (`intelligence-backend/tests/`), todas sobre SQLite en
memoria. Corren solo en mi máquina: no hay CI, y el repo no tiene workflows de GitHub Actions.

Cuatro huecos NO se pueden cerrar honestamente en SQLite y por eso quedaron sin cubrir.
Están documentados y son el objetivo de este trabajo:

1. Deriva entre modelos y migraciones. El esquema de las pruebas sale de
   `Base.metadata.create_all()`, o sea de los modelos, NO de Alembic. Si un modelo y su
   migración se separan, ninguna prueba lo nota. Esto ya pasó una vez en el proyecto
   (`lead_audits.user_id` quedó NOT NULL en varias bases después de que el modelo lo
   hiciera nullable).
2. Carreras reales de entregas concurrentes en `ingest_lead`. Hay dos ramas de
   `IntegrityError` que solo se ejercitan con conexiones compitiendo de verdad; SQLite
   en memoria usa StaticPool, una sola conexión, así que dos transacciones simultáneas
   no existen.
3. Búsqueda con acentos. `_like_patterns` en `app/crud/leads.py` maneja las variantes
   NFC/NFD y el escape \uXXXX del JSON, pero el `lower()` de SQLite es solo ASCII.
4. `ON DELETE CASCADE` de `clients.id` a nivel de base: hoy el ORM borra los hijos en
   Python, así que la cascada real de la base no queda probada.

UNA TRAMPA QUE YA NOS MORDIÓ
SQLite ignora las llaves foráneas salvo que se active `PRAGMA foreign_keys=ON` en cada
conexión. Sin eso, 16 de las 50 pruebas siguen en verde aunque las cascadas no se estén
probando. Por eso existe `tests/test_fk_enforcement.py`: no prueba el módulo, protege a
las otras pruebas. Al migrar a Postgres, verificar que ese guardia siga teniendo sentido
o adaptarlo.

UN LÍMITE HONESTO YA DOCUMENTADO — no intentar "arreglarlo"
El tiempo constante de `hmac.compare_digest` en la autenticación del webhook NO es
cubrible por pruebas de comportamiento: sustituirlo por `==` pasa las 50. La diferencia
es un canal lateral de tiempo. Es una propiedad a cuidar en revisión de código.

Empecemos evaluando opciones (Docker, servicio de CI, testcontainers) antes de implementar.
```

---

## Chat 3 — Fase 2: despliegue y validación en paralelo

```
Trabajo en VaoVao Intelligence: C:\Users\vfgut_7pxhpv9\Documents\vaovao inteligence

Voy a desplegar el módulo de leads a producción y validarlo en paralelo con el servicio
que ya existe. Hay datos reales de clientes de por medio, así que quiero cuidado.

ESTADO
`dev` tiene el módulo completo con 50 pruebas y el endurecimiento de seguridad.
`main` (producción) sigue en `dfff208`, sin nada de esto. Railway despliega desde main
(CONFIRMAR en el panel antes de nada).

El servicio `leads_traker` sigue intacto en producción, recibiendo webhooks de Meta y
escribiendo en Google Sheets. En Fase 2 conviven ambos; el apagado es Fase 3.

PASO MANUAL OBLIGATORIO ANTES DEL PRIMER DESPLIEGUE
    alembic stamp 0001
Una sola vez, contra la base de producción. Producción ya tiene datos en las tablas
anteriores a Alembic; el stamp le dice que ese esquema base ya existe. Sin ese paso, el
arranque intenta recrear tablas que ya tienen clientes dentro y el servicio entra en
crash-loop. Ver `intelligence-backend/docs/DEPLOY_ALEMBIC.md`.

DOS COSAS SIN VERIFICAR QUE HAY QUE RESOLVER
1. El repo tiene Procfile Y Dockerfile, ambos con `alembic upgrade head` cableado antes
   de uvicorn. Si el panel de Railway tiene un Start Command configurado a mano, ESE gana
   y hay que editarlo desde la interfaz.
2. Nada se probó nunca contra Postgres, solo SQLite. La migración 0003 emite
   DROP/ADD CONSTRAINT en Postgres, un camino distinto al que se ejecutó. Correr
   `alembic check` contra una copia del esquema real antes de desplegar.
   Nota: 0003 usa el inspector, así que NO funciona en modo offline (--sql).

CONFIGURACIÓN NUEVA REQUERIDA
`LEADS_SYNC_TOKEN` en Railway, con el mismo valor en leads_traker. La app NO arranca en
producción si queda vacío o con el valor de desarrollo (es intencional).

Empecemos revisando el estado real de Railway y armando el plan de despliegue paso a paso.
```

---

## Chat 4 — Fase 3: cutover

```
Trabajo en VaoVao Intelligence: C:\Users\vfgut_7pxhpv9\Documents\vaovao inteligence

Fase 2 ya está validada: el módulo de leads corre en producción en paralelo con
leads_traker. Toca el cutover — que Intelligence quede como único responsable.

CONTEXTO
leads_traker es un servicio aparte que recibe los webhooks de Meta Lead Ads y escribe en
Google Sheets. Durante Fase 2 ambos convivieron. El acuerdo desde el diseño es que
leads_traker se DEPRECA pero NO se elimina: queda como respaldo por si hay que volver.

LO QUE HAY QUE DECIDIR Y EJECUTAR
- Repuntar el webhook de Meta hacia Intelligence.
- Confirmar que no queden leads sin migrar ni huérfanos pendientes
  (`GET /leads/status` expone el conteo y los page_id afectados).
- Apagar leads_traker sin borrarlo, y dejar escrito cómo volver a encenderlo.

VERIFICAR ANTES DE APAGAR NADA
Que toda página de Facebook activa tenga su `ClientPage` registrada en Intelligence. Un
lead de una página sin configurar NO se pierde —se guarda como huérfano y se reconcilia
después— pero no entra al pipeline hasta que alguien lo note.

Empecemos con un inventario de qué páginas están configuradas y qué está pendiente.
```

---

## Datos que sirven a cualquier chat

**Rutas**
- Repo: `C:\Users\vfgut_7pxhpv9\Documents\vaovao inteligence` (el directorio principal está en `main`)
- Worktree de dev: `.claude\worktrees\dev`
- Intérprete: `intelligence-backend\.venv\Scripts\python.exe`
  (el worktree no tiene su propio venv; en PowerShell usar `-m alembic`, no `alembic` suelto)

**Documentación commiteada en dev**
- Diseño completo con enmiendas: `intelligence-backend/docs/superpowers/specs/2026-08-25-leads-integration-design.md`
- Despliegue de Alembic: `intelligence-backend/docs/DEPLOY_ALEMBIC.md`

**Historial de trabajo** (no está en git, es local)
- `.superpowers/sdd/leads-integration/progress.md` — ledger con todas las decisiones
- `.superpowers/sdd/leads-integration/*-report.md` — un reporte por tarea

**Hallazgos corregidos durante el desarrollo**, útiles como advertencia: casi todos los
problemas serios aparecieron en la costura entre componentes, no dentro de ninguno.
Aislamiento entre organizaciones en la reconciliación de huérfanos; fuga del token
compartido por el manejador de errores 422 de FastAPI; borrado de clientes que arrasaba
con el historial comercial por cascadas nuevas sobre un endpoint viejo; y una búsqueda
que habría fallado en toda petición por usar `.astext` sobre una columna JSON.
