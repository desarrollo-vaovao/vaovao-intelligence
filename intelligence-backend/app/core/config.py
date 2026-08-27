"""
Configuración central de la app.
Lee todo de variables de entorno (.env en local, Variables en Railway).
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # Lista de llaves separadas por coma, para PODER ROTAR sin romper nada.
    # La PRIMERA cifra lo nuevo; todas se prueban al descifrar. Tiene
    # precedencia sobre ENCRYPTION_KEY.
    #
    #   ENCRYPTION_KEYS="<llave_nueva>,<llave_anterior>"
    #
    # Para rotar: pon la nueva al frente y CONSERVA la anterior. Retírala
    # solo después de recifrar lo guardado (scripts/recifrar_credenciales.py).
    # Rotar sin conservar la anterior deja las credenciales de Meta ilegibles
    # y no recuperables — fue el incidente del 2026-08-27.
    ENCRYPTION_KEYS: str | None = None

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
