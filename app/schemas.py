from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional

class SubscriberBase(BaseModel):
    name: str
    email: EmailStr

class SubscriberCreate(SubscriberBase):
    pass

class Subscriber(SubscriberBase):
    id: int
    is_active: bool
    unsubscribe_token: str
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True  # Pydantic v1
        from_attributes = True  # Pydantic v2