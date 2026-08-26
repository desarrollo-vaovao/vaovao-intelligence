"""Esquema base: lo que ya existía antes de Alembic.

Revision ID: 0001
Revises:
Create Date: 2026-08-25

Esta revisión describe las SEIS tablas que la plataforma ya tenía en producción
cuando se adoptó Alembic: organizations, users, clients, ad_accounts,
facebook_connections y meta_central_tokens. Las creaba
`Base.metadata.create_all()` desde el lifespan de la app.

Cuándo se EJECUTA y cuándo NO
-----------------------------
- Base nueva y vacía (CI, un desarrollador que empieza de cero): se ejecuta y
  crea las seis tablas.
- Base existente con datos reales (producción, y la de cualquier
  desarrollador que ya haya corrido la app): NO se ejecuta. Se marca como ya
  aplicada con `alembic stamp 0001`. Correrla ahí no sólo fallaría por
  "ya existe": el objetivo es justamente NO tocar tablas con datos de
  clientes que pagan.

Por eso esta revisión es deliberadamente literal —crea y punto, sin
comprobaciones de "si no existe"—. Una baseline que se saltea a sí misma
cuando encuentra la tabla puesta deja de describir nada: no se sabría si la
base coincide con lo que dice el modelo o si simplemente se calló. El paso de
`stamp` es explícito a propósito: quien lo escribe está afirmando "esta base
ya tiene este esquema", y esa afirmación tiene que ser de un humano mirando
la base, no de un `if` dentro de la migración.

La revisión 0002 —el módulo de leads— sí es defensiva, por una razón distinta
que está explicada allí.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("meta_app_id", sa.String(length=40), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"], unique=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column(
            "role",
            sa.Enum("owner", "admin", "member", name="userrole"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_org_id", "users", ["org_id"], unique=False)

    op.create_table(
        "clients",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column(
            "type",
            sa.Enum("single", "multi_station", name="clienttype"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_clients_org_id", "clients", ["org_id"], unique=False)

    op.create_table(
        "ad_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("meta_ad_account_id", sa.String(length=60), nullable=False),
        sa.Column("recipient_emails", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ad_accounts_client_id", "ad_accounts", ["client_id"], unique=False)

    op.create_table(
        "facebook_connections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("fb_user_id", sa.String(length=60), nullable=False),
        sa.Column("fb_name", sa.String(length=160), nullable=False),
        sa.Column("token_encrypted", sa.String(length=700), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_facebook_connections_user_id", "facebook_connections", ["user_id"], unique=True
    )

    op.create_table(
        "meta_central_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("token_encrypted", sa.String(length=700), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_meta_central_tokens_org_id", "meta_central_tokens", ["org_id"], unique=False
    )


def downgrade() -> None:
    """Deja la base vacía. En producción esto BORRA a todos los clientes.

    Existe para que el ciclo upgrade/downgrade/upgrade se pueda probar en una
    base desechable, no para ejecutarse en un servidor con datos.
    """
    op.drop_index("ix_meta_central_tokens_org_id", table_name="meta_central_tokens")
    op.drop_table("meta_central_tokens")

    op.drop_index("ix_facebook_connections_user_id", table_name="facebook_connections")
    op.drop_table("facebook_connections")

    op.drop_index("ix_ad_accounts_client_id", table_name="ad_accounts")
    op.drop_table("ad_accounts")

    op.drop_index("ix_clients_org_id", table_name="clients")
    op.drop_table("clients")

    op.drop_index("ix_users_org_id", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

    op.drop_index("ix_organizations_slug", table_name="organizations")
    op.drop_table("organizations")

    # En Postgres, DROP TABLE no se lleva el tipo ENUM que la tabla usaba: se
    # queda huérfano y el siguiente upgrade revienta con "type already exists".
    # SQLite no tiene tipos ENUM (guarda VARCHAR + CHECK), así que no aplica.
    if op.get_bind().dialect.name == "postgresql":
        sa.Enum(name="userrole").drop(op.get_bind(), checkfirst=True)
        sa.Enum(name="clienttype").drop(op.get_bind(), checkfirst=True)
