import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal

from app.schemas import Product, ProductIn

_SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    description TEXT,
    price       TEXT NOT NULL,
    quantity    INTEGER NOT NULL
)
"""


class ProductRepository:
    """SQLite-backed storage for product cards."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        with self._connection() as conn:
            conn.execute(_SCHEMA)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        # A connection per operation: endpoints run in a thread pool, and
        # sqlite3 connections must not be shared between threads.
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def add(self, data: ProductIn) -> Product:
        with self._connection() as conn:
            cursor = conn.execute(
                "INSERT INTO products (name, description, price, quantity) VALUES (?, ?, ?, ?)",
                (data.name, data.description, str(data.price), data.quantity),
            )
            return Product(id=cursor.lastrowid, **data.model_dump())

    def get(self, product_id: int) -> Product | None:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        return _to_product(row) if row else None

    def list(self) -> list[Product]:
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM products ORDER BY id").fetchall()
        return [_to_product(row) for row in rows]

    def update(self, product_id: int, data: ProductIn) -> Product | None:
        with self._connection() as conn:
            cursor = conn.execute(
                "UPDATE products SET name = ?, description = ?, price = ?, quantity = ? WHERE id = ?",
                (data.name, data.description, str(data.price), data.quantity, product_id),
            )
        if cursor.rowcount == 0:
            return None
        return Product(id=product_id, **data.model_dump())


def _to_product(row: sqlite3.Row) -> Product:
    # Price is stored as text to keep exact decimal values.
    return Product(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        price=Decimal(row["price"]),
        quantity=row["quantity"],
    )
