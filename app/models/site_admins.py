from sqlmodel import SQLModel, Field
from uuid import UUID, uuid4

class SiteAdmins(SQLModel, table=True):
    __tablename__ = "site_admins"  # This must match the Supabase table name

    user_id: UUID = Field(foreign_key="users.id", primary_key=True)