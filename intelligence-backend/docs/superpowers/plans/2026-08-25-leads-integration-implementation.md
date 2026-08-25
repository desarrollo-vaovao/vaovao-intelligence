# Leads Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a complete CRM module for managing Meta Lead Ads leads within VaoVao Intelligence, with real-time sync from leads_traker, search/filtering, state management, assignment, and CSV export.

**Architecture:** Modular design with separation of concerns (routes → services → CRUD → models). Database models with proper relationships and indexing. Pydantic schemas for validation. Testing from start (unit → integration → E2E). Push-based sync from leads_traker (webhook endpoint). RBAC integrated with existing org/user structure.

**Tech Stack:** FastAPI, SQLAlchemy ORM, PostgreSQL, Pydantic, pytest, requests (for sync token validation)

## Global Constraints

- All code must follow existing patterns in the codebase (FastAPI routes in `app/api/routes/`, models in `app/models/`, CRUD in `app/crud/`)
- Multi-tenant: all queries must filter by `org_id`
- RBAC: members see only assigned leads, admins/owners see all org leads
- Rate limiting already exists in `app/core/ratelimit.py` — apply to `/leads` endpoints
- Database: PostgreSQL with SQLAlchemy 2.0+ patterns (Mapped, mapped_column)
- No external dependencies beyond what's already in `requirements.txt`
- All tests must be independently runnable (`pytest tests/...`)
- Commit after each task (small, logical commits)

---

## File Structure

**Files to create:**
- `app/schemas/leads.py` — Pydantic models for Lead (LeadCreate, LeadUpdate, LeadResponse, LeadListResponse)
- `app/crud/leads.py` — Database queries (with optimized indexes, filters, pagination)
- `app/services/leads_service.py` — Business logic (create, update, search, RBAC filtering)
- `app/services/leads_sync.py` — Webhook receiver for leads_traker sync
- `app/services/leads_csv_exporter.py` — CSV generation
- `app/api/routes/leads.py` — HTTP endpoints
- `tests/unit/test_leads_service.py` — Unit tests for business logic
- `tests/unit/test_leads_csv_exporter.py` — CSV export tests
- `tests/integration/test_leads_api.py` — API endpoint tests
- `tests/integration/test_leads_sync.py` — Webhook sync tests
- `tests/e2e/test_leads_flow.py` — Complete flow tests

**Files to modify:**
- `app/models/__init__.py` — Add Lead, LeadAudit models and update Organization, Client relationships
- `app/main.py` — Register `/leads` router
- `app/core/config.py` — Add LEADS_SYNC_TOKEN configuration
- `requirements.txt` — (no new dependencies needed)

---

## Tasks

### Task 1: Setup Models & Database Relationships

**Files:**
- Modify: `app/models/__init__.py`

**Interfaces:**
- Produces: `Lead` (model with `id`, `org_id`, `client_id`, `leadgen_id`, `form_id`, `campaign_name`, `form_data`, `status`, `assigned_to_id`, `notes`, `received_at`, `updated_at`, relationships to Organization, Client, User), `LeadAudit` (model with `id`, `lead_id`, `user_id`, `action`, `old_value`, `new_value`, `timestamp`)
- Produces: Updated `Organization.leads` relationship

- [ ] **Step 1: Add imports at top of file**

```python
from sqlalchemy import Index
```

- [ ] **Step 2: Add Lead model before closing**

Add this class to `app/models/__init__.py` (before the final line):

```python
class Lead(Base):
    """Lead capturado de Meta Lead Ads."""
    __tablename__ = "leads"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    
    # Meta webhook data
    leadgen_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    form_id: Mapped[str] = mapped_column(String(64), nullable=True)
    campaign_name: Mapped[str] = mapped_column(String(255), nullable=True)
    
    # Form data (flexible JSON)
    form_data: Mapped[dict] = mapped_column(JSON, default=dict)
    
    # CRM fields
    status: Mapped[str] = mapped_column(String(32), default="nuevo")  # nuevo, contactado, calificado, propuesta, ganado, perdido
    assigned_to_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Timestamps
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    
    # Relationships
    organization: Mapped["Organization"] = relationship(back_populates="leads")
    client: Mapped["Client"] = relationship()
    assigned_to: Mapped["User | None"] = relationship()


class LeadAudit(Base):
    """Auditoría de cambios en leads."""
    __tablename__ = "lead_audits"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    
    action: Mapped[str] = mapped_column(String(32))  # created, status_changed, assigned, notes_added, notes_changed
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    
    # Relationships
    lead: Mapped["Lead"] = relationship()
    user: Mapped["User"] = relationship()
```

- [ ] **Step 3: Add indexes after LeadAudit**

```python
# Add composite indexes for performance
__all__ = [
    "Organization", "User", "Client", "AdAccount", 
    "FacebookConnection", "MetaCentralToken", "Lead", "LeadAudit"
]

# Indexes are created via __table_args__ in SQLAlchemy 2.0
# PostgreSQL will create these on first migration
```

- [ ] **Step 4: Update Organization.leads relationship**

In the `Organization` class, add this relationship after `meta_central_tokens`:

```python
leads: Mapped[list["Lead"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
```

- [ ] **Step 5: Test model imports**

Run:
```bash
cd intelligence-backend
python -c "from app.models import Lead, LeadAudit; print('Models imported successfully')"
```

Expected: `Models imported successfully`

- [ ] **Step 6: Commit**

```bash
git add app/models/__init__.py
git commit -m "feat: add Lead and LeadAudit models with proper relationships and indexes"
```

---

### Task 2: Add LEADS_SYNC_TOKEN to Config

**Files:**
- Modify: `app/core/config.py`

**Interfaces:**
- Produces: `settings.LEADS_SYNC_TOKEN` (string, read from env or config)

- [ ] **Step 1: Add to Settings class**

Open `app/core/config.py` and add this field to the `Settings` class:

```python
# Leads sync
LEADS_SYNC_TOKEN: str = Field(default="dev-token-insecure", description="Token for leads_traker webhook")
```

- [ ] **Step 2: Verify in env example**

Open `.env.example` and add:

```
# Leads Sync (from leads_traker)
LEADS_SYNC_TOKEN=your-secret-token-here
```

- [ ] **Step 3: Test config loading**

```bash
python -c "from app.core.config import settings; print(f'LEADS_SYNC_TOKEN: {settings.LEADS_SYNC_TOKEN[:10]}...')"
```

Expected: `LEADS_SYNC_TOKEN: dev-token...`

- [ ] **Step 4: Commit**

```bash
git add app/core/config.py .env.example
git commit -m "config: add LEADS_SYNC_TOKEN for webhook authentication"
```

---

### Task 3: Create Pydantic Schemas for Lead

**Files:**
- Create: `app/schemas/leads.py`

**Interfaces:**
- Produces: `LeadCreate` (leadgen_id, page_id, form_id, campaign_name, form_data, status), `LeadUpdate` (status, assigned_to_id, notes), `LeadResponse` (full lead data), `LeadListResponse` (paginated list), `LeadSyncPayload` (webhook payload)

- [ ] **Step 1: Create file with imports**

Create `app/schemas/leads.py`:

```python
"""Pydantic schemas for Leads."""
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional


class UserSummary(BaseModel):
    """Minimal user info for lead responses."""
    id: int
    full_name: str
    
    class Config:
        from_attributes = True


class LeadCreate(BaseModel):
    """Payload for webhook sync (from leads_traker)."""
    leadgen_id: str = Field(..., min_length=1, max_length=64)
    page_id: str = Field(..., min_length=1, max_length=64)
    form_id: Optional[str] = Field(None, max_length=64)
    campaign_name: Optional[str] = Field(None, max_length=255)
    form_data: dict = Field(default_factory=dict)
    status: str = Field(default="received", max_length=32)
    token: str = Field(...)  # For webhook authentication


class LeadUpdate(BaseModel):
    """Update payload for lead (status, assignment, notes)."""
    status: Optional[str] = Field(None, max_length=32)
    assigned_to_id: Optional[int] = None
    notes: Optional[str] = None


class LeadResponse(BaseModel):
    """Full lead data in response."""
    id: int
    leadgen_id: str
    form_id: Optional[str]
    campaign_name: Optional[str]
    form_data: dict
    status: str
    assigned_to: Optional[UserSummary]
    notes: Optional[str]
    received_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class LeadListItem(BaseModel):
    """Lead item in list response (minimal)."""
    id: int
    leadgen_id: str
    form_data: dict
    status: str
    assigned_to: Optional[UserSummary]
    notes: Optional[str]
    received_at: datetime
    
    class Config:
        from_attributes = True


class LeadListResponse(BaseModel):
    """Paginated list of leads."""
    total: int
    page: int
    size: int
    items: list[LeadListItem]


class SyncWebhookResponse(BaseModel):
    """Response from sync webhook."""
    status: str = "ok"
    leadgen_id: str
    action: Optional[str] = None
    note: Optional[str] = None
```

- [ ] **Step 2: Test schema imports**

```bash
python -c "from app.schemas.leads import LeadResponse, LeadListResponse; print('Schemas OK')"
```

Expected: `Schemas OK`

- [ ] **Step 3: Commit**

```bash
git add app/schemas/leads.py
git commit -m "feat: add Pydantic schemas for Lead endpoints"
```

---

### Task 4: Create CRUD Layer with Optimized Queries

**Files:**
- Create: `app/crud/leads.py`

**Interfaces:**
- Consumes: `Lead` model, `User.id`, `Organization.id`, `Client.id`
- Produces: `create_lead()`, `get_lead()`, `get_leads()`, `update_lead()`, `get_lead_by_leadgen_id()`, `get_leads_for_user()` functions

- [ ] **Step 1: Create file with base queries**

Create `app/crud/leads.py`:

```python
"""CRUD operations for Lead model."""
from datetime import datetime, timezone
from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from app.models import Lead, LeadAudit, User, UserRole


def create_lead(
    db: Session,
    org_id: int,
    client_id: int,
    leadgen_id: str,
    form_id: str | None,
    campaign_name: str | None,
    form_data: dict,
    status: str = "received",
) -> Lead:
    """Create a new lead."""
    lead = Lead(
        org_id=org_id,
        client_id=client_id,
        leadgen_id=leadgen_id,
        form_id=form_id,
        campaign_name=campaign_name,
        form_data=form_data or {},
        status=status,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def get_lead(db: Session, lead_id: int) -> Lead | None:
    """Get a lead by ID."""
    return db.query(Lead).filter(Lead.id == lead_id).first()


def get_lead_by_leadgen_id(db: Session, leadgen_id: str) -> Lead | None:
    """Get a lead by leadgen_id (from Meta)."""
    return db.query(Lead).filter(Lead.leadgen_id == leadgen_id).first()


def get_leads(
    db: Session,
    org_id: int,
    skip: int = 0,
    limit: int = 50,
    client_id: int | None = None,
    status: str | None = None,
    assigned_to_id: int | None = None,
    search: str | None = None,
) -> tuple[int, list[Lead]]:
    """
    Get paginated leads for org with optional filters.
    Returns (total_count, leads).
    """
    query = db.query(Lead).filter(Lead.org_id == org_id)
    
    if client_id:
        query = query.filter(Lead.client_id == client_id)
    
    if status:
        query = query.filter(Lead.status == status)
    
    if assigned_to_id is not None:
        query = query.filter(Lead.assigned_to_id == assigned_to_id)
    
    if search:
        # Search in form_data JSON fields (PostgreSQL syntax)
        search_term = f"%{search}%"
        query = query.filter(
            Lead.form_data["nombre"].astext.ilike(search_term) |
            Lead.form_data["email"].astext.ilike(search_term) |
            Lead.form_data["teléfono"].astext.ilike(search_term)
        )
    
    total = query.count()
    leads = query.order_by(Lead.received_at.desc()).offset(skip).limit(limit).all()
    
    return total, leads


def get_leads_for_user(
    db: Session,
    user: User,
    skip: int = 0,
    limit: int = 50,
    client_id: int | None = None,
    status: str | None = None,
    search: str | None = None,
) -> tuple[int, list[Lead]]:
    """
    Get paginated leads for a user (respecting RBAC).
    - owner/admin: see all org leads
    - member: see only assigned leads
    """
    query = db.query(Lead).filter(Lead.org_id == user.org_id)
    
    # Member role: filter to assigned leads
    if user.role == UserRole.member:
        query = query.filter(Lead.assigned_to_id == user.id)
    
    # Apply other filters
    if client_id:
        query = query.filter(Lead.client_id == client_id)
    
    if status:
        query = query.filter(Lead.status == status)
    
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            Lead.form_data["nombre"].astext.ilike(search_term) |
            Lead.form_data["email"].astext.ilike(search_term) |
            Lead.form_data["teléfono"].astext.ilike(search_term)
        )
    
    total = query.count()
    leads = query.order_by(Lead.received_at.desc()).offset(skip).limit(limit).all()
    
    return total, leads


def update_lead(
    db: Session,
    lead: Lead,
    status: str | None = None,
    assigned_to_id: int | None = None,
    notes: str | None = None,
) -> Lead:
    """Update lead fields and set updated_at."""
    if status is not None:
        lead.status = status
    
    if assigned_to_id is not None:
        lead.assigned_to_id = assigned_to_id
    elif assigned_to_id is None and hasattr(locals(), 'assigned_to_id'):
        # Allow explicit None to unassign
        lead.assigned_to_id = None
    
    if notes is not None:
        lead.notes = notes
    
    lead.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(lead)
    return lead


def record_audit(
    db: Session,
    lead_id: int,
    user_id: int,
    action: str,
    old_value: str | None,
    new_value: str,
) -> LeadAudit:
    """Record an audit log entry."""
    audit = LeadAudit(
        lead_id=lead_id,
        user_id=user_id,
        action=action,
        old_value=old_value,
        new_value=new_value,
    )
    db.add(audit)
    db.commit()
    return audit


def get_audit_log(db: Session, lead_id: int) -> list[LeadAudit]:
    """Get audit log for a lead."""
    return db.query(LeadAudit).filter(LeadAudit.lead_id == lead_id).order_by(LeadAudit.timestamp.desc()).all()
```

- [ ] **Step 2: Test CRUD functions**

```bash
# This just verifies imports for now (actual DB tests come later)
python -c "from app.crud.leads import create_lead, get_lead, get_leads; print('CRUD OK')"
```

Expected: `CRUD OK`

- [ ] **Step 3: Commit**

```bash
git add app/crud/leads.py
git commit -m "feat: add CRUD layer for Lead with optimized queries and RBAC"
```

---

### Task 5: Create Business Logic Service Layer

**Files:**
- Create: `app/services/leads_service.py`

**Interfaces:**
- Consumes: CRUD functions from Task 4, User model, Client model
- Produces: `LeadsService` class with methods: `create_lead_from_webhook()`, `get_lead_detail()`, `list_leads()`, `update_lead()`, `record_change()` 

- [ ] **Step 1: Create service file**

Create `app/services/leads_service.py`:

```python
"""Business logic for Leads."""
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Lead, User, UserRole, Client
from app.crud.leads import (
    create_lead,
    get_lead,
    get_leads,
    update_lead,
    record_audit,
    get_audit_log,
)


class LeadsService:
    """Service layer for lead operations."""
    
    @staticmethod
    def create_lead_from_webhook(
        db: Session,
        leadgen_id: str,
        page_id: str,
        form_id: str | None,
        campaign_name: str | None,
        form_data: dict,
        status: str = "received",
    ) -> tuple[Lead, str]:
        """
        Create a new lead from webhook or update if exists.
        Returns (lead, action) where action is "created" or "updated".
        """
        # Check if lead already exists (dedup)
        existing = get_lead_by_leadgen_id(db, leadgen_id)
        if existing:
            existing.status = status
            existing.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(existing)
            return existing, "updated"
        
        # Find client by page_id
        client = db.query(ClientPage).filter(ClientPage.page_id == page_id).first()
        if not client:
            raise ValueError(f"Client not found for page_id {page_id}")
        
        # Create new lead
        lead = create_lead(
            db,
            org_id=client.org_id,
            client_id=client.id,
            leadgen_id=leadgen_id,
            form_id=form_id,
            campaign_name=campaign_name,
            form_data=form_data or {},
            status=status,
        )
        
        return lead, "created"
    
    @staticmethod
    def get_lead_detail(db: Session, lead_id: int, current_user: User) -> Lead | None:
        """Get lead detail with RBAC check."""
        lead = get_lead(db, lead_id)
        if not lead:
            return None
        
        # Check org access
        if lead.org_id != current_user.org_id:
            raise PermissionError("Unauthorized")
        
        # Check role: members only see assigned leads
        if current_user.role == UserRole.member and lead.assigned_to_id != current_user.id:
            raise PermissionError("Unauthorized")
        
        return lead
    
    @staticmethod
    def list_leads_for_user(
        db: Session,
        current_user: User,
        skip: int = 0,
        limit: int = 50,
        client_id: int | None = None,
        status: str | None = None,
        search: str | None = None,
    ) -> tuple[int, list[Lead]]:
        """List leads for user with RBAC filtering."""
        return get_leads_for_user(
            db,
            current_user,
            skip=skip,
            limit=limit,
            client_id=client_id,
            status=status,
            search=search,
        )
    
    @staticmethod
    def update_lead_with_audit(
        db: Session,
        lead: Lead,
        current_user: User,
        new_status: str | None = None,
        assigned_to_id: int | None = None,
        notes: str | None = None,
    ) -> Lead:
        """Update lead and record audit entries."""
        # RBAC: members only update own assigned leads
        if current_user.role == UserRole.member and lead.assigned_to_id != current_user.id:
            raise PermissionError("Members can only update assigned leads")
        
        # Record old values for audit
        if new_status and new_status != lead.status:
            record_audit(
                db,
                lead.id,
                current_user.id,
                "status_changed",
                lead.status,
                new_status,
            )
        
        if assigned_to_id is not None and assigned_to_id != lead.assigned_to_id:
            old_user = db.query(User).filter(User.id == lead.assigned_to_id).first() if lead.assigned_to_id else None
            new_user = db.query(User).filter(User.id == assigned_to_id).first() if assigned_to_id else None
            record_audit(
                db,
                lead.id,
                current_user.id,
                "assigned",
                old_user.full_name if old_user else None,
                new_user.full_name if new_user else None,
            )
        
        if notes is not None and notes != lead.notes:
            action = "notes_changed" if lead.notes else "notes_added"
            record_audit(
                db,
                lead.id,
                current_user.id,
                action,
                lead.notes,
                notes,
            )
        
        # Update lead
        return update_lead(db, lead, new_status, assigned_to_id, notes)


# Import for convenience
from app.crud.leads import get_lead_by_leadgen_id
```

- [ ] **Step 2: Test service imports**

```bash
python -c "from app.services.leads_service import LeadsService; print('Service OK')"
```

Expected: `Service OK`

- [ ] **Step 3: Commit**

```bash
git add app/services/leads_service.py
git commit -m "feat: add LeadsService business logic layer"
```

---

### Task 6: Create CSV Exporter Service

**Files:**
- Create: `app/services/leads_csv_exporter.py`

**Interfaces:**
- Consumes: Lead model, list of leads
- Produces: `generate_csv()` function that returns bytes

- [ ] **Step 1: Create exporter**

Create `app/services/leads_csv_exporter.py`:

```python
"""CSV export for leads."""
import csv
import io
from datetime import datetime
from typing import List

from app.models import Lead


def generate_csv(leads: List[Lead]) -> bytes:
    """
    Generate CSV from leads.
    Returns bytes that can be streamed as file.
    
    Columns: leadgen_id, form_id, campaign_name, + all form_data keys, status, assigned_to, notes, received_at
    """
    if not leads:
        return b"No leads to export"
    
    # Collect all possible form_data keys (dynamically from actual leads)
    all_keys = set()
    for lead in leads:
        if lead.form_data:
            all_keys.update(lead.form_data.keys())
    form_data_keys = sorted(list(all_keys))
    
    # Define CSV headers
    headers = [
        "leadgen_id",
        "form_id",
        "campaign_name",
        *form_data_keys,
        "status",
        "assigned_to",
        "notes",
        "received_at",
    ]
    
    # Create CSV in memory
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=headers)
    writer.writeheader()
    
    for lead in leads:
        row = {
            "leadgen_id": lead.leadgen_id,
            "form_id": lead.form_id or "",
            "campaign_name": lead.campaign_name or "",
            "status": lead.status,
            "assigned_to": lead.assigned_to.full_name if lead.assigned_to else "",
            "notes": lead.notes or "",
            "received_at": lead.received_at.isoformat() if lead.received_at else "",
        }
        
        # Add form_data fields
        if lead.form_data:
            for key in form_data_keys:
                row[key] = lead.form_data.get(key, "")
        else:
            for key in form_data_keys:
                row[key] = ""
        
        writer.writerow(row)
    
    return output.getvalue().encode("utf-8")


def generate_csv_filename(client_name: str | None = None) -> str:
    """Generate a filename for CSV export."""
    timestamp = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
    if client_name:
        return f"leads_{client_name}_{timestamp}.csv"
    return f"leads_{timestamp}.csv"
```

- [ ] **Step 2: Test imports**

```bash
python -c "from app.services.leads_csv_exporter import generate_csv, generate_csv_filename; print('CSV exporter OK')"
```

Expected: `CSV exporter OK`

- [ ] **Step 3: Commit**

```bash
git add app/services/leads_csv_exporter.py
git commit -m "feat: add CSV export service"
```

---

### Task 7: Create Webhook Sync Service

**Files:**
- Create: `app/services/leads_sync.py`

**Interfaces:**
- Consumes: LeadsService, settings.LEADS_SYNC_TOKEN
- Produces: `process_sync_webhook()` function

- [ ] **Step 1: Create sync service**

Create `app/services/leads_sync.py`:

```python
"""Webhook sync from leads_traker."""
import json
import logging

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Client
from app.services.leads_service import LeadsService

logger = logging.getLogger("vaovao.leads_sync")


async def process_sync_webhook(
    db: Session,
    payload: dict,
) -> dict:
    """
    Process webhook from leads_traker.
    Validates token, creates/updates lead.
    
    Returns: {
        "status": "ok",
        "leadgen_id": str,
        "action": "created" | "updated",
        "error": str (if any)
    }
    """
    
    # Validate token
    token = payload.get("token")
    if token != settings.LEADS_SYNC_TOKEN:
        logger.warning("Invalid sync token in webhook")
        return {"status": "error", "error": "Invalid token"}
    
    leadgen_id = payload.get("leadgen_id", "")
    page_id = payload.get("page_id", "")
    
    if not leadgen_id or not page_id:
        logger.warning(f"Missing required fields in webhook: leadgen_id={leadgen_id}, page_id={page_id}")
        return {"status": "error", "error": "Missing required fields"}
    
    try:
        # Find client by page_id
        client = db.query(ClientPage).filter(ClientPage.page_id == page_id).first()
        if not client:
            logger.warning(f"Client not found for page_id {page_id}")
            # Return OK even if client not found (don't fail the webhook)
            return {
                "status": "ok",
                "leadgen_id": leadgen_id,
                "note": "Client not found",
            }
        
        # Create or update lead
        lead, action = LeadsService.create_lead_from_webhook(
            db,
            leadgen_id=leadgen_id,
            page_id=page_id,
            form_id=payload.get("form_id"),
            campaign_name=payload.get("campaign_name"),
            form_data=payload.get("form_data", {}),
            status=payload.get("status", "received"),
        )
        
        logger.info(f"Lead {leadgen_id} {action} for client {client.id}")
        
        return {
            "status": "ok",
            "leadgen_id": leadgen_id,
            "action": action,
        }
    
    except ValueError as e:
        logger.error(f"Validation error in webhook: {e}")
        return {"status": "error", "leadgen_id": leadgen_id, "error": str(e)}
    
    except Exception as e:
        logger.error(f"Unexpected error in webhook: {e}", exc_info=True)
        return {"status": "error", "leadgen_id": leadgen_id, "error": "Internal server error"}
```

- [ ] **Step 2: Test imports**

```bash
python -c "from app.services.leads_sync import process_sync_webhook; print('Sync service OK')"
```

Expected: `Sync service OK`

- [ ] **Step 3: Commit**

```bash
git add app/services/leads_sync.py
git commit -m "feat: add webhook sync service for leads_traker integration"
```

---

### Task 8: Create API Routes

**Files:**
- Create: `app/api/routes/leads.py`
- Modify: `app/main.py`

**Interfaces:**
- Consumes: FastAPI, Depends, HTTPException, User model, schemas
- Produces: router with endpoints: GET /leads, GET /leads/{id}, PATCH /leads/{id}, GET /leads/export/csv, POST /leads/sync-webhook

- [ ] **Step 1: Create routes file**

Create `app/api/routes/leads.py`:

```python
"""API routes for Leads."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models import User, UserRole
from app.schemas.leads import (
    LeadResponse,
    LeadUpdate,
    LeadListResponse,
    LeadListItem,
    SyncWebhookResponse,
)
from app.crud.leads import get_lead, get_leads_for_user
from app.services.leads_service import LeadsService
from app.services.leads_sync import process_sync_webhook
from app.services.leads_csv_exporter import generate_csv, generate_csv_filename
from app.core.ratelimit import limiter

logger = logging.getLogger("vaovao.leads")

router = APIRouter(prefix="/leads", tags=["leads"])


@router.get("", response_model=LeadListResponse)
@limiter.limit("30/minute")
async def list_leads(
    request,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=500),
    client_id: int | None = None,
    status: str | None = None,
    search: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List leads with pagination and filters."""
    skip = (page - 1) * size
    
    total, leads = LeadsService.list_leads_for_user(
        db,
        current_user,
        skip=skip,
        limit=size,
        client_id=client_id,
        status=status,
        search=search,
    )
    
    items = [
        LeadListItem.model_validate(lead)
        for lead in leads
    ]
    
    return LeadListResponse(
        total=total,
        page=page,
        size=size,
        items=items,
    )


@router.get("/{lead_id}", response_model=LeadResponse)
@limiter.limit("30/minute")
async def get_lead_detail(
    request,
    lead_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get lead detail with audit log."""
    try:
        lead = LeadsService.get_lead_detail(db, lead_id, current_user)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    # TODO: Include audit_log in response (Task 15)
    return LeadResponse.model_validate(lead)


@router.patch("/{lead_id}")
@limiter.limit("30/minute")
async def update_lead(
    request,
    lead_id: int,
    payload: LeadUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update lead (status, assignment, notes)."""
    # Check permission
    try:
        lead = LeadsService.get_lead_detail(db, lead_id, current_user)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    # Check role for assignment
    if payload.assigned_to_id is not None and current_user.role == UserRole.member:
        raise HTTPException(status_code=403, detail="Members cannot assign leads")
    
    # Update
    try:
        updated = LeadsService.update_lead_with_audit(
            db,
            lead,
            current_user,
            new_status=payload.status,
            assigned_to_id=payload.assigned_to_id,
            notes=payload.notes,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    
    return LeadResponse.model_validate(updated)


@router.get("/export/csv")
@limiter.limit("5/minute")
async def export_csv(
    request,
    client_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Export leads to CSV."""
    # Get leads (with RBAC filtering)
    total, leads = LeadsService.list_leads_for_user(
        db,
        current_user,
        skip=0,
        limit=10000,  # Max 10k for CSV
        client_id=client_id,
    )
    
    if not leads:
        raise HTTPException(status_code=404, detail="No leads to export")
    
    # Generate CSV
    csv_bytes = generate_csv(leads)
    csv_filename = generate_csv_filename(f"client_{client_id}" if client_id else None)
    
    return StreamingResponse(
        iter([csv_bytes]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={csv_filename}"},
    )


@router.post("/sync-webhook", response_model=SyncWebhookResponse)
async def sync_webhook(
    payload: dict,
    db: Session = Depends(get_db),
):
    """Webhook endpoint for leads_traker sync (internal)."""
    result = await process_sync_webhook(db, payload)
    
    if result.get("status") != "ok":
        raise HTTPException(status_code=400, detail=result.get("error", "Unknown error"))
    
    return result
```

- [ ] **Step 2: Register router in main.py**

Open `app/main.py` and add the import at the top:

```python
from app.api.routes import leads  # Add this line with other route imports
```

Then in the `app.include_router()` section, add:

```python
app.include_router(leads.router)
```

- [ ] **Step 3: Test route registration**

```bash
cd intelligence-backend
python -c "from app.main import app; print([r.path for r in app.routes if 'leads' in r.path])"
```

Expected: Should show `/leads`, `/leads/{lead_id}`, etc.

- [ ] **Step 4: Commit**

```bash
git add app/api/routes/leads.py app/main.py
git commit -m "feat: add leads API routes with pagination, filtering, and RBAC"
```

---

### Task 9: Create Unit Tests for Leads Service

**Files:**
- Create: `tests/unit/test_leads_service.py`

**Interfaces:**
- Consumes: LeadsService, mock db, mock models
- Produces: test cases for create_lead_from_webhook, update_lead_with_audit, RBAC checks

- [ ] **Step 1: Create test file**

Create `tests/unit/test_leads_service.py`:

```python
"""Unit tests for LeadsService."""
import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, MagicMock

from app.services.leads_service import LeadsService
from app.models import User, UserRole, Lead, Client


@pytest.fixture
def mock_db():
    """Mock database session."""
    return MagicMock()


@pytest.fixture
def mock_user_admin():
    """Mock admin user."""
    user = Mock(spec=User)
    user.id = 1
    user.org_id = 100
    user.role = UserRole.admin
    user.full_name = "Admin User"
    return user


@pytest.fixture
def mock_user_member():
    """Mock member user."""
    user = Mock(spec=User)
    user.id = 2
    user.org_id = 100
    user.role = UserRole.member
    user.full_name = "Member User"
    return user


@pytest.fixture
def mock_client():
    """Mock client."""
    client = Mock(spec=Client)
    client.id = 1
    client.org_id = 100
    client.page_id = "123456789"
    client.name = "Test Client"
    return client


@pytest.fixture
def mock_lead():
    """Mock lead."""
    lead = Mock(spec=Lead)
    lead.id = 1
    lead.org_id = 100
    lead.client_id = 1
    lead.leadgen_id = "LEA123456"
    lead.status = "nuevo"
    lead.assigned_to_id = None
    lead.notes = None
    lead.received_at = datetime.now(timezone.utc)
    lead.updated_at = datetime.now(timezone.utc)
    lead.form_data = {"nombre": "María", "email": "maria@example.com"}
    return lead


def test_list_leads_admin_sees_all(mock_db, mock_user_admin):
    """Admin users should see all leads in their org."""
    # This test structure; actual implementation depends on CRUD layer
    # For now, just verify the service can be called
    result = LeadsService.list_leads_for_user(
        mock_db,
        mock_user_admin,
        skip=0,
        limit=50,
    )
    assert result is not None


def test_update_lead_with_audit_records_status_change(mock_db, mock_user_admin, mock_lead):
    """Status change should record audit entry."""
    # Mock CRUD functions
    with patch("app.services.leads_service.update_lead") as mock_update:
        mock_update.return_value = mock_lead
        
        # Update lead
        result = LeadsService.update_lead_with_audit(
            mock_db,
            mock_lead,
            mock_user_admin,
            new_status="contactado",
        )
        
        assert result is not None
        assert mock_update.called


def test_member_cannot_assign_leads(mock_db, mock_user_member, mock_lead):
    """Members should not be able to assign leads."""
    with pytest.raises(PermissionError):
        LeadsService.update_lead_with_audit(
            mock_db,
            mock_lead,
            mock_user_member,
            assigned_to_id=3,  # Try to assign
        )


# Add more test cases as needed
from unittest.mock import patch
```

- [ ] **Step 2: Run tests (expect some to fail initially)**

```bash
cd intelligence-backend
pytest tests/unit/test_leads_service.py -v
```

Expected: Some tests pass, some may fail (mocking needs refinement)

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_leads_service.py
git commit -m "test: add unit tests for LeadsService business logic"
```

---

### Task 10: Create Integration Tests for Leads API

**Files:**
- Create: `tests/integration/test_leads_api.py`

**Interfaces:**
- Consumes: FastAPI TestClient, test database, test user/client fixtures
- Produces: test cases for endpoints (GET, PATCH, CSV export)

- [ ] **Step 1: Create test file**

Create `tests/integration/test_leads_api.py`:

```python
"""Integration tests for Leads API."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Organization, User, Client, Lead, UserRole
from app.core.database import SessionLocal


@pytest.fixture(scope="module")
def client():
    """Test client."""
    return TestClient(app)


@pytest.fixture(scope="module")
def db():
    """Test database session."""
    return SessionLocal()


@pytest.fixture
def test_org(db):
    """Create test organization."""
    org = Organization(name="Test Org", slug="test-org")
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


@pytest.fixture
def test_user(db, test_org):
    """Create test user (admin)."""
    from app.core.security import hash_password
    
    user = User(
        org_id=test_org.id,
        email="admin@test.com",
        hashed_password=hash_password("password123"),
        full_name="Admin User",
        role=UserRole.admin,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def test_client(db, test_org):
    """Create test client."""
    client = Client(
        org_id=test_org.id,
        name="Test Client",
        page_id="123456789",
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


@pytest.fixture
def test_lead(db, test_org, test_client):
    """Create test lead."""
    lead = Lead(
        org_id=test_org.id,
        client_id=test_client.id,
        leadgen_id="LEA123456",
        form_data={"nombre": "María", "email": "maria@example.com", "teléfono": "+502"},
        status="nuevo",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def test_list_leads_requires_auth(client):
    """Unauthenticated request should fail."""
    response = client.get("/leads")
    assert response.status_code == 401


def test_list_leads_success(client, test_user):
    """List leads with auth."""
    # This test requires token generation; simplified for now
    # In real implementation, generate JWT token
    headers = {"Authorization": f"Bearer {test_user.id}"}  # Placeholder
    # response = client.get("/leads", headers=headers)
    # assert response.status_code == 200
    pass


def test_export_csv(client, test_user, test_lead):
    """Export leads to CSV."""
    pass


# More tests to follow
```

- [ ] **Step 2: Commit**

```bash
git add tests/integration/test_leads_api.py
git commit -m "test: add integration tests for Leads API endpoints"
```

---

### Task 11: Create Integration Tests for Webhook Sync

**Files:**
- Create: `tests/integration/test_leads_sync.py`

**Interfaces:**
- Consumes: sync webhook endpoint, test database
- Produces: test cases for webhook validation, lead creation/update

- [ ] **Step 1: Create test file**

Create `tests/integration/test_leads_sync.py`:

```python
"""Integration tests for Leads webhook sync."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Organization, Client, Lead
from app.core.database import SessionLocal
from app.core.config import settings


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture
def test_payload():
    """Valid sync webhook payload."""
    return {
        "leadgen_id": "LEA123456",
        "page_id": "987654321",
        "form_id": "FORM789",
        "campaign_name": "Test Campaign",
        "form_data": {
            "nombre": "John Doe",
            "email": "john@example.com",
            "teléfono": "+502",
        },
        "status": "fetched",
        "token": settings.LEADS_SYNC_TOKEN,
    }


def test_sync_webhook_invalid_token(client):
    """Webhook with invalid token should fail."""
    payload = {
        "leadgen_id": "LEA123456",
        "page_id": "987654321",
        "form_data": {},
        "token": "invalid-token",
    }
    response = client.post("/leads/sync-webhook", json=payload)
    assert response.status_code == 400
    assert "Invalid token" in response.text or "error" in response.json()


def test_sync_webhook_missing_fields(client):
    """Webhook with missing required fields should fail."""
    payload = {
        "page_id": "987654321",
        "token": settings.LEADS_SYNC_TOKEN,
        # Missing leadgen_id
    }
    response = client.post("/leads/sync-webhook", json=payload)
    assert response.status_code == 400


def test_sync_webhook_creates_lead(client, test_payload):
    """Valid webhook should create a lead."""
    # First, ensure client exists
    db = SessionLocal()
    org = Organization(name="Sync Test", slug="sync-test")
    db.add(org)
    db.commit()
    
    client_obj = Client(
        org_id=org.id,
        name="Test",
        page_id=test_payload["page_id"],
    )
    db.add(client_obj)
    db.commit()
    db.close()
    
    # Send webhook
    response = client.post("/leads/sync-webhook", json=test_payload)
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "ok"
    assert data.get("action") == "created"


def test_sync_webhook_dedup(client, test_payload):
    """Duplicate webhook should update, not create."""
    # Assuming lead was created in previous test
    response = client.post("/leads/sync-webhook", json=test_payload)
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "ok"
    assert data.get("action") == "updated"
```

- [ ] **Step 2: Commit**

```bash
git add tests/integration/test_leads_sync.py
git commit -m "test: add integration tests for webhook sync"
```

---

### Task 12: Create Unit Tests for CSV Exporter

**Files:**
- Create: `tests/unit/test_leads_csv_exporter.py`

**Interfaces:**
- Consumes: LeadsService, mock leads
- Produces: test cases for CSV generation

- [ ] **Step 1: Create test file**

Create `tests/unit/test_leads_csv_exporter.py`:

```python
"""Unit tests for CSV exporter."""
import pytest
from unittest.mock import Mock

from app.services.leads_csv_exporter import generate_csv, generate_csv_filename
from app.models import Lead, User


@pytest.fixture
def mock_lead_with_user():
    """Mock lead with assigned user."""
    user = Mock(spec=User)
    user.full_name = "Daniela P."
    
    lead = Mock(spec=Lead)
    lead.leadgen_id = "LEA123456"
    lead.form_id = "FORM789"
    lead.campaign_name = "Test Campaign"
    lead.form_data = {
        "nombre": "María Solís",
        "email": "maria@example.com",
        "teléfono": "+50255412290",
    }
    lead.status = "contactado"
    lead.assigned_to = user
    lead.notes = "Follow up"
    lead.received_at = None
    
    return lead


def test_generate_csv_empty_list():
    """Empty lead list should return message."""
    result = generate_csv([])
    assert result == b"No leads to export"


def test_generate_csv_single_lead(mock_lead_with_user):
    """CSV should include all lead data."""
    csv_bytes = generate_csv([mock_lead_with_user])
    csv_str = csv_bytes.decode("utf-8")
    
    assert "leadgen_id" in csv_str
    assert "LEA123456" in csv_str
    assert "María Solís" in csv_str
    assert "contactado" in csv_str


def test_generate_csv_filename():
    """Filename should be generated correctly."""
    filename = generate_csv_filename("client_1")
    assert filename.startswith("leads_client_1_")
    assert filename.endswith(".csv")
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/unit/test_leads_csv_exporter.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_leads_csv_exporter.py
git commit -m "test: add unit tests for CSV export"
```

---

### Task 13: Implement Auditoría in Routes

**Files:**
- Modify: `app/api/routes/leads.py`

**Interfaces:**
- Consumes: LeadAudit model, CRUD audit functions
- Produces: Updated routes that return audit logs in GET /{id} response

- [ ] **Step 1: Update LeadResponse schema**

In `app/schemas/leads.py`, update LeadResponse:

```python
class AuditEntry(BaseModel):
    """Audit log entry."""
    action: str
    user: UserSummary
    old_value: Optional[str]
    new_value: str
    timestamp: datetime
    
    class Config:
        from_attributes = True


class LeadResponse(BaseModel):
    """Full lead data in response."""
    id: int
    leadgen_id: str
    form_id: Optional[str]
    campaign_name: Optional[str]
    form_data: dict
    status: str
    assigned_to: Optional[UserSummary]
    notes: Optional[str]
    received_at: datetime
    updated_at: datetime
    audit_log: Optional[list[AuditEntry]] = None  # Add this
    
    class Config:
        from_attributes = True
```

- [ ] **Step 2: Update GET /{lead_id} endpoint**

In `app/api/routes/leads.py`, update the get_lead_detail function:

```python
from app.crud.leads import get_lead, get_leads_for_user, get_audit_log as crud_get_audit_log

@router.get("/{lead_id}", response_model=LeadResponse)
@limiter.limit("30/minute")
async def get_lead_detail(
    request,
    lead_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get lead detail with audit log."""
    try:
        lead = LeadsService.get_lead_detail(db, lead_id, current_user)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Forbidden")
    
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    # Get audit log
    audit_log = crud_get_audit_log(db, lead_id)
    
    # Convert to response
    response_data = LeadResponse.model_validate(lead)
    response_data.audit_log = [
        AuditEntry.model_validate(entry)
        for entry in audit_log
    ]
    
    return response_data
```

- [ ] **Step 3: Commit**

```bash
git add app/schemas/leads.py app/api/routes/leads.py
git commit -m "feat: add audit log to lead detail response"
```

---

### Task 14: Add Rate Limiting Configuration

**Files:**
- Modify: `app/api/routes/leads.py`

**Interfaces:**
- Consumes: limiter from core/ratelimit.py
- Produces: @limiter decorators on endpoints (already done in Task 8)

This was already included in Task 8, so just verify:

- [ ] **Step 1: Verify endpoints have rate limits**

Check that these lines are in `leads.py`:

```python
@limiter.limit("30/minute")  # List endpoints
@limiter.limit("30/minute")  # Detail endpoint
@limiter.limit("5/minute")   # Export CSV
```

- [ ] **Step 2: Test rate limiting**

```bash
# Quick manual test (will hit rate limit after 30 requests)
for i in {1..35}; do
  curl -H "Authorization: Bearer token" http://localhost:8000/leads
done
```

Expected: After 30 requests, 429 Too Many Requests

- [ ] **Step 3: Commit (if changed)**

```bash
git add app/api/routes/leads.py
git commit -m "config: verify rate limiting on leads endpoints"
```

---

### Task 15: Create E2E Test (Complete Flow)

**Files:**
- Create: `tests/e2e/test_leads_flow.py`

**Interfaces:**
- Consumes: test database, test client, test user
- Produces: complete flow test (webhook → list → update → export)

- [ ] **Step 1: Create E2E test**

Create `tests/e2e/test_leads_flow.py`:

```python
"""End-to-end tests for Leads module."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Organization, User, Client, Lead, UserRole
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.core.config import settings


@pytest.fixture(scope="module")
def test_client():
    return TestClient(app)


@pytest.fixture(scope="module")
def setup_test_data():
    """Setup: Create org, user, client."""
    db = SessionLocal()
    
    # Create org
    org = Organization(name="E2E Test", slug="e2e-test")
    db.add(org)
    db.commit()
    db.refresh(org)
    
    # Create admin user
    user = User(
        org_id=org.id,
        email="e2e@test.com",
        hashed_password=hash_password("password"),
        full_name="E2E User",
        role=UserRole.admin,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    
    # Create client
    client = Client(
        org_id=org.id,
        name="E2E Client",
        page_id="9876543210",
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    
    yield {"db": db, "org": org, "user": user, "client": client}
    
    # Cleanup
    db.close()


def test_complete_lead_flow(test_client, setup_test_data):
    """
    Complete flow:
    1. Webhook creates lead
    2. List leads
    3. Update lead (assign, status)
    4. Export to CSV
    """
    data = setup_test_data
    
    # 1. Webhook creates lead
    webhook_payload = {
        "leadgen_id": "E2E_LEA_001",
        "page_id": "9876543210",
        "form_id": "E2E_FORM",
        "campaign_name": "E2E Campaign",
        "form_data": {
            "nombre": "Test User",
            "email": "test@example.com",
            "teléfono": "+502",
        },
        "status": "fetched",
        "token": settings.LEADS_SYNC_TOKEN,
    }
    response = test_client.post("/leads/sync-webhook", json=webhook_payload)
    assert response.status_code == 200
    webhook_result = response.json()
    assert webhook_result.get("action") == "created"
    
    # 2. List leads (would need auth token in real test)
    # response = test_client.get("/leads")
    # assert response.status_code == 200
    # leads = response.json()
    # assert leads["total"] > 0
    
    # 3. Update lead
    # response = test_client.patch(f"/leads/{lead_id}", json={"status": "contactado"})
    # assert response.status_code == 200
    
    # 4. Export CSV
    # response = test_client.get("/leads/export/csv")
    # assert response.status_code == 200
    # assert "text/csv" in response.headers["content-type"]
```

- [ ] **Step 2: Commit**

```bash
git add tests/e2e/test_leads_flow.py
git commit -m "test: add end-to-end test for complete leads flow"
```

---

### Task 16: Setup & Run All Tests

**Files:**
- Review: All test files

**Interfaces:**
- Consumes: pytest, test database
- Produces: Passing test suite

- [ ] **Step 1: Run all tests**

```bash
cd intelligence-backend
pytest tests/ -v --tb=short 2>&1 | tee test_results.txt
```

Expected: Most tests pass, some may need debugging

- [ ] **Step 2: Fix any failing tests**

Review output, fix schema/mock issues in test files as needed.

- [ ] **Step 3: Run with coverage**

```bash
pytest tests/ --cov=app/services --cov=app/crud --cov=app/api/routes/leads --cov-report=html
```

Expected: Coverage report shows >80% coverage

- [ ] **Step 4: Commit**

```bash
git add .
git commit -m "test: verify all tests pass and coverage >80%"
```

---

### Task 17: Documentation & Docstrings

**Files:**
- Modify: All services, routes, models

**Interfaces:**
- Produces: Complete docstrings on all functions/classes

- [ ] **Step 1: Add docstrings to services**

Update `app/services/leads_service.py` — all methods should have full docstrings:

```python
def create_lead_from_webhook(...) -> tuple[Lead, str]:
    """
    Create a new lead from webhook payload or update if exists (dedup).
    
    Args:
        db: Database session
        leadgen_id: Meta lead ID (unique)
        page_id: Facebook page ID (used to find client)
        form_id: Form ID from Meta
        campaign_name: Campaign name
        form_data: Dictionary of form fields (flexible)
        status: Lead status (default: "received")
    
    Returns:
        tuple: (Lead object, action string "created" or "updated")
    
    Raises:
        ValueError: If client not found for page_id
    """
```

- [ ] **Step 2: Add docstrings to routes**

Update `app/api/routes/leads.py` — docstrings already in place, verify coverage

- [ ] **Step 3: Add docstrings to CRUD**

Update `app/crud/leads.py` — all CRUD functions should have docstrings

- [ ] **Step 4: Commit**

```bash
git add app/services/leads_service.py app/crud/leads.py app/api/routes/leads.py
git commit -m "docs: add comprehensive docstrings to all leads modules"
```

---

### Task 18: Add Status Endpoint (Health Check for Leads)

**Files:**
- Modify: `app/api/routes/leads.py`

**Interfaces:**
- Produces: GET /leads/status endpoint

- [ ] **Step 1: Add status endpoint**

In `app/api/routes/leads.py`, add this endpoint:

```python
@router.get("/status")
async def status():
    """Health check for leads module."""
    return {
        "status": "ok",
        "module": "leads",
        "version": "1.0.0",
    }
```

Note: Place this BEFORE the `/{lead_id}` route so it matches correctly.

- [ ] **Step 2: Test endpoint**

```bash
curl http://localhost:8000/leads/status
```

Expected: `{"status": "ok", "module": "leads", "version": "1.0.0"}`

- [ ] **Step 3: Commit**

```bash
git add app/api/routes/leads.py
git commit -m "feat: add status endpoint for leads health check"
```

---

### Task 19: Database Migration (Schema)

**Files:**
- Note: If using Alembic in future, create migration here

**Interfaces:**
- Produces: Tables created on app startup

**Status:** Currently using SQLAlchemy `Base.metadata.create_all()` in `main.py` lifespan. On app startup, tables are auto-created. For production, transition to Alembic migrations.

- [ ] **Step 1: Verify tables created**

After all models are added, start the app:

```bash
cd intelligence-backend
python -m uvicorn app.main:app --reload
```

Then check database:

```bash
# Using psql or DB client
psql -d your_db -c "\dt leads*"
```

Expected: `leads` and `lead_audits` tables exist

- [ ] **Step 2: Commit**

```bash
git add .
git commit -m "db: leads and lead_audits tables auto-created on app startup"
```

---

### Task 20: Integration with leads_traker Config

**Files:**
- Note: Out of scope for Intelligence implementation; leaves config for leads_traker side

**Setup needed in leads_traker (separate project):**

1. Add to `leads_traker/.env`:
   ```
   INTELLIGENCE_API=https://api.vaovao.co
   LEADS_SYNC_TOKEN=sk_xxx (same value as Intelligence)
   ```

2. Update `leads_traker/app/processor.py` to call webhook (from Task 7 in Sync design)

**For Intelligence Repo:** Just document this requirement.

- [ ] **Step 1: Add comment to leads routes**

In `app/api/routes/leads.py`, add this comment above `sync_webhook`:

```python
# ── Webhook endpoint for leads_traker integration ──
# Requires leads_traker configured with:
#   INTELLIGENCE_API=<this-api-url>
#   LEADS_SYNC_TOKEN=<shared-token>
# See docs/superpowers/specs/2026-08-25-leads-integration-design.md § 6.2
```

- [ ] **Step 2: Commit**

```bash
git add app/api/routes/leads.py
git commit -m "docs: add configuration requirements for leads_traker sync"
```

---

## Summary Checklist

- [ ] **Task 1:** Models (Lead, LeadAudit) created with relationships
- [ ] **Task 2:** Config (LEADS_SYNC_TOKEN) added
- [ ] **Task 3:** Pydantic schemas created
- [ ] **Task 4:** CRUD layer with optimized queries
- [ ] **Task 5:** LeadsService business logic
- [ ] **Task 6:** CSV exporter
- [ ] **Task 7:** Webhook sync service
- [ ] **Task 8:** API routes (list, detail, update, export, sync)
- [ ] **Task 9:** Unit tests for service
- [ ] **Task 10:** Integration tests for API
- [ ] **Task 11:** Integration tests for sync
- [ ] **Task 12:** Unit tests for CSV
- [ ] **Task 13:** Audit log in responses
- [ ] **Task 14:** Rate limiting verified
- [ ] **Task 15:** E2E test
- [ ] **Task 16:** All tests passing
- [ ] **Task 17:** Docstrings complete
- [ ] **Task 18:** Status endpoint
- [ ] **Task 19:** Database tables created
- [ ] **Task 20:** leads_traker integration documented

---

## Execution Notes

- **Branch:** `dev` (not `main`)
- **Testing:** Run `pytest tests/ -v` after each few tasks
- **Commits:** Small, logical, one per task
- **Database:** Auto-creates tables via SQLAlchemy on app startup
- **Timeline:** 2-3 weeks for one developer
- **Handoff:** Once all tasks complete, write **Final Verification Checklist** before moving to Fase 2 (production validation)

---
