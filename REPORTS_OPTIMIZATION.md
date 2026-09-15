# 📊 Optimización de Reportes - Sin Esperas

**Problema:** Usuario hace click en "Descargar reporte" y espera 30-60 segundos.
**Solución:** Reportes se generan en background desde caché, se descargan al instante.

---

## 🎯 Arquitectura Reportería

```
Usuario hace click "Descargar"
    ↓
POST /api/reports/generate (retorna inmediato)
    ├→ Retorna: { status: "queued", report_id: "..." }
    └→ Trigger Celery task en background
         ↓
    Celery Worker:
         ├→ Lee datos del CACHÉ Redis (no Meta API)
         ├→ Procesa con Playwright (PDF) o openpyxl (Excel)
         ├→ Guarda en S3 o filesystem
         └→ Emite WebSocket: "report_ready"
         
Usuario ve notificación "Tu reporte está listo"
    ↓
GET /api/reports/{report_id}/download (retorna al instante)
    └→ Descarga desde S3/storage
```

---

## 📁 Nuevos Archivos a Crear

### 1. Modelo para Reportes (`app/models/__init__.py` - agregar)

```python
from sqlalchemy import Column, String, DateTime, Enum as SQLEnum
from app.db.base import Base
from datetime import datetime
import enum
from uuid import uuid4

class ReportStatus(str, enum.Enum):
    PENDING = "pending"      # En cola
    GENERATING = "generating"  # Procesando
    READY = "ready"          # Listo para descargar
    FAILED = "failed"        # Error

class Report(Base):
    __tablename__ = "reports"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    organization_id = Column(String, ForeignKey("organization.id"), nullable=False)
    user_id = Column(String, ForeignKey("user.id"), nullable=False)
    
    # Tipo
    report_type = Column(String, nullable=False)  # "dashboard", "clients", "accounts"
    format = Column(String, nullable=False)  # "pdf", "excel"
    
    # Filtros
    date_from = Column(DateTime, nullable=True)
    date_to = Column(DateTime, nullable=True)
    client_ids = Column(String, nullable=True)  # JSON array
    
    # Status
    status = Column(SQLEnum(ReportStatus), default=ReportStatus.PENDING)
    
    # Storage
    file_url = Column(String, nullable=True)  # S3 URL o path
    file_size = Column(Integer, nullable=True)  # bytes
    
    # Timing
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)  # Para limpiar después
    
    # Error handling
    error_message = Column(String, nullable=True)
```

---

### 2. Task de Generación de Reportes (`app/tasks.py` - agregar)

```python
from celery import shared_task
from app.core.cache import get_cached_metrics
from app.db.session import SessionLocal
from app.models import Report, ReportStatus
from datetime import datetime, timedelta
from pathlib import Path
import json
import logging

logger = logging.getLogger(__name__)

@shared_task(name="generate_pdf_report")
def generate_pdf_report(report_id: str):
    """
    Genera PDF desde datos en caché (NO llama Meta).
    Guarda en S3 o filesystem local.
    """
    db = SessionLocal()
    try:
        report = db.query(Report).filter(Report.id == report_id).first()
        if not report:
            logger.error(f"Report {report_id} not found")
            return
        
        # Marcar como "generando"
        report.status = ReportStatus.GENERATING
        db.commit()
        
        # 1. Obtener datos del CACHÉ (no Meta)
        metrics = get_cached_metrics(report.organization_id)
        if not metrics:
            raise Exception("No cached metrics available")
        
        metrics_data = json.loads(metrics)
        
        # 2. Procesar datos según tipo de reporte
        if report.report_type == "dashboard":
            report_content = _generate_dashboard_report(
                metrics_data,
                report.date_from,
                report.date_to
            )
        elif report.report_type == "clients":
            report_content = _generate_clients_report(metrics_data)
        elif report.report_type == "accounts":
            report_content = _generate_accounts_report(metrics_data)
        else:
            raise ValueError(f"Unknown report type: {report.report_type}")
        
        # 3. Generar PDF con Playwright
        pdf_path = _generate_pdf(report_content, report_id)
        
        # 4. Guardar en S3 (ó filesystem)
        file_url = _upload_to_storage(pdf_path, report.organization_id, report_id)
        
        # 5. Actualizar BD
        report.status = ReportStatus.READY
        report.file_url = file_url
        report.file_size = Path(pdf_path).stat().st_size
        report.completed_at = datetime.utcnow()
        report.expires_at = datetime.utcnow() + timedelta(days=30)  # Válido 30 días
        db.commit()
        
        logger.info(f"✅ Report {report_id} generated: {file_url}")
        
        # 6. Notificar vía WebSocket
        await broadcast_report_ready(report.organization_id, report_id)
        
        return {"report_id": report_id, "url": file_url}
        
    except Exception as e:
        logger.error(f"❌ Error generating report {report_id}: {e}")
        report.status = ReportStatus.FAILED
        report.error_message = str(e)
        db.commit()
        raise
    finally:
        db.close()

@shared_task(name="generate_excel_report")
def generate_excel_report(report_id: str):
    """
    Genera Excel desde datos en caché.
    Más rápido que PDF.
    """
    db = SessionLocal()
    try:
        report = db.query(Report).filter(Report.id == report_id).first()
        if not report:
            return
        
        report.status = ReportStatus.GENERATING
        db.commit()
        
        # Obtener caché
        metrics = get_cached_metrics(report.organization_id)
        metrics_data = json.loads(metrics)
        
        # Generar Excel
        excel_path = _generate_excel(metrics_data, report_id)
        file_url = _upload_to_storage(excel_path, report.organization_id, report_id)
        
        # Actualizar
        report.status = ReportStatus.READY
        report.file_url = file_url
        report.file_size = Path(excel_path).stat().st_size
        report.completed_at = datetime.utcnow()
        db.commit()
        
        logger.info(f"✅ Excel report {report_id} ready")
        await broadcast_report_ready(report.organization_id, report_id)
        
        return {"report_id": report_id, "url": file_url}
        
    except Exception as e:
        logger.error(f"Error generating excel: {e}")
        report.status = ReportStatus.FAILED
        report.error_message = str(e)
        db.commit()
        raise
    finally:
        db.close()

# Helper functions

def _generate_dashboard_report(metrics: dict, date_from, date_to):
    """Procesa datos para reporte dashboard"""
    return {
        "title": "Dashboard Report",
        "date_range": f"{date_from} to {date_to}",
        "summary": {
            "total_clients": len(metrics.get("clients", {})),
            "total_spend": sum(
                sum(
                    float(m.get("spend", 0)) 
                    for m in client.get("metrics", [])
                )
                for client in metrics.get("clients", {}).values()
            )
        },
        "clients": metrics.get("clients", {})
    }

def _generate_clients_report(metrics: dict):
    """Reporte por cliente"""
    return {
        "title": "Clients Report",
        "clients": metrics.get("clients", {})
    }

def _generate_accounts_report(metrics: dict):
    """Reporte detallado de cuentas"""
    accounts = []
    for client in metrics.get("clients", {}).values():
        for acc in client.get("ad_accounts", {}).values():
            accounts.append({
                "client": client.get("name"),
                "account": acc.get("name"),
                "metrics": acc.get("metrics")
            })
    return {"title": "Ad Accounts Report", "accounts": accounts}

def _generate_pdf(content: dict, report_id: str) -> str:
    """
    Genera PDF usando Playwright.
    Playwright ya está instalado en el env.
    """
    from playwright.sync_api import sync_playwright
    import tempfile
    
    html = f"""
    <html>
        <head>
            <style>
                body {{ font-family: Arial; margin: 20px; }}
                h1 {{ color: #333; }}
                .summary {{ background: #f0f0f0; padding: 10px; margin: 20px 0; }}
                table {{ width: 100%; border-collapse: collapse; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                th {{ background-color: #4CAF50; color: white; }}
            </style>
        </head>
        <body>
            <h1>{content.get('title')}</h1>
            <div class="summary">
                <h2>Resumen</h2>
                <p>Clientes: {content.get('summary', {}).get('total_clients')}</p>
                <p>Gasto Total: ${content.get('summary', {}).get('total_spend', 0):.2f}</p>
            </div>
            <h2>Detalles</h2>
            <pre>{json.dumps(content.get('clients', {}), indent=2)}</pre>
        </body>
    </html>
    """
    
    output_path = f"/tmp/report_{report_id}.pdf"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        page.pdf(path=output_path)
        browser.close()
    
    return output_path

def _generate_excel(metrics: dict, report_id: str) -> str:
    """Genera Excel con openpyxl"""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    
    wb = Workbook()
    ws = wb.active
    ws.title = "Metrics"
    
    # Headers
    headers = ["Client", "Account", "Spend", "Impressions", "Clicks", "Conversions"]
    ws.append(headers)
    
    # Style headers
    fill = PatternFill(start_color="4CAF50", end_color="4CAF50", fill_type="solid")
    font = Font(bold=True, color="FFFFFF")
    for cell in ws[1]:
        cell.fill = fill
        cell.font = font
    
    # Data
    for client_id, client in metrics.get("clients", {}).items():
        for acc_id, account in client.get("ad_accounts", {}).items():
            ws.append([
                client.get("name"),
                account.get("name"),
                account.get("metrics", {}).get("spend", 0),
                account.get("metrics", {}).get("impressions", 0),
                account.get("metrics", {}).get("clicks", 0),
                account.get("metrics", {}).get("conversions", 0),
            ])
    
    output_path = f"/tmp/report_{report_id}.xlsx"
    wb.save(output_path)
    return output_path

def _upload_to_storage(file_path: str, org_id: str, report_id: str) -> str:
    """
    Sube archivo a S3 o filesystem.
    
    Opciones:
    1. S3 (AWS) - para producción
    2. Filesystem local - para desarrollo
    """
    from app.core.config import settings
    
    if settings.STORAGE_TYPE == "s3":
        # TODO: Implementar S3 upload con boto3
        # s3_client.upload_file(file_path, bucket, key)
        # return f"https://{bucket}.s3.amazonaws.com/{key}"
        pass
    else:
        # Filesystem local
        storage_dir = Path(settings.STORAGE_PATH) / org_id
        storage_dir.mkdir(parents=True, exist_ok=True)
        
        dest_path = storage_dir / f"{report_id}.pdf"
        shutil.copy(file_path, dest_path)
        
        # Retornar URL relativa para download
        return f"/api/reports/{report_id}/download"

async def broadcast_report_ready(org_id: str, report_id: str):
    """Notifica a WebSocket que reporte está listo"""
    try:
        from app.websocket import sio
        await sio.emit("report_ready", {
            "report_id": report_id,
            "status": "ready"
        }, room=f"org_{org_id}")
    except Exception as e:
        logger.warning(f"WebSocket broadcast error: {e}")
```

---

### 3. Endpoints de Reportería (`app/api/routes/reports.py` - ampliar)

```python
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from app.api.deps import get_current_user
from app.db.session import SessionLocal
from app.models import Report, ReportStatus, User
from app.tasks import generate_pdf_report, generate_excel_report
from datetime import datetime
from uuid import uuid4

router = APIRouter(prefix="/reports", tags=["reports"])

@router.post("/generate")
async def create_report(
    report_type: str = Query(..., regex="^(dashboard|clients|accounts)$"),
    format: str = Query("pdf", regex="^(pdf|excel)$"),
    date_from: datetime = None,
    date_to: datetime = None,
    client_ids: str = None,  # JSON array
    current_user: User = Depends(get_current_user)
):
    """
    Crea un reporte y lo genera en background.
    Retorna INMEDIATO con report_id y status.
    
    Usuario NO espera a que se genere.
    """
    db = SessionLocal()
    try:
        # Crear registro de reporte
        report = Report(
            id=str(uuid4()),
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            report_type=report_type,
            format=format,
            date_from=date_from,
            date_to=date_to,
            client_ids=client_ids,
            status=ReportStatus.PENDING
        )
        db.add(report)
        db.commit()
        
        # Trigger background task
        if format == "pdf":
            generate_pdf_report.delay(report.id)
        else:  # excel
            generate_excel_report.delay(report.id)
        
        # Retornar INMEDIATO (no esperar a que se genere)
        return {
            "report_id": report.id,
            "status": "queued",
            "message": "Reporte en cola. Te notificaremos cuando esté listo.",
            "estimated_time": "30-60 segundos"
        }
        
    finally:
        db.close()

@router.get("/{report_id}/status")
async def get_report_status(
    report_id: str,
    current_user: User = Depends(get_current_user)
):
    """Check status de un reporte (poll)"""
    db = SessionLocal()
    try:
        report = db.query(Report).filter(
            Report.id == report_id,
            Report.organization_id == current_user.organization_id
        ).first()
        
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        
        return {
            "report_id": report.id,
            "status": report.status.value,
            "created_at": report.created_at,
            "completed_at": report.completed_at,
            "download_url": f"/api/reports/{report.id}/download" if report.status == ReportStatus.READY else None,
            "error": report.error_message
        }
        
    finally:
        db.close()

@router.get("/{report_id}/download")
async def download_report(
    report_id: str,
    current_user: User = Depends(get_current_user)
):
    """
    Descarga un reporte listo.
    Retorna al instante (archivo ya generado).
    """
    db = SessionLocal()
    try:
        report = db.query(Report).filter(
            Report.id == report_id,
            Report.organization_id == current_user.organization_id
        ).first()
        
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        
        if report.status != ReportStatus.READY:
            raise HTTPException(
                status_code=400, 
                detail=f"Report not ready yet: {report.status.value}"
            )
        
        # Retornar archivo
        return FileResponse(
            path=report.file_url,
            filename=f"report_{report.id}.{report.format}",
            media_type="application/pdf" if report.format == "pdf" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
    finally:
        db.close()

@router.get("/list")
async def list_reports(
    current_user: User = Depends(get_current_user),
    limit: int = Query(10, ge=1, le=50)
):
    """Lista reportes del usuario"""
    db = SessionLocal()
    try:
        reports = db.query(Report).filter(
            Report.organization_id == current_user.organization_id,
            Report.expires_at > datetime.utcnow()
        ).order_by(Report.created_at.desc()).limit(limit).all()
        
        return [
            {
                "report_id": r.id,
                "type": r.report_type,
                "format": r.format,
                "status": r.status.value,
                "created_at": r.created_at,
                "download_url": f"/api/reports/{r.id}/download" if r.status == ReportStatus.READY else None
            }
            for r in reports
        ]
        
    finally:
        db.close()
```

---

### 4. WebSocket Reportería (`app/websocket.py` - agregar)

```python
# Agregar al websocket.py existente:

@sio.on("subscribe_report_updates")
async def subscribe_report_updates(sid, data):
    """Usuario se suscribe a notificaciones de reportes"""
    org_id = data.get("org_id")
    
    if f"org_{org_id}" not in connected_users:
        connected_users[f"org_{org_id}"] = []
    connected_users[f"org_{org_id}"].append(sid)

async def broadcast_report_ready(org_id: str, report_id: str):
    """Notifica cuando un reporte está listo"""
    if f"org_{org_id}" in connected_users:
        await sio.emit(
            "report_ready",
            {
                "report_id": report_id,
                "message": "Tu reporte está listo para descargar",
                "download_url": f"/api/reports/{report_id}/download"
            },
            room=f"org_{org_id}"
        )
```

---

### 5. Frontend - Interfaz de Reportes (`components/ReportGenerator.jsx`)

```javascript
import { useState } from 'react';
import { useReportUpdates } from '@/hooks/useReportUpdates';

export default function ReportGenerator() {
  const [loading, setLoading] = useState(false);
  const [reportId, setReportId] = useState(null);
  const [reportStatus, setReportStatus] = useState(null);
  const { reports, subscribeToReports } = useReportUpdates();

  const handleGenerateReport = async (reportType, format) => {
    setLoading(true);
    
    try {
      // POST /api/reports/generate (retorna INMEDIATO)
      const res = await fetch('/api/reports/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          report_type: reportType,
          format: format,
          date_from: new Date(Date.now() - 7 * 24 * 60 * 60 * 1000),
          date_to: new Date()
        })
      });
      
      const data = await res.json();
      setReportId(data.report_id);
      setReportStatus('queued');
      
      // Mostrar toast: "Reporte en cola, te avisaremos cuando esté listo"
      toast.info(data.message, { autoClose: 5000 });
      
      // Suscribirse a notificaciones
      subscribeToReports();
      
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="report-generator">
      <h2>Generar Reportes</h2>
      
      {/* Botones para generar */}
      <div className="button-group">
        <button 
          onClick={() => handleGenerateReport('dashboard', 'pdf')}
          disabled={loading}
        >
          📊 Dashboard (PDF)
        </button>
        <button 
          onClick={() => handleGenerateReport('clients', 'excel')}
          disabled={loading}
        >
          📋 Clientes (Excel)
        </button>
        <button 
          onClick={() => handleGenerateReport('accounts', 'pdf')}
          disabled={loading}
        >
          🎯 Cuentas (PDF)
        </button>
      </div>

      {/* Status actual */}
      {reportId && (
        <div className="report-status">
          <p>Reporte ID: {reportId}</p>
          <p>Status: {reportStatus}</p>
          
          {reportStatus === 'ready' && (
            <a href={`/api/reports/${reportId}/download`}>
              ✅ Descargar Ahora
            </a>
          )}
        </div>
      )}

      {/* Historial de reportes */}
      <div className="report-history">
        <h3>Mis Reportes</h3>
        {reports.map(r => (
          <div key={r.report_id} className="report-item">
            <span>{r.type} - {r.format.toUpperCase()}</span>
            <span className={`status ${r.status}`}>{r.status}</span>
            {r.status === 'ready' && (
              <a href={r.download_url}>Descargar</a>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
```

---

### 6. Hook para Reportes (`hooks/useReportUpdates.js`)

```javascript
import { useState, useEffect } from 'react';
import { initSocket } from '@/lib/socket';

export const useReportUpdates = () => {
  const [reports, setReports] = useState([]);

  useEffect(() => {
    // Cargar reportes existentes
    const fetchReports = async () => {
      const res = await fetch('/api/reports/list');
      const data = await res.json();
      setReports(data);
    };

    fetchReports();
  }, []);

  const subscribeToReports = () => {
    const socket = initSocket();
    
    socket.emit('subscribe_report_updates', { org_id: 'current-org' });
    
    socket.on('report_ready', (data) => {
      console.log('✅ Report ready!', data);
      
      // Agregar a lista o actualizar
      setReports(prev => [
        { 
          report_id: data.report_id, 
          status: 'ready',
          download_url: data.download_url 
        },
        ...prev
      ]);
      
      // Notificación visual
      toast.success('Tu reporte está listo para descargar!', {
        autoClose: false,
        action: {
          label: 'Descargar',
          onClick: () => window.location.href = data.download_url
        }
      });
    });
  };

  return { reports, subscribeToReports };
};
```

---

## 🔧 Configuración Necesaria

**`app/core/config.py`** - Agregar:

```python
# Storage
STORAGE_TYPE: str = "filesystem"  # "filesystem" o "s3"
STORAGE_PATH: str = "/tmp/reports"  # Donde guardar reportes

# Reportes
REPORT_TTL: int = 30  # Días antes de expirar
REPORT_MAX_SIZE_MB: int = 100

# Opcionalmente, si usan S3:
AWS_ACCESS_KEY_ID: str = ""
AWS_SECRET_ACCESS_KEY: str = ""
AWS_S3_BUCKET: str = ""
```

---

## 📊 Flujo Completo

```
1️⃣ Usuario hace click "Generar Reporte"
   └→ POST /api/reports/generate
   └→ Retorna: { report_id: "...", status: "queued" }
   └→ Usuario ve: "Reporte en cola ⏳"

2️⃣ Celery task empieza en background
   └→ Lee datos del CACHÉ Redis (no Meta API)
   └→ Genera PDF/Excel
   └→ Guarda en /tmp/reports/{org_id}/
   └→ Emite WebSocket: "report_ready"

3️⃣ Usuario recibe notificación
   └→ Toast: "Tu reporte está listo"
   └→ Botón: "Descargar Ahora"

4️⃣ Usuario descarga
   └→ GET /api/reports/{report_id}/download
   └→ Retorna archivo (ya generado, instantáneo)

5️⃣ Reporte se expira en 30 días
   └→ Cleanup automático
```

---

## ⚡ Ventajas

| Antes | Después |
|--------|---------|
| Usuario espera 30-60s | Usuario espera 0s (retorno inmediato) |
| Browser se bloquea | UI fluida |
| Timeout si Meta es lento | No afecta (generado en background) |
| Una descarga a la vez | Múltiples descargadas simultaneas |

---

## 🧪 Testing Local

```bash
# Terminal 1: Redis + API + Workers (como siempre)

# Terminal 2: Test generador
curl -X POST "http://localhost:8000/api/reports/generate?report_type=dashboard&format=pdf"

# Respuesta esperada:
# {
#   "report_id": "abc123",
#   "status": "queued",
#   "message": "Reporte en cola..."
# }

# Terminal 3: Ver en WebSocket cuando esté listo (DevTools)
# Evento: "report_ready" → { report_id: "abc123" }

# Terminal 4: Descargar
curl "http://localhost:8000/api/reports/abc123/download" > reporte.pdf
```

---

## 🚀 Integración con Plan Existente

Esta sección **Fase 6.5** se integra así:

```
FASE 6: BD Histórico
├── Guardar snapshots en MetricsSnapshot
└── ✅ Creada

FASE 6.5: Reportería Optimizada (NUEVO)
├── Modelo Report
├── Tasks de generación (PDF/Excel)
├── Endpoints /api/reports/*
├── WebSocket broadcasts
├── Frontend ReportGenerator
└── Storage (filesystem o S3)

FASE 7: Docker Compose
└── Incluir Playwright en requirements
```

---

## 📋 Checklist Reportería

- [ ] Modelo `Report` en BD
- [ ] Task `generate_pdf_report` escrito
- [ ] Task `generate_excel_report` escrito
- [ ] Endpoints `/api/reports/*` funcionando
- [ ] WebSocket broadcast "report_ready" funcionando
- [ ] Frontend ReportGenerator componente
- [ ] useReportUpdates hook
- [ ] Storage local funciona
- [ ] Toast notificaciones
- [ ] Descarga instantánea verificada

---

## 💡 Próximas Mejoras

- [ ] Exportar a Google Sheets
- [ ] Scheduling automático (ej: cada lunes)
- [ ] Reportes de comparación (mes anterior vs actual)
- [ ] Watermark con logo de cliente
- [ ] Multi-idioma (es/en)

