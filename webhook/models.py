from typing import List  # , Literal

from pydantic import BaseModel, Field


class Item(BaseModel):
    unit_price: float = Field(description="The price of a single unit of the item.")
    unit: str = Field(description="The unit of the item (e.g., 'kg', 'piece').")
    weight: float = Field(description="The weight of the item in kg.")
    quantity: int = Field(description="How many units")
    discount: float = Field(description="Discount on the item in euros.")
    # total_amount: float = Field(description="Total amount for item, unit*unit_price, denoted by bedrag")
    description: str = Field(description="The description of the item.")
    # category: Literal['Fruits', 'Vegetables', 'Cookies_snacks', 'Meat', 'Fish', 'Coffee', 'Milk', 'Garbage_bags', 'soft_drink', 'Cleaning_product', 'cooking', 'baking', 'tools']


class Invoice(BaseModel):
    date: str = Field(description="The date of the invoice (YYYY-MM-DD).")
    page: int = Field(description="Page number of invoice.")
    total_amount_invoice: float = Field(description="The total amount of the invoice.")
    items: List[Item] = Field(description="A list of items in the invoice, either weight or quantity is given.")
