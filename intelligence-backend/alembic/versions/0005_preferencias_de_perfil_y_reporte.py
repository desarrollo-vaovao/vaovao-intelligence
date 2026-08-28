"""Preferencias de perfil y de reporte: cargo, moneda/cadencia por usuario,
ventana de atribucion por organizacion, zona horaria por activo comercial.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-28

La pagina de Ajustes era de solo lectura (nombre, correo, rol) mas el tipo
de cambio. Estas columnas la vuelven funcional: cada persona fija con que
moneda y cadencia prefiere abrir Resumen/Reportes, y la organizacion fija
una ventana de atribucion unica para que dos personas nunca generen el
mismo reporte con conversiones distintas sin darse cuenta.

`ad_accounts.timezone_name` es puramente informativo: Meta agrupa "por dia"
segun la zona horaria de CADA cuenta publicitaria, y eso no se puede
sobreescribir via parametro (a diferencia de la ventana de atribucion). Un
selector de zona horaria editable estaria mintiendo; esto solo muestra la
real, igual que native_currency se resuelve on-demand contra la API de Meta
la primera vez que hace falta (ver meta_api.get_account_currency).

Todas las columnas son nullable: agregarlas es seguro en cualquier motor
sin migrar datos existentes. NULL significa "sin configurar" y cae al
comportamiento de hoy (ver report_builder y meta_api).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("job_title", sa.String(length=120), nullable=True))
    op.add_column("users", sa.Column("default_currency", sa.String(length=3), nullable=True))
    op.add_column("users", sa.Column("default_cadence", sa.String(length=20), nullable=True))
    op.add_column(
        "organizations",
        sa.Column("attribution_window", sa.String(length=30), nullable=True),
    )
    op.add_column(
        "ad_accounts",
        sa.Column("timezone_name", sa.String(length=60), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ad_accounts", "timezone_name")
    op.drop_column("organizations", "attribution_window")
    op.drop_column("users", "default_cadence")
    op.drop_column("users", "default_currency")
    op.drop_column("users", "job_title")
