# PROMPT: Plan de Solución de Vulnerabilidades de Seguridad

Copia y pega este prompt en Claude para generar un plan de solución completo:

---

## 📋 CONTEXTO DEL ANÁLISIS

He realizado un análisis de seguridad exhaustivo en mi proyecto **VaoVao Intelligence** usando Cyber Neo. Se identificaron **12 vulnerabilidades** siendo **3 críticas**.

### Stack Tecnológico:
- **Backend:** FastAPI + SQLAlchemy + PyJWT + bcrypt + Fernet
- **Frontend:** Next.js 14.2.5 + React 18.3.1
- **BD:** PostgreSQL (en Railway)
- **Deploy:** Railway (backend) + Vercel (frontend)

### 🔴 VULNERABILIDADES CRÍTICAS IDENTIFICADAS:

**1. Exposición de Secretos (CVSS 9.8)**
- Archivos `.env` contienen: SECRET_KEY, ENCRYPTION_KEY, FB_APP_SECRET, VERCEL_OIDC_TOKEN
- Riesgo: Comprometimiento total si se filtra
- Ubicación: Raíz del proyecto y en git history

**2. Gestión Débil de Credenciales (CVSS 8.8)**
- Endpoint `/auth/login` SIN rate limiting
- Vulnerable a brute force attacks
- Sin protección anti-automatización
- Token JWT sin expiración clara

**3. Cifrado Meta Incompleto (CVSS 8.5)**
- Tokens de integración Meta sin versionado de claves
- Sin rotación periódica de secrets
- Information disclosure en mensajes de error

### 🟡 VULNERABILIDADES ALTAS (5):
- Control de acceso multi-tenant incompleto
- CORS demasiado permisivo (wildcard?)
- Input validation débil en OAuth callback
- Falta rate limiting en endpoints críticos
- Information disclosure en errores de Facebook

### Métricas Actuales:
- **Puntuación Seguridad:** 2.4/5 (48%) 🔴 CRÍTICO
- **Post-remediación estimada:** 3.9/5 (78%) 🟡 ALTO
- **Target:** 4.5/5 (90%) 🟢 ACEPTABLE

---

## 📌 SOLICITUD

Por favor, **crea un plan de solución detallado** que incluya:

### 1️⃣ PRIORIZACIÓN
- Ordenar por criticidad y dependencias
- Agrupar cambios por componente (Backend, Frontend, Deploy, Secrets)
- Especificar qué debe hacerse PRIMERO, HOY, ESTA SEMANA

### 2️⃣ PLAN TÉCNICO DETALLADO
Para cada vulnerabilidad:
- **Problema:** Descripción clara
- **Solución:** Implementación paso a paso
- **Código:** Ejemplos específicos (Python/FastAPI, Node.js/Next.js según corresponda)
- **Testing:** Cómo verificar la fix
- **Tiempo estimado:** Horas de desarrollo

### 3️⃣ SECRETS MANAGEMENT
- Cómo generar nuevos secretos seguros
- Dónde almacenarlos (Railway, Vercel, KeyVault, etc.)
- Cómo rotarlos sin downtime
- Revocar secretos antiguos en Meta/Vercel

### 4️⃣ IMPLEMENTACIÓN STEP-BY-STEP
- Orden de implementación (qué hacer primero)
- Dependencias entre fixes
- Testing en cada paso
- Deployment strategy (¿se puede hacer incrementalmente?)

### 5️⃣ TIMELINE
- Hoy (24h): Acciones críticas inmediatas
- Esta semana (5 días): Fixes de vulnerabilidades altas
- Próximas 2 semanas: Vulnerabilidades medias
- Próximo mes: Technical debt y best practices

### 6️⃣ VALIDACIÓN
- Checklist de verificación post-fix
- Cómo auditar que cada remediación está en place
- Testing de seguridad recomendado (SAST, SCA, etc.)
- Proceso de review antes de deploy

### 7️⃣ DOCUMENTACIÓN
- README de seguridad para el equipo
- Políticas de secrets (cómo manejarlos)
- Procedimiento de rotación de credenciales
- Incident response (si se filtra un secret)

---

## 🎯 ENTREGABLES ESPERADOS

Al finalizar, deberías tener:
1. ✅ Documento de Plan de Remediación (este documento)
2. ✅ Script de setup de secrets (bash/python)
3. ✅ Cambios de código listos para PR
4. ✅ Checklist de testing
5. ✅ Comunicación a stakeholders

---

## 📊 ÉXITO = 

- [ ] Cero secretos en `.env` local o git
- [ ] Rate limiting activo en `/auth/login`
- [ ] Tokens Meta con versionado y rotación
- [ ] Multi-tenant RBAC verificado
- [ ] CORS restrictivo por origin
- [ ] Input validation en OAuth callbacks
- [ ] Security headers HTTP en todas las responses
- [ ] Error handling que NO expone internals
- [ ] Puntuación de seguridad ≥ 3.5/5

---

Presenta el plan en secciones claras, con código runnable y un timeline realista. Sé específico: "cambiar línea 42 en auth.py" vs "mejorar autenticación".
