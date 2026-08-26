"""lead_audits.user_id: ON DELETE CASCADE -> SET NULL.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-25

Borrar un usuario borraba TODA la bitácora que esa persona hubiera escrito,
mientras que sus leads sobrevivían. Una bitácora que se puede hacer
desaparecer borrando al autor no sirve como bitácora.

Con `SET NULL` la fila se queda y su `user_id` pasa a NULL, que en este
esquema ya significa "lo hizo el sistema" y ya se pinta como "Sistema"
(`AuditEntry.user` es opcional). El criterio es el mismo que ya usa
`leads.assigned_to_id`.

Esto va en su propia revisión y NO como enmienda de 0002 a propósito: una
base que ya aplicó 0002 tiene su `alembic_version` en 0002 y jamás volvería a
ejecutarla, así que el cambio pasaría inadvertido.

Cambiar el `ondelete` de una FK es, en los dos motores, soltarla y volverla a
crear. En SQLite no existe `ALTER ... DROP CONSTRAINT`, así que se usa
`batch_alter_table`, que recrea la tabla entera copiando los datos — el mismo
patrón que ya usa 0002 para volver `user_id` nullable.

Sobre el nombre de la constraint
--------------------------------
Para soltar una FK hace falta su nombre, y 0002 no le puso ninguno. En
Postgres eso no importa: el servidor la autonombró (`lead_audits_user_id_fkey`)
y el inspector lo devuelve. En SQLite la constraint es literalmente anónima y
el inspector devuelve `None`; por eso se pasa una `naming_convention` a
`batch_alter_table` —la receta de la propia documentación de Alembic— para
que la FK reflejada reciba un nombre calculado con el que sí se puede soltar.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Convención con la que se nombra la FK cuando la base no le dio nombre
# (SQLite). Sólo se aplica a la tabla reflejada dentro del batch.
_CONVENCION_NOMBRES = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}
_FK_ANONIMA = "fk_lead_audits_user_id_users"


def _nombre_fk_user_id() -> str:
    """Nombre de la FK `lead_audits.user_id -> users.id` en ESTA base.

    El del catálogo si lo tiene (Postgres), y si no el que le va a poner
    `_CONVENCION_NOMBRES` al reflejarla (SQLite).
    """
    bind = op.get_bind()
    for fk in sa.inspect(bind).get_foreign_keys("lead_audits"):
        if fk.get("constrained_columns") == ["user_id"]:
            return fk.get("name") or _FK_ANONIMA
    return _FK_ANONIMA


def _recrear_fk(ondelete: str) -> None:
    nombre = _nombre_fk_user_id()
    with op.batch_alter_table(
        "lead_audits", naming_convention=_CONVENCION_NOMBRES
    ) as batch_op:
        batch_op.drop_constraint(nombre, type_="foreignkey")
        batch_op.create_foreign_key(
            nombre, "users", ["user_id"], ["id"], ondelete=ondelete
        )


def upgrade() -> None:
    _recrear_fk("SET NULL")


def downgrade() -> None:
    """Vuelve a CASCADE.

    OJO: las filas que ya quedaron con `user_id` NULL por un usuario borrado no
    se pueden reatribuir —esa información ya no existe—, así que seguirán
    mostrándose como "Sistema". El downgrade restaura el esquema, no los datos.
    """
    _recrear_fk("CASCADE")
