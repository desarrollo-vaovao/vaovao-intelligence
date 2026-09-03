"""Cachea la lista de paises targeteados por activo comercial.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-04

GET /reports/countries pedia esta lista a Meta EN CADA carga del selector
de pais en Reportes -- una llamada completa (listado de campanas + listado
de anuncios) solo para leer targeting, que ademas competia por el mismo
cupo de concurrencia que los reportes de verdad (ver
meta_api._account_fetch_semaphore). Los paises targeteados por una cuenta
cambian con muy poca frecuencia (a diferencia del gasto), asi que no hace
falta pedirlos de nuevo cada vez que alguien abre el formulario.

`cached_countries` guarda la ultima lista que se obtuvo de Meta;
`cached_countries_updated_at` cuando se obtuvo. NULL en ambas = todavia no
se ha consultado nunca (cuentas existentes antes de este cambio, o una
cuenta nueva) -- cae al comportamiento de hoy (se consulta a Meta la
primera vez que hace falta, ver app/api/routes/reports.py).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ad_accounts", sa.Column("cached_countries", sa.JSON(), nullable=True))
    op.add_column(
        "ad_accounts",
        sa.Column("cached_countries_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ad_accounts", "cached_countries_updated_at")
    op.drop_column("ad_accounts", "cached_countries")
