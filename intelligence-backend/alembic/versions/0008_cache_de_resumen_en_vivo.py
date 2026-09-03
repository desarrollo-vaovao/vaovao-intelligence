"""Cachea POST /reports/summary por (cuenta, rango de fechas, moneda, pais).

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-03

El panel de Resumen llamaba a Meta en vivo cada vez que alguien lo abria
o cambiaba fecha/moneda, sin importar si otra persona (o la misma) ya
habia pedido exactamente lo mismo hace un minuto. A diferencia de los
paises y las campanas (migraciones 0006 y 0007), el gasto de un periodo
que incluye HOY sigue cambiando en vivo, asi que esto no se puede
cachear "para siempre": se guarda la ultima respuesta completa en
report_summary_cache y se sirve al instante en cada visita, mientras se
refresca en segundo plano cada pocos minutos (ver _SUMMARY_CACHE_TTL en
app/api/routes/reports.py) -- nadie espera a Meta para ver el Resumen,
y el dato se va poniendo al dia solo.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, Sequence[str], None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "report_summary_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "account_id", sa.Integer(),
            sa.ForeignKey("ad_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False, server_default=""),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "account_id", "date_from", "date_to", "currency", "country_code",
            name="uq_summary_cache_key",
        ),
    )
    op.create_index(
        "ix_report_summary_cache_account_id",
        "report_summary_cache", ["account_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_report_summary_cache_account_id", table_name="report_summary_cache")
    op.drop_table("report_summary_cache")
