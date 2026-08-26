"""Módulo de leads: client_pages, leads, lead_audits, orphan_leads.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-25

Las cuatro tablas del módulo de leads. No existen en producción —esta rama
nunca se desplegó—, así que para el servidor real esto es creación pura.

Por qué ESTA revisión sí comprueba antes de crear
-------------------------------------------------
Mientras la rama se desarrollaba, el lifespan de la app llamaba a
`Base.metadata.create_all()`. Cualquier desarrollador que haya corrido la app
en un commit intermedio tiene ya algunas de estas tablas creadas por
SQLAlchemy, sin fila en `alembic_version` que lo registre — y en la versión que
tuvieran en ese momento. En particular `lead_audits.user_id` nació NOT NULL y
se volvió nullable después; `create_all` no altera columnas de tablas que ya
existen, así que esas bases quedaron con el NOT NULL viejo. Ése es exactamente
el cambio que motivó traer Alembic.

Si esta revisión creara a ciegas, esas máquinas fallarían con "table already
exists" y su único camino sería borrar la base. Comprobando, las tres
situaciones —producción, base vacía y máquina de desarrollo a medio camino—
terminan en el mismo esquema.

Esto es una concesión de UNA vez, la de la adopción. Las revisiones futuras
deben ser literales: a partir de aquí `alembic_version` dice la verdad sobre
en qué estado está cada base, y una migración que adivina es una migración que
no se puede razonar.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _crear_client_pages() -> None:
    op.create_table(
        "client_pages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("page_id", sa.String(length=64), nullable=False),
        sa.Column("page_name", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_client_pages_client_id", "client_pages", ["client_id"], unique=False)
    op.create_index("ix_client_pages_page_id", "client_pages", ["page_id"], unique=True)


def _crear_leads() -> None:
    op.create_table(
        "leads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("leadgen_id", sa.String(length=64), nullable=False),
        sa.Column("form_id", sa.String(length=64), nullable=True),
        sa.Column("campaign_name", sa.String(length=255), nullable=True),
        sa.Column("form_data", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("assigned_to_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["assigned_to_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_lead_org_assigned", "leads", ["org_id", "assigned_to_id"], unique=False)
    op.create_index(
        "idx_lead_org_client_status", "leads", ["org_id", "client_id", "status"], unique=False
    )
    op.create_index("idx_lead_received_at", "leads", ["received_at"], unique=False)
    op.create_index("ix_leads_client_id", "leads", ["client_id"], unique=False)
    op.create_index("ix_leads_leadgen_id", "leads", ["leadgen_id"], unique=True)
    op.create_index("ix_leads_org_id", "leads", ["org_id"], unique=False)


def _crear_lead_audits() -> None:
    op.create_table(
        "lead_audits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        # NULL = "lo hizo el sistema" (la ingesta por webhook no actúa en
        # nombre de nadie). Ver el modelo LeadAudit.
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lead_audits_lead_id", "lead_audits", ["lead_id"], unique=False)
    op.create_index("ix_lead_audits_user_id", "lead_audits", ["user_id"], unique=False)


def _crear_orphan_leads() -> None:
    op.create_table(
        "orphan_leads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("leadgen_id", sa.String(length=64), nullable=False),
        sa.Column("page_id", sa.String(length=64), nullable=False),
        sa.Column("form_id", sa.String(length=64), nullable=True),
        sa.Column("campaign_name", sa.String(length=255), nullable=True),
        sa.Column("form_data", sa.JSON(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_orphan_leads_leadgen_id", "orphan_leads", ["leadgen_id"], unique=True)
    op.create_index("ix_orphan_leads_page_id", "orphan_leads", ["page_id"], unique=False)


def _poner_user_id_nullable(bind) -> None:
    """Alinea una `lead_audits` preexistente con el modelo actual.

    Sólo toca la columna si de verdad está NOT NULL, para no recrear la tabla
    sin motivo: en SQLite no hay `ALTER COLUMN` y `batch_alter_table` resuelve
    el cambio copiando la tabla entera a una nueva.
    """
    columnas = {c["name"]: c for c in sa.inspect(bind).get_columns("lead_audits")}
    user_id = columnas.get("user_id")
    if user_id is None or user_id["nullable"]:
        return

    with op.batch_alter_table("lead_audits") as batch_op:
        batch_op.alter_column("user_id", existing_type=sa.Integer(), nullable=True)


def upgrade() -> None:
    if context.is_offline_mode():
        # `alembic upgrade head --sql` no abre conexión, así que no hay nada
        # que inspeccionar. Se emite el SQL completo, que es justo lo correcto
        # para el único escenario en que se usa el modo offline: generar el
        # script del despliegue a producción, donde ninguna de estas cuatro
        # tablas existe. Una base de desarrollo a medio camino se migra
        # conectándose, nunca con un .sql revisado a mano.
        _crear_client_pages()
        _crear_leads()
        _crear_lead_audits()
        _crear_orphan_leads()
        return

    bind = op.get_bind()
    existentes = set(sa.inspect(bind).get_table_names())

    if "client_pages" not in existentes:
        _crear_client_pages()

    if "leads" not in existentes:
        _crear_leads()

    if "lead_audits" not in existentes:
        _crear_lead_audits()
    else:
        _poner_user_id_nullable(bind)

    if "orphan_leads" not in existentes:
        _crear_orphan_leads()


def downgrade() -> None:
    """Quita el módulo de leads y deja el esquema base intacto.

    Aquí no hay comprobaciones: al bajar de 0002 la base está, por definición,
    en 0002, y eso significa que las cuatro tablas existen. Borra los leads
    guardados — es un downgrade de esquema, no un respaldo.
    """
    op.drop_index("ix_orphan_leads_page_id", table_name="orphan_leads")
    op.drop_index("ix_orphan_leads_leadgen_id", table_name="orphan_leads")
    op.drop_table("orphan_leads")

    op.drop_index("ix_lead_audits_user_id", table_name="lead_audits")
    op.drop_index("ix_lead_audits_lead_id", table_name="lead_audits")
    op.drop_table("lead_audits")

    op.drop_index("ix_leads_org_id", table_name="leads")
    op.drop_index("ix_leads_leadgen_id", table_name="leads")
    op.drop_index("ix_leads_client_id", table_name="leads")
    op.drop_index("idx_lead_received_at", table_name="leads")
    op.drop_index("idx_lead_org_client_status", table_name="leads")
    op.drop_index("idx_lead_org_assigned", table_name="leads")
    op.drop_table("leads")

    op.drop_index("ix_client_pages_page_id", table_name="client_pages")
    op.drop_index("ix_client_pages_client_id", table_name="client_pages")
    op.drop_table("client_pages")
