"""Guarda desde que dia cubre la sincronizacion diaria de cada cuenta.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-04

daily_metrics_synced_until solo dice HASTA que dia se sincronizo una
cuenta, nunca DESDE cuando. El backfill inicial (daily_sync.BACKFILL_DAYS,
90 dias) es una ventana FIJA que nunca se vuelve a extender hacia atras --
pedir un dia anterior a esa ventana (ej. navegando varios meses atras en
Resumen) contestaria "$0" en silencio sumando de una tabla vacia en vez de
ir a buscarlo a Meta.

daily_metrics_synced_since guarda ese limite inferior, fijado UNA sola vez
en la primera sincronizacion. Las cuentas que ya se hayan sincronizado con
la version anterior de daily_sync.py (antes de esta migracion) quedan con
NULL: se resuelve solo la proxima vez que corra su sincronizacion (ver
daily_sync.sync_account).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, Sequence[str], None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ad_accounts", sa.Column("daily_metrics_synced_since", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("ad_accounts", "daily_metrics_synced_since")
