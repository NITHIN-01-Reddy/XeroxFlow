import io
import json
from pathlib import Path
from PIL import Image
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.database import get_db
from app.models import User, Shop, PrintOrder
from app.security import create_token, hash_password
from app.config import MAX_UPLOAD_MB

def create_dummy_pdf(num_pages: int = 2) -> bytes:
    """Generate minimal syntactically valid multi-page PDF."""
    content = b"%PDF-1.4\n"
    offsets = []
    offsets.append(len(content))
    content += b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    
    page_obj_ids = [f"{3 + i} 0 R" for i in range(num_pages)]
    kids_str = " ".join(page_obj_ids)
    
    offsets.append(len(content))
    content += f"2 0 obj\n<< /Type /Pages /Kids [{kids_str}] /Count {num_pages} >>\nendobj\n".encode("latin1")
    
    for i in range(num_pages):
        offsets.append(len(content))
        obj_id = 3 + i
        content += f"{obj_id} 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n".encode("latin1")
        
    xref_offset = len(content)
    content += f"xref\n0 {len(offsets) + 1}\n0000000000 65535 f \n".encode("latin1")
    for off in offsets:
        content += f"{off:010d} 00000 n \n".encode("latin1")
        
    content += f"trailer\n<< /Size {len(offsets) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("latin1")
    return content

def run_phase3_tests():
    client = TestClient(app)
    db = next(get_db())

    print("==================================================")
    print("RUNNING XEROXFLOW SMARTPRINT PHASE 3 TEST SUITE")
    print("==================================================")

    # 1. Setup Test Users
    # Shopkeeper Surya
    surya_sk = db.scalar(select(User).where(User.email == "surya_sk@example.com"))
    if not surya_sk:
        surya_sk = User(
            name="Surya Shopkeeper",
            email="surya_sk@example.com",
            phone="9876543210",
            password_hash=hash_password("password123"),
            role="shopkeeper"
        )
        db.add(surya_sk)
        db.flush()
        surya_shop = Shop(
            owner_id=surya_sk.id,
            name="Surya Xerox",
            address="42 Main Bazaar, Near Campus",
            phone="9876543210",
            bw_price=2.0,
            color_price=10.0,
            a3_multiplier=2.0,
            a5_multiplier=0.8,
            double_sided_discount=10.0,
            stapling_price=5.0
        )
        db.add(surya_shop)
        db.commit()
        db.refresh(surya_sk)
        db.refresh(surya_shop)
    else:
        surya_shop = db.scalar(select(Shop).where(Shop.owner_id == surya_sk.id))

    # Other Shopkeeper (Beta)
    other_sk = db.scalar(select(User).where(User.email == "other_sk3@example.com"))
    if not other_sk:
        other_sk = User(
            name="Other Shopkeeper",
            email="other_sk3@example.com",
            phone="9123456789",
            password_hash=hash_password("password123"),
            role="shopkeeper"
        )
        db.add(other_sk)
        db.flush()
        other_shop = Shop(
            owner_id=other_sk.id,
            name="Other Fast Print",
            address="88 Market Lane",
            phone="9123456789",
            bw_price=3.0,
            color_price=12.0
        )
        db.add(other_shop)
        db.commit()
        db.refresh(other_sk)
        db.refresh(other_shop)
    else:
        other_shop = db.scalar(select(Shop).where(Shop.owner_id == other_sk.id))

    # Named Customer Surya Customer
    customer_surya = db.scalar(select(User).where(User.email == "surya_customer@example.com"))
    if not customer_surya:
        customer_surya = User(
            name="Surya",
            email="surya_customer@example.com",
            phone="9988776655",
            password_hash=hash_password("password123"),
            role="customer"
        )
        db.add(customer_surya)
        db.commit()
        db.refresh(customer_surya)

    # Customer with empty name to test fallback
    customer_noname = db.scalar(select(User).where(User.email == "noname_customer@example.com"))
    if not customer_noname:
        customer_noname = User(
            name="",
            email="noname_customer@example.com",
            phone="9900000000",
            password_hash=hash_password("password123"),
            role="customer"
        )
        db.add(customer_noname)
        db.commit()
        db.refresh(customer_noname)

    sk_token = create_token(surya_sk)
    other_sk_token = create_token(other_sk)
    cust_token = create_token(customer_surya)
    noname_cust_token = create_token(customer_noname)

    # --- TEST 1: Shop QR Destination Points Directly to Upload Page ---
    print("\n--- TEST 1: Shopkeeper QR Code Destination URL ---")
    r_qr = client.get("/api/shopkeeper/qr", headers={"Authorization": f"Bearer {sk_token}"})
    assert r_qr.status_code == 200, f"Expected 200, got {r_qr.status_code}: {r_qr.text}"
    qr_url = r_qr.headers.get("X-Shop-Order-URL", "")
    assert "/customer/upload?shop=" in qr_url, f"QR URL should point to /customer/upload?shop=, got: {qr_url}"
    assert f"?shop={surya_shop.id}" in qr_url, f"QR URL must contain shop ID {surya_shop.id}"
    print(f"[PASS] QR code target URL points directly to upload: {qr_url}")

    # Custom domain support
    custom_base = "https://print.surya.com"
    r_custom = client.get(f"/api/shopkeeper/qr?base_url={custom_base}", headers={"Authorization": f"Bearer {sk_token}"})
    assert r_custom.status_code == 200
    assert r_custom.headers["X-Shop-Order-URL"] == f"https://print.surya.com/customer/upload?shop={surya_shop.id}"
    print(f"[PASS] Custom base URL honored: {r_custom.headers['X-Shop-Order-URL']}")

    # --- TEST 2: Shop Details Endpoint for Upload Landing Page ---
    print("\n--- TEST 2: Shop Details Endpoint Validation ---")
    r_shop = client.get(f"/api/shops/{surya_shop.id}")
    assert r_shop.status_code == 200
    shop_data = r_shop.json()
    assert shop_data["name"] == "Surya Xerox"
    assert shop_data["bw_price"] == 2.0
    assert shop_data["color_price"] == 10.0
    print(f"[PASS] Shop details retrieved for QR landing: {shop_data['name']} (ID {shop_data['id']})")

    # Nonexistent shop returns 404
    r_bad_shop = client.get("/api/shops/999999")
    assert r_bad_shop.status_code == 404
    print("[PASS] Non-existent shop ID correctly returns 404 Not Found")

    # --- TEST 3: Pre-flight Document Inspection & Pricing ---
    print("\n--- TEST 3: Pre-flight Document Inspection (POST /api/pricing/inspect-document) ---")
    pdf_3pages = create_dummy_pdf(3)
    files = {"document": ("syllabus_chapter3.pdf", pdf_3pages, "application/pdf")}
    data = {
        "shop_id": str(surya_shop.id),
        "copies": "2",
        "color_mode": "bw",
        "paper_size": "A4",
        "sides": "single",
        "orientation": "portrait",
        "finishing": "none"
    }
    r_inspect = client.post(
        "/api/pricing/inspect-document",
        data=data,
        files=files,
        headers={"Authorization": f"Bearer {cust_token}"}
    )
    assert r_inspect.status_code == 200, f"Inspect failed: {r_inspect.text}"
    insp_data = r_inspect.json()
    assert insp_data["detected_page_count"] == 3
    assert insp_data["filename"] == "syllabus_chapter3.pdf"
    assert insp_data["breakdown"]["final_total"] == 12.0  # 3 pages * 2 copies * ₹2.00 = ₹12.00
    print(f"[PASS] PDF inspection accurately extracted 3 pages; breakdown total: INR {insp_data['breakdown']['final_total']}")

    # --- TEST 4: Image Inspection (1 page) ---
    print("\n--- TEST 4: Image File Inspection ---")
    img_buf = io.BytesIO()
    Image.new("RGB", (100, 100), color="blue").save(img_buf, format="PNG")
    img_bytes = img_buf.getvalue()
    files_img = {"document": ("id_card_scan.png", img_bytes, "image/png")}
    data_img = {
        "shop_id": str(surya_shop.id),
        "copies": "1",
        "color_mode": "color",
        "paper_size": "A4",
        "sides": "single"
    }
    r_img_inspect = client.post(
        "/api/pricing/inspect-document",
        data=data_img,
        files=files_img,
        headers={"Authorization": f"Bearer {cust_token}"}
    )
    assert r_img_inspect.status_code == 200
    img_insp_data = r_img_inspect.json()
    assert img_insp_data["detected_page_count"] == 1
    assert img_insp_data["breakdown"]["final_total"] == 10.0  # 1 page * ₹10.00 = ₹10.00
    print(f"[PASS] Image file detected as 1 page; Colour total: INR {img_insp_data['breakdown']['final_total']}")

    # --- TEST 5: Corrupt & Oversized File Handling ---
    print("\n--- TEST 5: Corrupt & Oversized File Rejection ---")
    corrupt_files = {"document": ("corrupt.png", b"NOT_A_VALID_IMAGE_DATA", "image/png")}
    r_corrupt = client.post(
        "/api/pricing/inspect-document",
        data={"shop_id": str(surya_shop.id)},
        files=corrupt_files,
        headers={"Authorization": f"Bearer {cust_token}"}
    )
    assert r_corrupt.status_code == 400
    print("[PASS] Corrupt image rejected by inspect-document with 400")

    empty_files = {"document": ("empty.pdf", b"", "application/pdf")}
    r_empty = client.post(
        "/api/pricing/inspect-document",
        data={"shop_id": str(surya_shop.id)},
        files=empty_files,
        headers={"Authorization": f"Bearer {cust_token}"}
    )
    assert r_empty.status_code == 400
    print("[PASS] Empty file rejected by inspect-document with 400")

    # --- TEST 6: Direct Order Creation by Authenticated Customer ---
    print("\n--- TEST 6: Direct Order Creation ---")
    files_order = {"document": ("xeroxflow_lab_manual.pdf", create_dummy_pdf(4), "application/pdf")}
    order_data = {
        "shop_id": str(surya_shop.id),
        "copies": "1",
        "pages": "all",
        "color_mode": "bw",
        "paper_size": "A4",
        "sides": "double",
        "notes": "Please staple on the top-left corner"
    }
    r_create = client.post(
        "/api/orders",
        data=order_data,
        files=files_order,
        headers={"Authorization": f"Bearer {cust_token}"}
    )
    assert r_create.status_code == 200, f"Order creation failed: {r_create.text}"
    order1 = r_create.json()
    assert order1["shop_id"] == surya_shop.id
    assert order1["original_filename"] == "xeroxflow_lab_manual.pdf"
    assert order1["customer_name"] == "Surya"
    print(f"[PASS] Customer Surya placed Order #{order1['id']} at {surya_shop.name}")

    # Create second order with no-name customer to test fallback
    files_order2 = {"document": ("assignment_draft.pdf", create_dummy_pdf(2), "application/pdf")}
    r_create2 = client.post(
        "/api/orders",
        data={"shop_id": str(surya_shop.id), "copies": "1", "color_mode": "bw"},
        files=files_order2,
        headers={"Authorization": f"Bearer {noname_cust_token}"}
    )
    assert r_create2.status_code == 200
    order2 = r_create2.json()
    assert order2["customer_name"] == "Customer"
    print(f"[PASS] No-name customer order created with fallback name: {order2['customer_name']} (Order #{order2['id']})")

    # --- TEST 7: Shopkeeper Order Display Prioritizes Customer Name ---
    print("\n--- TEST 7: Shopkeeper Order Display & Customer Name Hierarchy ---")
    r_sk_orders = client.get("/api/orders", headers={"Authorization": f"Bearer {sk_token}"})
    assert r_sk_orders.status_code == 200
    sk_orders = r_sk_orders.json()
    
    # Locate Order #1 (Surya)
    surya_o1 = next((o for o in sk_orders if o["id"] == order1["id"]), None)
    assert surya_o1 is not None, f"Order #{order1['id']} not found in shopkeeper list"
    assert surya_o1["customer_name"] == "Surya", f"Expected customer name 'Surya', got {surya_o1['customer_name']}"
    assert surya_o1["original_filename"] == "xeroxflow_lab_manual.pdf"
    assert surya_o1["customer_phone"] == "9988776655"
    print(f"[PASS] Shopkeeper sees customer name in order title: '{surya_o1['customer_name']} · Order #{surya_o1['id']}'")
    print(f"[PASS] Document filename preserved underneath: 'File: {surya_o1['original_filename']}'")

    # Locate Order #2 (Fallback Customer)
    fallback_o2 = next((o for o in sk_orders if o["id"] == order2["id"]), None)
    assert fallback_o2 is not None
    assert fallback_o2["customer_name"] == "Customer"
    print(f"[PASS] Missing customer name displays fallback: '{fallback_o2['customer_name']} · Order #{fallback_o2['id']}'")

    # --- TEST 8: Cross-Shop Isolation for Customer Metadata ---
    print("\n--- TEST 8: Customer Info Privacy & Cross-Shop Isolation ---")
    r_other_orders = client.get("/api/orders", headers={"Authorization": f"Bearer {other_sk_token}"})
    assert r_other_orders.status_code == 200
    other_orders = r_other_orders.json()
    # Ensure other shopkeeper cannot see Surya's orders
    assert not any(o["id"] == order1["id"] for o in other_orders), "Cross-shop leak: Other shopkeeper saw Surya Xerox's order!"
    print("[PASS] Other shopkeeper cannot see orders from Surya Xerox")

    # Attempting to fetch detail directly returns 403
    r_tamper = client.get(f"/api/orders/{order1['id']}", headers={"Authorization": f"Bearer {other_sk_token}"})
    assert r_tamper.status_code == 403
    print("[PASS] Unauthorized shopkeeper blocked from viewing order details (403 Forbidden)")

    print("\n==================================================")
    print("ALL PHASE 3 TEST SUITES PASSED PERFECTLY!")
    print("==================================================")

if __name__ == "__main__":
    run_phase3_tests()
