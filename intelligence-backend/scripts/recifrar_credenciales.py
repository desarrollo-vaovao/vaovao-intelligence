"""
Recifra todas las credenciales guardadas con la llave vigente.

Es el segundo paso de una rotación de ENCRYPTION_KEY. El orden importa y no
se puede saltar ninguno:

  1. Pon la llave nueva AL FRENTE, conservando la anterior:
         ENCRYPTION_KEYS="<nueva>,<anterior>"
     A partir de aquí lo nuevo se cifra con la nueva y lo viejo se sigue
     leyendo con la anterior. Nada se rompe.

  2. Corre este script. Recifra todo lo guardado con la llave vigente.

         python -m scripts.recifrar_credenciales          # muestra qué haría
         python -m scripts.recifrar_credenciales --apply  # lo escribe

  3. Recién entonces retira la anterior:
         ENCRYPTION_KEYS="<nueva>"

Saltarse el paso 2 y retirar la anterior deja las credenciales ilegibles y
NO recuperables. Eso fue el incidente del 2026-08-27, que costó las tres
credenciales de Meta de la organización.
"""
import sys

from sqlalchemy import select

from app.core import crypto
from app.core.database import SessionLocal
from app.models import FacebookConnection, MetaCentralToken


def main(aplicar: bool) -> int:
    with SessionLocal() as db:
        filas = [
            (f"token central '{r.label}'", r)
            for r in db.scalars(select(MetaCentralToken)).all()
        ] + [
            (f"Facebook de user_id={r.user_id}", r)
            for r in db.scalars(select(FacebookConnection)).all()
        ]

        if not filas:
            print("No hay credenciales guardadas. Nada que hacer.")
            return 0

        recifradas, ilegibles = 0, []
        for descripcion, fila in filas:
            nuevo = crypto.rotate(fila.token_encrypted)
            if nuevo is None:
                ilegibles.append(descripcion)
                continue
            if aplicar:
                fila.token_encrypted = nuevo
            recifradas += 1
            print(f"  {'recifrada' if aplicar else 'se recifraría'}: {descripcion}")

        if aplicar:
            db.commit()

        print(
            f"\n{recifradas} de {len(filas)} credencial(es) "
            f"{'recifradas' if aplicar else 'listas para recifrar'}."
        )

        if ilegibles:
            # Ninguna llave configurada las lee. Retirar la anterior ahora las
            # daría por perdidas para siempre, así que se avisa fuerte.
            # Sin símbolos fuera de ASCII: la consola de Windows usa cp1252 y
            # un carácter como "⚠" la hace reventar con UnicodeEncodeError,
            # justo en el aviso que más importa que se lea.
            print(
                f"\n[ATENCION] {len(ilegibles)} credencial(es) que NINGUNA "
                "llave configurada puede leer:"
            )
            for d in ilegibles:
                print(f"     - {d}")
            print(
                "\n   NO retires ninguna llave de ENCRYPTION_KEYS todavía.\n"
                "   Si falta una llave anterior, agrégala. Si ya no existe,\n"
                "   esas credenciales hay que recapturarlas en Conexión Meta."
            )
            return 1

        if not aplicar:
            print("\nNada se escribió. Repite con --apply para aplicarlo.")
        else:
            print("\nYa puedes retirar la llave anterior de ENCRYPTION_KEYS.")
        return 0


if __name__ == "__main__":
    sys.exit(main(aplicar="--apply" in sys.argv))
