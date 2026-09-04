"""Guarda el id de campana en los leads para poder filtrarlos por activo.

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-04

Un cliente con varios activos comerciales (cuentas publicitarias) mezclaba
los leads de TODOS sus activos en una sola bandeja -- Lead solo se
guardaba con client_id, nunca con la campana de la que vino. Se agrega
leads.campaign_id (y orphan_leads.campaign_id, para que sobreviva la
reconciliacion) con el id REAL de campana de Meta que manda leads_traker
desde el mismo fetch que ya trae campaign_name.

Con esto, GET /leads puede filtrar por activo comercial cruzando
campaign_id contra SyncedCampaign (ver app/services/daily_sync.py,
migracion 0009): un lead cuya campana ya se sincronizo como de un activo
especifico aparece solo ahi; uno sin campana resuelta todavia (formulario
sin anuncio, o campana muy nueva que aun no se sincronizo) aparece en
TODOS los activos del cliente en vez de perderse.

No hay leads existentes que migrar: el modulo de leads recien esta
arrancando en produccion.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, Sequence[str], None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("campaign_id", sa.String(length=64), nullable=True))
    op.create_index("ix_leads_campaign_id", "leads", ["campaign_id"])
    op.add_column("orphan_leads", sa.Column("campaign_id", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("orphan_leads", "campaign_id")
    op.drop_index("ix_leads_campaign_id", table_name="leads")
    op.drop_column("leads", "campaign_id")
