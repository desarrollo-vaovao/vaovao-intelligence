# ⚡ QuickStart - Real-time Architecture

**Paso a paso para implementar la arquitectura tiempo real.**

---

## 1️⃣ Setup Local

```bash
# Backend
cd intelligence-backend
python3 -m venv .venv
source .venv/bin/activate
pip install celery redis python-socketio aioredis
pip freeze > requirements.txt

# Redis (separa terminal)
redis-server

# Validar
redis-cli ping  # PONG
```

---

## 2️⃣ Crear Archivos Base

### A. Cache manager (`app/core/cache.py`)
```python
import redis

redis_client = redis.Redis(host="localhost", port=6379, decode_responses=True)

def get_cached_metrics(org_id: str):
    return redis_client.get(f"metrics:org:{org_id}")

def set_cached_metrics(org_id: str, data: dict, ttl: int = 60):
    redis_client.setex(f"metrics:org:{org_id}", ttl, str(data))
```

### B. Celery app (`app/celery_app.py`)
```python
from celery import Celery

celery_app = Celery(
    "vaovao_intelligence",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/1",
)

celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
)
```

### C. Tareas Celery (`app/tasks.py`) - LO MÁS IMPORTANTE
```python
from celery import shared_task
from app.core.cache import set_cached_metrics
from app.integrations.meta_ads import MetaAdsAPI
from datetime import datetime, timedelta
import json

@shared_task
def refresh_organization_metrics(org_id: str):
    """Una sola llamada a Meta, guarda en caché"""
    
    # 1. Fetch a Meta (UNA VEZ)
    org = get_org(org_id)  # De DB
    meta = MetaAdsAPI(org.meta_token)
    
    all_metrics = {}
    for client in org.clients:
        for ad_account in client.ad_accounts:
            metrics = meta.get_account_metrics(ad_account.id)
            all_metrics[ad_account.id] = metrics
    
    # 2. Guarda en Redis
    data = {
        "org_id": org_id,
        "timestamp": datetime.utcnow().isoformat(),
        "metrics": all_metrics
    }
    set_cached_metrics(org_id, data, ttl=60)
    
    # 3. Broadcast a WebSocket (vea abajo)
    
    return data

# Scheduler (ejecuta cada 30s)
from celery.schedules import schedule

celery_app.conf.beat_schedule = {
    'refresh-metrics-every-30s': {
        'task': 'app.tasks.refresh_organization_metrics',
        'schedule': 30.0,  # segundos
    },
}
```

---

## 3️⃣ Endpoints Caché

### GET /api/metrics - LO RÁPIDO
```python
from fastapi import APIRouter, Depends
from app.core.cache import get_cached_metrics
from app.api.deps import get_current_user

router = APIRouter()

@router.get("/api/metrics")
async def get_metrics(current_user = Depends(get_current_user)):
    """Retorna datos del caché Redis - <100ms"""
    cached = get_cached_metrics(current_user.organization_id)
    return json.loads(cached) if cached else {"status": "initializing"}
```

Registrar en `app/main.py`:
```python
from app.api.routes import metrics
app.include_router(metrics.router)
```

---

## 4️⃣ WebSocket para Real-time

### Backend (`app/websocket.py`)
```python
from python_socketio import AsyncServer

sio = AsyncServer(
    async_mode='asgi',
    cors_allowed_origins=['*']
)

@sio.event
async def connect(sid, environ):
    print(f"✅ Client {sid} connected")

@sio.on("subscribe_metrics")
async def subscribe(sid, data):
    org_id = data.get("org_id")
    # Usuario subscrito a cambios de su org
    # Cuando Celery actualiza caché, broadcast aquí ↓

async def broadcast_metrics_update(org_id: str, metrics: dict):
    """Llamada desde Celery task"""
    await sio.emit("metrics_updated", metrics, to=f"org_{org_id}")

# En app.main:
from app.websocket import sio, ASGIApp
app = FastAPI()
socket_app = ASGIApp(sio, app)  # Wrap app con socket.io
```

### Celery task (`app/tasks.py` - agregar al final)
```python
@shared_task
def refresh_organization_metrics(org_id: str):
    # ... código anterior ...
    
    # BROADCAST a WebSocket
    try:
        from app.websocket import broadcast_metrics_update
        import asyncio
        asyncio.run(broadcast_metrics_update(org_id, data))
    except Exception as e:
        print(f"WebSocket broadcast error: {e}")
    
    return data
```

---

## 5️⃣ Frontend Real-time (Next.js)

### Socket.io client (`lib/socket.js`)
```javascript
import io from 'socket.io-client';

const socket = io('http://localhost:8000', {
  reconnection: true,
});

export const subscribeToMetrics = (orgId, onUpdate) => {
  socket.emit('subscribe_metrics', { org_id: orgId });
  socket.on('metrics_updated', onUpdate);
};
```

### Hook (`hooks/useMetrics.js`)
```javascript
import { useEffect, useState } from 'react';
import { subscribeToMetrics } from '@/lib/socket';

export const useMetrics = (orgId) => {
  const [metrics, setMetrics] = useState(null);

  useEffect(() => {
    // Fetch inicial
    fetch(`/api/metrics`)
      .then(r => r.json())
      .then(setMetrics);

    // Suscribirse a updates
    subscribeToMetrics(orgId, setMetrics);
  }, [orgId]);

  return metrics;
};
```

### Componente (`components/Dashboard.jsx`)
```javascript
import { useMetrics } from '@/hooks/useMetrics';

export default function Dashboard() {
  const metrics = useMetrics('org-123');
  
  if (!metrics) return <div>Cargando...</div>;

  return (
    <div>
      <h1>Dashboard Tiempo Real</h1>
      <pre>{JSON.stringify(metrics, null, 2)}</pre>
    </div>
  );
}
```

---

## 6️⃣ Correr Todo Local

```bash
# Terminal 1: Redis
redis-server

# Terminal 2: API FastAPI
cd intelligence-backend
uvicorn app.main:app --reload

# Terminal 3: Celery Worker
celery -A app.tasks worker -l info

# Terminal 4: Celery Beat (scheduler)
celery -A app beat -l info

# Terminal 5: Frontend
cd intelligence-web
npm run dev

# Listo! http://localhost:3000
# Dashboard actualiza automáticamente cada 30s
```

---

## 7️⃣ Validar Funcionamiento

```bash
# Verificar caché en Redis
redis-cli
> GET metrics:org:*

# Ver logs Celery (verificar que task ejecuta)
# Terminal 3/4: Debe decir "✅ Task completed"

# Ver WebSocket en browser
# DevTools → Network → WS → socket.io eventos

# Ver métricas rápidas
curl http://localhost:8000/api/metrics
# Retorna en <100ms
```

---

## 8️⃣ Docker Compose (opcional, para toda la stack)

Crear `docker-compose.yml` en raíz:
```yaml
version: '3.9'

services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_PASSWORD: postgres
    ports: ["5432:5432"]

  redis:
    image: redis:7
    ports: ["6379:6379"]

  api:
    build: ./intelligence-backend
    ports: ["8000:8000"]
    environment:
      DATABASE_URL: postgresql://postgres:postgres@postgres:5432/vaovao
      REDIS_HOST: redis
      CELERY_BROKER_URL: redis://redis:6379/0
    depends_on: [postgres, redis]
    command: uvicorn app.main:app --host 0.0.0.0

  celery_worker:
    build: ./intelligence-backend
    environment:
      DATABASE_URL: postgresql://postgres:postgres@postgres:5432/vaovao
      CELERY_BROKER_URL: redis://redis:6379/0
    depends_on: [postgres, redis]
    command: celery -A app.tasks worker -l info

  celery_beat:
    build: ./intelligence-backend
    environment:
      DATABASE_URL: postgresql://postgres:postgres@postgres:5432/vaovao
      CELERY_BROKER_URL: redis://redis:6379/0
    depends_on: [postgres, redis]
    command: celery -A app beat -l info

  web:
    build: ./intelligence-web
    ports: ["3000:3000"]
    environment:
      NEXT_PUBLIC_API_URL: http://localhost:8000
    command: npm run dev

volumes:
  postgres_data:
  redis_data:
```

```bash
docker-compose up
# Toma 2-3 min en arrancar, luego http://localhost:3000
```

---

## ⚠️ Errores Comunes

| Error | Solución |
|-------|----------|
| `ConnectionError: Redis` | ¿Redis corre? `redis-server` |
| `ModuleNotFoundError: celery` | `pip install celery` |
| `WebSocket conexión rechazada` | Backend Socket.io no iniciado |
| `Caché vacío` | ¿Celery worker corriendo? Ver Terminal 3 |
| `Meta API 401` | Token encriptado correctamente en DB |

---

## 🎯 Próximos Pasos

1. ✅ Crear archivos base (Fases 1-3)
2. ✅ WebSocket funcionando (Fase 4)
3. ✅ Frontend actualiza sin refresh (Fase 5)
4. ⏳ Guardar histórico en BD (Fase 6)
5. ⏳ Deploy a Railway

---

## 📞 Verificaciones Finales

- [ ] Redis conecta (`redis-cli ping`)
- [ ] Celery Worker inicia sin errores
- [ ] Celery Beat ejecuta tareas cada 30s
- [ ] API retorna métricas en <100ms
- [ ] WebSocket conecta sin 403/404
- [ ] Frontend ve datos actualizados sin refresh
- [ ] Logs limpios (sin errores de conexión)

¡Listo para implementar! 🚀

