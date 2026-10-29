from datetime import datetime, timezone
from sqlalchemy import String, Integer, Float, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

def utcnow():
    return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[str] = mapped_column(String(30), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    shop: Mapped["Shop | None"] = relationship(back_populates="owner", uselist=False)

class Shop(Base):
    __tablename__ = "shops"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    address: Mapped[str] = mapped_column(String(300), default="")
    phone: Mapped[str] = mapped_column(String(30), default="")
    bw_price: Mapped[float] = mapped_column(Float, default=2.0)
    color_price: Mapped[float] = mapped_column(Float, default=10.0)
    a3_multiplier: Mapped[float] = mapped_column(Float, default=2.0)
    a5_multiplier: Mapped[float] = mapped_column(Float, default=0.8)
    double_sided_discount: Mapped[float] = mapped_column(Float, default=0.0)
    stapling_price: Mapped[float] = mapped_column(Float, default=5.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    owner: Mapped[User] = relationship(back_populates="shop")
    orders: Mapped[list["PrintOrder"]] = relationship(back_populates="shop")

class PrintOrder(Base):
    __tablename__ = "print_orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_filename: Mapped[str] = mapped_column(String(255))
    copies: Mapped[int] = mapped_column(Integer, default=1)
    pages: Mapped[str] = mapped_column(String(100), default="all")
    page_count: Mapped[int] = mapped_column(Integer, default=1)
    sheets_count: Mapped[int] = mapped_column(Integer, default=1)
    color_mode: Mapped[str] = mapped_column(String(20), default="bw")
    paper_size: Mapped[str] = mapped_column(String(10), default="A4")
    sides: Mapped[str] = mapped_column(String(20), default="single")
    orientation: Mapped[str] = mapped_column(String(20), default="portrait")
    finishing: Mapped[str] = mapped_column(String(30), default="none")
    notes: Mapped[str] = mapped_column(Text, default="")
    estimated_price: Mapped[float] = mapped_column(Float, default=0.0)
    final_price: Mapped[float] = mapped_column(Float, default=0.0)
    price_breakdown: Mapped[str] = mapped_column(Text, default="{}")
    requires_quote: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    payment_status: Mapped[str] = mapped_column(String(30), default="pending")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    paid_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, default=None)
    detected_page_count: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    billable_page_count: Mapped[int] = mapped_column(Integer, default=1)
    cancellation_reason: Mapped[str] = mapped_column(String(255), default="")
    rejection_reason: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    shop: Mapped[Shop] = relationship(back_populates="orders")
    customer: Mapped[User] = relationship(foreign_keys=[customer_id])


def run_db_migrations(engine):
    """
    Safely update SQLite database tables with new columns if they do not exist.
    Preserves all existing data, users, shops, and orders.
    """
    import json
    with engine.begin() as conn:
        # 1. Update shops table
        shop_cols = [c[1] for c in conn.exec_driver_sql("PRAGMA table_info(shops)").fetchall()]
        if "a3_multiplier" not in shop_cols:
            conn.exec_driver_sql("ALTER TABLE shops ADD COLUMN a3_multiplier FLOAT DEFAULT 2.0")
        if "a5_multiplier" not in shop_cols:
            conn.exec_driver_sql("ALTER TABLE shops ADD COLUMN a5_multiplier FLOAT DEFAULT 0.8")
        if "stapling_price" not in shop_cols:
            conn.exec_driver_sql("ALTER TABLE shops ADD COLUMN stapling_price FLOAT DEFAULT 5.0")

        # 2. Update print_orders table
        order_cols = [c[1] for c in conn.exec_driver_sql("PRAGMA table_info(print_orders)").fetchall()]
        if "orientation" not in order_cols:
            conn.exec_driver_sql("ALTER TABLE print_orders ADD COLUMN orientation VARCHAR(20) DEFAULT 'portrait'")
        if "finishing" not in order_cols:
            conn.exec_driver_sql("ALTER TABLE print_orders ADD COLUMN finishing VARCHAR(30) DEFAULT 'none'")
        if "page_count" not in order_cols:
            conn.exec_driver_sql("ALTER TABLE print_orders ADD COLUMN page_count INTEGER DEFAULT 1")
        if "sheets_count" not in order_cols:
            conn.exec_driver_sql("ALTER TABLE print_orders ADD COLUMN sheets_count INTEGER DEFAULT 1")
        if "price_breakdown" not in order_cols:
            conn.exec_driver_sql("ALTER TABLE print_orders ADD COLUMN price_breakdown TEXT DEFAULT '{}'")
        if "requires_quote" not in order_cols:
            conn.exec_driver_sql("ALTER TABLE print_orders ADD COLUMN requires_quote BOOLEAN DEFAULT 0")
        if "final_price" not in order_cols:
            conn.exec_driver_sql("ALTER TABLE print_orders ADD COLUMN final_price FLOAT DEFAULT 0.0")
        if "payment_status" not in order_cols:
            conn.exec_driver_sql("ALTER TABLE print_orders ADD COLUMN payment_status VARCHAR(30) DEFAULT 'pending'")
        if "paid_at" not in order_cols:
            conn.exec_driver_sql("ALTER TABLE print_orders ADD COLUMN paid_at DATETIME DEFAULT NULL")
        if "paid_by_id" not in order_cols:
            conn.exec_driver_sql("ALTER TABLE print_orders ADD COLUMN paid_by_id INTEGER DEFAULT NULL")
        if "detected_page_count" not in order_cols:
            conn.exec_driver_sql("ALTER TABLE print_orders ADD COLUMN detected_page_count INTEGER DEFAULT NULL")
        if "billable_page_count" not in order_cols:
            conn.exec_driver_sql("ALTER TABLE print_orders ADD COLUMN billable_page_count INTEGER DEFAULT 1")
        if "cancellation_reason" not in order_cols:
            conn.exec_driver_sql("ALTER TABLE print_orders ADD COLUMN cancellation_reason VARCHAR(255) DEFAULT ''")
        if "rejection_reason" not in order_cols:
            conn.exec_driver_sql("ALTER TABLE print_orders ADD COLUMN rejection_reason VARCHAR(255) DEFAULT ''")

        # 3. Safe historical order repair for empty or corrupt price_breakdown
        rows = conn.exec_driver_sql(
            "SELECT id, shop_id, copies, page_count, color_mode, paper_size, sides, orientation, finishing, "
            "estimated_price, final_price, price_breakdown, detected_page_count, billable_page_count "
            "FROM print_orders"
        ).fetchall()

        for row in rows:
            oid, s_id, copies, p_count, c_mode, p_size, sides, orient, fin, est, fin_price, bk_raw, det_p, bill_p = row
            bk_data = {}
            needs_repair = False
            try:
                bk_data = json.loads(bk_raw or "{}")
            except Exception:
                needs_repair = True

            effective_rate = bk_data.get("effective_page_rate") or bk_data.get("base_page_rate")
            if not effective_rate or effective_rate <= 0:
                needs_repair = True

            if needs_repair:
                # Lookup shop rates
                shop_row = conn.exec_driver_sql("SELECT bw_price, color_price, a3_multiplier, a5_multiplier, double_sided_discount, stapling_price FROM shops WHERE id = ?", (s_id,)).fetchone()
                if shop_row:
                    s_bw, s_col, s_a3, s_a5, s_dup, s_stap = shop_row
                else:
                    s_bw, s_col, s_a3, s_a5, s_dup, s_stap = (2.0, 10.0, 2.0, 0.8, 0.0, 5.0)

                base_rate = s_col if c_mode == "color" else s_bw
                mult = s_a3 if p_size == "A3" else (s_a5 if p_size == "A5" else 1.0)
                eff_rate = round(base_rate * mult, 2)
                b_pages = bill_p or p_count or 1
                c_copies = copies or 1
                printed_copies = b_pages * c_copies
                if sides == "double":
                    import math
                    sheets = max(1, math.ceil(b_pages / 2)) * c_copies
                    disc_factor = max(0.0, 1.0 - ((s_dup or 0.0) / 100.0))
                    print_cost = round(printed_copies * eff_rate * disc_factor, 2)
                else:
                    sheets = b_pages * c_copies
                    print_cost = round(printed_copies * eff_rate, 2)

                stap_cost = round((s_stap or 0.0) * c_copies, 2) if fin == "stapling" else 0.0
                calc_sub = round(print_cost + stap_cost, 2)
                actual_total = fin_price if fin_price and fin_price > 0 else (est if est and est > 0 else calc_sub)

                repaired_bk = {
                    "currency": "INR",
                    "color_mode": c_mode,
                    "base_page_rate": round(base_rate, 2),
                    "paper_size": p_size,
                    "size_multiplier": round(mult, 2),
                    "effective_page_rate": eff_rate,
                    "rate_per_page": eff_rate,
                    "actual_page_count": det_p or p_count or 1,
                    "selected_page_count": b_pages,
                    "billable_page_count": b_pages,
                    "copies": c_copies,
                    "printed_page_copies": printed_copies,
                    "sides": sides,
                    "orientation": orient or "portrait",
                    "sheets_per_copy": sheets // c_copies if c_copies > 0 else sheets,
                    "total_sheets": sheets,
                    "double_sided_discount_percent": s_dup or 0.0,
                    "printing_cost_per_copy": round(print_cost / c_copies, 2) if c_copies > 0 else print_cost,
                    "total_printing_cost": print_cost,
                    "finishing": fin or "none",
                    "finishing_unit_price": s_stap if fin == "stapling" else 0.0,
                    "total_finishing_cost": stap_cost,
                    "subtotal": actual_total,
                    "final_total": actual_total,
                    "requires_quote": False,
                    "quote_reason": ""
                }
                conn.exec_driver_sql(
                    "UPDATE print_orders SET price_breakdown = ?, estimated_price = ?, final_price = ?, billable_page_count = ?, detected_page_count = coalesce(detected_page_count, ?) WHERE id = ?",
                    (json.dumps(repaired_bk), actual_total, actual_total, b_pages, p_count or 1, oid)
                )
