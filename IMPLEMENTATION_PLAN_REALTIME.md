# Plan de Implementación: Tiempo Real + Caché + Background Jobs
## Vao Vao Intelligence - Arquitectura para Dashboard y Reportes en Vivo

**Objetivo:** Sistema donde el usuario ve métricas frescas sin esperas, con una sola llamada a Meta cada 30-60 segundos en background.

**Stack:** Python (FastAPI) + Celery + Redis + PostgreSQL + Next.js + WebSocket

---

## 🏗️ Arquitectura Objetivo

```
┌──────────────────────────────────────────────────────────────┐
│                    FRONTEND (Next.js)                         │
│  - Dashboard con métricas en vivo                            │
│  - Reportes con datos frescos                                │
│  - Socket.io listener para updates en tiempo real            │
└──────────────────────┬───────────────────────────────────────┘
                       │ WebSocket (Socket.io)
         ┌─────────────▼──────────────┐
         │  FastAPI Backend           │
         │  - GET /api/metrics        │
         │  - GET /api/reports        │
         │  - WebSocket handler       │
         │  - Health check            │
         └──────────────┬──────────────┘
                        │
       ┌────────────────┼────────────────┐
       │                │                │
   ┌───▼────────┐  ┌───▼────────┐  ┌───▼──────────┐
   │   Redis    │  │ PostgreSQL  │  │   Celery     │
   │  (Caché)   │  │ (Histórico) │  │  (Workers)   │
   └────────────┘  └─────────────┘  └───┬──────────┘
                                         │
                              ┌──────────▼──────────┐
                              │  Meta Ads API       │
                              │  (Una sola llamada  │
                              │   cada 30-60s)      │
                              └─────────────────────┘
```

---

## 📋 Fases de Implementación

### **FASE 1: Infraestructura Base (Semana 1)**
Configurar Celery, Redis y la orquestación básica.

#### Tarea 1.1: Agregar dependencias
**Archivo:** `intelligence-backend/requirements.txt`

```
# Agregar:
celery==5.3.4
redis==5.0.1
python-socketio==5.9.0
python-socketio[client]==5.9.0
aioredis==2.0.1
```

**Validación:** `pip install -r requirements.txt` sin errores

---

#### Tarea 1.2: Configurar Redis
**Archivo:** `intelligence-backend/app/core/cache.py` (crear nuevo)

```python
import redis
from app.core.config import settings

# Conexión a Redis
redis_client = redis.Redis(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    db=0,
    decode_responses=True
)

async def get_cached_metrics(org_id: str):
    """Obtiene métricas del caché"""
    return redis_client.get(f"metrics:org:{org_id}")

async def set_cached_metrics(org_id: str, data: dict, ttl: int = 60):
    """Guarda métricas en caché con TTL"""
    redis_client.setex(f"metrics:org:{org_id}", ttl, str(data))

async def clear_org_cache(org_id: str):
    """Limpia caché de una organización"""
    pattern = f"metrics:org:{org_id}:*"
    for key in redis_client.scan_iter(match=pattern):
        redis_client.delete(key)
```

**Validación:** Redis corre (`redis-cli ping` retorna PONG)

---

#### Tarea 1.3: Configurar Celery
**Archivo:** `intelligence-backend/app/celery_app.py` (crear nuevo)

```python
from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "vaovao_intelligence",
    broker=settings.CELERY_BROKER_URL,  # redis://localhost:6379/0
    backend=settings.CELERY_RESULT_BACKEND,  # redis://localhost:6379/1
)

celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 min timeout
)
```

**Validación:** Celery puede conectar a Redis

---

#### Tarea 1.4: Actualizar configuración
**Archivo:** `intelligence-backend/app/core/config.py` (agregar)

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # ... config existente ...
    
    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    
    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"
    
    # Meta Ads
    META_FETCH_INTERVAL: int = 30  # segundos
    META_CACHE_TTL: int = 60  # segundos
    
    class Config:
        env_file = ".env"
```

**Validación:** App arranca sin errores

---

### **FASE 2: Background Jobs para Meta Ads (Semana 1-2)**
Crear el worker que hace fetch a Meta y actualiza caché.

#### Tarea 2.1: Crear tareas de Celery
**Archivo:** `intelligence-backend/app/tasks.py` (crear nuevo)

```python
import logging
from typing import Optional
from app.celery_app import celery_app
from app.core.cache import set_cached_metrics, get_cached_metrics
from app.db.session import SessionLocal
from app.models import Organization, Client, AdAccount
from app.integrations.meta_ads import MetaAdsAPI
from app.core.config import settings

logger = logging.getLogger(__name__)

@celery_app.task(name="refresh_organization_metrics")
def refresh_organization_metrics(org_id: str):
    """
    Actualiza métricas de una organización desde Meta Ads.
    Se ejecuta cada META_FETCH_INTERVAL segundos.
    """
    db = SessionLocal()
    try:
        org = db.query(Organization).filter(
            Organization.id == org_id
        ).first()
        
        if not org or not org.meta_system_user_token:
            logger.warning(f"Org {org_id} sin credenciales Meta")
            return
        
        # Obtener todas las cuentas de la org
        clients = db.query(Client).filter(
            Client.organization_id == org_id
        ).all()
        
        metrics_data = {
            "org_id": org_id,
            "timestamp": datetime.utcnow().isoformat(),
            "clients": {}
        }
        
        for client in clients:
            client_metrics = {
                "id": client.id,
                "name": client.name,
                "ad_accounts": {}
            }
            
            # Una sola llamada a Meta por cliente
            for ad_account in client.ad_accounts:
                try:
                    meta = MetaAdsAPI(org.meta_system_user_token)
                    account_metrics = meta.get_account_metrics(
                        ad_account.meta_account_id,
                        date_range={
                            "start": datetime.now() - timedelta(days=7),
                            "end": datetime.now()
                        }
                    )
                    
                    client_metrics["ad_accounts"][ad_account.id] = {
                        "account_id": ad_account.meta_account_id,
                        "name": ad_account.name,
                        "metrics": account_metrics
                    }
                    
                    # Guardar en BD para histórico
                    _save_metrics_to_db(db, ad_account.id, account_metrics)
                    
                except Exception as e:
                    logger.error(f"Error fetching account {ad_account.id}: {e}")
                    client_metrics["ad_accounts"][ad_account.id] = {
                        "error": str(e)
                    }
            
            metrics_data["clients"][client.id] = client_metrics
        
        # Guardar en Redis con TTL
        set_cached_metrics(org_id, metrics_data, ttl=settings.META_CACHE_TTL)
        
        logger.info(f"✅ Métricas actualizadas para org {org_id}")
        return metrics_data
        
    except Exception as e:
        logger.error(f"❌ Error en refresh_organization_metrics: {e}")
        raise
    finally:
        db.close()

@celery_app.task(name="refresh_all_organizations")
def refresh_all_organizations():
    """
    Refresca métricas de TODAS las organizaciones.
    Llamada por Celery Beat cada META_FETCH_INTERVAL.
    """
    db = SessionLocal()
    try:
        orgs = db.query(Organization).filter(
            Organization.is_active == True
        ).all()
        
        for org in orgs:
            refresh_organization_metrics.delay(org.id)
            
        logger.info(f"🔄 Iniciadas actualizaciones para {len(orgs)} orgs")
        return len(orgs)
        
    finally:
        db.close()

def _save_metrics_to_db(db, ad_account_id: str, metrics: dict):
    """Guarda un snapshot de métricas en BD para histórico"""
    # TODO: Crear modelo MetricsSnapshot en models
    pass
```

**Validación:** `celery -A app.tasks worker -l info` inicia sin errores

---

#### Tarea 2.2: Configurar Celery Beat (scheduler)
**Archivo:** `intelligence-backend/app/celery_beat.py` (crear nuevo)

```python
from celery.schedules import schedule
from app.celery_app import celery_app
from app.core.config import settings
from datetime import timedelta

celery_app.conf.beat_schedule = {
    'refresh-all-organizations': {
        'task': 'refresh_all_organizations',
        'schedule': timedelta(seconds=settings.META_FETCH_INTERVAL),
    },
}
```

**Validación:** `celery -A app beat -l info` comienza scheduler

---

#### Tarea 2.3: Integración con Meta Ads API
**Archivo:** `intelligence-backend/app/integrations/meta_ads.py` (crear nuevo)

```python
import requests
from typing import Dict, Any
from datetime import datetime, timedelta

class MetaAdsAPI:
    """Wrapper para Meta Ads API"""
    
    BASE_URL = "https://graph.instagram.com"
    API_VERSION = "v18.0"
    
    def __init__(self, system_user_token: str):
        self.token = system_user_token
    
    def get_account_metrics(self, account_id: str, date_range: Dict) -> Dict[str, Any]:
        """
        Obtiene métricas de una cuenta de ads.
        Retorna: spend, impressions, clicks, conversions, ROAS, etc.
        """
        endpoint = f"{self.BASE_URL}/{self.API_VERSION}/{account_id}/insights"
        
        fields = [
            "spend",
            "impressions", 
            "clicks",
            "conversions",
            "cpc",
            "cpm",
            "date_start",
            "date_stop"
        ]
        
        params = {
            "fields": ",".join(fields),
            "access_token": self.token,
            "date_preset": "last_7d"  # O usar date_range si es custom
        }
        
        response = requests.get(endpoint, params=params)
        response.raise_for_status()
        
        data = response.json()
        return {
            "account_id": account_id,
            "data": data.get("data", []),
            "fetched_at": datetime.utcnow().isoformat()
        }
```

**Validación:** Llamada a Meta API retorna datos sin error 401/403

---

### **FASE 3: Endpoints de Caché (Semana 2)**
Crear los endpoints que sirven datos desde Redis.

#### Tarea 3.1: Endpoint GET /api/metrics
**Archivo:** `intelligence-backend/app/api/routes/metrics.py` (crear nuevo)

```python
from fastapi import APIRouter, Depends, HTTPException
from app.api.deps import get_current_user
from app.core.cache import get_cached_metrics
from app.models import User
import json

router = APIRouter(prefix="/metrics", tags=["metrics"])

@router.get("/")
async def get_metrics(current_user: User = Depends(get_current_user)):
    """
    Retorna métricas en caché para la organización del usuario.
    NO espera a Meta, retorna instantly desde Redis.
    """
    org_id = current_user.organization_id
    
    cached = get_cached_metrics(org_id)
    if not cached:
        # Si no hay caché, retornar estructura vacía (worker rellena en background)
        return {
            "org_id": org_id,
            "clients": {},
            "status": "initializing"  # Frontend mostrará "Cargando..."
        }
    
    return json.loads(cached)

@router.get("/status")
async def metrics_status(current_user: User = Depends(get_current_user)):
    """Estado del caché: cuándo se actualizó por última vez"""
    cached = get_cached_metrics(current_user.organization_id)
    if cached:
        data = json.loads(cached)
        return {
            "status": "fresh",
            "last_updated": data.get("timestamp"),
            "ttl_seconds": 60
        }
    return {"status": "empty", "last_updated": None}
```

**Registrar en** `intelligence-backend/app/main.py`:
```python
from app.api.routes import metrics

app.include_router(metrics.router, prefix="/api")
```

**Validación:** `GET /api/metrics` retorna datos en <100ms

---

#### Tarea 3.2: Endpoint GET /api/reports
**Archivo:** `intelligence-backend/app/api/routes/reports.py` (crear nuevo)

```python
from fastapi import APIRouter, Depends, Query
from app.api.deps import get_current_user
from app.core.cache import get_cached_metrics
from app.models import User
from datetime import datetime
import json

router = APIRouter(prefix="/reports", tags=["reports"])

@router.get("/dashboard")
async def get_dashboard_report(
    current_user: User = Depends(get_current_user),
    format: str = Query("json", regex="^(json|pdf)$")
):
    """
    Genera reporte para dashboard usando datos en caché.
    Format: json (instant) o pdf (background job)
    """
    cached = get_cached_metrics(current_user.organization_id)
    if not cached:
        return {"error": "No metrics available", "status": "initializing"}
    
    metrics = json.loads(cached)
    
    # Procesar datos en caché para reporte
    report = {
        "title": "Dashboard Report",
        "generated_at": datetime.utcnow().isoformat(),
        "summary": {
            "total_clients": len(metrics.get("clients", {})),
            "total_accounts": sum(
                len(c.get("ad_accounts", {})) 
                for c in metrics.get("clients", {}).values()
            ),
        },
        "clients": metrics.get("clients", {})
    }
    
    if format == "pdf":
        # Trigger background job para generar PDF
        # return generate_pdf_report_task.delay(org_id)
        return {"message": "PDF generation queued"}
    
    return report
```

**Validación:** `GET /api/reports/dashboard` retorna reporte en <200ms

---

### **FASE 4: WebSocket para Notificaciones en Tiempo Real (Semana 2-3)**
Updates en vivo cuando se actualiza caché.

#### Tarea 4.1: Configurar Socket.io en FastAPI
**Archivo:** `intelligence-backend/app/websocket.py` (crear nuevo)

```python
from fastapi import FastAPI
from python_socketio import AsyncServer, ASGIApp
from app.core.config import settings
import json
from app.core.cache import get_cached_metrics

# Socket.io server
sio = AsyncServer(
    async_mode='asgi',
    cors_allowed_origins=settings.ALLOWED_ORIGINS,
    ping_timeout=60,
    ping_interval=25
)

# Tracking de conexiones por org
connected_users = {}  # {org_id: [sid1, sid2, ...]}

@sio.event
async def connect(sid, environ):
    """Usuario conecta al WebSocket"""
    # Extraer org_id del token (necesita middleware)
    print(f"✅ Client {sid} connected")

@sio.event
async def disconnect(sid):
    """Usuario desconecta"""
    for org_id, sids in connected_users.items():
        if sid in sids:
            sids.remove(sid)
    print(f"❌ Client {sid} disconnected")

@sio.on("subscribe_org_metrics")
async def subscribe_metrics(sid, data):
    """Usuario se suscribe a métricas de su org"""
    org_id = data.get("org_id")
    
    if org_id not in connected_users:
        connected_users[org_id] = []
    connected_users[org_id].append(sid)
    
    # Enviar métricas actuales
    cached = get_cached_metrics(org_id)
    if cached:
        await sio.emit("metrics_updated", json.loads(cached), to=sid)

async def broadcast_metrics_update(org_id: str, metrics: dict):
    """
    Llamada desde Celery cuando se actualizan métricas.
    Notifica a todos los usuarios conectados de esa org.
    """
    if org_id in connected_users:
        await sio.emit(
            "metrics_updated",
            metrics,
            room=org_id  # Broadcast a la sala
        )
```

**Registrar en** `intelligence-backend/app/main.py`:
```python
from app.websocket import sio, ASGIApp

socket_app = ASGIApp(sio, app)
```

**Validación:** WebSocket conecta y recibe updates

---

#### Tarea 4.2: Trigger de broadcast desde Celery
**Archivo:** `intelligence-backend/app/tasks.py` (modificar)

```python
# Al final de refresh_organization_metrics, agregar:

@celery_app.task(bind=True)
def refresh_organization_metrics(self, org_id: str):
    # ... código existente ...
    
    # DESPUÉS de set_cached_metrics:
    from app.websocket import broadcast_metrics_update
    import asyncio
    
    # Broadcast a clientes conectados
    try:
        asyncio.run(broadcast_metrics_update(org_id, metrics_data))
    except Exception as e:
        logger.warning(f"⚠️ WebSocket broadcast error: {e}")
    
    return metrics_data
```

**Validación:** Cambios en caché disparan actualización en frontend

---

### **FASE 5: Frontend - Dashboard en Tiempo Real (Semana 3)**
Conectar Next.js a WebSocket y mostrar métricas vivas.

#### Tarea 5.1: Configurar Socket.io en Next.js
**Archivo:** `intelligence-web/lib/socket.js` (crear nuevo)

```javascript
import io from 'socket.io-client';

const SOCKET_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

let socket = null;

export const initSocket = () => {
  if (socket) return socket;
  
  socket = io(SOCKET_URL, {
    reconnection: true,
    reconnectionDelay: 1000,
    reconnectionDelayMax: 5000,
    reconnectionAttempts: 5,
  });
  
  socket.on('connect', () => {
    console.log('✅ WebSocket connected');
  });
  
  socket.on('disconnect', () => {
    console.log('❌ WebSocket disconnected');
  });
  
  return socket;
};

export const subscribeToMetrics = (orgId, callback) => {
  const socket = initSocket();
  
  socket.emit('subscribe_org_metrics', { org_id: orgId });
  socket.on('metrics_updated', callback);
};

export const unsubscribeFromMetrics = () => {
  if (socket) {
    socket.off('metrics_updated');
  }
};
```

**Validación:** Socket.io conecta a backend

---

#### Tarea 5.2: Hook React para métricas en vivo
**Archivo:** `intelligence-web/hooks/useMetrics.js` (crear nuevo)

```javascript
import { useState, useEffect } from 'react';
import { subscribeToMetrics, unsubscribeFromMetrics } from '@/lib/socket';

export const useMetrics = (orgId) => {
  const [metrics, setMetrics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState(null);

  useEffect(() => {
    // 1. Fetch inicial (desde caché Redis)
    const fetchInitialMetrics = async () => {
      try {
        const res = await fetch(`/api/metrics`, {
          headers: { 'Authorization': `Bearer ${getToken()}` }
        });
        const data = await res.json();
        setMetrics(data);
        setLastUpdated(new Date());
        setLoading(false);
      } catch (error) {
        console.error('Error fetching metrics:', error);
      }
    };

    fetchInitialMetrics();

    // 2. Suscribirse a updates en tiempo real
    subscribeToMetrics(orgId, (newMetrics) => {
      setMetrics(newMetrics);
      setLastUpdated(new Date());
    });

    return () => {
      unsubscribeFromMetrics();
    };
  }, [orgId]);

  return { metrics, loading, lastUpdated };
};
```

**Validación:** Componentes React ven updates sin refresh

---

#### Tarea 5.3: Componente Dashboard
**Archivo:** `intelligence-web/components/Dashboard.jsx` (crear/actualizar)

```javascript
import { useMetrics } from '@/hooks/useMetrics';
import { useSession } from 'next-auth/react';

export default function Dashboard() {
  const { data: session } = useSession();
  const { metrics, loading, lastUpdated } = useMetrics(session?.user?.org_id);

  if (loading) return <div>Cargando métricas...</div>;
  if (!metrics) return <div>Sin datos disponibles</div>;

  return (
    <div className="dashboard">
      <h1>Dashboard en Vivo</h1>
      <div className="status">
        Actualizado: {lastUpdated?.toLocaleTimeString()}
      </div>

      {Object.entries(metrics.clients || {}).map(([clientId, client]) => (
        <div key={clientId} className="client-card">
          <h2>{client.name}</h2>
          
          {Object.entries(client.ad_accounts || {}).map(([accId, acc]) => (
            <div key={accId} className="ad-account">
              <h3>{acc.name}</h3>
              <div className="metrics-grid">
                {acc.metrics?.data?.map((m, i) => (
                  <div key={i} className="metric">
                    <span className="label">{m.spend}</span>
                    <span className="value">${m.spend}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
```

**Validación:** Dashboard muestra datos sin refresh, updates en vivo

---

### **FASE 6: Persistencia y Histórico en BD (Semana 3-4)**
Guardar snapshots para reportes históricos.

#### Tarea 6.1: Modelo para histórico de métricas
**Archivo:** `intelligence-backend/app/models/__init__.py` (agregar)

```python
from sqlalchemy import Column, String, Float, DateTime, Integer, ForeignKey
from app.db.base import Base
from datetime import datetime

class MetricsSnapshot(Base):
    __tablename__ = "metrics_snapshots"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    organization_id = Column(String, ForeignKey("organization.id"), nullable=False)
    client_id = Column(String, ForeignKey("client.id"), nullable=False)
    ad_account_id = Column(String, ForeignKey("ad_account.id"), nullable=False)
    
    # Métricas
    spend = Column(Float, nullable=True)
    impressions = Column(Integer, nullable=True)
    clicks = Column(Integer, nullable=True)
    conversions = Column(Float, nullable=True)
    cpc = Column(Float, nullable=True)
    cpm = Column(Float, nullable=True)
    roas = Column(Float, nullable=True)
    
    # Timestamp
    snapshot_date = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_org_snapshot', 'organization_id', 'snapshot_date'),
        Index('idx_account_snapshot', 'ad_account_id', 'snapshot_date'),
    )
```

**Validación:** Migración de BD crea tabla

---

#### Tarea 6.2: Guardar en BD en paralelo a Redis
**Archivo:** `intelligence-backend/app/tasks.py` (modificar `_save_metrics_to_db`)

```python
from app.models import MetricsSnapshot
from sqlalchemy import insert

def _save_metrics_to_db(db, ad_account_id: str, metrics: dict):
    """Guarda snapshot de métricas en BD"""
    try:
        snapshots = []
        for daily_data in metrics.get("data", []):
            snapshot = MetricsSnapshot(
                id=str(uuid4()),
                organization_id=metrics.get("org_id"),
                ad_account_id=ad_account_id,
                spend=float(daily_data.get("spend", 0)),
                impressions=int(daily_data.get("impressions", 0)),
                clicks=int(daily_data.get("clicks", 0)),
                conversions=float(daily_data.get("conversions", 0)),
                cpc=float(daily_data.get("cpc", 0)),
                cpm=float(daily_data.get("cpm", 0)),
            )
            snapshots.append(snapshot)
        
        db.bulk_save_objects(snapshots)
        db.commit()
        
    except Exception as e:
        logger.error(f"Error saving snapshots: {e}")
        db.rollback()
```

**Validación:** Datos persisten en PostgreSQL

---

### **FASE 7: Docker Compose para Local (Semana 4)**
Orquestación completa en contenedores.

#### Tarea 7.1: docker-compose.yml
**Archivo:** `docker-compose.yml` (crear en raíz)

```yaml
version: '3.9'

services:
  # PostgreSQL
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: vaovao_intelligence
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  # Redis
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    command: redis-server --appendonly yes
    volumes:
      - redis_data:/data

  # FastAPI Backend
  api:
    build:
      context: ./intelligence-backend
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql://postgres:postgres@postgres:5432/vaovao_intelligence
      REDIS_HOST: redis
      REDIS_PORT: 6379
      CELERY_BROKER_URL: redis://redis:6379/0
      SECRET_KEY: dev-secret-key-change-in-prod
      ENVIRONMENT: development
    depends_on:
      - postgres
      - redis
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
    volumes:
      - ./intelligence-backend:/app

  # Celery Worker
  celery_worker:
    build:
      context: ./intelligence-backend
      dockerfile: Dockerfile
    environment:
      DATABASE_URL: postgresql://postgres:postgres@postgres:5432/vaovao_intelligence
      REDIS_HOST: redis
      REDIS_PORT: 6379
      CELERY_BROKER_URL: redis://redis:6379/0
    depends_on:
      - postgres
      - redis
    command: celery -A app.tasks worker -l info
    volumes:
      - ./intelligence-backend:/app

  # Celery Beat (Scheduler)
  celery_beat:
    build:
      context: ./intelligence-backend
      dockerfile: Dockerfile
    environment:
      DATABASE_URL: postgresql://postgres:postgres@postgres:5432/vaovao_intelligence
      REDIS_HOST: redis
      REDIS_PORT: 6379
      CELERY_BROKER_URL: redis://redis:6379/0
    depends_on:
      - postgres
      - redis
    command: celery -A app beat -l info
    volumes:
      - ./intelligence-backend:/app

  # Next.js Frontend
  web:
    build:
      context: ./intelligence-web
      dockerfile: Dockerfile
    ports:
      - "3000:3000"
    environment:
      NEXT_PUBLIC_API_URL: http://localhost:8000
    depends_on:
      - api
    command: npm run dev
    volumes:
      - ./intelligence-web:/app

volumes:
  postgres_data:
  redis_data:
```

**Validación:** `docker-compose up` levanta toda la stack

---

## 📊 Testing & Validación

### Unit Tests (Celery Tasks)
**Archivo:** `intelligence-backend/tests/test_tasks.py`

```python
def test_refresh_organization_metrics(monkeypatch):
    """Verifica que el task fetcha datos y los guarda en caché"""
    # Mock Meta API
    # Mock Redis
    # Assert datos en caché
    pass

def test_metrics_broadcast():
    """Verifica que broadcast llega a WebSocket clients"""
    pass
```

### Integration Tests
- Flujo completo: Backend → Redis → Frontend
- WebSocket reconexión
- Error handling (Meta API down)

### Load Testing
```bash
# Simular 100 usuarios actualizando métricas
locust -f tests/load_test.py --host=http://localhost:8000
```

---

## 🚀 Deployment

### Railway
1. Agregar PostgreSQL service
2. Agregar Redis service (ó usar add-on externo)
3. Crear 3 servicios:
   - `api` (FastAPI)
   - `celery-worker` (Celery Worker)
   - `celery-beat` (Scheduler)
4. Env vars:
   - `DATABASE_URL = ${{Postgres.DATABASE_URL}}`
   - `REDIS_HOST = ${{Redis.REDIS_HOST}}` (o externo)
   - `SECRET_KEY = ...` (generate)
   - `META_FETCH_INTERVAL = 30`

---

## ✅ Checklist de Implementación

### FASE 1: Base
- [ ] Dependencias instaladas (Celery, Redis, Socket.io)
- [ ] Redis running locally
- [ ] Celery app configurado
- [ ] Config actualizada (.env vars)

### FASE 2: Workers
- [ ] Tareas Celery escritas
- [ ] Celery Beat scheduler funcionando
- [ ] Meta Ads integration wrapper
- [ ] Worker ejecutando sin errores

### FASE 3: Cache API
- [ ] GET /api/metrics retorna <100ms
- [ ] GET /api/reports/dashboard funciona
- [ ] Health check OK

### FASE 4: WebSocket
- [ ] Socket.io integrado
- [ ] Broadcast desde Celery
- [ ] Clientes reciben updates

### FASE 5: Frontend
- [ ] Socket.io cliente configurado
- [ ] Hook useMetrics funciona
- [ ] Dashboard actualiza sin refresh
- [ ] Status "last updated" visible

### FASE 6: BD
- [ ] Modelo MetricsSnapshot creado
- [ ] Datos persisten en PostgreSQL
- [ ] Índices optimizados

### FASE 7: Docker
- [ ] docker-compose.yml funciona
- [ ] Stack completa levanta con `up`
- [ ] Logs limpios (sin errores)

### FASE 8: Testing & Deploy
- [ ] Tests pasan
- [ ] Deploy a Railway OK
- [ ] Monitoreo en lugar (logs, métricas)

---

## 📈 Métricas de Éxito

- ✅ Dashboard carga en <500ms (desde caché)
- ✅ Updates en vivo llegan en <2s (tras cambio en Meta)
- ✅ Una sola llamada a Meta cada 30s (no por usuario)
- ✅ 0 errores en logs (meta down = graceful degradation)
- ✅ Frontend fluida (sin freezes)
- ✅ Histórico disponible en BD para reportes

---

## 🔧 Troubleshooting

| Problema | Solución |
|----------|----------|
| Celery no conecta a Redis | Verificar `redis-cli ping` |
| WebSocket no actualiza | Revisar logs de Celery broadcast |
| Caché vacío | Revisar que worker esté corriendo |
| Meta API 401 | Token encriptado correctamente? |
| Memory leak en worker | Revisar `task_time_limit` |

---

## 📞 Contacto & Preguntas

Este plan está listo para pasarlo a otro agente. Si hay dudas específicas:
- Arquitectura: Celery + Redis es el core
- Real-time: WebSocket broadcast desde tasks
- Escala: Agregar workers Celery horizontalmente

**Estima:** 3-4 semanas para completar todas las fases (1 dev full-time)

