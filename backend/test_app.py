import io
from pathlib import Path
from PIL import Image
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.database import get_db
from app.models import User, Shop, PrintOrder
from app.config import UPLOAD_DIR
from app.security import create_token, hash_password

def run_tests():
    client = TestClient(app)
    db = next(get_db())

    print("==================================================")
    print("RUNNING XEROXFLOW SMARTPRINT BUG VERIFICATION TESTS")
    print("==================================================")

    # 1. Setup Test Users and Shops
    shopkeeper_user = db.scalar(select(User).where(User.email == "test_shopkeeper@example.com"))
    if not shopkeeper_user:
        shopkeeper_user = User(
            name="Test Shopkeeper",
            email="test_shopkeeper@example.com",
            phone="9876543210",
            password_hash=hash_password("password123"),
            role="shopkeeper"
        )
        db.add(shopkeeper_user)
        db.flush()
        test_shop = Shop(
            owner_id=shopkeeper_user.id,
            name="Super Test Xerox",
            address="123 College Road",
            phone="9876543210",
            bw_price=2.0,
            color_price=10.0
        )
        db.add(test_shop)
        db.commit()
        db.refresh(shopkeeper_user)
        db.refresh(test_shop)
    else:
        test_shop = db.scalar(select(Shop).where(Shop.owner_id == shopkeeper_user.id))

    customer_user = db.scalar(select(User).where(User.email == "test_customer@example.com"))
    if not customer_user:
        customer_user = User(
            name="Test Customer",
            email="test_customer@example.com",
            phone="9123456780",
            password_hash=hash_password("password123"),
            role="customer"
        )
        db.add(customer_user)
        db.commit()
        db.refresh(customer_user)

    other_shopkeeper = db.scalar(select(User).where(User.email == "other_shopkeeper@example.com"))
    if not other_shopkeeper:
        other_shopkeeper = User(
            name="Other Shopkeeper",
            email="other_shopkeeper@example.com",
            phone="9998887770",
            password_hash=hash_password("password123"),
            role="shopkeeper"
        )
        db.add(other_shopkeeper)
        db.flush()
        other_shop = Shop(
            owner_id=other_shopkeeper.id,
            name="Other Xerox",
            address="456 Other St",
            phone="9998887770"
        )
        db.add(other_shop)
        db.commit()
        db.refresh(other_shopkeeper)

    other_customer = db.scalar(select(User).where(User.email == "other_customer@example.com"))
    if not other_customer:
        other_customer = User(
            name="Other Customer",
            email="other_customer@example.com",
            phone="9112233445",
            password_hash=hash_password("password123"),
            role="customer"
        )
        db.add(other_customer)
        db.commit()
        db.refresh(other_customer)

    sk_token = create_token(shopkeeper_user)
    cust_token = create_token(customer_user)
    other_sk_token = create_token(other_shopkeeper)
    other_cust_token = create_token(other_customer)

    # ----------------------------------------------------
    # TEST SUITE A: QR CODE GENERATION & DOWNLOAD
    # ----------------------------------------------------
    print("\n--- TEST SUITE A: QR Code Generation & Download ---")

    # A1: Unauthenticated request should fail with 401
    r_unauth = client.get("/api/shopkeeper/qr")
    assert r_unauth.status_code == 401, f"Expected 401, got {r_unauth.status_code}"
    print("[PASS] Unauthenticated access to /api/shopkeeper/qr is rejected with 401")

    # A2: Customer role request should fail with 403
    r_cust_qr = client.get("/api/shopkeeper/qr", headers={"Authorization": f"Bearer {cust_token}"})
    assert r_cust_qr.status_code == 403, f"Expected 403, got {r_cust_qr.status_code}"
    print("[PASS] Customer access to /api/shopkeeper/qr is rejected with 403")

    # A3: Authorized Shopkeeper generates QR
    r_qr = client.get("/api/shopkeeper/qr", headers={"Authorization": f"Bearer {sk_token}"})
    assert r_qr.status_code == 200, f"Expected 200, got {r_qr.status_code}: {r_qr.text}"
    assert r_qr.headers["content-type"] == "image/png", f"Unexpected content-type: {r_qr.headers.get('content-type')}"
    assert "X-Shop-Order-URL" in r_qr.headers, "X-Shop-Order-URL header missing"
    qr_url = r_qr.headers["X-Shop-Order-URL"]
    print(f"[PASS] QR code generated successfully. Header X-Shop-Order-URL: {qr_url}")

    # A4: Check that URL does not use localhost for mobile phone compatibility
    assert "localhost" not in qr_url and "127.0.0.1" not in qr_url, f"QR URL should not use localhost: {qr_url}"
    assert f"?shop={test_shop.id}" in qr_url, f"QR URL must contain ?shop={test_shop.id}"
    print(f"[PASS] QR destination URL uses network/LAN IP ({qr_url}) and points to shop {test_shop.id}")

    # A5: Verify PNG binary validity and opening with PIL
    png_bytes = r_qr.content
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n", "Generated content does not have PNG magic bytes"
    img = Image.open(io.BytesIO(png_bytes))
    assert img.format == "PNG", f"Expected PNG format, got {img.format}"
    assert img.size[0] > 100 and img.size[1] > 100, f"Unexpected image dimensions: {img.size}"
    print(f"[PASS] Valid PNG image verified by PIL (format={img.format}, size={img.size})")

    # A6: Test custom base_url parameter (e.g. from deployed frontend or custom domain)
    custom_origin = "https://smartprint.example.com"
    r_custom_qr = client.get(f"/api/shopkeeper/qr?base_url={custom_origin}", headers={"Authorization": f"Bearer {sk_token}"})
    assert r_custom_qr.status_code == 200
    assert r_custom_qr.headers["X-Shop-Order-URL"] == f"https://smartprint.example.com/customer/upload?shop={test_shop.id}"
    print(f"[PASS] Custom base_url honored: {r_custom_qr.headers['X-Shop-Order-URL']}")

    # A7: Test graceful handling of invalid / malformed base_url
    r_bad_url = client.get("/api/shopkeeper/qr?base_url=invalid-url", headers={"Authorization": f"Bearer {sk_token}"})
    assert r_bad_url.status_code == 200
    assert "invalid-url" not in r_bad_url.headers["X-Shop-Order-URL"]
    print("[PASS] Malformed base_url handled gracefully with safe fallback")

    # ----------------------------------------------------
    # TEST SUITE B: CUSTOMER FILE UPLOAD & SHOPKEEPER DOWNLOAD
    # ----------------------------------------------------
    print("\n--- TEST SUITE B: Customer Upload & Shopkeeper Download ---")

    test_file_content = b"%PDF-1.4\n%Test XeroxFlow SmartPrint Document Content\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"
    test_filename = "biology_assignment_notes.pdf"

    # B1: Customer uploads a document and places order
    order_payload = {
        "shop_id": str(test_shop.id),
        "copies": "2",
        "pages": "all",
        "color_mode": "bw",
        "paper_size": "A4",
        "sides": "single",
        "notes": "Please staple on top-left"
    }
    files = {
        "document": (test_filename, io.BytesIO(test_file_content), "application/pdf")
    }
    r_order = client.post(
        "/api/orders",
        data=order_payload,
        files=files,
        headers={"Authorization": f"Bearer {cust_token}"}
    )
    assert r_order.status_code == 200, f"Order creation failed: {r_order.status_code} {r_order.text}"
    order_data = r_order.json()
    order_id = order_data["id"]
    assert order_data["original_filename"] == test_filename
    assert order_data["customer_id"] == customer_user.id
    assert order_data["shop_id"] == test_shop.id
    print(f"[PASS] Customer placed order #{order_id} with file '{test_filename}'")

    # B2: Verify file is saved in private UPLOAD_DIR
    db_order = db.get(PrintOrder, order_id)
    assert db_order is not None
    assert db_order.stored_filename is not None
    stored_path = UPLOAD_DIR / db_order.stored_filename
    assert stored_path.is_file(), f"File {stored_path} not found on disk"
    assert stored_path.read_bytes() == test_file_content, "Saved file content does not match uploaded content"
    print(f"[PASS] File saved in private storage directory: {stored_path.name} ({len(test_file_content)} bytes)")

    # B3: Shopkeeper sees the order in dashboard
    r_jobs = client.get("/api/orders", headers={"Authorization": f"Bearer {sk_token}"})
    assert r_jobs.status_code == 200
    jobs = r_jobs.json()
    matching = [j for j in jobs if j["id"] == order_id]
    assert len(matching) == 1, f"Order {order_id} not visible to shopkeeper"
    assert matching[0]["original_filename"] == test_filename
    print(f"[PASS] Shopkeeper sees order #{order_id} with original filename '{test_filename}'")

    # B4: Authorized shopkeeper downloads the customer file
    r_dl = client.get(f"/api/orders/{order_id}/download", headers={"Authorization": f"Bearer {sk_token}"})
    assert r_dl.status_code == 200, f"Shopkeeper download failed: {r_dl.status_code} {r_dl.text}"
    assert r_dl.content == test_file_content, "Downloaded file content corrupted or does not match original"
    assert "attachment" in r_dl.headers.get("content-disposition", "") or test_filename in r_dl.headers.get("content-disposition", "")
    print(f"[PASS] Shopkeeper downloaded file successfully ({len(r_dl.content)} bytes). Bit-for-bit identical to original upload.")

    # B5: Customer who owns the order can also download it
    r_cust_dl = client.get(f"/api/orders/{order_id}/download", headers={"Authorization": f"Bearer {cust_token}"})
    assert r_cust_dl.status_code == 200
    assert r_cust_dl.content == test_file_content
    print("[PASS] Customer owner downloaded their own file successfully")

    # B6: Security - Unauthenticated download attempt rejected with 401
    r_anon = client.get(f"/api/orders/{order_id}/download")
    assert r_anon.status_code == 401, f"Expected 401, got {r_anon.status_code}"
    print("[PASS] Security: Unauthenticated download rejected with 401")

    # B7: Security - Another customer cannot download this file (rejected with 403)
    r_bad_cust = client.get(f"/api/orders/{order_id}/download", headers={"Authorization": f"Bearer {other_cust_token}"})
    assert r_bad_cust.status_code == 403, f"Expected 403, got {r_bad_cust.status_code}"
    print("[PASS] Security: Unrelated customer download rejected with 403")

    # B8: Security - Another shopkeeper cannot download this file (rejected with 403)
    r_bad_sk = client.get(f"/api/orders/{order_id}/download", headers={"Authorization": f"Bearer {other_sk_token}"})
    assert r_bad_sk.status_code == 403, f"Expected 403, got {r_bad_sk.status_code}"
    print("[PASS] Security: Unrelated shopkeeper download rejected with 403")

    # B9: Error handling - Non-existent order returns 404
    r_missing_order = client.get("/api/orders/999999/download", headers={"Authorization": f"Bearer {sk_token}"})
    assert r_missing_order.status_code == 404
    print("[PASS] Non-existent order download returns 404")

    # B10: Error handling - Order with missing file on disk returns 404 with clean message
    ghost_order = PrintOrder(
        customer_id=customer_user.id,
        shop_id=test_shop.id,
        original_filename="ghost.pdf",
        stored_filename="non_existent_file_12345.pdf",
        copies=1,
        pages="all",
        color_mode="bw",
        paper_size="A4",
        sides="single",
        notes="",
        estimated_price=2.0,
        status="pending"
    )
    db.add(ghost_order)
    db.commit()
    db.refresh(ghost_order)

    r_ghost = client.get(f"/api/orders/{ghost_order.id}/download", headers={"Authorization": f"Bearer {sk_token}"})
    assert r_ghost.status_code == 404, f"Expected 404, got {r_ghost.status_code}"
    assert "not found" in r_ghost.json()["detail"].lower()
    print(f"[PASS] Missing disk file handled cleanly with 404: {r_ghost.json()['detail']}")

    # Clean up test orders created during testing
    try:
        stored_path.unlink(missing_ok=True)
        db.delete(ghost_order)
        db.delete(db_order)
        db.commit()
    except Exception:
        pass

    print("\n==================================================")
    print("ALL TEST SUITES PASSED! BOTH BUGS SUCCESSFULLY FIXED.")
    print("==================================================")

if __name__ == "__main__":
    run_tests()
