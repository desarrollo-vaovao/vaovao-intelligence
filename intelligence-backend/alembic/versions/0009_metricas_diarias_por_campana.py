"""Trae el gasto diario por campana en segundo plano en vez de por rango.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-03

Resumen le pedia a Meta una consulta EN VIVO por cada combinacion nueva de
(cuenta, rango de fechas, moneda) -- cada vez que alguien cambiaba de mes,
quincena o simplemente abria un periodo que nadie habia visto antes, eso
disparaba una llamada nueva, y varias de esas llamadas coincidiendo (mas
las pruebas de carga de este mismo dia) terminaron en un
"User request limit reached" real en produccion.

Este cambio le da la vuelta al problema: un proceso en segundo plano
(app/services/daily_sync.py) trae el gasto DIARIO por campana de cada
cuenta con UNA sola llamada a Meta (time_increment=1, sin importar cuantos
dias o campanas abarque), y lo guarda aqui. Las fechas que elige la
persona en Resumen dejan de ser una peticion a Meta y pasan a ser solo un
filtro SQL sobre lo que ya esta guardado.

- synced_campaigns: la foto mas reciente de que campanas existen (nombre,
  objetivo, estado) -- independiente de la fecha, para que una campana
  activa/pausada sin gasto en el rango elegido no desaparezca del listado.
- campaign_daily_metrics: una fila por (campana, dia) con su gasto/alcance
  de ESE dia.
- ad_accounts.daily_metrics_synced_until: hasta que dia se sincronizo una
  cuenta por ultima vez. NULL = todavia no se ha sincronizado nunca --
  /reports/summary usa esto para saber si puede contestar sumando de la
  base de datos o si todavia necesita el camino viejo mientras llega la
  primera sincronizacion.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, Sequence[str], None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ad_accounts", sa.Column("daily_metrics_synced_until", sa.Date(), nullable=True))

    op.create_table(
        "synced_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "account_id", sa.Integer(),
            sa.ForeignKey("ad_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("campaign_id", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("objective", sa.String(length=60), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("account_id", "campaign_id", name="uq_synced_campaign"),
    )
    op.create_index("ix_synced_campaigns_account_id", "synced_campaigns", ["account_id"])

    op.create_table(
        "campaign_daily_metrics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "account_id", sa.Integer(),
            sa.ForeignKey("ad_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("campaign_id", sa.String(length=40), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("spend", sa.Float(), nullable=False, server_default="0"),
        sa.Column("impressions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reach", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clicks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("account_id", "campaign_id", "date", name="uq_campaign_daily_metric"),
    )
    op.create_index(
        "idx_campaign_daily_metric_account_date",
        "campaign_daily_metrics", ["account_id", "date"],
    )


def downgrade() -> None:
    op.drop_index("idx_campaign_daily_metric_account_date", table_name="campaign_daily_metrics")
    op.drop_table("campaign_daily_metrics")
    op.drop_index("ix_synced_campaigns_account_id", table_name="synced_campaigns")
    op.drop_table("synced_campaigns")
    op.drop_column("ad_accounts", "daily_metrics_synced_until")
