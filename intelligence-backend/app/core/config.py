"""
Configuración central de la app.
Lee todo de variables de entorno (.env en local, Variables en Railway).
"""
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Valor de desarrollo para LEADS_SYNC_TOKEN. NUNCA debe usarse en producción;
# el validador de abajo lo rechaza explícitamente cuando ENVIRONMENT=production.
LEADS_SYNC_TOKEN_DEV_DEFAULT = "dev-leads-sync-token-inseguro"

# Valor de desarrollo para SECRET_KEY. NUNCA debe usarse en producción;
# el validador de abajo lo rechaza explícitamente cuando ENVIRONMENT=production.
SECRET_KEY_DEV_DEFAULT = "cambia-esto-en-produccion-por-favor"

# Largo mínimo aceptable para SECRET_KEY en producción. `openssl rand -hex 32`
# entrega 64 caracteres; 32 deja pasar cualquier llave generada al azar y corta
# las contraseñas escritas a mano, que es lo que realmente queremos evitar.
SECRET_KEY_MIN_LARGO = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Base de datos ─────────────────────────────────────────
    # En Railway: ${{Postgres.DATABASE_URL}}
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/intelligence"

    # ── Seguridad / JWT ───────────────────────────────────────
    # GENERA UNA LLAVE FUERTE para producción:  openssl rand -hex 32
    # OBLIGATORIA en producción — ver validador _validar_secretos_produccion.
    SECRET_KEY: str = SECRET_KEY_DEV_DEFAULT
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

        Para cubrir un secreto nuevo: agrega un bloque `if` que meta su
        mensaje en `problemas`. Se juntan todos y se reportan de una sola
        vez, para no descubrirlos de a uno por despliegue.
        """
        if self.ENVIRONMENT != "production":
            return self

        problemas: list[str] = []

        # Firma los JWT de sesión. Si es débil o conocida, cualquiera puede
        # emitir tokens válidos y hacerse pasar por cualquier usuario.
        secret_key = (self.SECRET_KEY or "").strip()
        if not secret_key:
            problemas.append("SECRET_KEY está vacía.")
        elif secret_key == SECRET_KEY_DEV_DEFAULT:
            problemas.append(
                "SECRET_KEY conserva su valor de desarrollo, que es público."
            )
        elif len(secret_key) < SECRET_KEY_MIN_LARGO:
            problemas.append(
                f"SECRET_KEY tiene {len(secret_key)} caracteres; se requieren al "
                f"menos {SECRET_KEY_MIN_LARGO}. Genera una con: openssl rand -hex 32"
            )

        # Cifra los tokens de Meta guardados en la base (Fernet). Sin ella la
        # app arranca igual y solo truena cuando alguien conecta su cuenta.
        if not (self.ENCRYPTION_KEY or "").strip():
            problemas.append(
                "ENCRYPTION_KEY no está configurada. Genera una con: python -c "
                '"from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"'
            )

        # Valida las firmas de los webhooks de Facebook y completa el
        # intercambio OAuth. Sin él no hay forma de confiar en lo que llega.
        if not (self.FB_APP_SECRET or "").strip():
            problemas.append("FB_APP_SECRET no está configurado.")

        # Autentica el webhook POST /leads/sync-webhook, la única puerta del
        # servicio abierta a Internet sin JWT.
        token_leads = (self.LEADS_SYNC_TOKEN or "").strip()
        if not token_leads:
            problemas.append("LEADS_SYNC_TOKEN está vacío.")
        elif token_leads == LEADS_SYNC_TOKEN_DEV_DEFAULT:
            problemas.append(
                "LEADS_SYNC_TOKEN conserva su valor de desarrollo, que es público."
            )

        if problemas:
            detalle = "\n".join(f"  - {p}" for p in problemas)
            raise ValueError(
                "Hay secretos sin configurar correctamente para producción "
                f"(ENVIRONMENT=production):\n{detalle}\n"
                "Define valores fuertes y únicos en las variables de entorno "
                "(nunca los valores de desarrollo) antes de desplegar."
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
