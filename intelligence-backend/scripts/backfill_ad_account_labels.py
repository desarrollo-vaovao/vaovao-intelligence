"""
Backfill de un solo uso: reescribe el label de cada activo comercial con su
nombre real en Meta.

Antes, el label se escribía a mano al registrar la cuenta ("OLR_NETWORK");
ahora se hereda de Meta ("OLR_C807 Network, S.A."). Este script alinea lo que
ya estaba registrado.

Usa solo los tokens centrales de cada organización — no hay usuario logueado
que aporte su Facebook personal. Las cuentas que ningún token pueda leer se
dejan intactas y se listan al final.

    python -m scripts.backfill_ad_account_labels          # muestra qué cambiaría
    python -m scripts.backfill_ad_account_labels --apply  # lo escribe
"""
import asyncio
import sys

from sqlalchemy import select

from app.core import crypto
from app.core.database import SessionLocal
from app.models import AdAccount, Client, MetaCentralToken
from app.services import meta_api


async def main(apply: bool) -> None:
    db = SessionLocal()
    try:
        accounts = db.scalars(
            select(AdAccount).join(Client, AdAccount.client_id == Client.id)
        ).all()

        # Los tokens centrales, agrupados por organización: cada activo solo se
        # puede leer con los de SU organización.
        tokens_by_org: dict[int, list[str]] = {}
        for row in db.scalars(select(MetaCentralToken)).all():
            token = crypto.decrypt(row.token_encrypted)
            if token:
                tokens_by_org.setdefault(row.org_id, []).append(token)

        sin_resolver = []
        for account in accounts:
            org_id = db.get(Client, account.client_id).org_id
            tokens = tokens_by_org.get(org_id, [])
            if not tokens:
                sin_resolver.append((account, "la organización no tiene tokens centrales"))
                continue

            ok, detail = await meta_api.check_account_access_with_fallback(
                tokens, account.meta_ad_account_id
            )
            if not ok:
                sin_resolver.append((account, detail))
                continue
            if detail == account.label:
                continue

            print(f"  {account.meta_ad_account_id}: {account.label!r} → {detail!r}")
            if apply:
                account.label = detail

        if apply:
            db.commit()
            print("\nCambios aplicados.")
        else:
            print("\nSimulación — nada se escribió. Corre con --apply para guardar.")

        if sin_resolver:
            print("\nNo se pudieron resolver (quedaron como estaban):")
            for account, motivo in sin_resolver:
                print(f"  {account.meta_ad_account_id} ({account.label!r}): {motivo}")
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main(apply="--apply" in sys.argv))
