# XeroxFlow SmartPrint — Version 1

A mobile-friendly MVP for customers to upload print jobs and shopkeepers to manage them.

## Stack
- Frontend: React + Vite
- Backend: FastAPI + SQLAlchemy + SQLite
- Authentication: JWT bearer tokens + password hashing
- Files: private local upload folder (for local testing)
- QR: shop-specific public order URL

## Requirements
- Windows 11
- Python 3.11+
- Node.js 20+

## 1. Run the backend (PowerShell)
```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload
```
Backend: http://127.0.0.1:8000
API docs: http://127.0.0.1:8000/docs

## 2. Run the frontend (new PowerShell terminal)
```powershell
cd frontend
npm install
Copy-Item .env.example .env
npm run dev
```
Frontend: http://localhost:5173

## 3. Test the flow
1. Register a shopkeeper from the app. Use a shop name and phone number.
2. Open the public shop link shown on the shopkeeper dashboard, or copy its shop ID.
3. Register a customer in another browser/incognito window.
4. Select the shop and create an order with a PDF.
5. Sign back in as shopkeeper, accept the order and update its status.
6. Customer can refresh their orders dashboard to see the new status.

## Notes / MVP boundaries
- This is a local-testable MVP, not yet a production deployment.
- Uploaded files are stored in `backend/uploads/` and should not be publicly served.
- The app calculates an estimate from shop prices. The shopkeeper confirms final details.
- Online payments, email/SMS notifications, cloud object storage, malware scanning, printer integration, and production deployment configuration are later hardening tasks.
- Do not expose this local development server directly to the public internet.
