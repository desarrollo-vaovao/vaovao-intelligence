"""
Rate limiting configuration using slowapi.
Protects critical endpoints (auth, OAuth) from brute force and DoS attacks.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

# Rate limit definitions (key: display name, value: limit expression)
# Format: "N/period" where period is s/m/h/d
LIMITS = {
    "auth_login": "5/15 minutes",           # 5 attempts per 15 minutes per IP
    "auth_register": "3/1 hour",            # 3 registrations per hour per IP
    "facebook_callback": "10/15 minutes",   # 10 OAuth callbacks per 15 minutes per IP
    "reports_generate": "20/1 hour",        # 20 report generations per hour per IP
    # El webhook de leads es la excepción: no lo llama una persona, lo llama
    # el servicio `leads_traker` desde UNA sola IP, así que todos los leads de
    # todos los clientes comparten un mismo balde. El límite tiene que dejar
    # pasar un pico legítimo (una campaña que se dispara + las reentregas de
    # Meta + el drenaje de una cola acumulada tras una caída) y aun así poner
    # techo a una URL filtrada. Ver el docstring del endpoint en
    # app/api/routes/leads.py para el razonamiento del número.
    "leads_sync_webhook": "120/minute",     # 120 leads per minute per IP

    # ── CRM de leads (app/api/routes/leads.py) ──────────────────
    # A diferencia del webhook, aquí quien llama SÍ es una persona con su
    # navegador; el balde es por IP, así que un equipo detrás de un mismo NAT
    # lo comparte. Por eso los límites de lectura son holgados: cortarle la
    # bandeja a media oficina porque tres personas filtraron a la vez sería
    # peor que el ataque que se intenta frenar. Los de escritura y los caros
    # (exportar, reconciliar) sí son estrechos. Cada número está justificado
    # en el docstring de su endpoint.
    "leads_list": "120/minute",             # bandeja: filtros + búsqueda + paginar
    "leads_detail": "240/minute",           # abrir tarjetas: 1 fila por índice
    "leads_update": "60/minute",            # PATCH: escribe lead + bitácora
    "leads_export_csv": "20/hour",          # CSV: miles de filas, igual que un PDF
    "leads_status": "60/minute",            # panel de estado (2 conteos)
    "leads_reconcile": "20/hour",           # admin: convierte N huérfanos en N leads
}
