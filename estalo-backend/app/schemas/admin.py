from pydantic import BaseModel, Field


class AdminUserOut(BaseModel):
    user_id: int
    email: str
    daily_tokens_consumed: int
    daily_limit: int


class UpdateLimitRequest(BaseModel):
    daily_limit: int = Field(..., ge=0)
