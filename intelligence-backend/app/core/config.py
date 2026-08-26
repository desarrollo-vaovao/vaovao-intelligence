"""
Configuración central de la app.
Lee todo de variables de entorno (.env en local, Variables en Railway).
"""
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Valor de desarrollo para LEADS_SYNC_TOKEN. NUNCA debe usarse en producción;
# el validador de abajo lo rechaza explícitamente cuando ENVIRONMENT=production.
LEADS_SYNC_TOKEN_DEV_DEFAULT = "dev-leads-sync-token-inseguro"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Base de datos ─────────────────────────────────────────
    # En Railway: ${{Postgres.DATABASE_URL}}
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/intelligence"

    # ── Seguridad / JWT ───────────────────────────────────────
    # GENERA UNA LLAVE FUERTE para producción:  openssl rand -hex 32
    SECRET_KEY: str = "cambia-esto-en-produccion-por-favor"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 horas

    # ── Cifrado de credenciales (token de Meta, etc.) ─────────
    # Genera una con:  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    ENCRYPTION_KEY: str | None = None

    # ── Leads (integración con leads_traker) ──────────────────
    # Token compartido para autenticar POST /leads/sync-webhook.
    # OBLIGATORIO en producción — ver validador _validar_secretos_produccion.
    LEADS_SYNC_TOKEN: str = LEADS_SYNC_TOKEN_DEV_DEFAULT

    # ── Facebook / Meta OAuth ("Conectar con Facebook") ───────
    FB_APP_ID: str | None = None
    FB_APP_SECRET: str | None = None          # sensible — solo en .env, nunca en Git
    FB_REDIRECT_URI: str = "http://localhost:8000/auth/facebook/callback"
    FB_API_VERSION: str = "v23.0"
    # A dónde regresa al usuario después de conectar (el frontend)
    FRONTEND_URL: str = "http://localhost:3000"
    # ── App ───────────────────────────────────────────────────
    APP_NAME: str = "VaoVao Intelligence"
    ENVIRONMENT: str = "development"  # development | production

    # Orígenes permitidos para el frontend (separados por coma).
    # En prod: "https://intelligence.vaovao.co"
    CORS_ORIGINS: str = "http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @model_validator(mode="after")
    def _validar_secretos_produccion(self) -> "Settings":
        """
        En producción, ningún secreto puede quedarse en su valor de
        desarrollo o vacío. Falla rápido al arrancar en vez de aceptar
        webhooks/requests silenciosamente con credenciales débiles.
        """
        if self.ENVIRONMENT == "production":
            if not self.LEADS_SYNC_TOKEN or self.LEADS_SYNC_TOKEN == LEADS_SYNC_TOKEN_DEV_DEFAULT:
                raise ValueError(
                    "LEADS_SYNC_TOKEN no está configurado con un valor seguro en "
                    "producción. Define un token fuerte y único en las variables "
                    "de entorno (nunca el valor de desarrollo) antes de desplegar."
                )
        return self

    @property
    def database_url_normalized(self) -> str:
        """
        Railway a veces entrega la URL como 'postgres://'.
        SQLAlchemy con psycopg2 necesita 'postgresql://'.
        """
        url = self.DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return url


settings = Settings()
