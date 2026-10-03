from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["user", "admin"]


class ProductIn(BaseModel):
    """Product card fields supplied by the client on create and update."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=100, examples=["Яблоко Гренни Смит"])
    description: str | None = Field(default=None, max_length=1000)
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2, examples=["129.90"])
    quantity: int = Field(default=0, ge=0, description="Units in stock")


class Product(ProductIn):
    """Product card as stored and returned by the API."""

    id: int


class ChatRequest(BaseModel):
    """Customer message to the shop assistant."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    message: str = Field(min_length=1, max_length=2000, examples=["Какие яблоки у вас есть?"])
    # Training project: the role is taken from the request as is, without authentication,
    # so any client can act as admin. A real service must derive it from verified credentials.
    role: Role = Field(default="user", description="admin can also add products and edit product cards")


class ChatResponse(BaseModel):
    """Assistant answer; every request is handled on its own, without conversation history."""

    status: Literal["success", "error"]
    action: str = Field(description="What the assistant did")
    data: list[Product] | str | None = Field(
        description="Product cards from the catalogue, a text answer for coffee questions, or null"
    )
    errors: list[str] = Field(description="Problems with the request; empty on success")
