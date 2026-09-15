# 🚨 Escenario Extremo: 1000 Usuarios, 1000 Reportes Diferentes

**Pregunta:** 1000 usuarios simultáneos generando 1000 reportes de 1000 clientes diferentes.
**Respuesta:** ❌ **TRUENA** sin cambios arquitectónicos.

---

## 📊 Análisis de Bottlenecks

### 1. **Celery Workers** ⚠️ CRÍTICO

```
Current setup: 4 workers

1000 tasks llegan
├─ 4 procesan en paralelo
├─ 996 esperan en la queue
└─ Tiempo total: 1000 / 4 = 250 iterations × 2s = ~500 segundos (8+ minutos)

Usuario espera: 8+ minutos ❌
```

**Solución:** Escalar workers → 128 workers
```
128 workers (en Kubernetes)
├─ 128 procesan en paralelo
├─ 872 esperan
└─ Tiempo total: 1000 / 128 = 8 iterations × 2s = ~16 segundos

Usuario espera: 16 segundos ✅
```

**Cost:** 128 workers × $0.05/worker/hora = $6.40/hora (AWS)

---

### 2. **Playwright (Generación PDF)** ⚠️ MUY CRITICO

```
Recurso: Memory
└─ Playwright instance: ~50-100MB por proceso
   128 workers × 100MB = 12.8 GB

Recurso: CPU
└─ Rendering HTML: CPU-bound
   128 instancias simultáneas = 1280% CPU (12.8 cores)

Recurso: File Descriptors
└─ Chromium abre muchos fds
   128 × 50 fds = 6400 fds (limit typical: 1024)
```

**El VERDADERO problema:** Playwright NO es escalable horizontalmente

**Soluciones:**
1. Cambiar de Playwright a headless Chrome API (más eficiente)
2. Usar servicio externo (CloudConvert, AWS Lambda)
3. Pre-generar reportes en background (no on-demand)

---

### 3. **Redis (Caché)** ✅ Probablemente OK

```
Capacidad: 50,000 req/sec típicamente
Tu caso: 1000 reads simultáneos = 2% capacidad

Pero: Cada read es datos grande (metrics)
└─ Network I/O: ~100KB × 1000 = 100MB/sec
└─ Redis típicamente aguanta ~500MB/sec

✅ Redis no es bottleneck
```

---

### 4. **PostgreSQL (BD)** ⚠️ CRITICO

```
Escribe histórico de cada reporte generado

1000 reports × 5 inserts (por cuenta publicitaria) = 5000 writes

Capacidad: 1000 writes/sec típicamente

Problema: Indexes, locks, autovacuum
└─ Con picos de 5000 writes → Contenedor
└─ Otros queries se vuelven lentos
```

---

### 5. **Storage (Disk/S3)** ⚠️ CRITICO

```
Write Speed:
├─ Local SSD: ~500 MB/sec (secuencial), ~50MB/sec (random)
├─ S3: ~100 uploads/sec (con rate limiting)

1000 PDFs simultáneos:
├─ Size: 2-5MB promedio = 2-5GB total
├─ Time (local): 2-5GB / 50MB/sec = 40-100 segundos
└─ Time (S3): Timeout si intentas subir todo simultáneo

❌ S3 rate limiting será problema
```

**Solución:** Async uploads a S3, no sincrónico

---

## 🔴 Puntos de Quiebre (en orden)

```
Capacidad    | Bottleneck              | Síntoma
-------------|-------------------------|-----------------------------
   10 users  | Ninguno                 | ✅ Fluye normal
  100 users  | Celery workers          | ⚠️ Cola larga
  500 users  | Playwright memory       | ⚠️ OOM (Out of Memory)
 1000 users  | Playwright + S3 + Disk  | ❌ CRASH total
 5000 users  | Todo                    | ❌ Impossible sin redesign
```

---

## 🏗️ Arquitectura Actual (Limitaciones)

```
Limitante: Generar PDF on-demand es SÍNCRONO

User Request
    ↓
POST /api/reports/generate
    ↓
Celery Worker
    ├─ Read Redis (fast)
    ├─ Playwright (SLOW + MEMORY)
    ├─ Write S3 (SLOW + RATE LIMITED)
    └─ Notificar WebSocket
    ↓
User espera...
```

**Problema:** Playwright es bottleneck real, no Redis/Caché

---

## ✅ Soluciones Arquitectónicas

### Opción 1: Microservicio de PDF Separado (Recomendado)

**Idea:** Generar PDFs en máquina dedicada

```
Arquitectura:

Frontend + API (Python/FastAPI)
    ↓
Redis Queue
    ↓
PDF Microservice (Node.js Puppeteer cluster)
    │
    ├─ 8 CPUs dedicadas
    ├─ 16GB RAM
    ├─ Puppeteer cluster (8 instances)
    ├─ PDF generation optimizada
    └─ S3 upload (buffered, no concurrent)
```

**Código:**

```javascript
// pdf-service/worker.js (Node.js Puppeteer cluster)

const Cluster = require('puppeteer-cluster');

const cluster = new Cluster({
  concurrency: Cluster.CONCURRENCY_CONTEXT,
  maxConcurrency: 8,  // 8 concurrent browsers
  puppeteerOptions: {
    headless: true,
    args: ['--no-sandbox']
  }
});

cluster.task(async ({ page, data: { html, reportId } }) => {
  await page.setContent(html);
  const pdf = await page.pdf({ 
    format: 'A4',
    margin: { top: 20, right: 20, bottom: 20, left: 20 }
  });
  
  // Upload a S3
  await uploadToS3(pdf, reportId);
  
  // Notificar API
  await notifyApiReportReady(reportId);
});

// Queue de reportes
await cluster.queue(reportData1);
await cluster.queue(reportData2);
// ... 1000 reports queued pero solo 8 procesando en paralelo
```

**Ventajas:**
- Generar 1000 PDFs sin bloquear API
- Optimizado para Playwright
- Escalable horizontalmente
- API responde inmediato

**Cost:** +$50-100/mes (máquina dedicada)

---

### Opción 2: AWS Lambda para PDF (Serverless)

**Idea:** Usar AWS Lambda para generar PDFs

```
Frontend + API
    ↓
SQS Queue
    ↓
Lambda (PDF generation)
├─ Auto-scales 0 → 1000 concurrent
├─ Pre-built PDF layer
├─ Direct S3 upload
└─ No server management
```

**Ventajas:**
- Escala automática
- Pay per use (~$0.0000002 per invocation)
- No mantenimiento

**Desventaja:**
- 15 minuto timeout por Lambda
- Costo escala rápido si muchos reportes

---

### Opción 3: Pre-generar Reportes (Mejor UX)

**Idea:** No generar on-demand, sino en background

```
Diario (3am UTC):
├─ Celery beat task: "generate_daily_reports"
├─ Recorre todas las orgs
├─ Genera PDFs para cada cliente
├─ Almacena en S3
└─ Usuario: "Descargar" → Retorna archivo pre-generado (50ms)

Usuario solicita reporte:
├─ Si existe: Descarga inmediato ✅
├─ Si no: Queue para generar (notificación en 2-5 min)
└─ Mejor UX que esperar
```

**Ventajas:**
- 99% de descargas son instant
- Distribuye carga
- Menor CPU/Memory en picos

**Desventaja:**
- Requiere predicción de qué reportes pedir

---

### Opción 4: Cambiar Formato (más rápido)

**Idea:** En lugar de PDF (lento), generar HTML + download como PDF en browser

```
Opción A: PDF backend
├─ Tiempo: 2-5 segundos
├─ Formato: Controlado
└─ Uso: Download

Opción B: HTML + Browser download (PDF)
├─ Tiempo: <500ms backend
├─ Formato: Depende del navegador
└─ Uso: Preview + Download

Opción C: Excel (más rápido que PDF)
├─ Tiempo: <1 segundo
├─ Formato: Excel nativo
└─ Uso: Datos crudos
```

**Cambiar a Excel:**
```python
# 1000 usuarios → Excel es 10x más rápido
# Tarda ~1 segundo en lugar de 3-5

generate_excel_report.delay(report_id)  # Ultra rápido
```

---

## 🚀 Plan de Escalabilidad Realista

### **Tier 1: Actual (hasta 100 usuarios)**
```
✅ MVP funciona
- 4 workers Celery
- Playwright local
- Storage local
- Soporta: 100 usuarios simultáneos
```

### **Tier 2: Optimization (100-500 usuarios)**
```
✅ Agregar capacidad
- 16 workers Celery
- Excel en lugar de PDF (10x más rápido)
- S3 con CloudFront CDN
- Deduplicación + rate limiting
- Soporta: 500 usuarios
```

### **Tier 3: Scale (500-1000+ usuarios)**
```
✅ Cambio arquitectónico
- PDF Microservice (Node.js cluster) separado
- S3 + CDN + regional caching
- Pre-generate reportes
- Kafka/Redis streams para eventos
- Soporta: 5000+ usuarios
```

---

## 💰 Cost Analysis: 1000 Usuarios Simultáneos

### **Option A: Keep Python (Horizontal Scale)**
```
128 Celery workers @ $0.05/hr = $6.40/hr
PostgreSQL upgrade = $2/hr
S3 storage = $100/month
CDN = $200/month
Total: ~$300-400/month
```
❌ Expensive, still limited

### **Option B: PDF Microservice + Python**
```
API servers (2x) = $1/hr
PDF microservice (1x 8-CPU) = $0.50/hr
PostgreSQL = $1/hr
S3 + CDN = $300/month
Total: ~$800/month
```
✅ Better, scalable

### **Option C: Lambda + Serverless**
```
PDF Lambdas (5M invocations/month) = $1000
API Lambdas = $200
S3 + CDN = $300
Database (managed) = $500
Total: ~$2000/month
```
✅ Scalable but expensive

### **Option D: Pre-generate Reports**
```
Same as Option B but:
└─ Generación off-peak (cheaper compute)
└─ S3 storage (reportes pre-generados)
Total: ~$500/month
```
✅ Most cost-effective

---

## 📊 Comparativa de Soluciones

| Solución | Setup | Scalability | Cost | Performance | Recomendación |
|----------|-------|-------------|------|-------------|--|
| Horizontal (128 workers) | ⭐ Simple | ⭐ Medio | ⭐⭐⭐ Alto | ⭐ OK | MVP |
| PDF Microservice | ⭐⭐ Moderado | ⭐⭐⭐ Alto | ⭐⭐ Medio | ⭐⭐⭐ Excelente | Production |
| Lambda | ⭐⭐⭐ Complejo | ⭐⭐⭐ Alto | ⭐ Muy alto | ⭐⭐ Bueno | No recomendado |
| Pre-generate | ⭐⭐ Moderado | ⭐⭐⭐ Alto | ⭐⭐ Bajo | ⭐⭐⭐ Excelente | Mejor UX |

---

## 🛠️ Implementación: PDF Microservice

**Paso 1: Crear servicio Node.js**

```bash
# pdf-service/package.json
{
  "name": "pdf-generation-service",
  "dependencies": {
    "puppeteer": "^21.0.0",
    "puppeteer-cluster": "^0.23.0",
    "redis": "^4.0.0",
    "aws-sdk": "^2.0.0"
  }
}
```

**Paso 2: Worker con Cluster**

```javascript
// pdf-service/worker.js

const Cluster = require('puppeteer-cluster');
const redis = require('redis');
const AWS = require('aws-sdk');

const client = redis.createClient({
  host: process.env.REDIS_HOST,
  port: process.env.REDIS_PORT
});

const s3 = new AWS.S3();

(async () => {
  const cluster = await Cluster.launch({
    concurrency: 8,
    maxConcurrency: 8,
    puppeteerOptions: {
      headless: 'new',
      args: ['--no-sandbox', '--disable-setuid-sandbox']
    }
  });

  cluster.task(async ({ page, data }) => {
    try {
      const { reportId, html, orgId } = data;
      
      console.log(`📄 Generando PDF: ${reportId}`);
      
      // Renderizar HTML
      await page.setContent(html, { waitUntil: 'networkidle2' });
      
      // Generar PDF
      const pdf = await page.pdf({
        format: 'A4',
        margin: { top: 20, right: 20, bottom: 20, left: 20 },
        printBackground: true
      });
      
      console.log(`📤 Subiendo a S3: ${reportId}`);
      
      // Upload a S3 (buffered, no concurrent)
      const key = `reports/${orgId}/${reportId}.pdf`;
      await s3.putObject({
        Bucket: process.env.S3_BUCKET,
        Key: key,
        Body: pdf,
        ContentType: 'application/pdf'
      }).promise();
      
      const fileUrl = `https://${process.env.S3_BUCKET}.s3.amazonaws.com/${key}`;
      
      console.log(`✅ Reporte listo: ${fileUrl}`);
      
      // Notificar API
      await fetch(`${process.env.API_URL}/api/reports/${reportId}/mark-ready`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_url: fileUrl })
      });
      
      // Broadcast WebSocket
      await client.publish(`report:${orgId}`, JSON.stringify({
        event: 'report_ready',
        report_id: reportId,
        file_url: fileUrl
      }));
      
    } catch (error) {
      console.error(`❌ Error en ${data.reportId}:`, error);
      // Notificar error a API
    }
  });

  // Escuchar queue de Redis
  const subscriber = redis.createClient({
    host: process.env.REDIS_HOST,
    port: process.env.REDIS_PORT
  });

  subscriber.subscribe('pdf:queue', (err, count) => {
    if (err) console.error('Subscription error:', err);
  });

  subscriber.on('message', async (channel, message) => {
    if (channel === 'pdf:queue') {
      const reportData = JSON.parse(message);
      await cluster.queue(reportData);
      console.log(`📋 Report queued: ${reportData.reportId}`);
    }
  });

  console.log('🚀 PDF Service listening...');
})();
```

**Paso 3: API integrarse**

```python
# app/tasks.py

@shared_task(name="queue_pdf_generation")
def queue_pdf_generation(report_id: str, html: str):
    """
    En lugar de generar PDF aquí, enviar a microservicio
    """
    import json
    from app.core.cache import redis_client
    
    message = {
        "reportId": report_id,
        "html": html,
        "orgId": "...",
        "timestamp": datetime.utcnow().isoformat()
    }
    
    # Publicar en queue (no esperar respuesta)
    redis_client.publish("pdf:queue", json.dumps(message))
    
    return {"status": "queued", "report_id": report_id}
```

---

## 📈 Resultados Esperados

### Con PDF Microservice (8 concurrent workers):

```
1000 usuarios, 1000 reportes diferentes

Generación:
├─ 8 Playwright instances
├─ 1000 tasks en queue
├─ Todos generados en: 1000 / 8 = 125 iterations × 3s = ~6-7 minutos
├─ Primeiro reporte ready: ~3 segundos
└─ Último reporte: ~7 minutos

Usuario experience:
├─ API responde: <100ms ✅
├─ Notificación en: 3-7 minutos
└─ Descarga: <100ms (desde S3)
```

**Ventaja:** No hay "waiting time" en frontend, solo notificación cuando listo

---

## 🎯 Recomendación Final

**Para 1000 usuarios simultáneos:**

1. **No intentes** con Playwright + 128 workers local
   - OOM, timeouts, problemas de file descriptors

2. **Implementa** PDF Microservice (Node.js cluster)
   - Arquitectura proven
   - Escalable
   - Cost-effective

3. **Considera** pre-generate reportes
   - Mejor UX
   - Menor cost
   - Off-peak processing

4. **Monitorizá** continuamente
   - Queue length
   - Generation time
   - Error rate

---

## 🧪 Test Antes de Producción

```bash
# Load test con 1000 usuarios
locust -f load_test.py --host=http://localhost:8000 -u 1000 -r 50

# Monitorear:
# - Queue length en Redis
# - Memory usage en workers
# - Generation time (p50, p95, p99)
# - Error rate
# - S3 upload latency
```

---

## 📝 Checklist para 1000 Users

- [ ] Implementar PDF Microservice
- [ ] Queue buffering en Redis
- [ ] S3 con regional endpoints
- [ ] CloudFront CDN
- [ ] Pre-generate daily reports
- [ ] Monitoreo (Prometheus/CloudWatch)
- [ ] Alertas (queue > 500, error rate > 5%)
- [ ] Rate limiting por user
- [ ] Horizontal pod autoscaling (K8s)
- [ ] Load testing completado

