"""
Script de una sola vez para sembrar datos de prueba del panel de leads en
dev.db: un usuario owner con password conocido en la org de "Menos Pausa",
y 8-10 leads variados en distintas etapas del pipeline con bitácora.

Uso: .venv/Scripts/python.exe scripts/seed_leads_dev.py
"""
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import Client, Lead, LeadAudit, User, UserRole

TEST_EMAIL = "leads-test@vaovao.co"
TEST_PASSWORD = "test-leads-2026!"


def now():
    return datetime.now(timezone.utc)


def main():
    db = SessionLocal()
    try:
        client = db.query(Client).filter(Client.name.like("Menos Pausa%")).first()
        if not client:
            print("No se encontró el cliente 'Menos Pausa'. Abortando.")
            return
        org_id = client.org_id

        user = db.query(User).filter(User.email == TEST_EMAIL).first()
        if not user:
            user = User(
                org_id=org_id,
                email=TEST_EMAIL,
                hashed_password=hash_password(TEST_PASSWORD),
                full_name="Leads Test",
                role=UserRole.owner,
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            print(f"Usuario creado: {TEST_EMAIL} / {TEST_PASSWORD} (id={user.id}, org_id={org_id})")
        else:
            print(f"Usuario ya existía: {TEST_EMAIL} (id={user.id})")

        # Un segundo usuario para tener a quién asignar leads.
        assignee = db.query(User).filter(User.email == "asesor-test@vaovao.co").first()
        if not assignee:
            assignee = User(
                org_id=org_id,
                email="asesor-test@vaovao.co",
                hashed_password=hash_password("asesor-test-2026!"),
                full_name="Ana Asesora",
                role=UserRole.member,
                is_active=True,
            )
            db.add(assignee)
            db.commit()
            db.refresh(assignee)
            print(f"Usuario asesor creado: asesor-test@vaovao.co (id={assignee.id})")

        existing = db.query(Lead).filter(Lead.client_id == client.id).count()
        if existing > 0:
            print(f"Ya hay {existing} leads para el cliente {client.id}. No se siembran más.")
            return

        seed_leads = [
            dict(name="José Ramírez", phone="+502 5555-1010", status="nuevo", campaign="Campaña Verano — Conversión", assigned=None),
            dict(name="María Fernanda López", phone="+502 5555-2020", status="nuevo", campaign="Campaña Verano — Conversión", assigned=None),
            dict(name="Carlos Enrique Pérez", phone="+502 5555-3030", status="contactado", campaign="Retargeting Q3", assigned=assignee),
            dict(name="Ángela Morales", phone="+502 5555-4040", status="contactado", campaign="Retargeting Q3", assigned=None),
            dict(name="Luis Fernando Gómez", phone="+502 5555-5050", status="calificado", campaign="Leads Formulario Rápido", assigned=assignee),
            dict(name="Andrea Xitumul", phone="+502 5555-6060", status="propuesta", campaign="Leads Formulario Rápido", assigned=assignee),
            dict(name="José Antonio Sical", phone="+502 5555-7070", status="propuesta", campaign="Campaña Verano — Conversión", assigned=None),
            dict(name="Mónica Herrera", phone="+502 5555-8080", status="ganado", campaign="Retargeting Q3", assigned=assignee),
            dict(name="Wilson Ixchop", phone="+502 5555-9090", status="perdido", campaign="Leads Formulario Rápido", assigned=None),
            dict(name="Fátima Nineth Cabrera", phone="+502 5555-1212", status="nuevo", campaign="Campaña Verano — Conversión", assigned=None),
        ]

        created_leads = []
        for i, s in enumerate(seed_leads):
            received = now() - timedelta(hours=(len(seed_leads) - i) * 3)
            lead = Lead(
                org_id=org_id,
                client_id=client.id,
                leadgen_id=f"seed-leadgen-{1000 + i}",
                form_id="seed-form-1",
                campaign_name=s["campaign"],
                form_data={
                    "full_name": s["name"],
                    "phone_number": s["phone"],
                    "email": s["name"].lower().replace(" ", ".").replace("á","a").replace("é","e").replace("í","i").replace("ó","o").replace("ú","u") + "@example.com",
                },
                status=s["status"],
                assigned_to_id=s["assigned"].id if s["assigned"] else None,
                notes="Contactar en horario de tarde." if s["status"] not in ("nuevo",) else None,
                received_at=received,
                updated_at=received,
            )
            db.add(lead)
            created_leads.append((lead, s, received))

        db.commit()
        for lead, s, received in created_leads:
            db.refresh(lead)

        # Bitácora: para el primer lead "ganado" y el de "propuesta" con asesor,
        # dejamos varias entradas para ver la bitácora con contenido real.
        for lead, s, received in created_leads:
            db.add(LeadAudit(
                lead_id=lead.id, user_id=None, action="created",
                old_value=None, new_value="nuevo", timestamp=received,
            ))
            if s["status"] != "nuevo":
                db.add(LeadAudit(
                    lead_id=lead.id, user_id=user.id, action="status_changed",
                    old_value="nuevo", new_value="contactado",
                    timestamp=received + timedelta(hours=1),
                ))
            if s["assigned"]:
                db.add(LeadAudit(
                    lead_id=lead.id, user_id=user.id, action="assigned",
                    old_value=None, new_value=s["assigned"].full_name,
                    timestamp=received + timedelta(hours=1, minutes=10),
                ))
            if s["status"] in ("calificado", "propuesta", "ganado"):
                db.add(LeadAudit(
                    lead_id=lead.id, user_id=user.id, action="status_changed",
                    old_value="contactado", new_value="calificado",
                    timestamp=received + timedelta(hours=2),
                ))
            if s["status"] in ("propuesta", "ganado"):
                db.add(LeadAudit(
                    lead_id=lead.id, user_id=user.id, action="status_changed",
                    old_value="calificado", new_value="propuesta",
                    timestamp=received + timedelta(hours=3),
                ))
            if s["status"] == "ganado":
                db.add(LeadAudit(
                    lead_id=lead.id, user_id=user.id, action="status_changed",
                    old_value="propuesta", new_value="ganado",
                    timestamp=received + timedelta(hours=4),
                ))
                db.add(LeadAudit(
                    lead_id=lead.id, user_id=user.id, action="notes_added",
                    old_value=None, new_value="Contactar en horario de tarde.",
                    timestamp=received + timedelta(hours=4, minutes=5),
                ))

        db.commit()
        print(f"Se crearon {len(created_leads)} leads de prueba para el cliente '{client.name}' (id={client.id}).")
        print(f"Login: {TEST_EMAIL} / {TEST_PASSWORD}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
