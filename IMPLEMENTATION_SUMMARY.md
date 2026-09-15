# 📋 Resumen Ejecutivo: Arquitectura Tiempo Real

**Objetivo:** Dashboard y reportes con métricas en vivo, sin esperas, con una sola llamada a Meta cada 30s.

---

## 🎯 Lo Más Importante

1. **Una sola llamada a Meta cada 30 segundos** (Celery + scheduler)
2. **Datos en caché Redis** → API retorna en <100ms
3. **WebSocket para updates en vivo** → Usuario ve cambios sin refresh
4. **Histórico en PostgreSQL** → Reportes con datos históricos

---

## 🏗️ Stack

```
Next.js Frontend
    ↓ (WebSocket - Socket.io)
FastAPI Backend + Uvicorn
    ↓
┌─────────────────────┐
│ Redis (Caché)       │ ← API lee aquí (super rápido)
│ PostgreSQL (BD)     │ ← Histórico para reportes
│ Celery + Workers    │ ← Actualiza caché cada 30s
└─────────────────────┘
    ↓
Meta Ads API (1 llamada/30s)
```

---

## 📦 Dependencias a Agregar

```bash
pip install celery redis python-socketio aioredis
```

---

## 📁 Archivos a Crear (en orden)

| Archivo | Fase | Descripción |
|---------|------|-------------|
| `app/core/cache.py` | 1 | Redis get/set funciones |
| `app/celery_app.py` | 1 | Configuración Celery |
| `app/tasks.py` | 2 | Tareas: fetch Meta + actualiza caché |
| `app/integrations/meta_ads.py` | 2 | Wrapper Meta API |
| `app/api/routes/metrics.py` | 3 | GET /api/metrics (desde caché) |
| `app/api/routes/reports.py` | 3 | GET /api/reports/dashboard |
| `app/websocket.py` | 4 | Socket.io server + broadcast |
| `lib/socket.js` | 5 | Socket.io client (Next.js) |
| `hooks/useMetrics.js` | 5 | Hook React para métricas vivas |
| `components/Dashboard.jsx` | 5 | Componente que muestra datos |
| `app/models/MetricsSnapshot` | 6 | Modelo BD para histórico |
| `docker-compose.yml` | 7 | Orquestación completa |

---

## ⚙️ Configuración Base

**`app/core/config.py`** - Agregar:
```python
REDIS_HOST = "localhost"
REDIS_PORT = 6379
CELERY_BROKER_URL = "redis://localhost:6379/0"
META_FETCH_INTERVAL = 30  # segundos
META_CACHE_TTL = 60  # TTL en Redis
```

---

## 🔄 Flujo de Datos

```
1️⃣ Celery Beat dispara cada 30s
   └→ Task: refresh_organization_metrics

2️⃣ Celery Worker ejecuta task
   └→ Fetch a Meta Ads API
   └→ Guarda en Redis (caché)
   └→ Guarda en PostgreSQL (histórico)
   └→ Broadcast vía WebSocket

3️⃣ API GET /metrics
   └→ Lee Redis (instant)
   └→ Retorna en <100ms

4️⃣ WebSocket emite "metrics_updated"
   └→ Frontend recibe
   └→ React re-render (sin refresh)
```

---

## ✅ Fases Rápidas

### Fase 1 (1-2 días)
- Redis + Celery + Socket.io instalados
- Config base en place
- Worker puede ejecutar

### Fase 2 (3-4 días)
- Tareas Celery escritas
- Fetch a Meta funcionando
- Datos en Redis

### Fase 3 (2-3 días)
- Endpoints /api/metrics y /api/reports
- WebSocket broadcasting
- Frontend escucha updates

### Fase 4 (2-3 días)
- Dashboard React funcional
- BD histórico
- Docker Compose

**Total estimado:** 2-3 semanas (1 dev FT)

---

## 🧪 Testing Rápido Local

```bash
# Terminal 1: Backend
cd intelligence-backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# Terminal 2: Redis
redis-server

# Terminal 3: Celery Worker
celery -A app.tasks worker -l info

# Terminal 4: Celery Beat (scheduler)
celery -A app beat -l info

# Terminal 5: Frontend
cd intelligence-web
npm run dev

# Abrir http://localhost:3000 y ver dashboard actualizar cada 30s
```

---

## 🚀 Deployment (Railway)

1. Agregar PostgreSQL + Redis (Railway add-on o externo)
2. Crear 3 servicios:
   - `api` (FastAPI) - main.py
   - `celery-worker` - tasks worker
   - `celery-beat` - scheduler
3. Env vars:
   ```
   DATABASE_URL=...
   REDIS_HOST=...
   CELERY_BROKER_URL=...
   SECRET_KEY=...
   META_FETCH_INTERVAL=30
   ```

---

## 💡 Puntos Clave

✅ **Una sola llamada a Meta** - Celery scheduler hace el fetch, no cada usuario
✅ **API ultra-rápida** - Lee caché, no Meta
✅ **Real-time updates** - WebSocket notifica cambios
✅ **Histórico** - PostgreSQL para reportes
✅ **Sin bloqueos** - Todo async/background
✅ **Escalable** - Agregar workers Celery

---

## 🤔 Preguntas Comunes

**¿Qué pasa si Meta API falla?**
- Caché sigue sirviendo datos antiguos (graceful degradation)
- Retry automático en siguiente ciclo de Celery

**¿Cuántos usuarios por segundo puede soportar?**
- API desde caché: miles/segundo
- Bottleneck: BD (pero eso es solo escritura historica)

**¿Y si necesito updates más frecuentes (cada 10s)?**
- Solo cambiar `META_FETCH_INTERVAL = 10` en config

**¿Java en algún punto?**
- No. Python + Celery es más que suficiente.
- Agregar complejidad sin beneficio real.

---

## 📞 Próximos Pasos

1. Pasar este plan a otro agente
2. Agente implementa **Fase 1** (infraestructura)
3. Validar que Celery + Redis funcionen
4. Implementar **Fase 2** (tasks + Meta integration)
5. Iterar hasta Fase 7 (deployment)

