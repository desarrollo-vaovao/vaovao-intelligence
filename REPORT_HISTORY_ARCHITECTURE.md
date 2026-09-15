# 📚 Arquitectura Optimizada: Historial de Reportes

**Idea:** En lugar de generar reportes on-demand, guardar un historial. Usuarios descargan del historial sin regenerar.

**Beneficio:** Soporta millones de descargas simultáneas sin carga adicional.

---

## 🎯 Concepto

```
Usuario 1 (3pm):
  └─ "Generar reporte Cliente A"
     ├─ Genera PDF (2-3 seg)
     ├─ Guarda en BD: Report {id, client_id, date, file_url, created_at}
     └─ Guarda en S3: /reports/client-a/2025-09-15.pdf

Usuario 2 (3:01pm):
  └─ "Descargar reporte Cliente A"
     ├─ Busca en BD: "¿Existe reporte de hoy?"
     ├─ SÍ → Retorna URL de S3
     └─ Descarga (instant, desde CloudFront caché)
     ❌ NO regenera

Usuario 100,000 (5pm):
  └─ Descargan el MISMO reporte
     └─ Del caché CloudFront (1 reporte → N descargas)
```

---

## 📊 Modelo de BD

```python
# app/models/__init__.py

class ReportHistory(Base):
    __tablename__ = "report_history"
    
    id = Column(String, primary_key=True)
    organization_id = Column(String, ForeignKey("organization.id"))
    client_id = Column(String, ForeignKey("client.id"))
    
    # Tipo de reporte
    report_type = Column(String)  # "dashboard", "performance", etc
    format = Column(String)  # "pdf", "excel"
    
    # Metadata
    report_date = Column(DateTime)  # Día del reporte (ej: 2025-09-15)
    date_from = Column(DateTime)  # Rango de datos (ej: 30 días atrás)
    date_to = Column(DateTime)
    
    # Storage
    file_url = Column(String)  # S3 URL
    file_size = Column(Integer)
    
    # Tracking
    created_at = Column(DateTime, default=datetime.utcnow)
    downloaded_count = Column(Integer, default=0)  # Analytics
    
    # Refresh
    last_refreshed = Column(DateTime)  # Cuándo se regeneró por última vez
    refresh_needed = Column(Boolean, default=False)  # Si datos están "stale"
    
    # Index para búsqueda rápida
    __table_args__ = (
        Index('idx_client_date', 'client_id', 'report_date'),
        Index('idx_org_client', 'organization_id', 'client_id'),
    )
```

---

## 🔄 Flujo Simplificado

### **Caso 1: Generar Reporte (Primera Vez)**

```python
@router.post("/api/reports/generate")
async def generate_report(
    client_id: str,
    report_type: str = "dashboard",
    current_user: User = Depends(get_current_user)
):
    """Generar y guardar en historial"""
    
    db = SessionLocal()
    
    # 1. ¿Existe reporte de hoy para este cliente?
    today = datetime.now().date()
    existing = db.query(ReportHistory).filter(
        ReportHistory.client_id == client_id,
        ReportHistory.report_date == today,
        ReportHistory.report_type == report_type
    ).first()
    
    if existing:
        # ✅ Retornar el que ya existe (instant)
        return {
            "report_id": existing.id,
            "file_url": existing.file_url,
            "status": "cached",
            "message": "Reporte de hoy ya disponible",
            "generated_at": existing.created_at
        }
    
    # 2. NO EXISTE → Generar
    report = ReportHistory(
        id=str(uuid4()),
        organization_id=current_user.organization_id,
        client_id=client_id,
        report_type=report_type,
        report_date=today,
        date_from=today - timedelta(days=30),
        date_to=today
    )
    db.add(report)
    db.commit()
    
    # 3. Trigger Celery task (genera en background)
    generate_and_store_report.delay(report.id)
    
    # 4. Retornar INMEDIATO
    return {
        "report_id": report.id,
        "status": "generating",
        "message": "Reporte se está generando. Te avisaremos en 2-3 min.",
        "file_url": None  # Aún no está listo
    }
```

### **Caso 2: Descargar Reporte (Ya Existe)**

```python
@router.get("/api/reports/{report_id}/download")
async def download_report(
    report_id: str,
    current_user: User = Depends(get_current_user)
):
    """Descargar reporte del historial"""
    
    db = SessionLocal()
    
    report = db.query(ReportHistory).filter(
        ReportHistory.id == report_id,
        ReportHistory.organization_id == current_user.organization_id
    ).first()
    
    if not report:
        raise HTTPException(404, "Reporte no encontrado")
    
    if not report.file_url:
        raise HTTPException(400, "Reporte aún se está generando")
    
    # Incrementar contador (analytics)
    report.downloaded_count += 1
    db.commit()
    
    # Retornar archivo (CloudFront sirve desde caché)
    return {
        "file_url": report.file_url,  # Redirect a S3/CloudFront
        "size": report.file_size,
        "created_at": report.created_at,
        "downloaded": report.downloaded_count
    }
```

### **Caso 3: Listar Historial**

```python
@router.get("/api/clients/{client_id}/reports/history")
async def get_report_history(
    client_id: str,
    limit: int = 30,
    current_user: User = Depends(get_current_user)
):
    """Listar últimos N reportes de un cliente"""
    
    db = SessionLocal()
    
    reports = db.query(ReportHistory).filter(
        ReportHistory.client_id == client_id,
        ReportHistory.organization_id == current_user.organization_id
    ).order_by(ReportHistory.report_date.desc()).limit(limit).all()
    
    return [
        {
            "report_id": r.id,
            "date": r.report_date,
            "format": r.format,
            "size": r.file_size,
            "downloads": r.downloaded_count,
            "file_url": r.file_url,
            "status": "ready" if r.file_url else "generating"
        }
        for r in reports
    ]
```

---

## 📈 Ventajas de Este Enfoque

### **1. Soporta Millones de Descargas**

```
Escenario: 100,000 usuarios descargan el mismo reporte

Flujo:
├─ Usuario 1: Genera → 3 segundos (escrito a BD/S3)
├─ Usuario 2-100,000: Descargan → <100ms cada uno
│                                  (del caché CloudFront)
└─ Carga en servidor: Mínima

Result:
├─ Bandwidth: Servido desde CloudFront (gratis)
├─ CPU: 0% (caché)
├─ Database: 0 writes (solo lectura de URL)
└─ Cost: ~$0 adicional
```

### **2. Deduplicación Automática**

```
Sin historial:
├─ User A genera reporte (3seg)
├─ User B genera reporte (3seg) ← Duplicado
├─ User C genera reporte (3seg) ← Duplicado
└─ Costo: 3 × 3seg = 9 segundos + 3 PDFs

Con historial:
├─ User A genera reporte (3seg) ✅
├─ User B descarga del historial (<100ms) ✅
├─ User C descarga del historial (<100ms) ✅
└─ Costo: 1 × 3seg = 3 segundos + 1 PDF
```

### **3. Análisis de Uso**

```python
# Qué reportes descarga más la gente
reports = db.query(ReportHistory).order_by(
    ReportHistory.downloaded_count.desc()
).limit(10).all()

# Cuál es el tamaño típico
avg_size = db.query(func.avg(ReportHistory.file_size)).scalar()

# Cuándo descargan reportes
download_by_hour = db.query(
    func.hour(ReportHistory.created_at),
    func.count(ReportHistory.id)
).group_by(func.hour(ReportHistory.created_at)).all()
```

### **4. Limpieza Automática**

```python
# Eliminar reportes viejos (> 90 días)
@celery.task
def cleanup_old_reports():
    cutoff = datetime.now() - timedelta(days=90)
    
    old_reports = db.query(ReportHistory).filter(
        ReportHistory.created_at < cutoff
    ).all()
    
    for report in old_reports:
        # Borrar de S3
        s3.delete_object(Bucket=bucket, Key=report.file_url)
        
        # Borrar de BD
        db.delete(report)
    
    db.commit()
```

---

## 🔄 Refresh Automático

### **Opción A: Refresh Diario**

```python
# Celery beat task: ejecuta cada día a las 4am
@celery.task
def refresh_daily_reports():
    """Regenera reportes del día anterior"""
    
    yesterday = datetime.now().date() - timedelta(days=1)
    
    # Encontrar todos los reportes de ayer que fueron descargados
    popular_reports = db.query(ReportHistory).filter(
        ReportHistory.report_date == yesterday,
        ReportHistory.downloaded_count > 10  # Solo populares
    ).all()
    
    for report in popular_reports:
        # Regenerar (datos ahora completos)
        generate_and_store_report.delay(report.id, refresh=True)
```

### **Opción B: Refresh On-Demand**

```python
# Usuario puede solicitar versión más fresca
@router.post("/api/reports/{report_id}/refresh")
async def refresh_report(
    report_id: str,
    current_user: User = Depends(get_current_user)
):
    """Regenerar reporte con datos más frescos"""
    
    report = db.query(ReportHistory).filter(
        ReportHistory.id == report_id
    ).first()
    
    if not report:
        raise HTTPException(404)
    
    # Trigger refresh
    generate_and_store_report.delay(report.id, refresh=True)
    
    return {
        "report_id": report.id,
        "status": "refreshing",
        "message": "Reporte se está actualizar con datos frescos"
    }
```

---

## 💾 Storage Strategy

### **S3 Path Structure**

```
s3://vaovao-reports/
├── {org_id}/
│   ├── {client_id}/
│   │   ├── 2025-09-15_dashboard.pdf
│   │   ├── 2025-09-15_performance.pdf
│   │   ├── 2025-09-14_dashboard.pdf
│   │   └── ...
│   └── {client_id}/
│       └── ...
└── {org_id}/
    └── ...
```

### **CloudFront CDN**

```
Distribución CloudFront:
├─ Origin: S3 bucket
├─ TTL: 24 horas (reportes no cambian en el día)
├─ Caching: Aggressive
└─ Cost: ~$0.085 per GB served (muy barato)

Resultado:
├─ Primera descarga: 3-5 seg (desde S3)
├─ Subsecuentes: <100ms (desde edge location)
└─ 100,000 descargas = ~$8.50 en CDN
```

---

## 📊 Escalabilidad vs Original

| Métrica | Generar On-Demand | Con Historial | Mejora |
|---------|-------------------|---------------|--------|
| 1000 usuarios, mismo reporte | 1000 × 3seg = 50min | 1 × 3seg = 3seg | **16x** |
| 100K descargas | 100K × 3seg | 1 × 3seg + cache | **Infinite** |
| CPU en picos | 80% | <5% | **16x** |
| Bandwidth | 1000 × 5MB = 5GB | 1 × 5MB + CDN | **100x** |
| Database writes | 1000 writes/sec | 1 write/day | **Infinite** |
| Cost | $50+/mes | $5-10/mes | **5-10x cheaper** |

---

## 🔧 Implementación Mínima

### **Paso 1: Migración de BD**

```python
# Agregar tabla a models
class ReportHistory(Base):
    __tablename__ = "report_history"
    
    id = Column(String, primary_key=True)
    client_id = Column(String, ForeignKey("client.id"))
    report_date = Column(DateTime)
    file_url = Column(String)
    downloaded_count = Column(Integer, default=0)
    
    # ... (resto de campos)
```

### **Paso 2: Task Celery Actualizada**

```python
@shared_task
def generate_and_store_report(report_id: str, refresh: bool = False):
    """Genera y guarda en historial"""
    
    db = SessionLocal()
    report = db.query(ReportHistory).filter(
        ReportHistory.id == report_id
    ).first()
    
    # Generar PDF desde caché
    pdf = generate_pdf(report)
    
    # Subir a S3
    s3_key = f"{report.organization_id}/{report.client_id}/{report.report_date}.pdf"
    s3_url = upload_to_s3(pdf, s3_key)
    
    # Guardar en BD
    report.file_url = s3_url
    report.file_size = len(pdf)
    report.last_refreshed = datetime.utcnow()
    db.commit()
    
    # Notificar vía WebSocket
    await broadcast_report_ready(report.organization_id, report.id)
```

### **Paso 3: Cleanup Automático**

```python
# En config beat schedule
celery_app.conf.beat_schedule = {
    'cleanup-reports': {
        'task': 'app.tasks.cleanup_old_reports',
        'schedule': crontab(hour=2, minute=0),  # 2am diario
    },
    'refresh-popular-reports': {
        'task': 'app.tasks.refresh_daily_reports',
        'schedule': crontab(hour=4, minute=0),  # 4am diario
    },
}
```

---

## 📱 Frontend - Historial

```javascript
// components/ReportHistory.jsx

export default function ReportHistory({ clientId }) {
  const [reports, setReports] = useState([]);
  
  useEffect(() => {
    // Cargar historial
    fetch(`/api/clients/${clientId}/reports/history`)
      .then(r => r.json())
      .then(setReports);
  }, [clientId]);
  
  return (
    <div className="report-history">
      <h2>Historial de Reportes</h2>
      
      {reports.map(report => (
        <div key={report.report_id} className="report-item">
          <span>{report.date.toLocaleDateString()}</span>
          <span>{report.format.toUpperCase()}</span>
          <span>{report.downloads} descargas</span>
          
          {report.status === 'ready' ? (
            <>
              <a href={report.file_url}>Descargar</a>
              <button onClick={() => refreshReport(report.report_id)}>
                🔄 Actualizar
              </button>
            </>
          ) : (
            <span>Generando...</span>
          )}
        </div>
      ))}
    </div>
  );
}
```

---

## 🎯 Escalabilidad Final

### **Con Historial + CloudFront CDN**

```
Usuarios Simultáneos | Arquitectura | Tiempo | CPU | Memory | Cost
                1000 | 1 generar     |   3s   | 10% |  50MB  | $5
               10000 | 1 generar     |   3s   | 10% |  50MB  | $5
              100000 | 1 generar     |   3s   | 10% |  50MB  | $5
             1000000 | 1 generar     |   3s   | 10% |  50MB  | $5
```

✅ **Escala infinitamente sin cambiar el servidor**

---

## 📝 Checklist

- [ ] Crear tabla `ReportHistory`
- [ ] Migración de datos (si existen reportes viejos)
- [ ] Task `generate_and_store_report` actualizada
- [ ] Endpoints GET listar historial
- [ ] Endpoint POST refresh reporte
- [ ] Cleanup task (Celery beat)
- [ ] CloudFront distribution configurada
- [ ] S3 bucket con versioning (backup)
- [ ] Frontend: ReportHistory component
- [ ] Analytics: descargas por reporte

---

## 💡 Próximas Mejoras

- [ ] Exportar a Google Sheets (guardar en Drive)
- [ ] Scheduling automático (genera cada lunes)
- [ ] Watermark customizable
- [ ] Multi-formato (PDF + Excel + CSV simultáneo)
- [ ] Compartir reportes públicamente (link)
- [ ] Versionamiento (ver cambios en el tiempo)

