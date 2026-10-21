from pydantic import BaseModel, EmailStr, Field, ConfigDict
from typing import Literal

class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class ProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    department: str | None = None
    year: int | None = Field(default=None, ge=1, le=5)
    semester: int | None = Field(default=None, ge=1, le=12)
    bio: str | None = Field(default=None, max_length=1000)

class UserOut(BaseModel):
    id: int; name: str; email: str; department: str; year: int; semester: int; bio: str; reputation_score: int; role: str
    model_config = ConfigDict(from_attributes=True)

class CommentIn(BaseModel): body: str = Field(min_length=1, max_length=5000)
class VoteIn(BaseModel): value: Literal[-1, 1]
class ReportIn(BaseModel): reason: Literal["incorrect", "spam", "duplicate", "inappropriate"]; details: str = Field(default="", max_length=2000)
class AskIn(BaseModel): question: str = Field(min_length=2, max_length=4000); selected_text: str = Field(default="", max_length=12000)
class VerifyIn(BaseModel): status: Literal["VERIFIED", "REJECTED", "PENDING"]
