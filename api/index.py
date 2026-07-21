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


def clean_number(raw: str):
    """Turn 'Rs. 1,40,000.00' into 140000.0 (handles Indian lakh-style commas too)."""
    if not raw:
        return None
    m = re.search(r"\d[\d,]*(?:\.\d+)?", raw)
    if not m:
        return None
    return float(m.group(0).replace(",", ""))


def parse_date(raw: str):
    """Turn '15 March 2026' / 'April 3, 2026' / '2026-01-22' into '2026-01-22'."""
    if not raw:
        return None
    raw = raw.strip()
    formats = [
        "%d %B %Y", "%d %b %Y",       # 15 March 2026 / 15 Mar 2026
        "%B %d, %Y", "%b %d, %Y",     # April 3, 2026
        "%d/%m/%Y", "%m/%d/%Y",       # 03/04/2026
        "%Y-%m-%d",                   # 2026-01-22 (already ISO)
    ]
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


# Words that identify each field when they appear as the "label" part of a
# "Label: value" line. Using whole-word matches (\b) so "GST" doesn't match
# inside "IGST" incorrectly and "Tax" doesn't match inside "Tax Invoice"
# (that line has no colon anyway, so it's skipped automatically).
INVOICE_NO_WORDS = r"\b(invoice|inv|ref|reference|order|receipt)\b"
BILL_NO_WORDS = r"\bbill\b.*\b(no\.?|number|#|id)\b"
INVOICE_NO_EXCLUDE = r"\b(date|amount|total|tax|vendor|seller|address|currency)\b"

DATE_WORDS = r"\b(date|issued|dated)\b"
VENDOR_WORDS = r"\b(vendor|seller|supplier)\b"
AMOUNT_WORDS = r"\bsub\s*-?\s*total\b|\bnet\s*amount\b"
TAX_WORDS = r"\b(gst|igst|cgst|sgst|vat|tax)\b"
CURRENCY_WORDS = r"\bcurrency\b"


@app.post("/extract")
def extract(payload: InvoiceRequest):
    text = payload.invoice_text
    lines = text.split("\n")

    result = {
        "invoice_no": None,
        "date": None,
        "vendor": None,
        "amount": None,
        "tax": None,
        "currency": None,
    }

    for line in lines:
        line = line.strip()
        if ":" not in line:
            continue
        label, _, value = line.partition(":")
        label_l = label.strip().lower()
        value = value.strip()
        if not value:
            continue

        if (
            result["invoice_no"] is None
            and not re.search(INVOICE_NO_EXCLUDE, label_l)
            and (re.search(INVOICE_NO_WORDS, label_l) or re.search(BILL_NO_WORDS, label_l))
        ):
            m = re.match(r"\S+", value)
            if m:
                result["invoice_no"] = m.group(0)

        if result["date"] is None and re.search(DATE_WORDS, label_l):
            parsed = parse_date(value)
            if parsed:
                result["date"] = parsed

        if result["vendor"] is None and re.search(VENDOR_WORDS, label_l):
            result["vendor"] = value

        if result["amount"] is None and re.search(AMOUNT_WORDS, label_l):
            result["amount"] = clean_number(value)

        if result["tax"] is None and re.search(TAX_WORDS, label_l):
            result["tax"] = clean_number(value)

        if result["currency"] is None and re.search(CURRENCY_WORDS, label_l):
            result["currency"] = value.strip().upper()

    # Fallback: some invoices put the vendor name in the header line instead
    # of behind a "Vendor:"/"Seller:" label, e.g. "NovaSoft Solutions — Tax Invoice"
    if result["vendor"] is None and lines:
        m = re.match(r"^(.+?)\s*[\u2014\-]{1,2}\s*(?:Tax\s+)?Invoice", lines[0].strip(), re.IGNORECASE)
        if m:
            result["vendor"] = m.group(1).strip()

    # Fallback: guess currency from symbols if no explicit "Currency:" line
    if result["currency"] is None:
        if re.search(r"Rs\.?|INR|\u20b9", text):
            result["currency"] = "INR"
        elif re.search(r"\$|USD", text):
            result["currency"] = "USD"
        elif re.search(r"\u20ac|EUR", text):
            result["currency"] = "EUR"

    return result


@app.get("/")
def health():
    return {"status": "ok"}
