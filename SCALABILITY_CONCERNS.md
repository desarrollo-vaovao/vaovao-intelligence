# 🚨 Análisis de Escalabilidad & Concurrencia

**Pregunta:** ¿Qué pasa si 10 personas generan reportes simultáneamente?

**Respuesta corta:** Depende. Puede funcionar bien O truena, según el escenario.

---

## 📊 Escenario 1: 10 Personas, 10 Reportes, 10 Clientes DIFERENTES

```
Usuario 1 → Reporte Cliente A
Usuario 2 → Reporte Cliente B
Usuario 3 → Reporte Cliente C
...
Usuario 10 → Reporte Cliente J
```

**¿Truena?** ❌ NO

**Por qué:**
- 10 tasks Celery en la queue
- Cada una lee datos diferentes del caché Redis
- Cada una genera un PDF diferente
- Se guardan en rutas diferentes

**Bottlenecks (en orden):**
1. **CPU** (Playwright genera PDFs) - Es I/O bound, no CPU bound
2. **Memory** (Playwright abierto 10 veces) - ~50MB/proceso = 500MB total
3. **Disk I/O** (escribir 10 PDFs) - Moderno aguanta

**Tolerancia:** Con 4 workers Celery, esto tarda ~10 segundos, sin drama.

---

## 📊 Escenario 2: 10 Personas, 10 Reportes, MISMO Cliente

```
Usuario 1 → Reporte Cliente A
Usuario 2 → Reporte Cliente A
Usuario 3 → Reporte Cliente A
...
Usuario 10 → Reporte Cliente A
```

**¿Truena?** ⚠️ SÍ, es un DESPERDICIO

**El problema:**
- 10 tasks leyendo los MISMOS datos del caché
- Generando 10 PDFs IDÉNTICOS
- 10x trabajo innecesario

**Impacto:**
- 10x tiempo de procesamiento
- 10x memoria (10 Playwright instances)
- 10x disk I/O
- Usuario espera más (notificación llega más tarde)

**Solución:** Deduplicación (ver abajo)

---

## 🔍 Análisis por Componente

### Redis (Caché)
```
Capacidad: 10,000 req/sec sin problema
Tu caso: 10 simultáneas = 0.1% capacidad

✅ No es bottleneck
```

### Celery Workers
```
Default: 1 worker, 4 concurrent tasks

Escenario 1 (diferentes clientes):
└─ 4 tasks procesan en paralelo
   4 tareas esperan
   Total: ~10 segundos

Escenario 2 (mismo cliente):
└─ 4 tasks procesan el MISMO reporte
   Desperdicio de 2.5x
   Total: ~10 segundos (pero trabajo duplicado)

Solución: Agregar más workers o deduplicación
```

### Playwright (Generación PDF)
```
Memory: ~50MB por instancia
CPU: Moderado (rendering HTML)

Escenario con 10 PDFs simultáneos:
├─ Memory: 50MB * 4 (workers) = 200MB ✅
├─ CPU: ~30-40% en servidor
└─ Time: Secuencial (4 at a time) = 2.5x tiempo

Con 8 workers:
├─ Memory: 50MB * 8 = 400MB ✅
├─ CPU: ~60-70%
└─ Time: 10 segundos (casi paralelo)

Limit real: ~16 workers (800MB memory)
```

### Almacenamiento (Disk/S3)
```
Write speed: 10 MB/s (SSD local)
PDF size: ~2-5 MB

10 escrituras: ~25 segundos (secuencial)
                ~3 segundos (paralelo)

✅ No es problema real
```

---

## ✅ Matriz de Tolerancia

| Escenario | Workers | Memory | CPU | Tiempo | Estado |
|-----------|---------|--------|-----|--------|--------|
| 10 usuarios, clientes diferentes | 4 | 200MB | 40% | 10s | ✅ OK |
| 10 usuarios, clientes diferentes | 8 | 400MB | 60% | 5s | ✅ OK |
| 10 usuarios, MISMO cliente (sin dedup) | 4 | 200MB | 40% | 10s | ⚠️ Waste |
| 10 usuarios, MISMO cliente (con dedup) | 4 | 50MB | 10% | 2s | ✅ OK |
| 100 usuarios simultáneos | 4 | 200MB | 40% | 100s | ❌ QUEUE |
| 100 usuarios simultáneos | 16 | 800MB | 80% | 25s | ⚠️ SLOW |

---

## 🛡️ Soluciones (en orden de prioridad)

### 1️⃣ DEDUPLICACIÓN (Prevenir trabajo duplicado)

**Problema:** Mismas personas, mismo reporte → 10 tasks idénticas

**Solución:** Una sola task, múltiples usuarios esperan el resultado

```python
# app/tasks.py

import hashlib
from app.core.cache import redis_client

REPORT_DEDUP_KEY = "report:generating:{report_hash}"
REPORT_RESULT_KEY = "report:result:{report_hash}"

@shared_task(name="generate_report_dedup")
def generate_report_dedup(report_type, org_id, client_ids, format):
    """
    Genera reporte con deduplicación.
    Si otro usuario ya está generando el MISMO reporte, 
    solo espera el resultado.
    """
    
    # 1. Crear hash del reporte (parámetros)
    report_params = f"{report_type}:{org_id}:{client_ids}:{format}"
    report_hash = hashlib.md5(report_params.encode()).hexdigest()
    
    dedup_key = f"report:generating:{report_hash}"
    result_key = f"report:result:{report_hash}"
    
    # 2. ¿Alguien ya lo está generando?
    if redis_client.exists(dedup_key):
        # SÍ → esperar resultado (max 60 segundos)
        result = None
        for i in range(60):
            result = redis_client.get(result_key)
            if result:
                return json.loads(result)  # Retornar reporte ya generado
            time.sleep(1)
        
        raise Exception("Timeout esperando reporte dedup")
    
    # 3. NO → comenzar generación
    redis_client.setex(dedup_key, 60, "generating")
    
    try:
        # Generar reporte (código normal)
        metrics = get_cached_metrics(org_id)
        pdf_path = _generate_pdf(metrics, report_hash)
        file_url = _upload_to_storage(pdf_path, org_id, report_hash)
        
        result = {
            "report_hash": report_hash,
            "file_url": file_url,
            "generated_at": datetime.utcnow().isoformat()
        }
        
        # 4. Guardar resultado para otros que esperan
        redis_client.setex(result_key, 3600, json.dumps(result))  # Cache 1 hora
        
        return result
        
    finally:
        redis_client.delete(dedup_key)
```

**Impacto:**
- Escenario 2 (10 usuarios mismo cliente):
  - Sin dedup: 10 tasks, 10 PDFs, 10 segundos, 500MB memoria
  - Con dedup: 1 task, 1 PDF, 2 segundos, 50MB memoria

---

### 2️⃣ RATE LIMITING (Limitar req por usuario)

**Problema:** Un usuario genera 50 reportes sin parar

**Solución:** Max X reportes por usuario por minuto

```python
# app/api/routes/reports.py

from fastapi import HTTPException
from app.core.cache import redis_client

@router.post("/generate")
async def create_report(
    report_type: str,
    format: str,
    current_user: User = Depends(get_current_user)
):
    """Crea reporte con rate limiting"""
    
    # Rate limit: 5 reportes por usuario por minuto
    rate_limit_key = f"report:rate_limit:{current_user.id}"
    current_count = redis_client.incr(rate_limit_key)
    
    if current_count == 1:
        redis_client.expire(rate_limit_key, 60)  # Reset en 60s
    
    if current_count > 5:
        raise HTTPException(
            status_code=429,
            detail="Demasiados reportes. Max 5 por minuto."
        )
    
    # Crear reporte (código normal)
    ...
```

**Impacto:**
- Previene DoS accidental
- Usuario malintencionado no puede sobrecargar

---

### 3️⃣ QUEUE PRIORITIZATION (Reportes prioritarios)

**Problema:** 100 usuarios en queue esperan, algunos urgentes

**Solución:** Prioridades en Celery

```python
# app/tasks.py

@shared_task(name="generate_pdf_report", priority=5)
def generate_pdf_report(report_id):
    # Priority: 1 (bajo) a 10 (alto)
    pass

# En API, usuario choose prioridad:

@router.post("/generate")
async def create_report(
    ...,
    priority: int = Query(5, ge=1, le=10)  # Default: medio
):
    # Reportes urgentes (priority=10) se generan primero
    generate_pdf_report.apply_async(
        args=[report_id],
        priority=priority
    )
```

**Impacto:**
- Usuarios premium/urgentes no esperan a otros

---

### 4️⃣ HORIZONTAL SCALING (Más workers)

**Problema:** Max 4 workers → cola de espera

**Solución:** Agregar más workers Celery

```bash
# En Docker/Kubernetes, agregar replicas:

# docker-compose.yml
celery_worker_1:
  image: ...
  command: celery -A app.tasks worker -l info

celery_worker_2:
  image: ...
  command: celery -A app.tasks worker -l info
  
celery_worker_3:
  image: ...
  command: celery -A app.tasks worker -l info
  
celery_worker_4:
  image: ...
  command: celery -A app.tasks worker -l info
```

**Costo:**
- Memory: 50MB * 4 = 200MB extra
- CPU: Moderado
- Cost: ~$10-20/mes en Railway

**Impacto:**
- 10 usuarios simultáneos: De 10s → 2.5s
- 100 usuarios: De 100s → 25s

---

### 5️⃣ CACHÉ DE REPORTES GENERADOS (Reuse)

**Problema:** Mismo reporte pedido 100 veces = 100 generaciones

**Solución:** Guardar reportes + servir desde caché

```python
# app/tasks.py

# Si el reporte se pidió en últimas 2 horas Y los datos no cambiaron
# → Reutilizar archivo en lugar de regenerar

REPORT_CACHE_KEY = "report:cache:{report_hash}"

def generate_report_cached(report_params):
    report_hash = hashlib.md5(report_params).hexdigest()
    
    # ¿Ya existe en caché?
    cached_url = redis_client.get(f"report:cache:{report_hash}")
    if cached_url:
        return {"file_url": cached_url, "source": "cache"}  # Instant
    
    # NO → generar y cachear
    file_url = _generate_and_store(...)
    redis_client.setex(
        f"report:cache:{report_hash}",
        3600,  # 1 hora
        file_url
    )
    
    return {"file_url": file_url, "source": "generated"}
```

**Impacto:**
- Mismos reportes: Retorna en <100ms (sin Playwright)
- 100 requests idénticos: 1 generación + 99 caché

---

## 📈 Recomendación de Implementación

### Fase 1: MVP (Ahora)
```
✅ Básico funciona
⚠️ Sin deduplicación
⚠️ Sin rate limiting
⚠️ 4 workers Celery
```

**Soporta:** Hasta 50 usuarios simultáneos (diferentes reportes)

### Fase 2: Optimización (Semana 2-3)
```
✅ Deduplicación de tareas
✅ Rate limiting
✅ 8-12 workers Celery
```

**Soporta:** Hasta 500 usuarios simultáneos

### Fase 3: Escala (Semana 4+)
```
✅ Caché de reportes
✅ Prioridades Celery
✅ 16+ workers (Kubernetes)
✅ S3 con CloudFront CDN
```

**Soporta:** 5000+ usuarios simultáneos

---

## 🧪 Test de Carga Local

```bash
# Instalar locust
pip install locust

# load_test.py
from locust import HttpUser, task, between

class ReportUser(HttpUser):
    wait_time = between(5, 10)
    
    @task
    def generate_report(self):
        self.client.post("/api/reports/generate", json={
            "report_type": "dashboard",
            "format": "pdf"
        })

# Ejecutar
locust -f load_test.py --host=http://localhost:8000 -u 100 -r 10

# Simula 100 usuarios, 10 nuevos/segundo
# Ver: http://localhost:8089
```

---

## 📊 Monitoreo en Producción

```python
# app/monitoring.py

from prometheus_client import Counter, Histogram, Gauge

# Metrics
reports_generated = Counter(
    'reports_generated_total',
    'Total reports generated',
    ['report_type', 'format']
)

report_generation_time = Histogram(
    'report_generation_seconds',
    'Time to generate report',
    buckets=(1, 5, 10, 30, 60)
)

celery_queue_size = Gauge(
    'celery_queue_size',
    'Number of tasks in queue'
)

celery_active_tasks = Gauge(
    'celery_active_tasks',
    'Number of active tasks'
)

# En tasks.py
@shared_task
def generate_pdf_report(report_id):
    start = time.time()
    try:
        # ... código ...
        reports_generated.labels(
            report_type="dashboard",
            format="pdf"
        ).inc()
    finally:
        duration = time.time() - start
        report_generation_time.observe(duration)
```

**Alertas recomendadas:**
- ⚠️ Cola Celery > 100 tasks → Agregar workers
- ⚠️ Tiempo reporte > 30s → Investigar
- ⚠️ Error rate > 5% → Escalada

---

## 🎯 Respuesta Final

**Pregunta:** ¿10 personas, 10 reportes, truena?

**Respuesta:**

| Caso | ¿Truena? | Solución |
|------|----------|----------|
| 10 clientes diferentes | ❌ NO | Nada, funciona |
| 10 mismo cliente | ⚠️ Desperdicio | Agregar Deduplicación |
| 100 usuarios | ⚠️ Lento | Agregar workers + dedup |
| 1000 usuarios | ❌ SÍ | Escala horizontal + caché |

**Plan:**
1. Implementar MVP (Phase 1) ahora
2. Si usuarios > 50 → Agregar deduplicación
3. Si usuarios > 500 → Escala horizontal

**Máxima recomendación:** Empezar simple, monitorear, escalar cuando sea necesario.

