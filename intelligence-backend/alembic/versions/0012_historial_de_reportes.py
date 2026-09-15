"""Historial de reportes: un PDF generado se puede volver a descargar.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-15

Hasta ahora un reporte terminado vivia en un diccionario en memoria del
proceso (_JOBS en app/api/routes/reports.py) con 30 minutos de vida. Un
despliegue o un reinicio borraba todos los PDF ya generados, y volver a
pedir el mismo reporte obligaba a rehacer el trabajo completo: traer todo
de Meta otra vez y volver a renderizar en Chromium.

generated_reports guarda cada generacion -- sus parametros, su estado y
los bytes del PDF -- de modo que la fila ES a la vez el estado del job y
la entrada del historial. job_id sigue siendo el identificador publico que
consulta el frontend, asi que /reports/jobs/{job_id} no cambia de forma;
lo unico que cambia es que ahora sobrevive a un reinicio.

Los bytes van en la base y no en disco porque Railway no garantiza disco
persistente entre despliegues: un archivo en /tmp se perderia igual que la
memoria. El crecimiento lo acota la purga por antiguedad de reports.py,
que vacia la columna pdf de las filas viejas conservando la fila.

No hay datos que migrar: lo que habia solo existia en memoria.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, Sequence[str], None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "generated_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.String(length=32), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column("pdf", sa.LargeBinary(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("download_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["ad_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_generated_reports_job_id", "generated_reports", ["job_id"], unique=True)
    op.create_index("ix_generated_reports_org_id", "generated_reports", ["org_id"])
    op.create_index("ix_generated_reports_account_id", "generated_reports", ["account_id"])
    op.create_index("ix_generated_reports_created_at", "generated_reports", ["created_at"])
    op.create_index(
        "idx_generated_report_account", "generated_reports", ["account_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("idx_generated_report_account", table_name="generated_reports")
    op.drop_index("ix_generated_reports_created_at", table_name="generated_reports")
    op.drop_index("ix_generated_reports_account_id", table_name="generated_reports")
    op.drop_index("ix_generated_reports_org_id", table_name="generated_reports")
    op.drop_index("ix_generated_reports_job_id", table_name="generated_reports")
    op.drop_table("generated_reports")
