"""Moneda nativa por activo comercial y tipo de cambio USD->GTQ por organizacion.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-28

El panel de Resumen mostraba "Q75.59" al elegir quetzales, pero era el
MISMO numero en dolares con el simbolo cambiado - nunca hubo conversion
real. Corregirlo de verdad requiere saber DOS cosas que la base no
guardaba: en que moneda reporta gasto cada cuenta de Meta (no todas las
de un mismo cliente estan en la misma - algunas se configuraron en Meta
Ads Manager directamente en quetzales), y que tipo de cambio usar cuando
sea necesario convertir.

`ad_accounts.native_currency` (nullable): se resuelve on-demand contra la
API de Meta la primera vez que hace falta (ver report_builder) y se
persiste para no volver a consultarla. Cuentas existentes quedan en NULL
hasta esa primera consulta.

`organizations.exchange_rate_usd_gtq` (nullable): un valor fijo que cada
organizacion configura a mano en Ajustes, no una tasa en vivo - un
reporte no deberia poder fallar por depender de un servicio externo de
cambio de moneda. NULL hasta que el owner/admin lo configure; mientras
tanto se usa un valor de respaldo aproximado (ver
report_builder.DEFAULT_EXCHANGE_RATE_USD_GTQ).

Ambas son columnas nuevas y nullable: agregarlas es seguro en cualquier
motor sin migrar datos existentes.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ad_accounts",
        sa.Column("native_currency", sa.String(length=3), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column("exchange_rate_usd_gtq", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("organizations", "exchange_rate_usd_gtq")
    op.drop_column("ad_accounts", "native_currency")
