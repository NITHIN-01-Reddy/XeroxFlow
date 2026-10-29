from pydantic import BaseModel, EmailStr, Field, ConfigDict
from typing import Literal, Optional, Dict, Any, List

class UserOut(BaseModel):
    id: int
    name: str
    email: str
    phone: str
    role: str
    model_config = ConfigDict(from_attributes=True)

class ShopRegister(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: str = Field(min_length=5, max_length=30)
    password: str = Field(min_length=8, max_length=128)
    shop_name: str = Field(min_length=2, max_length=160)
    address: str = Field(min_length=3, max_length=300)

class CustomerRegister(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: str = Field(default="", max_length=30)
    password: str = Field(min_length=8, max_length=128)

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class ShopOut(BaseModel):
    id: int
    name: str
    address: str
    phone: str
    bw_price: float
    color_price: float
    a3_multiplier: float
    a5_multiplier: float
    double_sided_discount: float
    stapling_price: float
    model_config = ConfigDict(from_attributes=True)

class ShopUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    address: str = Field(min_length=3, max_length=300)
    phone: str = Field(min_length=5, max_length=30)
    bw_price: float = Field(ge=0, le=10000)
    color_price: float = Field(ge=0, le=10000)
    a3_multiplier: float = Field(default=2.0, ge=0.5, le=10.0)
    a5_multiplier: float = Field(default=0.8, ge=0.1, le=5.0)
    double_sided_discount: float = Field(default=0.0, ge=0, le=100)
    stapling_price: float = Field(default=5.0, ge=0, le=1000)

class ShopPricingUpdate(BaseModel):
    bw_price: float = Field(ge=0, le=10000)
    color_price: float = Field(ge=0, le=10000)
    a3_multiplier: float = Field(ge=0.5, le=10.0)
    a5_multiplier: float = Field(ge=0.1, le=5.0)
    double_sided_discount: float = Field(ge=0, le=100)
    stapling_price: float = Field(ge=0, le=1000)

class PriceEstimateRequest(BaseModel):
    shop_id: int
    copies: int = Field(default=1, ge=1, le=500)
    pages: str = Field(default="all")
    page_count: Optional[int] = Field(default=None, ge=1)
    color_mode: Literal["bw", "color"] = "bw"
    paper_size: Literal["A4", "A3", "A5"] = "A4"
    sides: Literal["single", "double"] = "single"
    orientation: Literal["portrait", "landscape"] = "portrait"
    finishing: Literal["none", "stapling"] = "none"

class PriceBreakdownOut(BaseModel):
    currency: str = "INR"
    color_mode: str
    base_page_rate: float
    paper_size: str
    size_multiplier: float
    effective_page_rate: float
    rate_per_page: Optional[float] = None
    actual_page_count: Optional[int] = None
    billable_page_count: Optional[int] = None
    selected_page_count: int
    copies: int
    printed_page_copies: Optional[int] = None
    sides: str
    orientation: str
    sheets_per_copy: int
    total_sheets: int
    double_sided_discount_percent: float
    printing_cost_per_copy: float
    total_printing_cost: float
    finishing: str
    finishing_unit_price: float
    total_finishing_cost: float
    subtotal: float
    final_total: float
    requires_quote: bool = False
    quote_reason: str = ""

class OrderOut(BaseModel):
    id: int
    customer_id: int
    shop_id: int
    shop_name: str = ""
    shop_address: str = ""
    shop_phone: str = ""
    original_filename: str
    copies: int
    pages: str
    page_count: int
    detected_page_count: Optional[int] = None
    billable_page_count: Optional[int] = None
    sheets_count: int
    color_mode: str
    paper_size: str
    sides: str
    orientation: str
    finishing: str
    notes: str
    estimated_price: float
    final_price: float
    price_breakdown: Optional[Dict[str, Any]] = None
    requires_quote: bool
    status: str
    payment_status: str
    paid_at: Optional[str] = None
    paid_by_id: Optional[int] = None
    cancellation_reason: str = ""
    rejection_reason: str = ""
    created_at: str
    updated_at: str
    customer_name: str
    customer_phone: str
    customer_email: str = ""

class PaymentUpdateIn(BaseModel):
    payment_status: Literal["pending", "paid", "refunded"] = "paid"

class OrderStatusUpdate(BaseModel):
    status_value: Optional[str] = Field(default=None, max_length=30)
    reason: Optional[str] = Field(default=None, max_length=255)
    quote_price: Optional[float] = Field(default=None, ge=0)
    payment_status: Optional[str] = Field(default=None, max_length=30)

class CustomerOrderCancel(BaseModel):
    reason: Optional[str] = Field(default="Cancelled by customer", max_length=255)

class ReceiptOut(BaseModel):
    order_id: int
    order_date: str
    updated_date: str
    status: str
    payment_status: str
    paid_at: Optional[str] = None
    requires_quote: bool = False
    quote_reason: str = ""
    shop: Dict[str, Any]
    customer: Dict[str, Any]
    document: Dict[str, Any]
    specifications: Dict[str, Any]
    breakdown: Dict[str, Any]
    final_amount_inr: float

