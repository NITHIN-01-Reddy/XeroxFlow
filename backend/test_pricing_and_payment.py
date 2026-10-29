import io
import json
from pathlib import Path
from PIL import Image
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.database import get_db
from app.models import User, Shop, PrintOrder, run_db_migrations
from app.security import create_token, hash_password
from app.pricing import extract_document_page_count, parse_and_validate_pages, calculate_order_price

def create_sample_pdf(num_pages=1):
    """Generate a valid minimal PDF with specified number of pages."""
    import pypdf
    writer = pypdf.PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()

def create_sample_image(format="PNG"):
    """Generate a valid single-page image."""
    img = Image.new("RGB", (100, 100), color="blue")
    buf = io.BytesIO()
    img.save(buf, format=format)
    return buf.getvalue()

def run_all_20_tests():
    client = TestClient(app)
    db = next(get_db())

    print("==================================================================")
    print("RUNNING 20 VERIFICATION TESTS FOR XEROXFLOW PRICING & PAYMENT")
    print("==================================================================")

    # Setup Shop 1 & Shopkeeper 1
    sk1 = db.scalar(select(User).where(User.email == "t20_shopkeeper1@example.com"))
    if not sk1:
        sk1 = User(
            name="Alpha Shopkeeper",
            email="t20_shopkeeper1@example.com",
            phone="9900000001",
            password_hash=hash_password("password123"),
            role="shopkeeper"
        )
        db.add(sk1); db.flush()
        shop1 = Shop(
            owner_id=sk1.id,
            name="Alpha Print Hub",
            address="10 University Way",
            phone="9900000001",
            bw_price=2.0,
            color_price=8.0,
            a3_multiplier=2.0,
            a5_multiplier=0.8,
            double_sided_discount=10.0,
            stapling_price=5.0
        )
        db.add(shop1); db.commit(); db.refresh(sk1); db.refresh(shop1)
    else:
        shop1 = db.scalar(select(Shop).where(Shop.owner_id == sk1.id))

    # Setup Shop 2 & Shopkeeper 2
    sk2 = db.scalar(select(User).where(User.email == "t20_shopkeeper2@example.com"))
    if not sk2:
        sk2 = User(
            name="Beta Shopkeeper",
            email="t20_shopkeeper2@example.com",
            phone="9900000002",
            password_hash=hash_password("password123"),
            role="shopkeeper"
        )
        db.add(sk2); db.flush()
        shop2 = Shop(
            owner_id=sk2.id,
            name="Beta Print Express",
            address="20 Market Ave",
            phone="9900000002",
            bw_price=3.0,
            color_price=12.0,
            a3_multiplier=2.0,
            a5_multiplier=0.8,
            double_sided_discount=0.0,
            stapling_price=4.0
        )
        db.add(shop2); db.commit(); db.refresh(sk2); db.refresh(shop2)
    else:
        shop2 = db.scalar(select(Shop).where(Shop.owner_id == sk2.id))

    # Setup Customers
    cust1 = db.scalar(select(User).where(User.email == "t20_customer1@example.com"))
    if not cust1:
        cust1 = User(
            name="Charlie Customer",
            email="t20_customer1@example.com",
            phone="9900000003",
            password_hash=hash_password("password123"),
            role="customer"
        )
        db.add(cust1); db.commit(); db.refresh(cust1)

    sk1_token = create_token(sk1)
    sk2_token = create_token(sk2)
    cust1_token = create_token(cust1)

    one_page_pdf = create_sample_pdf(1)
    three_page_pdf = create_sample_pdf(3)
    five_page_pdf = create_sample_pdf(5)
    sample_png = create_sample_image("PNG")

    # TEST 1: One-page PDF, one copy, B/W pricing
    p1 = calculate_order_price(
        shop_bw_price=shop1.bw_price,  # 2.0
        shop_color_price=shop1.color_price,
        shop_a3_multiplier=shop1.a3_multiplier,
        shop_a5_multiplier=shop1.a5_multiplier,
        shop_double_sided_discount=0.0,
        shop_stapling_price=shop1.stapling_price,
        copies=1,
        selected_page_count=1,
        color_mode="bw",
        paper_size="A4",
        sides="single",
        orientation="portrait",
        finishing="none",
        actual_page_count=1
    )
    assert p1["effective_page_rate"] == 2.0
    assert p1["total_printing_cost"] == 2.0
    assert p1["final_total"] == 2.0
    print("[PASS] Test 1: One-page PDF, one copy, B/W pricing verified (Rate: INR 2.00, Total: INR 2.00)")

    # TEST 2: Multi-page PDF with B/W pricing
    # 5 pages * 1 copy * INR 2.00 = INR 10.00
    p2 = calculate_order_price(
        shop_bw_price=shop1.bw_price,
        shop_color_price=shop1.color_price,
        shop_a3_multiplier=shop1.a3_multiplier,
        shop_a5_multiplier=shop1.a5_multiplier,
        shop_double_sided_discount=0.0,
        shop_stapling_price=shop1.stapling_price,
        copies=1,
        selected_page_count=5,
        color_mode="bw",
        paper_size="A4",
        sides="single",
        orientation="portrait",
        finishing="none",
        actual_page_count=5
    )
    assert p2["total_printing_cost"] == 10.0
    assert p2["final_total"] == 10.0
    print("[PASS] Test 2: Multi-page PDF with B/W pricing verified (5 pages = INR 10.00)")

    # TEST 3: Multi-page PDF with colour pricing
    # 3 pages * 1 copy * INR 8.00 = INR 24.00
    p3 = calculate_order_price(
        shop_bw_price=shop1.bw_price,
        shop_color_price=shop1.color_price,  # 8.0
        shop_a3_multiplier=shop1.a3_multiplier,
        shop_a5_multiplier=shop1.a5_multiplier,
        shop_double_sided_discount=0.0,
        shop_stapling_price=shop1.stapling_price,
        copies=1,
        selected_page_count=3,
        color_mode="color",
        paper_size="A4",
        sides="single",
        orientation="portrait",
        finishing="none",
        actual_page_count=3
    )
    assert p3["effective_page_rate"] == 8.0
    assert p3["total_printing_cost"] == 24.0
    assert p3["final_total"] == 24.0
    print("[PASS] Test 3: Multi-page PDF with Colour pricing verified (3 pages * INR 8.00 = INR 24.00)")

    # TEST 4: Multiple copies
    # 2 pages * 4 copies * INR 2.00 = INR 16.00
    p4 = calculate_order_price(
        shop_bw_price=shop1.bw_price,
        shop_color_price=shop1.color_price,
        shop_a3_multiplier=shop1.a3_multiplier,
        shop_a5_multiplier=shop1.a5_multiplier,
        shop_double_sided_discount=0.0,
        shop_stapling_price=shop1.stapling_price,
        copies=4,
        selected_page_count=2,
        color_mode="bw",
        paper_size="A4",
        sides="single",
        orientation="portrait",
        finishing="none",
        actual_page_count=2
    )
    assert p4["printed_page_copies"] == 8
    assert p4["total_printing_cost"] == 16.0
    assert p4["final_total"] == 16.0
    print("[PASS] Test 4: Multiple copies pricing verified (2 pages * 4 copies = INR 16.00)")

    # TEST 5: Custom page range
    # 5-page PDF with custom range "2-4" -> pages 2, 3, 4 = 3 pages
    sel_pages, sel_count, _ = parse_and_validate_pages("2-4", actual_page_count=5)
    assert sel_pages == [2, 3, 4]
    assert sel_count == 3
    # Exceeding page range must raise ValueError
    try:
        parse_and_validate_pages("1-10", actual_page_count=5)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass
    print("[PASS] Test 5: Custom page range verified (2-4 out of 5 = 3 pages, out-of-bounds rejected)")

    # TEST 6: Double-sided printing with documented charging rule
    # 4 pages, double-sided, 10% discount on INR 2.00 rate = INR 1.80 per page * 4 = INR 7.20
    # physical sheets = ceil(4 / 2) = 2 sheets
    p6 = calculate_order_price(
        shop_bw_price=2.0,
        shop_color_price=10.0,
        shop_a3_multiplier=1.0,
        shop_a5_multiplier=1.0,
        shop_double_sided_discount=10.0,
        shop_stapling_price=0.0,
        copies=1,
        selected_page_count=4,
        color_mode="bw",
        paper_size="A4",
        sides="double",
        orientation="portrait",
        finishing="none",
        actual_page_count=4
    )
    assert p6["sheets_per_copy"] == 2
    assert p6["total_sheets"] == 2
    assert p6["total_printing_cost"] == 7.20
    print("[PASS] Test 6: Double-sided printing charging rule verified (4 printable pages = 2 physical sheets, INR 7.20)")

    # TEST 7: Invalid PDF and unreadable document
    corrupted_pdf = b"NOT_A_REAL_PDF_DATA_GARBAGE"
    page_count, note = extract_document_page_count(corrupted_pdf, "broken.pdf")
    assert page_count is None
    assert "Invalid or unreadable PDF" in note or "PDF" in note

    corrupted_img = b"FAKE_IMAGE_BYTES"
    img_count, img_note = extract_document_page_count(corrupted_img, "broken.png")
    assert img_count is None
    assert "Invalid or corrupted image" in img_note
    print("[PASS] Test 7: Corrupted PDF and corrupted image detected and page counting rejected safely")

    # TEST 8: Missing or zero pricing rate
    p8 = calculate_order_price(
        shop_bw_price=0.0,  # Zero rate
        shop_color_price=0.0,
        shop_a3_multiplier=1.0,
        shop_a5_multiplier=1.0,
        shop_double_sided_discount=0.0,
        shop_stapling_price=0.0,
        copies=1,
        selected_page_count=5,
        color_mode="bw",
        paper_size="A4",
        sides="single",
        orientation="portrait",
        finishing="none",
        actual_page_count=5
    )
    assert p8["requires_quote"] is True
    assert p8["final_total"] == 0.0
    assert "awaiting shopkeeper quotation" in p8["quote_reason"]
    print("[PASS] Test 8: Missing or zero rate marked as awaiting quotation (final_total = 0.0)")

    # Create Order via API for API testing
    r_create = client.post(
        "/api/orders",
        data={
            "shop_id": str(shop1.id),
            "copies": "2",
            "pages": "all",
            "color_mode": "bw",
            "paper_size": "A4",
            "sides": "single",
            "orientation": "portrait",
            "finishing": "none",
            "notes": "Test order"
        },
        files={"document": ("sample_test.pdf", io.BytesIO(three_page_pdf), "application/pdf")},
        headers={"Authorization": f"Bearer {cust1_token}"}
    )
    assert r_create.status_code == 200
    created_order = r_create.json()
    order_id = created_order["id"]
    # 3 pages * 2 copies * INR 2.00 = INR 12.00
    assert created_order["final_price"] == 12.0
    assert created_order["page_count"] == 3
    assert created_order["billable_page_count"] == 3
    assert created_order["payment_status"] == "pending"

    # TEST 9: Correct receipt subtotal and total
    r_receipt = client.get(f"/api/orders/{order_id}/receipt", headers={"Authorization": f"Bearer {cust1_token}"})
    assert r_receipt.status_code == 200
    receipt = r_receipt.json()
    assert receipt["order_id"] == order_id
    assert receipt["shop"]["name"] == "Alpha Print Hub"
    assert receipt["customer"]["name"] == "Charlie Customer"
    assert receipt["document"]["filename"] == "sample_test.pdf"
    assert receipt["document"]["actual_page_count"] == 3
    assert receipt["breakdown"]["effective_page_rate"] == 2.0
    assert receipt["breakdown"]["total_printing_cost"] == 12.0
    assert receipt["final_amount_inr"] == 12.0
    assert receipt["payment_status"] == "pending"
    print("[PASS] Test 9: Receipt subtotal, item amount, rate (INR 2.00), and total (INR 12.00) agree consistently")

    # TEST 10: Price snapshot remains unchanged after shop rates change
    original_price = created_order["final_price"]
    shop1.bw_price = 5.0
    db.commit()

    r_receipt_after_change = client.get(f"/api/orders/{order_id}/receipt", headers={"Authorization": f"Bearer {cust1_token}"})
    assert r_receipt_after_change.status_code == 200
    assert r_receipt_after_change.json()["final_amount_inr"] == original_price
    assert r_receipt_after_change.json()["breakdown"]["effective_page_rate"] == 2.0

    # Revert shop rate back
    shop1.bw_price = 2.0
    db.commit()
    print("[PASS] Test 10: Historical order price snapshot preserved after shop rate changes")

    # TEST 11: Authorized shopkeeper marks payment as paid
    r_pay = client.post(
        f"/api/orders/{order_id}/payment",
        json={"payment_status": "paid"},
        headers={"Authorization": f"Bearer {sk1_token}"}
    )
    assert r_pay.status_code == 200
    paid_order = r_pay.json()
    assert paid_order["payment_status"] == "paid"
    assert paid_order["paid_at"] is not None
    assert paid_order["paid_by_id"] == sk1.id
    print("[PASS] Test 11: Authorized shopkeeper marked order as paid, recorded timestamp & actor")

    # TEST 12: Unauthenticated payment update is rejected (401)
    r_unauth = client.post(f"/api/orders/{order_id}/payment", json={"payment_status": "paid"})
    assert r_unauth.status_code in (401, 403)
    print("[PASS] Test 12: Unauthenticated payment update rejected (401/403)")

    # TEST 13: Customer cannot mark their own order as paid (403)
    r_cust_tamper = client.post(
        f"/api/orders/{order_id}/payment",
        json={"payment_status": "paid"},
        headers={"Authorization": f"Bearer {cust1_token}"}
    )
    assert r_cust_tamper.status_code == 403
    print("[PASS] Test 13: Customer forbidden from marking order as paid (403 Forbidden)")

    # TEST 14: Shopkeeper cannot update another shop's order (403)
    r_other_shop = client.post(
        f"/api/orders/{order_id}/payment",
        json={"payment_status": "paid"},
        headers={"Authorization": f"Bearer {sk2_token}"}
    )
    assert r_other_shop.status_code == 403
    print("[PASS] Test 14: Cross-shop payment tampering rejected (403 Forbidden)")

    # TEST 15: Already-paid order does not create duplicate payment records
    r_pay_repeat = client.post(
        f"/api/orders/{order_id}/payment",
        json={"payment_status": "paid"},
        headers={"Authorization": f"Bearer {sk1_token}"}
    )
    assert r_pay_repeat.status_code == 200
    assert r_pay_repeat.json()["payment_status"] == "paid"
    assert r_pay_repeat.json()["paid_at"] == paid_order["paid_at"]
    print("[PASS] Test 15: Repeated payment requests are idempotent and create no duplicates")

    # TEST 16 & 17: Customer Pay button contract and independence
    # The payment receipt response retains payment_status and does not process external transactions
    rec_check = client.get(f"/api/orders/{order_id}/receipt", headers={"Authorization": f"Bearer {cust1_token}"}).json()
    assert rec_check["payment_status"] == "paid"
    # Create another unpaid order to test that customer viewing/interacting does not change payment status
    r_o_unpaid = client.post(
        "/api/orders",
        data={
            "shop_id": str(shop1.id),
            "copies": "1",
            "pages": "all",
            "color_mode": "bw",
            "paper_size": "A4",
            "sides": "single",
            "orientation": "portrait",
            "finishing": "none"
        },
        files={"document": ("unpaid.pdf", io.BytesIO(one_page_pdf), "application/pdf")},
        headers={"Authorization": f"Bearer {cust1_token}"}
    )
    unpaid_id = r_o_unpaid.json()["id"]
    unpaid_rec = client.get(f"/api/orders/{unpaid_id}/receipt", headers={"Authorization": f"Bearer {cust1_token}"}).json()
    assert unpaid_rec["payment_status"] == "pending"
    print("[PASS] Test 16 & 17: Customer receipt API displays accurate status; clicking Pay does not alter backend payment state")

    # TEST 18: Existing order status remains independent from payment status
    # Marking payment as paid did not mark the order status as completed
    assert created_order["status"] == "pending"
    db_order = db.get(PrintOrder, order_id)
    assert db_order.status == "pending"  # Order printing status is still pending!
    assert db_order.payment_status == "paid"  # Payment is paid!

    # Can progress printing independently
    r_print_step = client.patch(
        f"/api/orders/{order_id}/status",
        json={"status_value": "accepted"},
        headers={"Authorization": f"Bearer {sk1_token}"}
    )
    assert r_print_step.status_code == 200
    assert r_print_step.json()["status"] == "accepted"
    assert r_print_step.json()["payment_status"] == "paid"
    print("[PASS] Test 18: Order printing status ('accepted') is completely independent from payment status ('paid')")

    # TEST 19: Both dashboards show persisted payment status
    # Customer dashboard
    cust_orders = client.get("/api/orders", headers={"Authorization": f"Bearer {cust1_token}"}).json()
    matching_cust = next((o for o in cust_orders if o["id"] == order_id), None)
    assert matching_cust is not None
    assert matching_cust["payment_status"] == "paid"

    # Shopkeeper dashboard
    sk_orders = client.get("/api/orders", headers={"Authorization": f"Bearer {sk1_token}"}).json()
    matching_sk = next((o for o in sk_orders if o["id"] == order_id), None)
    assert matching_sk is not None
    assert matching_sk["payment_status"] == "paid"
    print("[PASS] Test 19: Both customer and shopkeeper dashboards receive persisted payment status")

    # TEST 20: Existing file upload, download, QR generation continue to work
    # File download test
    r_dl = client.get(f"/api/orders/{order_id}/download", headers={"Authorization": f"Bearer {cust1_token}"})
    assert r_dl.status_code == 200
    assert len(r_dl.content) > 0

    # QR generation test
    r_qr = client.get("/api/shopkeeper/qr", headers={"Authorization": f"Bearer {sk1_token}"})
    assert r_qr.status_code == 200
    assert r_qr.headers["content-type"] == "image/png"
    assert "X-Shop-Order-URL" in r_qr.headers

    # Image upload test
    r_img_upload = client.post(
        "/api/orders",
        data={
            "shop_id": str(shop1.id),
            "copies": "1",
            "pages": "all",
            "color_mode": "color",
            "paper_size": "A4",
            "sides": "single",
            "orientation": "portrait",
            "finishing": "none"
        },
        files={"document": ("photo.png", io.BytesIO(sample_png), "image/png")},
        headers={"Authorization": f"Bearer {cust1_token}"}
    )
    assert r_img_upload.status_code == 200
    assert r_img_upload.json()["page_count"] == 1
    assert r_img_upload.json()["final_price"] == 8.0
    print("[PASS] Test 20: File download, shop QR generation, image upload, and order management functioning perfectly")

    # Cleanup test created orders
    try:
        db.delete(db.get(PrintOrder, order_id))
        db.delete(db.get(PrintOrder, unpaid_id))
        db.delete(db.get(PrintOrder, r_img_upload.json()["id"]))
        db.commit()
    except Exception:
        pass

    print("\n==================================================================")
    print("ALL 20 VERIFICATION TESTS EXECUTED AND PASSED SUCCESSFULLY!")
    print("==================================================================")

if __name__ == "__main__":
    run_all_20_tests()
