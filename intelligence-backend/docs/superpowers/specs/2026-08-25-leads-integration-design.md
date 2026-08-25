# Diseño: Integración de Módulo de Leads en VaoVao Intelligence

**Fecha:** 2026-08-25  
**Autor:** Equipo VaoVao  
**Estado:** Diseño Aprobado  

---

## 1. Resumen Ejecutivo

Se agrrega un módulo `/leads` dentro de VaoVao Intelligence para gestionar leads capturados de campañas Meta Lead Ads. El módulo actúa como **CRM interno** (panel para equipo VaoVao), reemplazando Google Sheets con una base de datos estructurada y un panel interactivo con búsqueda, filtrado, asignación de usuarios y gestión de estado.

**Alcance:** Módulo interno de VaoVao. Los clientes (portafolios) NO acceden al panel; solo descargan CSV exportado.

**Timeline:** 
- Fase 1 (Dev): 2-3 semanas
- Fase 2 (Validación): 1-2 semanas  
- Fase 3 (Cutover): sin downtime

---

## 2. Arquitectura & Flujo de Datos

### 2.1 Diagrama de Flujo

```
Meta Webhook (página del cliente)
    ↓
leads_traker (webhook endpoint, dedup, Meta Graph API)
    ↓ (evento push: lead_received/fetched/delivered/error)
    ↓
Intelligence /leads/sync-webhook (recibe evento, valida, escribe en DB)
    ↓
Tabla `Lead` en PostgreSQL
    ↓
Panel interno (búsqueda, filtrado, estado, asignación, notas)
    ↓
CSV export (descargado por cliente)
```

### 2.2 Fases de Ejecución

**Fase 1: Desarrollo (rama `dev`, 2-3 semanas)**
- Código nuevo en Intelligence (módulo `/leads`)
- leads_traker **intacto** en producción
- Testing en dev
- Sin impacto a clientes

**Fase 2: Validación en Paralelo (1-2 semanas)**
- Intelligence `/leads` desplegado en producción
- leads_traker sigue activo (source of truth)
- Sincronización push en paralelo
- **AMBAS apps vivas** (redundancia, sin riesgos)
- Auditar que todo funciona
- Sin cutover todavía

**Fase 3: Cutover (cuándo esté seguro)**
- Intelligence 100% responsable
- leads_traker deprecado (pero no eliminado, fallback si es necesario)
- Transición sin downtime

---

## 3. Modelo de Datos

### 3.1 Tabla `Lead`

```python
class Lead(Base):
    __tablename__ = "leads"
    
    # Identificadores
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    
    # Del webhook de Meta
    leadgen_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    form_id: Mapped[str] = mapped_column(String(64), nullable=True)
    campaign_name: Mapped[str] = mapped_column(String(255), nullable=True)
    
    # Datos del formulario (JSON, flexible para distintos formularios)
    form_data: Mapped[dict] = mapped_column(JSON, default=dict)
    # Ej: {"nombre": "María", "email": "maria@...", "teléfono": "+502..."}
    
    # CRM
    status: Mapped[str] = mapped_column(String(32), default="nuevo")
    # Valores permitidos: nuevo, contactado, calificado, propuesta, ganado, perdido
    
    assigned_to_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Auditoría
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    
    # Relaciones
    organization: Mapped["Organization"] = relationship(back_populates="leads")
    client: Mapped["Client"] = relationship()
    assigned_to: Mapped["User | None"] = relationship()
```

**Índices:**
```python
Index("idx_lead_org_client_status", "org_id", "client_id", "status"),
Index("idx_lead_org_assigned", "org_id", "assigned_to_id"),
Index("idx_lead_received_at", "received_at"),  # Para paginación
```

### 3.2 Tabla `LeadAudit` (Auditoría)

```python
class LeadAudit(Base):
    __tablename__ = "lead_audits"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    
    action: Mapped[str] = mapped_column(String(32))
    # Valores: created, status_changed, assigned, notes_added, notes_changed
    
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    
    lead: Mapped["Lead"] = relationship()
    user: Mapped["User"] = relationship()
```

---

## 4. API Endpoints

### 4.1 Listar Leads (con filtros)

```
GET /leads?page=1&size=50&status=nuevo&client_id=1&assigned_to=2&search=maria
```

**Response:**
```json
{
  "total": 128,
  "page": 1,
  "size": 50,
  "items": [
    {
      "id": 1,
      "leadgen_id": "LEA123456",
      "form_data": {"nombre": "María Solís", "email": "maria@...", "teléfono": "+502..."},
      "status": "contactado",
      "assigned_to": {"id": 5, "full_name": "Daniela P."},
      "notes": "Seguimiento lunes",
      "received_at": "2026-08-25T11:04:00Z"
    }
  ]
}
```

**Validaciones:**
- `page`, `size` (max 500)
- Usuario solo ve leads de su org
- `member` role solo ve leads asignados a él

### 4.2 Detalle de Lead

```
GET /leads/{lead_id}
```

**Response:**
```json
{
  "id": 1,
  "leadgen_id": "LEA123456",
  "form_id": "FORM789",
  "campaign_name": "Conversiones Ago",
  "form_data": {"nombre": "María", "email": "...", "teléfono": "..."},
  "status": "contactado",
  "assigned_to": {...},
  "notes": "...",
  "received_at": "...",
  "updated_at": "...",
  "audit_log": [
    {"action": "created", "user": "Sistema", "timestamp": "..."},
    {"action": "assigned", "user": "Daniela P.", "old": null, "new": "Daniela P.", "timestamp": "..."}
  ]
}
```

### 4.3 Actualizar Lead (estado, asignación, notas)

```
PATCH /leads/{lead_id}
```

**Request:**
```json
{
  "status": "ganado",
  "assigned_to_id": 5,
  "notes": "Seguimiento para Friday"
}
```

**Response:** Lead actualizado + audit log entry

**Validaciones:**
- `status` debe ser uno de: nuevo, contactado, calificado, propuesta, ganado, perdido
- `assigned_to_id` debe ser usuario de la misma org
- Usuario con role `member` solo puede cambiar leads asignados a él

### 4.4 Exportar a CSV

```
GET /leads/export/csv?client_id=1&desde=2026-08-01&hasta=2026-08-31
```

**Cabeceras de respuesta:**
```
Content-Type: text/csv; charset=utf-8
Content-Disposition: attachment; filename="leads-2026-08-25.csv"
```

**Contenido CSV:**
```
leadgen_id,form_id,campaign_name,nombre,email,teléfono,status,assigned_to,notas,received_at
LEA123456,FORM789,Conversiones Ago,María Solís,maria@email.com,+50255412290,contactado,Daniela P.,Seguimiento,2026-08-25T11:04:00Z
LEA123457,FORM789,Conversiones Ago,Jorge Díaz,jorge@email.com,+50233207745,ganado,Daniela P.,,2026-08-25T09:20:00Z
```

**Campos incluidos:**
- Todos los campos de `form_data` (nombre, email, teléfono, etc.)
- Metadata: leadgen_id, form_id, campaign_name, status, assigned_to, notas, received_at

**Performance:**
- Si <1000 leads: response inmediato (streaming)
- Si >1000 leads: background job, email con link de descarga

### 4.5 Status de Conexión

```
GET /leads/status
```

**Response:**
```json
{
  "connected": true,
  "leads_traker_healthy": true,
  "pending_sync": 3
}
```

### 4.6 Webhook de Sincronización (Interno)

```
POST /leads/sync-webhook
```

**Request (desde leads_traker):**
```json
{
  "leadgen_id": "LEA123456",
  "page_id": "123456789",
  "form_id": "FORM789",
  "campaign_name": "Conversiones Ago",
  "form_data": {"nombre": "María", "email": "maria@...", "teléfono": "+502..."},
  "status": "fetched",
  "token": "{LEADS_SYNC_TOKEN}"
}
```

**Response:**
```json
{
  "status": "ok",
  "leadgen_id": "LEA123456"
}
```

**Error handling:**
- Token inválido → 403 Forbidden
- Cliente no encontrado → 404 Not Found (logguear, no fallar)
- Duplicado (leadgen_id existe) → actualizar status, no crear nuevo

**Tolerancia a fallos:**
- Si Intelligence está down, leads_traker reintenta 3 veces con backoff exponencial
- Si falla, logguea pero continúa (no bloquea procesamiento del lead)

---

## 5. Permisos & RBAC

| Rol | Ver Todos Leads | Ver Leads Asignados | Cambiar Estado | Asignar | Exportar CSV |
|---|---|---|---|---|---|
| **owner** | ✅ Su org | ✅ | ✅ | ✅ | ✅ |
| **admin** | ✅ Su org | ✅ | ✅ | ✅ | ✅ |
| **member** | ❌ | ✅ Suyos | ✅ Suyos | ❌ | ✅ Suyos |

**Implementación:**
```python
def _filter_leads_for_user(query: Query, current_user: User) -> Query:
    query = query.filter(Lead.org_id == current_user.org_id)
    
    if current_user.role == UserRole.member:
        query = query.filter(Lead.assigned_to_id == current_user.id)
    
    return query
```

---

## 6. Sincronización (Push Architecture)

### 6.1 En leads_traker (Productor)

Cuando el lead cambia de estado (received → fetched → delivered), publica un evento:

```python
# leads_traker/app/processor.py
def process_lead(leadgen_id: str, page_id: str, form_id: str | None):
    db = SessionLocal()
    try:
        # ... lógica existente ...
        
        # Al final de cada cambio de estado:
        _notify_intelligence({
            "leadgen_id": leadgen_id,
            "page_id": page_id,
            "form_id": form_id,
            "campaign_name": raw.get("campaign_name", ""),
            "form_data": fields,
            "status": "delivered",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        logger.error(f"Error processing lead: {e}")

def _notify_intelligence(payload: dict):
    payload["token"] = settings.LEADS_SYNC_TOKEN
    
    for attempt in range(3):
        try:
            requests.post(
                f"{settings.INTELLIGENCE_API}/leads/sync-webhook",
                json=payload,
                timeout=5
            )
            logger.info(f"Lead {payload['leadgen_id']} synced to Intelligence")
            return
        except requests.RequestException as e:
            if attempt < 2:
                wait_time = 2 ** attempt
                logger.warning(f"Retry {attempt + 1}/3 in {wait_time}s: {e}")
                time.sleep(wait_time)
            else:
                logger.error(f"Failed to sync lead {payload['leadgen_id']} after 3 attempts: {e}")
```

### 6.2 En Intelligence (Consumidor)

```python
# intelligence-backend/app/api/routes/leads.py

@router.post("/leads/sync-webhook")
async def sync_webhook(payload: dict, db: Session = Depends(get_db)):
    """
    Recibe evento de leads_traker.
    Valida, dedup, escribe en tabla Lead.
    """
    # Validar token
    if payload.get("token") != settings.LEADS_SYNC_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid sync token")
    
    leadgen_id = payload["leadgen_id"]
    page_id = payload["page_id"]
    
    try:
        # Dedup: si existe, actualizar status
        lead = db.query(Lead).filter_by(leadgen_id=leadgen_id).first()
        
        if lead:
            lead.status = payload.get("status", "received")
            lead.updated_at = datetime.now(timezone.utc)
            db.commit()
            logger.info(f"Lead {leadgen_id} updated (status: {lead.status})")
            return {"status": "ok", "leadgen_id": leadgen_id, "action": "updated"}
        
        # Nuevo lead: buscar cliente por page_id
        client = db.query(ClientPage).filter(ClientPage.page_id == page_id).first()
        if not client:
            # Cliente no configurado, logguear pero no fallar
            logger.warning(f"No client found for page_id {page_id}, lead {leadgen_id} lost")
            return {"status": "ok", "leadgen_id": leadgen_id, "note": "no client found"}
        
        # Crear nuevo lead
        lead = Lead(
            org_id=client.organization.id,
            client_id=client.id,
            leadgen_id=leadgen_id,
            form_id=payload.get("form_id"),
            campaign_name=payload.get("campaign_name"),
            form_data=payload.get("form_data", {}),
            status=payload.get("status", "received"),
        )
        db.add(lead)
        db.commit()
        
        logger.info(f"Lead {leadgen_id} created for client {client.id}")
        return {"status": "ok", "leadgen_id": leadgen_id, "action": "created"}
    
    except Exception as e:
        logger.error(f"Error syncing lead {leadgen_id}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")
```

**Configuración necesaria:**

```python
# app/core/config.py
class Settings:
    LEADS_SYNC_TOKEN: str = Field(...)  # Token secreto (gen en Railway/Vercel)
    INTELLIGENCE_API: str = Field(...)  # URL de Intelligence (ej: https://api.vaovao.co)
```

En Railway:
```
LEADS_SYNC_TOKEN=sk_abc123def456...  (random 32+ chars)
INTELLIGENCE_API=https://api.vaovao.co
```

En leads_traker (Railway también):
```
INTELLIGENCE_API=https://api.vaovao.co
LEADS_SYNC_TOKEN=sk_abc123def456...  (MISMO valor)
```

---

## 7. Escalabilidad

### 7.1 Estructura de Carpetas

```
intelligence-backend/app/
├── api/routes/leads.py              # Endpoints HTTP
├── models/__init__.py                # Lead, LeadAudit
├── services/
│   ├── leads_service.py             # Lógica de negocio
│   ├── leads_sync.py                # Recepción de eventos
│   └── leads_csv_exporter.py        # Generación de CSV
├── crud/
│   ├── __init__.py
│   └── leads.py                      # Queries optimizadas (con índices)
├── schemas/
│   └── leads.py                      # Pydantic (LeadCreate, LeadUpdate, LeadResponse)
└── tests/
    ├── unit/
    │   ├── test_leads_service.py
    │   └── test_leads_csv_exporter.py
    ├── integration/
    │   ├── test_leads_api.py
    │   └── test_leads_sync.py
    └── e2e/
        └── test_leads_flow.py
```

### 7.2 Performance

**Paginación:**
- Default: 50 items/página
- Max: 500 items/página
- Filtros optimizados con índices (org, client, status, assigned_to, received_at)

**Búsqueda de texto:**
```python
# Búsqueda en form_data JSON (PostgreSQL)
Lead.form_data["nombre"].astext.ilike(f"%{search}%")
```

**CSV Export:**
- <1000 leads: respuesta inmediata (streaming)
- >1000 leads: background job con email

**Concurrencia:**
- Sincronización push: sin locks, eventual consistency
- Si 2 eventos llegan simultáneamente para el mismo leadgen_id: base de datos maneja (unique constraint)

### 7.3 Testing

**Unit tests** (sin DB):
- Lógica de búsqueda, filtrado
- Generación de CSV
- Validación de permisos

**Integration tests** (con DB test):
- CRUD en tabla Lead
- Webhook de sincronización
- Auditoría registra cambios

**E2E tests**:
- Flujo completo: crear lead → asignar → cambiar estado → exportar CSV
- En rama dev (sin tocar producción)

---

## 8. Error Handling & Auditoría

### 8.1 Error Handling

| Error | Causa | Acción |
|---|---|---|
| Token inválido en webhook | Breach/misconfiguration | 403, logguear, NO procesar |
| Cliente no encontrado (page_id) | Config incompleta | 200 OK pero logguear warning, NO crear lead |
| Leadgen duplicado | Meta reenvía webhook | Actualizar status, no fallar |
| DB error en Intelligence | Transient | 500, retry desde leads_traker |
| Intelligence down (sync) | Network/outage | Retry 3x con backoff, continuar en leads_traker |

### 8.2 Auditoría

Cada cambio se registra en `LeadAudit`:

```python
def _audit_lead_change(db: Session, lead_id: int, user_id: int, action: str, old: Any, new: Any):
    audit = LeadAudit(
        lead_id=lead_id,
        user_id=user_id,
        action=action,
        old_value=json.dumps(old) if old else None,
        new_value=json.dumps(new),
    )
    db.add(audit)
    db.commit()
```

**Casos auditados:**
- Lead creado (acción: `created`, user: `System`)
- Status cambió (acción: `status_changed`, old: `nuevo`, new: `contactado`)
- Asignado a usuario (acción: `assigned`, old: `null`, new: `Daniela P.`)
- Notas agregadas/cambiadas (acción: `notes_added` o `notes_changed`)

**Vista de audit log en endpoint GET /leads/{lead_id}**: último actor, timestamp, cambio realizado.

---

## 9. Seguridad

### 9.1 Consideraciones

- **Token de sincronización:** `LEADS_SYNC_TOKEN` es secreto, guardado en Railway/Vercel (no en `.env`)
- **RBAC:** Filtrado por org_id + role. Members solo ven sus leads
- **Rate limiting:** Ya está en Intelligence (`/app/core/ratelimit.py`)
- **Input validation:** Pydantic schemas validan entrada
- **SQL injection:** SQLAlchemy ORM previene (parametrized queries)
- **Error disclosure:** Mensajes genéricos al cliente, detalles en logs del servidor

### 9.2 Integración con Plan de Seguridad

- Rate limiting en `/leads` endpoints (mismo que reportes)
- CORS ya está configurado en main.py
- Security headers ya están en place
- Logs incluyen user_id, action, timestamp (auditoría compliance)

---

## 10. Dependencias & Impacto

### 10.1 Dependencias Técnicas

- PostgreSQL (ya existe)
- FastAPI + SQLAlchemy (ya en use)
- Requests library (para sincronización push)
- Pydantic (validación, ya en use)

### 10.2 Impacto en Servicios Existentes

- ✅ Zero impact en reportes
- ✅ Zero impact en auth
- ✅ Zero impact en clients/users/organization
- ✅ Zero impact en Facebook integration
- ✅ Rate limiting compartido (no interfiere)

### 10.3 Dependencias de leads_traker

- Debe tener `LEADS_SYNC_TOKEN` y `INTELLIGENCE_API` configurados
- Debe tener `requests` library instalado
- Retry logic implementado (tolerancia a fallos)

---

## 11. Success Criteria

- ✅ Tabla `Lead` creada en DB, con índices y relaciones
- ✅ Endpoints `/leads` funcionan (listar, detalle, actualizar, exportar CSV)
- ✅ Sincronización push funciona (leads_traker → Intelligence)
- ✅ RBAC implementado (member vs admin vs owner)
- ✅ Auditoría registra cambios
- ✅ CSV export con todos los campos
- ✅ Tests: unit + integration + E2E
- ✅ Error handling robusto
- ✅ Performance OK (paginación, índices)
- ✅ Documentación de API (docstrings)
- ✅ Fase 1 en rama dev sin impacto a producción
- ✅ Fase 2: validación en paralelo con leads_traker
- ✅ Fase 3: cutover sin downtime

---

## 12. Timeline Estimado

| Fase | Duración | Trabajo |
|---|---|---|
| **Fase 1: Dev** | 2-3 semanas | Código nuevo, testing en dev |
| **Fase 2: Validación** | 1-2 semanas | Deploy a producción, sync en paralelo, auditar |
| **Fase 3: Cutover** | 1 día | Apagar leads_traker (sin eliminar) |

---

## Aprobación

**Diseño validado:** ✅  
**Listo para escribir plan de implementación:** ✅

---

## 13. Enmiendas (2026-08-25, tras revisión de Task 1)

Dos huecos detectados al implementar los modelos. Ambos resueltos por decisión del equipo.

### 13.1 Etapas del pipeline: 6, no 4

El spec original definía 4 estados. El diseño del panel Kanban usa 5 columnas, más el
cierre negativo. Los valores válidos de `Lead.status` son:

    nuevo → contactado → calificado → propuesta → ganado
                                                → perdido

`perdido` es terminal y puede alcanzarse desde cualquier etapa. `status` se mantiene
como `String(32)` (no `Enum` nativo de Postgres) precisamente porque se espera que el
pipeline gane etapas: agregar una debe ser un cambio de código, no un `ALTER TYPE`.

La validación de estos valores vive en los schemas Pydantic y en la capa de servicio,
no en el modelo.

### 13.2 Enrutamiento por página: tabla `ClientPage`

El spec enrutaba webhooks por `Client.page_id`, pero esa columna no existe — y un
cliente puede tener varias páginas de Facebook, igual que ya tiene varias cuentas
publicitarias (`AdAccount`). Se agrega una tabla propia:

```python
class ClientPage(Base):
    """
    Página de Facebook de un cliente. Es la llave de enrutamiento de los leads:
    el webhook de Meta trae un page_id y por él sabemos de qué cliente es el lead.
    Un cliente puede tener varias páginas (igual que varias cuentas publicitarias).
    """
    __tablename__ = "client_pages"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    page_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    page_name: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    client: Mapped["Client"] = relationship(back_populates="pages")
```

Y en `Client`:

```python
pages: Mapped[list["ClientPage"]] = relationship(
    back_populates="client", cascade="all, delete-orphan"
)
```

`page_id` es único a nivel global: una página de Facebook pertenece a un solo cliente.
El enrutamiento del webhook queda:

```python
page = db.query(ClientPage).filter(ClientPage.page_id == page_id).first()
if not page:
    # sin página configurada → logguear y responder 200 (no perder el webhook)
    ...
client = page.client
```

Esto reemplaza toda referencia a `Client.page_id` en las secciones 6 y 4.6.

---

## 14. Enmiendas (2026-08-25, checkpoint tras Task 5)

### 14.1 Leads huérfanos: no se pierde ninguno

Cuando llega un webhook cuyo `page_id` no corresponde a ninguna `ClientPage`, el lead
no se puede atribuir a ningún cliente. Descartarlo con una línea de log significa
perder un lead real por un error de configuración — plata perdida sin que nadie lo note.

Se guarda en su propia tabla, sin atribuir:

```python
class OrphanLead(Base):
    """
    Lead que llegó de una página de Facebook que nadie configuró todavía.
    No se puede atribuir a un cliente, pero tampoco se tira: cuando alguien
    registre esa página, `reconciliar_huerfanos` los reprocesa y entran al
    pipeline como leads normales.
    """
    __tablename__ = "orphan_leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    leadgen_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    page_id: Mapped[str] = mapped_column(String(64), index=True)
    form_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    campaign_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    form_data: Mapped[dict] = mapped_column(JSON, default=dict)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # Se llena cuando el huérfano ya fue convertido en Lead real.
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

Flujo:

1. Webhook con `page_id` desconocido → se guarda `OrphanLead` y se responde 200.
   Meta no debe reintentar: el lead ya está a salvo.
2. Alguien registra la `ClientPage` faltante.
3. La reconciliación toma los huérfanos pendientes de ese `page_id`, los convierte
   en `Lead` normales y les marca `resolved_at`.

`leadgen_id` es único también aquí, y la deduplicación debe mirar ambas tablas: un
`leadgen_id` que ya existe como `Lead` no vuelve a entrar como huérfano.

El endpoint de estado (§4.5) expone cuántos huérfanos hay pendientes y de qué páginas,
para que la mala configuración sea visible sin leer logs.

### 14.2 Auditoría del sistema: `user_id` pasa a ser nullable

`LeadAudit.user_id` era `NOT NULL`, así que un lead creado por webhook no podía
generar su fila `created` — el webhook no actúa en nombre de ningún usuario. El valor
`created` quedaba sin emisor.

`user_id` pasa a `nullable=True`, donde **NULL significa "lo hizo el sistema"**. Es como
funcionan las bitácoras habitualmente y deja la traza completa: desde que el lead nace
hasta que se cierra.

Al mostrar la bitácora, un `user_id` nulo se presenta como "Sistema".
La ingesta por webhook emite ahora su fila `created` con `user_id=None`.
