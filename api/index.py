import re
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()

# Rule 4: CORS must be enabled so the Cloudflare Worker (grader) can call us
# from a different origin. allow_origins=["*"] means "any website can call this".
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class InvoiceRequest(BaseModel):
    invoice_text: str


def clean_number(raw: str) -> float | None:
    """Turn 'Rs. 2,199.00' into 2199.00"""
    if not raw:
        return None
    # find the actual number pattern (digits, commas, one decimal point)
    # this avoids accidentally grabbing a stray '.' from 'Rs.' itself
    m = re.search(r"\d[\d,]*(?:\.\d+)?", raw)
    if not m:
        return None
    return float(m.group(0).replace(",", ""))


def parse_date(raw: str) -> str | None:
    """Turn '15 March 2026' into '2026-03-15'"""
    if not raw:
        return None
    raw = raw.strip()
    # try a few common formats invoices tend to use
    formats = ["%d %B %Y", "%d %b %Y", "%B %d, %Y", "%d/%m/%Y", "%Y-%m-%d"]
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


@app.post("/extract")
def extract(payload: InvoiceRequest):
    text = payload.invoice_text

    result = {
        "invoice_no": None,
        "date": None,
        "vendor": None,
        "amount": None,
        "tax": None,
        "currency": None,
    }

    # --- invoice_no ---
    m = re.search(r"Invoice\s*No[:\s]*([A-Za-z0-9\-]+)", text, re.IGNORECASE)
    if m:
        result["invoice_no"] = m.group(1).strip()

    # --- date ---
    m = re.search(r"Date[:\s]*([0-9A-Za-z ,/\-]+)", text, re.IGNORECASE)
    if m:
        result["date"] = parse_date(m.group(1).strip())

    # --- vendor ---
    m = re.search(r"Vendor[:\s]*(.+)", text, re.IGNORECASE)
    if m:
        # cut off at the newline so we don't grab the next line too
        result["vendor"] = m.group(1).split("\n")[0].strip()

    # --- amount (subtotal, BEFORE tax) ---
    m = re.search(r"Sub\s*-?\s*total[:\s]*([^\n]+)", text, re.IGNORECASE)
    if m:
        result["amount"] = clean_number(m.group(1))

    # --- tax ---
    m = re.search(r"(?:GST|Tax|VAT)[^:\n]*[:\s]*([^\n]+)", text, re.IGNORECASE)
    if m:
        result["tax"] = clean_number(m.group(1))

    # --- currency ---
    if re.search(r"Rs\.?|INR|₹", text):
        result["currency"] = "INR"
    elif re.search(r"\$|USD", text):
        result["currency"] = "USD"
    elif re.search(r"€|EUR", text):
        result["currency"] = "EUR"

    return result


@app.get("/")
def health():
    return {"status": "ok"}
