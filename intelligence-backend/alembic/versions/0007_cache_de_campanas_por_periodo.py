"""Cachea GET /reports/campaigns por (cuenta, rango de fechas, pais).

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-03

GET /reports/campaigns pedia a Meta, en cada apertura del panel de
"Personalizar metricas", cuales campanas tuvieron datos reales en el
rango de fechas elegido -- eso implica correr el job asincrono de
insights por campana, el segundo mas lento que usa un reporte completo,
solo para dibujar un panel de configuracion.

Ese resultado es estable una vez que el periodo ya paso (Meta no
reescribe el historial), asi que se guarda una fila por combinacion
exacta de (account_id, date_from, date_to, country_code) y, si el
periodo ya cerro, se sirve para siempre sin volver a llamar a Meta. Si
el periodo todavia incluye hoy, la fila expira segun
_CAMPAIGNS_CACHE_TTL (ver app/api/routes/reports.py) para que una
campana nueva de hoy no tarde en aparecer.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "report_campaigns_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "account_id", sa.Integer(),
            sa.ForeignKey("ad_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False, server_default=""),
        sa.Column("campaigns", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "account_id", "date_from", "date_to", "country_code",
            name="uq_campaigns_cache_key",
        ),
    )
    op.create_index(
        "ix_report_campaigns_cache_account_id",
        "report_campaigns_cache", ["account_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_report_campaigns_cache_account_id", table_name="report_campaigns_cache")
    op.drop_table("report_campaigns_cache")
