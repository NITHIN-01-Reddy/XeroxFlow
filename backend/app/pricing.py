import math
import io
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP
from typing import Tuple, List, Optional, Dict, Any
from PIL import Image

try:
    import pypdf
except ImportError:
    pypdf = None


def extract_document_page_count(file_bytes: bytes, filename: str) -> Tuple[Optional[int], Optional[str]]:
    """
    Extract the actual page count of a document if reliably supported.
    Returns (page_count, note_or_warning).
    Never assumes 1 page on failure; unparseable/corrupted/unsupported files return (None, note).
    """
    if not file_bytes:
        return None, "Document file is empty (0 bytes)"

    ext = Path(filename).suffix.lower()

    if ext == ".pdf":
        if pypdf is None:
            return None, "PDF reader library not available on server"
        try:
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            if reader.is_encrypted:
                try:
                    decrypted = reader.decrypt("")
                    if decrypted == 0:
                        return None, "Encrypted PDF: password-protected and cannot be read automatically"
                except Exception:
                    return None, "Encrypted PDF: page count could not be verified automatically"
            count = len(reader.pages)
            if count <= 0:
                return None, "PDF contains 0 pages or is corrupt"
            return count, None
        except Exception as e:
            return None, f"Invalid or unreadable PDF: {str(e)}"

    if ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif"):
        try:
            with Image.open(io.BytesIO(file_bytes)) as img:
                # Validate that image data is parseable
                img.verify()
            # For multi-frame images (such as multi-page TIFFs), count frames
            with Image.open(io.BytesIO(file_bytes)) as img:
                n_frames = getattr(img, "n_frames", 1)
                return max(1, n_frames), None
        except Exception as e:
            return None, f"Invalid or corrupted image file: {str(e)}"

    # Other file formats (.doc, .docx, unverified files)
    return None, "Document page count cannot be determined reliably for this file type; manual quotation required"


def parse_and_validate_pages(
    pages_str: str,
    actual_page_count: Optional[int] = None
) -> Tuple[List[int], int, bool]:
    """
    Parse page selection string ('all', '1', '1-5', '1, 3, 5-8') and validate against actual_page_count.
    Returns: (selected_pages_list, count_of_pages, is_all_pages)
    Raises ValueError with user-friendly error message on invalid syntax or out-of-bounds pages.
    """
    clean_str = pages_str.strip()
    if not clean_str:
        raise ValueError("Page selection cannot be empty. Use 'all' or specific pages like '1-5'")

    if clean_str.lower() == "all":
        if actual_page_count is not None and actual_page_count > 0:
            return list(range(1, actual_page_count + 1)), actual_page_count, True
        # Actual page count is unknown in estimate mode
        return [1], 1, True

    selected_pages = set()
    parts = [p.strip() for p in clean_str.split(",") if p.strip()]
    if not parts:
        raise ValueError("Invalid page selection format")

    for part in parts:
        if "-" in part:
            bounds = [b.strip() for b in part.split("-")]
            if len(bounds) != 2 or not bounds[0].isdigit() or not bounds[1].isdigit():
                raise ValueError(f"Invalid page range syntax: '{part}'. Example: '1-5'")
            start, end = int(bounds[0]), int(bounds[1])
            if start < 1:
                raise ValueError(f"Page numbers must start at 1 or greater, got {start}")
            if end < start:
                raise ValueError(f"Invalid range '{part}': start page ({start}) cannot exceed end page ({end})")
            if actual_page_count is not None and end > actual_page_count:
                raise ValueError(
                    f"Requested page range {start}-{end} exceeds the document's total pages ({actual_page_count})"
                )
            selected_pages.update(range(start, end + 1))
        else:
            if not part.isdigit():
                raise ValueError(f"Invalid page entry: '{part}'. Use page numbers or ranges like '1-3, 5'")
            page = int(part)
            if page < 1:
                raise ValueError(f"Page numbers must start at 1 or greater, got {page}")
            if actual_page_count is not None and page > actual_page_count:
                raise ValueError(
                    f"Requested page {page} exceeds the document's total pages ({actual_page_count})"
                )
            selected_pages.add(page)

    sorted_pages = sorted(list(selected_pages))
    return sorted_pages, len(sorted_pages), False


def calculate_order_price(
    shop_bw_price: float,
    shop_color_price: float,
    shop_a3_multiplier: float,
    shop_a5_multiplier: float,
    shop_double_sided_discount: float,
    shop_stapling_price: float,
    copies: int,
    selected_page_count: int,
    color_mode: str,
    paper_size: str,
    sides: str,
    orientation: str,
    finishing: str,
    requires_quote: bool = False,
    quote_reason: str = "",
    actual_page_count: Optional[int] = None
) -> Dict[str, Any]:
    """
    Decimal-safe, itemized calculation of print order price.
    Follows XeroxFlow documented formula:
      billable_pages = number of selected pages
      printed_page_copies = billable_pages × number_of_copies
      printing_total = printed_page_copies × applicable_rate_per_page (with duplex discount if applicable)
      final_total = printing_total + applicable_finishing_charges
    Returns complete price breakdown snapshot dictionary.
    """
    # 1. Base rate & missing rate check
    raw_base_rate = shop_color_price if color_mode == "color" else shop_bw_price
    if raw_base_rate is None or float(raw_base_rate) <= 0:
        requires_quote = True
        quote_reason = quote_reason or "Shop pricing rate is missing or zero for this print mode; awaiting shopkeeper quotation"
        base_page_rate = Decimal("0.00")
    else:
        base_page_rate = Decimal(str(raw_base_rate))

    # 2. Paper size adjustment
    if paper_size == "A3":
        size_multiplier = Decimal(str(shop_a3_multiplier if shop_a3_multiplier is not None else 2.0))
    elif paper_size == "A5":
        size_multiplier = Decimal(str(shop_a5_multiplier if shop_a5_multiplier is not None else 0.8))
    else:  # A4
        size_multiplier = Decimal("1.0")

    effective_page_rate = (base_page_rate * size_multiplier).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # 3. Billable pages & Copies
    billable_pages = Decimal(str(max(0, selected_page_count)))
    num_copies = Decimal(str(max(1, copies)))
    printed_page_copies = billable_pages * num_copies

    # 4. Sides and Sheets calculation
    # In single-sided printing, 1 page = 1 physical sheet.
    # In double-sided printing, 2 pages = 1 physical sheet.
    if sides == "double":
        sheets_per_copy = max(1, math.ceil(int(billable_pages) / 2)) if int(billable_pages) > 0 else 0
        discount_percent = Decimal(str(shop_double_sided_discount or 0.0))
        discount_factor = max(Decimal("0.0"), (Decimal("100") - discount_percent) / Decimal("100"))
        # Per copy printing cost with shop duplex discount applied
        printing_cost_per_copy = (billable_pages * effective_page_rate * discount_factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        sheets_per_copy = int(billable_pages)
        discount_percent = Decimal("0.0")
        discount_factor = Decimal("1.0")
        printing_cost_per_copy = (billable_pages * effective_page_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    total_sheets = sheets_per_copy * int(num_copies)
    total_printing_cost = (printing_cost_per_copy * num_copies).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # 5. Finishing charges (e.g. stapling per copy set)
    if finishing == "stapling":
        finishing_unit_price = Decimal(str(shop_stapling_price or 0.0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_finishing_cost = (finishing_unit_price * num_copies).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        finishing_unit_price = Decimal("0.00")
        total_finishing_cost = Decimal("0.00")

    # 6. Totals
    subtotal = (total_printing_cost + total_finishing_cost).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    final_total = Decimal("0.00") if requires_quote else subtotal

    return {
        "currency": "INR",
        "color_mode": color_mode,
        "base_page_rate": float(base_page_rate.quantize(Decimal("0.01"))),
        "paper_size": paper_size,
        "size_multiplier": float(size_multiplier.quantize(Decimal("0.01"))),
        "effective_page_rate": float(effective_page_rate),
        "rate_per_page": float(effective_page_rate),
        "actual_page_count": actual_page_count,
        "selected_page_count": int(billable_pages),
        "billable_page_count": int(billable_pages),
        "copies": int(num_copies),
        "printed_page_copies": int(printed_page_copies),
        "sides": sides,
        "orientation": orientation,
        "sheets_per_copy": sheets_per_copy,
        "total_sheets": total_sheets,
        "double_sided_discount_percent": float(discount_percent),
        "printing_cost_per_copy": float(printing_cost_per_copy),
        "total_printing_cost": float(total_printing_cost),
        "finishing": finishing,
        "finishing_unit_price": float(finishing_unit_price),
        "total_finishing_cost": float(total_finishing_cost),
        "subtotal": float(subtotal),
        "final_total": float(final_total),
        "requires_quote": bool(requires_quote),
        "quote_reason": quote_reason or ("Awaiting quotation" if requires_quote else "")
    }
