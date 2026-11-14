from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    email: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class ReservationIn(BaseModel):
    area_id: int
    date: str = Field(description="YYYY-MM-DD")
    start: str = Field(description="HH:mm, aligned to the area's slots")
    note: str = Field(default="", max_length=500)


class CancelIn(BaseModel):
    reason: str = Field(default="", max_length=500)


class RejectIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
