"""LangChain tools that operate the Fruit Shop HTTP API."""

import json
import logging
from decimal import Decimal

import httpx
from langchain_core.tools import BaseTool, tool

logger = logging.getLogger(__name__)


def build_tools(http: httpx.Client) -> list[BaseTool]:
    """Read-only tools; every request role gets them."""

    @tool
    def list_products() -> str:
        """List every product in the shop: id, name, description, price in rubles and quantity in stock."""
        return call_api(http, "list_products", "GET", "/products")

    @tool
    def get_product(product_id: int) -> str:
        """Get one product card by its id."""
        return call_api(http, "get_product", "GET", f"/products/{product_id}")

    return [list_products, get_product]


def build_admin_tools(http: httpx.Client) -> list[BaseTool]:
    """Catalogue editing tools; only the administrator's agent gets them."""

    @tool
    def add_product(name: str, price: Decimal, quantity: int = 0, description: str | None = None) -> str:
        """Add a new product to the catalogue. Price is in rubles, quantity is the number of units in stock."""
        body = {"name": name, "price": str(price), "quantity": quantity, "description": description}
        return call_api(http, "add_product", "POST", "/products", body)

    @tool
    def update_product(
        product_id: int,
        name: str | None = None,
        description: str | None = None,
        price: Decimal | None = None,
        quantity: int | None = None,
    ) -> str:
        """Edit a product card. Pass only the fields to change; the others keep their current values."""
        # The API replaces the whole card, so read the current one and change only the given fields.
        current = call_api(http, "update_product", "GET", f"/products/{product_id}")
        if not json.loads(current)["ok"]:
            return current
        changes = {"name": name, "description": description, "price": price, "quantity": quantity}
        body = json.loads(current)["data"] | {k: v for k, v in changes.items() if v is not None}
        body.pop("id")
        body["price"] = str(body["price"])
        return call_api(http, "update_product", "PUT", f"/products/{product_id}", body)

    return [add_product, update_product]


def call_api(http: httpx.Client, tool_name: str, method: str, path: str, body: dict | None = None) -> str:
    """Call the API and return the outcome as a JSON string the model can read."""
    try:
        response = http.request(method, path, json=body)
    except httpx.HTTPError as e:
        result = {"ok": False, "error": f"The shop API is unavailable ({e.__class__.__name__})"}
    else:
        try:
            payload = response.json()
        except ValueError:
            payload = {"detail": response.text}
        if response.is_success:
            result = {"ok": True, "status_code": response.status_code, "data": payload}
        else:
            result = {"ok": False, "status_code": response.status_code, "error": payload.get("detail")}
    text = json.dumps(result, ensure_ascii=False)
    logger.info("tool %s: %s %s -> %s", tool_name, method, path, text)
    return text
