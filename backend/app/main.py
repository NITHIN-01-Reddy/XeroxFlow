import socket
import urllib.parse
import mimetypes
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4
from io import BytesIO
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Query, Response, Body, Request
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select, or_
import qrcode

from .database import Base, engine, get_db
from .models import User, Shop, PrintOrder, run_db_migrations
from .schemas import (
    CustomerRegister, ShopRegister, LoginIn, UserOut, ShopOut, ShopUpdate,
    ShopPricingUpdate, OrderOut, OrderStatusUpdate, CustomerOrderCancel,
    PriceEstimateRequest, PriceBreakdownOut, ReceiptOut, PaymentUpdateIn
)
from .security import hash_password, verify_password, create_token, get_current_user, require_role
from .config import UPLOAD_DIR, FRONTEND_URL, MAX_UPLOAD_MB
from .pricing import (
    extract_document_page_count,
    parse_and_validate_pages,
    calculate_order_price
)

# Initialize database schema and apply any SQLite migrations
Base.metadata.create_all(bind=engine)
run_db_migrations(engine)

app = FastAPI(title="XeroxFlow SmartPrint API", version="2.0.0")

def get_lan_ip() -> str:
    """Detect the host machine's LAN IP address for cross-device QR scanning."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def get_effective_frontend_url(base_url_param: str | None = None) -> str:
    """
    Resolve customer-accessible frontend URL for QR code generation.
    Avoids 'localhost' so mobile devices scanning the QR code can access the application.
    """
    if base_url_param:
        cleaned = base_url_param.strip().rstrip("/")
        if cleaned.startswith("http://") or cleaned.startswith("https://"):
            parsed = urllib.parse.urlparse(cleaned)
            if parsed.hostname and parsed.hostname not in ("localhost", "127.0.0.1"):
                return cleaned

    configured = (FRONTEND_URL or "http://localhost:5173").strip().rstrip("/")
    parsed_cfg = urllib.parse.urlparse(configured)
    if parsed_cfg.hostname and parsed_cfg.hostname not in ("localhost", "127.0.0.1"):
        return configured

    lan_ip = get_lan_ip()
    port = parsed_cfg.port or 5173
    scheme = parsed_cfg.scheme or "http"
    if lan_ip and lan_ip != "127.0.0.1":
        return f"{scheme}://{lan_ip}:{port}"

    return configured

allowed_origins = [
    "https://xerox-flow.vercel.app",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "*"],
    expose_headers=["Content-Disposition", "X-Shop-Order-URL"],
)

VALID_TRANSITIONS = {
    "pending": {"accepted", "rejected", "cancelled"},
    "accepted": {"printing", "cancelled"},
    "printing": {"ready", "cancelled"},
    "ready": {"completed"},
    "completed": set(),
    "rejected": set(),
    "cancelled": set()
}

@app.get("/api/health")
def health():
    return {"status": "healthy", "app": "XeroxFlow SmartPrint", "version": "2.0.0"}

def unique_email(db: Session, email: str):
    if db.scalar(select(User).where(User.email == email.lower())):
        raise HTTPException(status_code=409, detail="An account with this email already exists")

@app.post("/api/auth/register/customer")
def register_customer(data: CustomerRegister, db: Session = Depends(get_db)):
    unique_email(db, data.email)
    user = User(name=data.name.strip(), email=data.email.lower(), phone=data.phone,
                password_hash=hash_password(data.password), role="customer")
    db.add(user); db.commit(); db.refresh(user)
    return {"access_token": create_token(user), "token_type": "bearer", "user": UserOut.model_validate(user)}

@app.post("/api/auth/register/shopkeeper")
def register_shopkeeper(data: ShopRegister, db: Session = Depends(get_db)):
    unique_email(db, data.email)
    user = User(name=data.name.strip(), email=data.email.lower(), phone=data.phone,
                password_hash=hash_password(data.password), role="shopkeeper")
    db.add(user); db.flush()
    shop = Shop(
        owner_id=user.id,
        name=data.shop_name.strip(),
        address=data.address.strip(),
        phone=data.phone,
        bw_price=2.0,
        color_price=10.0,
        a3_multiplier=2.0,
        a5_multiplier=0.8,
        double_sided_discount=0.0,
        stapling_price=5.0
    )
    db.add(shop); db.commit(); db.refresh(user); db.refresh(shop)
    return {"access_token": create_token(user), "token_type": "bearer", "user": UserOut.model_validate(user), "shop": ShopOut.model_validate(shop)}

@app.post("/api/auth/login")
def login(data: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == data.email.lower()))
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    return {"access_token": create_token(user), "token_type": "bearer", "user": UserOut.model_validate(user)}

@app.get("/api/auth/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user

@app.get("/api/shops", response_model=list[ShopOut])
def list_shops(db: Session = Depends(get_db)):
    return list(db.scalars(select(Shop).order_by(Shop.name)).all())

@app.get("/api/shops/{shop_id}", response_model=ShopOut)
def get_shop(shop_id: int, db: Session = Depends(get_db)):
    shop = db.get(Shop, shop_id)
    if not shop: raise HTTPException(status_code=404, detail="Shop not found")
    return shop

@app.get("/api/shopkeeper/shop", response_model=ShopOut)
def my_shop(user: User = Depends(require_role("shopkeeper")), db: Session = Depends(get_db)):
    shop = db.scalar(select(Shop).where(Shop.owner_id == user.id))
    if not shop: raise HTTPException(status_code=404, detail="Shop not found")
    return shop

@app.put("/api/shopkeeper/shop", response_model=ShopOut)
def update_shop(data: ShopUpdate, user: User = Depends(require_role("shopkeeper")), db: Session = Depends(get_db)):
    shop = db.scalar(select(Shop).where(Shop.owner_id == user.id))
    if not shop: raise HTTPException(status_code=404, detail="Shop not found")
    for key, value in data.model_dump().items():
        setattr(shop, key, value)
    db.commit(); db.refresh(shop)
    return shop

@app.put("/api/shopkeeper/pricing", response_model=ShopOut)
def update_shop_pricing(data: ShopPricingUpdate, user: User = Depends(require_role("shopkeeper")), db: Session = Depends(get_db)):
    shop = db.scalar(select(Shop).where(Shop.owner_id == user.id))
    if not shop: raise HTTPException(status_code=404, detail="Shop not found")
    shop.bw_price = data.bw_price
    shop.color_price = data.color_price
    shop.a3_multiplier = data.a3_multiplier
    shop.a5_multiplier = data.a5_multiplier
    shop.double_sided_discount = data.double_sided_discount
    shop.stapling_price = data.stapling_price
    db.commit(); db.refresh(shop)
    return shop

def order_out(order: PrintOrder, db: Session | None = None, requesting_user: User | None = None) -> OrderOut:
    customer = getattr(order, "customer", None)
    if customer is None and db is not None:
        customer = db.get(User, order.customer_id)

    shop = getattr(order, "shop", None)
    if shop is None and db is not None:
        shop = db.get(Shop, order.shop_id)

    # Privacy check for customer metadata
    can_view_customer = False
    if requesting_user is not None:
        if requesting_user.role == "shopkeeper":
            if shop and shop.owner_id == requesting_user.id:
                can_view_customer = True
            elif db is not None:
                sk_shop = db.scalar(select(Shop).where(Shop.owner_id == requesting_user.id))
                if sk_shop and sk_shop.id == order.shop_id:
                    can_view_customer = True
        elif requesting_user.role == "customer" and requesting_user.id == order.customer_id:
            can_view_customer = True
    else:
        can_view_customer = True

    if can_view_customer and customer and customer.name and customer.name.strip():
        cust_name = customer.name.strip()
        cust_phone = customer.phone or ""
        cust_email = customer.email or ""
    elif can_view_customer and customer:
        cust_name = "Customer"
        cust_phone = customer.phone or ""
        cust_email = customer.email or ""
    else:
        cust_name = "Customer"
        cust_phone = ""
        cust_email = ""

    breakdown_data = None
    if order.price_breakdown:
        try:
            breakdown_data = json.loads(order.price_breakdown)
        except Exception:
            breakdown_data = None

    if not breakdown_data or not breakdown_data.get("effective_page_rate"):
        base_rate = shop.color_price if (shop and order.color_mode == "color") else (shop.bw_price if shop else 2.0)
        mult = 2.0 if order.paper_size == "A3" else (0.8 if order.paper_size == "A5" else 1.0)
        eff_rate = round(base_rate * mult, 2)
        b_pages = order.billable_page_count or order.page_count or 1
        c_copies = order.copies or 1
        printed_copies = b_pages * c_copies
        print_cost = round(printed_copies * eff_rate, 2)
        actual_total = order.final_price if order.final_price > 0 else (order.estimated_price if order.estimated_price > 0 else print_cost)
        breakdown_data = {
            "currency": "INR",
            "color_mode": order.color_mode,
            "base_page_rate": round(base_rate, 2),
            "paper_size": order.paper_size,
            "size_multiplier": round(mult, 2),
            "effective_page_rate": eff_rate,
            "rate_per_page": eff_rate,
            "actual_page_count": order.detected_page_count or order.page_count or 1,
            "selected_page_count": b_pages,
            "billable_page_count": b_pages,
            "copies": c_copies,
            "printed_page_copies": printed_copies,
            "sides": order.sides,
            "orientation": order.orientation or "portrait",
            "sheets_per_copy": order.sheets_count // c_copies if c_copies > 0 else 1,
            "total_sheets": order.sheets_count or 1,
            "double_sided_discount_percent": 0.0,
            "printing_cost_per_copy": round(print_cost / c_copies, 2) if c_copies > 0 else print_cost,
            "total_printing_cost": print_cost,
            "finishing": order.finishing or "none",
            "finishing_unit_price": 0.0,
            "total_finishing_cost": 0.0,
            "subtotal": actual_total,
            "final_total": actual_total,
            "requires_quote": bool(order.requires_quote),
            "quote_reason": ""
        }

    return OrderOut(
        id=order.id,
        customer_id=order.customer_id,
        shop_id=order.shop_id,
        shop_name=shop.name if shop else "Shop",
        shop_address=shop.address if shop else "",
        shop_phone=shop.phone if shop else "",
        original_filename=order.original_filename,
        copies=order.copies,
        pages=order.pages,
        page_count=order.page_count or 1,
        detected_page_count=order.detected_page_count,
        billable_page_count=order.billable_page_count or order.page_count or 1,
        sheets_count=order.sheets_count or 1,
        color_mode=order.color_mode,
        paper_size=order.paper_size,
        sides=order.sides,
        orientation=order.orientation or "portrait",
        finishing=order.finishing or "none",
        notes=order.notes or "",
        estimated_price=order.estimated_price,
        final_price=order.final_price if order.final_price > 0 else order.estimated_price,
        price_breakdown=breakdown_data,
        requires_quote=bool(order.requires_quote),
        status=order.status,
        payment_status=order.payment_status or "pending",
        paid_at=order.paid_at.isoformat() if order.paid_at else None,
        paid_by_id=order.paid_by_id,
        cancellation_reason=order.cancellation_reason or "",
        rejection_reason=order.rejection_reason or "",
        created_at=order.created_at.isoformat() if order.created_at else "",
        updated_at=order.updated_at.isoformat() if order.updated_at else "",
        customer_name=cust_name,
        customer_phone=cust_phone,
        customer_email=cust_email
    )

@app.post("/api/pricing/estimate", response_model=PriceBreakdownOut)
def estimate_price(data: PriceEstimateRequest, db: Session = Depends(get_db)):
    shop = db.get(Shop, data.shop_id)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    requires_quote = False
    quote_reason = ""

    if data.pages.strip().lower() == "all":
        if data.page_count is not None and data.page_count > 0:
            selected_count = data.page_count
        else:
            selected_count = 1
            requires_quote = True
            quote_reason = "Page count unknown; estimate assumes 1 page. Final price verified on file upload."
    else:
        try:
            _, selected_count, _ = parse_and_validate_pages(data.pages, data.page_count)
        except ValueError as ve:
            raise HTTPException(status_code=400, detail=str(ve))

    breakdown = calculate_order_price(
        shop_bw_price=shop.bw_price,
        shop_color_price=shop.color_price,
        shop_a3_multiplier=shop.a3_multiplier,
        shop_a5_multiplier=shop.a5_multiplier,
        shop_double_sided_discount=shop.double_sided_discount,
        shop_stapling_price=shop.stapling_price,
        copies=data.copies,
        selected_page_count=selected_count,
        color_mode=data.color_mode,
        paper_size=data.paper_size,
        sides=data.sides,
        orientation=data.orientation,
        finishing=data.finishing,
        requires_quote=requires_quote,
        quote_reason=quote_reason,
        actual_page_count=data.page_count
    )
    return breakdown

@app.post("/api/pricing/inspect-document")
async def inspect_document(
    shop_id: int = Form(...),
    copies: int = Form(1),
    pages: str = Form("all"),
    color_mode: str = Form("bw"),
    paper_size: str = Form("A4"),
    sides: str = Form("single"),
    orientation: str = Form("portrait"),
    finishing: str = Form("none"),
    document: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    shop = db.get(Shop, shop_id)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    if copies < 1 or copies > 500:
        raise HTTPException(status_code=400, detail="Copies must be between 1 and 500")

    color_mode = color_mode.lower()
    paper_size = paper_size.upper()
    sides = sides.lower()
    orientation = orientation.lower()
    finishing = finishing.lower()

    if color_mode not in ("bw", "color"):
        raise HTTPException(status_code=400, detail="Printing mode must be 'bw' or 'color'")
    if paper_size not in ("A4", "A3", "A5"):
        raise HTTPException(status_code=400, detail="Paper size must be A4, A3, or A5")
    if sides not in ("single", "double"):
        raise HTTPException(status_code=400, detail="Sides must be 'single' or 'double'")
    if orientation not in ("portrait", "landscape"):
        raise HTTPException(status_code=400, detail="Orientation must be 'portrait' or 'landscape'")
    if finishing not in ("none", "stapling"):
        raise HTTPException(status_code=400, detail="Finishing must be 'none' or 'stapling'")

    if not document.filename:
        raise HTTPException(status_code=400, detail="No document file provided")

    file_ext = Path(document.filename).suffix.lower()
    allowed_exts = (".pdf", ".txt", ".doc", ".docx", ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif")
    if file_ext not in allowed_exts:
        raise HTTPException(status_code=400, detail=f"Allowed file types: {', '.join(allowed_exts)}")

    content = await document.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty (0 bytes)")
    if len(content) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds the {MAX_UPLOAD_MB} MB limit")

    actual_page_count, note = extract_document_page_count(content, document.filename)

    requires_quote = False
    quote_reason = ""

    if file_ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif"):
        if actual_page_count is None:
            raise HTTPException(status_code=400, detail=f"Invalid or corrupted image file: {note}")
        selected_count = actual_page_count
    elif file_ext == ".pdf":
        if actual_page_count is None:
            if pages.strip().lower() == "all":
                selected_count = 0
                requires_quote = True
                quote_reason = f"PDF page count could not be extracted automatically ({note or 'Encrypted or unparseable'}). Marked for shopkeeper quote."
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unable to verify PDF pages: {note or 'Invalid or corrupted PDF file'}"
                )
        else:
            try:
                selected_pages, selected_count, _ = parse_and_validate_pages(pages, actual_page_count)
            except ValueError as ve:
                raise HTTPException(status_code=400, detail=str(ve))
    else:
        if pages.strip().lower() == "all":
            selected_count = 0
            requires_quote = True
            quote_reason = "Page count cannot be confirmed automatically for this document type. Marked for shopkeeper review and quote."
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unable to verify custom page range: {note or 'Page count cannot be confirmed automatically for this file type'}"
            )

    rate_to_check = shop.color_price if color_mode == "color" else shop.bw_price
    if rate_to_check is None or float(rate_to_check) <= 0:
        requires_quote = True
        quote_reason = "Shop rate is missing or zero for this print mode; awaiting shopkeeper quotation"

    breakdown = calculate_order_price(
        shop_bw_price=shop.bw_price,
        shop_color_price=shop.color_price,
        shop_a3_multiplier=shop.a3_multiplier,
        shop_a5_multiplier=shop.a5_multiplier,
        shop_double_sided_discount=shop.double_sided_discount,
        shop_stapling_price=shop.stapling_price,
        copies=copies,
        selected_page_count=selected_count,
        color_mode=color_mode,
        paper_size=paper_size,
        sides=sides,
        orientation=orientation,
        finishing=finishing,
        requires_quote=requires_quote,
        quote_reason=quote_reason,
        actual_page_count=actual_page_count
    )

    return {
        "filename": Path(document.filename).name,
        "size_bytes": len(content),
        "detected_page_count": actual_page_count,
        "billable_page_count": selected_count,
        "breakdown": breakdown,
        "requires_quote": requires_quote,
        "quote_reason": quote_reason,
        "note": note
    }

@app.post("/api/orders", response_model=OrderOut)
async def create_order(
    shop_id: int = Form(...),
    copies: int = Form(1),
    pages: str = Form("all"),
    color_mode: str = Form("bw"),
    paper_size: str = Form("A4"),
    sides: str = Form("single"),
    orientation: str = Form("portrait"),
    finishing: str = Form("none"),
    notes: str = Form(""),
    document: UploadFile = File(...),
    user: User = Depends(require_role("customer")),
    db: Session = Depends(get_db)
):
    shop = db.get(Shop, shop_id)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    if copies < 1 or copies > 500:
        raise HTTPException(status_code=400, detail="Copies must be between 1 and 500")

    color_mode = color_mode.lower()
    paper_size = paper_size.upper()
    sides = sides.lower()
    orientation = orientation.lower()
    finishing = finishing.lower()

    if color_mode not in ("bw", "color"):
        raise HTTPException(status_code=400, detail="Printing mode must be 'bw' or 'color'")
    if paper_size not in ("A4", "A3", "A5"):
        raise HTTPException(status_code=400, detail="Paper size must be A4, A3, or A5")
    if sides not in ("single", "double"):
        raise HTTPException(status_code=400, detail="Sides must be 'single' or 'double'")
    if orientation not in ("portrait", "landscape"):
        raise HTTPException(status_code=400, detail="Orientation must be 'portrait' or 'landscape'")
    if finishing not in ("none", "stapling"):
        raise HTTPException(status_code=400, detail="Finishing must be 'none' or 'stapling'")

    if not document.filename:
        raise HTTPException(status_code=400, detail="No document file provided")

    file_ext = Path(document.filename).suffix.lower()
    allowed_exts = (".pdf", ".txt", ".doc", ".docx", ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif")
    if file_ext not in allowed_exts:
        raise HTTPException(status_code=400, detail=f"Allowed file types: {', '.join(allowed_exts)}")

    content = await document.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty (0 bytes)")
    if len(content) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds the {MAX_UPLOAD_MB} MB limit")

    # Extract page count from document using reliable inspection
    actual_page_count, note = extract_document_page_count(content, document.filename)

    requires_quote = False
    quote_reason = ""

    # Validate requested page range
    if file_ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif"):
        if actual_page_count is None:
            raise HTTPException(status_code=400, detail=f"Invalid or corrupted image file: {note}")
        selected_count = actual_page_count
    elif file_ext == ".pdf":
        if actual_page_count is None:
            if pages.strip().lower() == "all":
                selected_count = 0
                requires_quote = True
                quote_reason = f"PDF page count could not be extracted automatically ({note or 'Encrypted or unparseable'}). Marked for shopkeeper quote."
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unable to verify PDF pages: {note or 'Invalid or corrupted PDF file'}"
                )
        else:
            try:
                selected_pages, selected_count, _ = parse_and_validate_pages(pages, actual_page_count)
            except ValueError as ve:
                raise HTTPException(status_code=400, detail=str(ve))
    else:
        # Non-PDF documents (.doc, .docx, .txt)
        if pages.strip().lower() == "all":
            selected_count = 0
            requires_quote = True
            quote_reason = "Page count cannot be confirmed automatically for this document type. Marked for shopkeeper review and quote."
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unable to verify custom page range: {note or 'Page count cannot be confirmed automatically for this file type'}"
            )

    # Check for missing or zero pricing rate from shop
    rate_to_check = shop.color_price if color_mode == "color" else shop.bw_price
    if rate_to_check is None or float(rate_to_check) <= 0:
        requires_quote = True
        quote_reason = "Shop rate is missing or zero for this print mode; awaiting shopkeeper quotation"

    # Calculate itemized price breakdown
    breakdown = calculate_order_price(
        shop_bw_price=shop.bw_price,
        shop_color_price=shop.color_price,
        shop_a3_multiplier=shop.a3_multiplier,
        shop_a5_multiplier=shop.a5_multiplier,
        shop_double_sided_discount=shop.double_sided_discount,
        shop_stapling_price=shop.stapling_price,
        copies=copies,
        selected_page_count=selected_count,
        color_mode=color_mode,
        paper_size=paper_size,
        sides=sides,
        orientation=orientation,
        finishing=finishing,
        requires_quote=requires_quote,
        quote_reason=quote_reason,
        actual_page_count=actual_page_count
    )

    # Secure file storage
    stored_name = f"{uuid4().hex}{file_ext}"
    (UPLOAD_DIR / stored_name).write_bytes(content)

    order = PrintOrder(
        customer_id=user.id,
        shop_id=shop.id,
        original_filename=Path(document.filename).name,
        stored_filename=stored_name,
        copies=copies,
        pages=pages,
        page_count=actual_page_count if actual_page_count is not None else (selected_count or 1),
        detected_page_count=actual_page_count,
        billable_page_count=selected_count,
        sheets_count=breakdown["total_sheets"],
        color_mode=color_mode,
        paper_size=paper_size,
        sides=sides,
        orientation=orientation,
        finishing=finishing,
        notes=notes[:1000] if notes else "",
        estimated_price=breakdown["subtotal"],
        final_price=breakdown["final_total"],
        price_breakdown=json.dumps(breakdown),
        requires_quote=requires_quote,
        status="pending",
        payment_status="pending"
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order_out(order, db)

@app.get("/api/orders", response_model=list[OrderOut])
def list_orders(
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    date_range: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = select(PrintOrder).options(joinedload(PrintOrder.customer), joinedload(PrintOrder.shop))

    if user.role == "customer":
        query = query.where(PrintOrder.customer_id == user.id)
    else:
        shop = db.scalar(select(Shop).where(Shop.owner_id == user.id))
        if not shop:
            return []
        query = query.where(PrintOrder.shop_id == shop.id)

    # Filter by status
    if status and status.lower() != "all":
        query = query.where(PrintOrder.status == status.lower())

    # Filter by date range
    now = datetime.now(timezone.utc)
    if date_range == "today":
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        query = query.where(PrintOrder.created_at >= start_of_day)
    elif date_range == "week":
        start_of_week = now - timedelta(days=7)
        query = query.where(PrintOrder.created_at >= start_of_week)
    elif date_range == "month":
        start_of_month = now - timedelta(days=30)
        query = query.where(PrintOrder.created_at >= start_of_month)

    orders = list(db.scalars(query.order_by(PrintOrder.created_at.desc())).all())

    # Text search
    if search and search.strip():
        term = search.strip().lower()
        filtered = []
        for o in orders:
            cust = o.customer or (db.get(User, o.customer_id) if db else None)
            c_name = cust.name.lower() if cust and cust.name else ""
            c_email = cust.email.lower() if cust and cust.email else ""
            c_phone = cust.phone.lower() if cust and cust.phone else ""
            matches = (
                term in str(o.id)
                or term in o.original_filename.lower()
                or term in c_name
                or term in c_email
                or term in c_phone
            )
            if matches:
                filtered.append(o)
        orders = filtered

    return [order_out(o, db, requesting_user=user) for o in orders]

@app.get("/api/orders/{order_id}", response_model=OrderOut)
def get_order_detail(order_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    order = db.scalar(
        select(PrintOrder)
        .options(joinedload(PrintOrder.customer), joinedload(PrintOrder.shop))
        .where(PrintOrder.id == order_id)
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if user.role == "customer":
        if order.customer_id != user.id:
            raise HTTPException(status_code=403, detail="You do not have permission to view this order")
    else:
        shop = db.scalar(select(Shop).where(Shop.owner_id == user.id))
        if not shop or shop.id != order.shop_id:
            raise HTTPException(status_code=403, detail="You do not have permission to view orders for another shop")

    return order_out(order, db, requesting_user=user)

@app.patch("/api/orders/{order_id}/status")
async def update_order_status(
    order_id: int,
    request: Request,
    user: User = Depends(require_role("shopkeeper")),
    db: Session = Depends(get_db)
):
    content_type = request.headers.get("content-type", "")
    target_status = ""
    update_reason = ""
    new_quote = None
    new_payment = ""

    if "application/json" in content_type:
        try:
            body = await request.json()
            target_status = body.get("status_value") or body.get("status") or ""
            update_reason = body.get("reason") or ""
            new_quote = body.get("quote_price")
            new_payment = body.get("payment_status") or ""
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")
    else:
        try:
            form = await request.form()
            target_status = form.get("status_value") or form.get("status") or ""
            update_reason = form.get("reason") or ""
            qp = form.get("quote_price")
            if qp is not None and str(qp).strip() != "":
                new_quote = float(qp)
            new_payment = form.get("payment_status") or ""
        except Exception:
            pass

    if not target_status and not new_payment and new_quote is None:
        raise HTTPException(status_code=400, detail="No status, quote, or payment update provided")

    shop = db.scalar(select(Shop).where(Shop.owner_id == user.id))
    order = db.get(PrintOrder, order_id)
    if not shop or not order or order.shop_id != shop.id:
        raise HTTPException(status_code=404, detail="Order not found")

    # If updating status
    if target_status and target_status.lower() != order.status:
        target_status = target_status.lower()
        if target_status not in ("pending", "accepted", "rejected", "printing", "ready", "completed", "cancelled"):
            raise HTTPException(status_code=400, detail=f"Invalid status: {target_status}")

        if order.status in ("completed", "rejected", "cancelled"):
            raise HTTPException(
                status_code=409,
                detail=f"This order is already closed ({order.status}) and cannot be changed"
            )

        allowed_next = VALID_TRANSITIONS.get(order.status, set())
        if target_status != order.status and target_status not in allowed_next:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status transition from '{order.status}' to '{target_status}'. Allowed: {', '.join(allowed_next) or 'none'}"
            )

        order.status = target_status
        if target_status == "rejected" and update_reason:
            order.rejection_reason = update_reason
        elif target_status == "cancelled" and update_reason:
            order.cancellation_reason = update_reason

    # If updating quotation price
    if new_quote is not None:
        if new_quote < 0:
            raise HTTPException(status_code=400, detail="Quote price cannot be negative")
        order.final_price = round(new_quote, 2)
        order.requires_quote = False
        try:
            bk = json.loads(order.price_breakdown or "{}")
            bk["final_total"] = order.final_price
            bk["requires_quote"] = False
            bk["quoted_by_shopkeeper"] = True
            order.price_breakdown = json.dumps(bk)
        except Exception:
            pass

    # If updating payment status
    if new_payment:
        new_payment = new_payment.lower()
        if new_payment not in ("pending", "paid", "refunded"):
            raise HTTPException(status_code=400, detail="Payment status must be 'pending', 'paid', or 'refunded'")
        if order.payment_status != new_payment:
            order.payment_status = new_payment
            if new_payment == "paid":
                order.paid_at = datetime.now(timezone.utc)
                order.paid_by_id = user.id
            elif new_payment == "pending":
                order.paid_at = None
                order.paid_by_id = None

    db.commit()
    db.refresh(order)
    return order_out(order, db)

@app.post("/api/orders/{order_id}/payment", response_model=OrderOut)
@app.patch("/api/orders/{order_id}/payment", response_model=OrderOut)
async def update_order_payment(
    order_id: int,
    data: PaymentUpdateIn = Body(default=PaymentUpdateIn()),
    user: User = Depends(require_role("shopkeeper")),
    db: Session = Depends(get_db)
):
    """
    Dedicated authenticated endpoint for authorized shopkeepers to mark an order's payment status.
    Verifies JWT, role, and shop ownership. Independent from order printing status.
    Idempotent: safe against repeated requests.
    """
    shop = db.scalar(select(Shop).where(Shop.owner_id == user.id))
    order = db.get(PrintOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if not shop or order.shop_id != shop.id:
        raise HTTPException(status_code=403, detail="You do not have permission to update payments for another shop's order")

    target_payment = data.payment_status.lower()
    if target_payment not in ("pending", "paid", "refunded"):
        raise HTTPException(status_code=400, detail="Invalid payment status. Must be 'pending', 'paid', or 'refunded'")

    # Idempotent: repeated calls when already in target state
    if order.payment_status == target_payment:
        return order_out(order, db)

    order.payment_status = target_payment
    if target_payment == "paid":
        order.paid_at = datetime.now(timezone.utc)
        order.paid_by_id = user.id
    elif target_payment == "pending":
        order.paid_at = None
        order.paid_by_id = None

    db.commit()
    db.refresh(order)
    return order_out(order, db)

@app.post("/api/orders/{order_id}/cancel", response_model=OrderOut)
def customer_cancel_order(
    order_id: int,
    data: CustomerOrderCancel = Body(default=CustomerOrderCancel()),
    user: User = Depends(require_role("customer")),
    db: Session = Depends(get_db)
):
    order = db.get(PrintOrder, order_id)
    if not order or order.customer_id != user.id:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Order cannot be cancelled because it is already {order.status}. Only pending orders can be cancelled."
        )

    order.status = "cancelled"
    order.cancellation_reason = data.reason or "Cancelled by customer"
    db.commit()
    db.refresh(order)
    return order_out(order, db)

@app.get("/api/orders/{order_id}/receipt", response_model=ReceiptOut)
def get_order_receipt(
    order_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    order = db.get(PrintOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if user.role == "customer":
        if order.customer_id != user.id:
            raise HTTPException(status_code=403, detail="Not authorized to access receipt for this order")
    else:
        shop = db.scalar(select(Shop).where(Shop.owner_id == user.id))
        if not shop or shop.id != order.shop_id:
            raise HTTPException(status_code=403, detail="Not authorized to access receipt for this order")

    customer = db.get(User, order.customer_id)
    shop = db.get(Shop, order.shop_id)

    breakdown_data = {}
    if order.price_breakdown:
        try:
            breakdown_data = json.loads(order.price_breakdown)
        except Exception:
            breakdown_data = {}

    if not breakdown_data or not breakdown_data.get("effective_page_rate"):
        base_rate = shop.color_price if order.color_mode == "color" else (shop.bw_price if shop else 2.0)
        mult = 2.0 if order.paper_size == "A3" else (0.8 if order.paper_size == "A5" else 1.0)
        eff_rate = round(base_rate * mult, 2)
        b_pages = order.billable_page_count or order.page_count or 1
        c_copies = order.copies or 1
        printed_copies = b_pages * c_copies
        print_cost = round(printed_copies * eff_rate, 2)
        actual_total = order.final_price if order.final_price > 0 else (order.estimated_price if order.estimated_price > 0 else print_cost)
        breakdown_data = {
            "currency": "INR",
            "color_mode": order.color_mode,
            "base_page_rate": round(base_rate, 2),
            "paper_size": order.paper_size,
            "size_multiplier": round(mult, 2),
            "effective_page_rate": eff_rate,
            "rate_per_page": eff_rate,
            "actual_page_count": order.detected_page_count or order.page_count or 1,
            "selected_page_count": b_pages,
            "billable_page_count": b_pages,
            "copies": c_copies,
            "printed_page_copies": printed_copies,
            "sides": order.sides,
            "orientation": order.orientation or "portrait",
            "sheets_per_copy": order.sheets_count // c_copies if c_copies > 0 else 1,
            "total_sheets": order.sheets_count or 1,
            "double_sided_discount_percent": 0.0,
            "printing_cost_per_copy": round(print_cost / c_copies, 2) if c_copies > 0 else print_cost,
            "total_printing_cost": print_cost,
            "finishing": order.finishing or "none",
            "finishing_unit_price": 0.0,
            "total_finishing_cost": 0.0,
            "subtotal": actual_total,
            "final_total": actual_total,
            "requires_quote": bool(order.requires_quote),
            "quote_reason": ""
        }

    final_amount = 0.0 if order.requires_quote else (order.final_price if order.final_price > 0 else order.estimated_price)

    return ReceiptOut(
        order_id=order.id,
        order_date=order.created_at.strftime("%d %b %Y, %I:%M %p") if order.created_at else "",
        updated_date=order.updated_at.strftime("%d %b %Y, %I:%M %p") if order.updated_at else "",
        status=order.status,
        payment_status=order.payment_status or "pending",
        paid_at=order.paid_at.strftime("%d %b %Y, %I:%M %p") if order.paid_at else None,
        requires_quote=bool(order.requires_quote),
        quote_reason=breakdown_data.get("quote_reason", ""),
        shop={
            "id": shop.id if shop else 0,
            "name": shop.name if shop else "Xerox Shop",
            "address": shop.address if shop else "",
            "phone": shop.phone if shop else ""
        },
        customer={
            "id": customer.id if customer else 0,
            "name": customer.name if customer else "Customer",
            "phone": customer.phone if customer else "",
            "email": customer.email if customer else ""
        },
        document={
            "filename": order.original_filename,
            "pages_selected": order.pages,
            "actual_page_count": order.detected_page_count or breakdown_data.get("actual_page_count") or order.page_count or 1,
            "page_count": order.page_count or 1,
            "billable_page_count": order.billable_page_count or order.page_count or 1,
            "sheets_used": order.sheets_count or 1
        },
        specifications={
            "copies": order.copies,
            "color_mode": "Colour" if order.color_mode == "color" else "Black & White",
            "paper_size": order.paper_size,
            "sides": "Double-sided" if order.sides == "double" else "Single-sided",
            "orientation": (order.orientation or "portrait").capitalize(),
            "finishing": "Stapling" if order.finishing == "stapling" else "None",
            "notes": order.notes or "None"
        },
        breakdown=breakdown_data,
        final_amount_inr=round(final_amount, 2)
    )

@app.get("/api/orders/{order_id}/download")
def download_order_file(order_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    order = db.get(PrintOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if user.role == "customer":
        if order.customer_id != user.id:
            raise HTTPException(status_code=403, detail="You do not have permission to access this order")
    elif user.role == "shopkeeper":
        shop = db.scalar(select(Shop).where(Shop.owner_id == user.id))
        if not shop or shop.id != order.shop_id:
            raise HTTPException(status_code=403, detail="You do not have permission to access orders for another shop")
    else:
        raise HTTPException(status_code=403, detail="Unauthorized role")

    if not order.stored_filename:
        raise HTTPException(status_code=404, detail="No file attached to this order")

    upload_root = UPLOAD_DIR.resolve()
    file_path = (UPLOAD_DIR / order.stored_filename).resolve()
    try:
        file_path.relative_to(upload_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid file path")

    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Uploaded file was not found on the server")

    media_type = mimetypes.guess_type(order.original_filename)[0] or "application/octet-stream"
    return FileResponse(
        path=str(file_path),
        filename=order.original_filename,
        media_type=media_type
    )

@app.get("/api/shopkeeper/qr")
def shop_qr(
    base_url: str | None = None,
    user: User = Depends(require_role("shopkeeper")),
    db: Session = Depends(get_db)
):
    shop = db.scalar(select(Shop).where(Shop.owner_id == user.id))
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    frontend_base = get_effective_frontend_url(base_url)
    url = f"{frontend_base}/customer/upload?shop={shop.id}"
    img = qrcode.make(url)
    buf = BytesIO()
    img.save(buf)
    return Response(
        content=buf.getvalue(),
        media_type="image/png",
        headers={
            "X-Shop-Order-URL": url,
            "Content-Disposition": f'inline; filename="shop-{shop.id}-qr.png"'
        }
    )
