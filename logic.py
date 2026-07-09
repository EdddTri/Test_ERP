"""
Centralized business logic for the Job-Shop ERP demo.

Every rule the prompt cares about (stage routing, progression, payment gating,
stock deduction, enquiry aging) lives here as a plain function so the UI stays
thin and the rules are easy to tweak in one place.
"""

from datetime import datetime

from database import query, query_one, execute

# Canonical routing order. Multi-stage jobs always run Print -> Binding -> Other.
JOB_TYPE_ORDER = ["Print", "Binding", "Other"]


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def current_user():
    """Who is acting right now (assigns/routes jobs).

    Placeholder until authentication is wired in — then this returns the logged-in
    user. Centralised so the swap is a one-line change.
    """
    return "AT"


# --------------------------------------------------------------------------- #
# Config / AlertConfig
# --------------------------------------------------------------------------- #
def get_config(key, default=None):
    row = query_one("SELECT config_value FROM AlertConfig WHERE config_key = ?", (key,))
    return row["config_value"] if row else default


def get_config_int(key, default=0):
    try:
        return int(get_config(key, default))
    except (TypeError, ValueError):
        return default


def set_config(key, value):
    if query_one("SELECT 1 FROM AlertConfig WHERE config_key = ?", (key,)):
        execute("UPDATE AlertConfig SET config_value = ? WHERE config_key = ?", (str(value), key))
    else:
        execute("INSERT INTO AlertConfig (config_key, config_value) VALUES (?, ?)", (key, str(value)))


def all_config():
    return query("SELECT config_key, config_value FROM AlertConfig ORDER BY config_key")


# --------------------------------------------------------------------------- #
# Lookups
# --------------------------------------------------------------------------- #
def job_type_map():
    """name -> id and id -> name in one dict for convenience."""
    rows = query("SELECT job_type_id, job_type_name FROM JobTypes")
    m = {}
    for r in rows:
        m[r["job_type_name"]] = r["job_type_id"]
        m[r["job_type_id"]] = r["job_type_name"]
    return m


# --------------------------------------------------------------------------- #
# Items  (each item belongs to a job type — Print items, Binding items, ...)
# --------------------------------------------------------------------------- #
def items_for_job_types(job_type_ids):
    """Items belonging to the given job type id(s), for type-aware pickers."""
    ids = [i for i in job_type_ids if i is not None]
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    return query(
        f"SELECT item_id, item_name, job_type_id, unit_of_measure "
        f"FROM Items WHERE job_type_id IN ({placeholders}) ORDER BY item_name",
        tuple(ids),
    )


def create_item(item_name, job_type_id, unit_of_measure="Units",
                initial_qty=0, reorder_level=None, rate=None):
    """Add a new item under a job type and open a stock record for it.

    `rate` is the per-unit rate (optional — left unset/NULL if not provided).
    """
    if reorder_level is None:
        reorder_level = get_config_int("stock_reorder_default", 10)
    item_id = execute(
        "INSERT INTO Items (item_name, job_type_id, unit_of_measure, rate) "
        "VALUES (?, ?, ?, ?)",
        (item_name.strip(), job_type_id, unit_of_measure, rate),
    )
    execute(
        "INSERT INTO Stock (item_id, quantity_available, reorder_level, last_updated) "
        "VALUES (?, ?, ?, ?)",
        (item_id, initial_qty, reorder_level, now_str()),
    )
    return item_id


def update_item(item_id, item_name, job_type_id, unit_of_measure, reorder_level, rate=None):
    """Edit an item's master fields, rate and reorder level (upserting Stock if needed)."""
    execute(
        "UPDATE Items SET item_name = ?, job_type_id = ?, unit_of_measure = ?, rate = ? "
        "WHERE item_id = ?",
        (item_name.strip(), job_type_id, unit_of_measure, rate, item_id),
    )
    if query_one("SELECT 1 FROM Stock WHERE item_id = ?", (item_id,)):
        execute("UPDATE Stock SET reorder_level = ? WHERE item_id = ?", (reorder_level, item_id))
    else:
        execute(
            "INSERT INTO Stock (item_id, quantity_available, reorder_level, last_updated) "
            "VALUES (?, 0, ?, ?)",
            (item_id, reorder_level, now_str()),
        )


def resolve_item(selection, job_type_id):
    """
    Turn a type-aware item picker's value into an item_id.

    `selection` is either an existing item dict (chosen from the list) or a
    free-typed string (a brand-new item) — in which case it's created under the
    given job type, reusing an existing row if the name already exists.
    """
    if isinstance(selection, dict):
        return selection["item_id"]
    name = str(selection).strip()
    if not name:
        return None
    existing = query_one("SELECT item_id FROM Items WHERE item_name = ?", (name,))
    return existing["item_id"] if existing else create_item(name, job_type_id)


def resolve_customer(selection):
    """
    Turn a customer picker value into a customer_id.

    `selection` is either an existing customer dict (chosen from the list) or a
    free-typed name. A typed name is created as a lightweight stub (name only),
    which can be completed later on the Customer Master page.
    """
    if isinstance(selection, dict):
        return selection["customer_id"]
    if not selection:
        return None
    name = str(selection).strip()
    if not name:
        return None
    existing = query_one("SELECT customer_id FROM Customers WHERE customer_name = ?", (name,))
    if existing:
        return existing["customer_id"]
    return execute(
        "INSERT INTO Customers (customer_name, phone, email) VALUES (?, '', '')", (name,)
    )


# --------------------------------------------------------------------------- #
# Bill line items  (materials a stage will consume)
# --------------------------------------------------------------------------- #
def add_bill_item(bill_id, stage_label, job_type_id, item_id, quantity, color=None):
    """Attach a line item (item + quantity + optional colour) to a stage of a bill."""
    return execute(
        "INSERT INTO BillItem (bill_id, stage_label, job_type_id, item_id, quantity, color) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (bill_id, stage_label, job_type_id, item_id, quantity, color),
    )


def get_bill_items(bill_id, stage_label=None):
    """Line items for a bill, optionally restricted to a single stage label."""
    sql = (
        "SELECT bi.*, i.item_name, i.unit_of_measure, i.rate "
        "FROM BillItem bi JOIN Items i ON bi.item_id = i.item_id "
        "WHERE bi.bill_id = ?"
    )
    params = [bill_id]
    if stage_label is not None:
        sql += " AND bi.stage_label = ?"
        params.append(stage_label)
    sql += " ORDER BY bi.stage_label, i.item_name"
    return query(sql, tuple(params))


def bill_items_summary(bill_id, stage_label=None):
    """Compact 'ItemA ×5, ItemB ×2' string for tables."""
    rows = get_bill_items(bill_id, stage_label)
    if not rows:
        return "—"
    return ", ".join(f"{r['item_name']} ×{int(r['quantity'])}" for r in rows)


def bill_document_html(bill_id):
    """A print-ready job-work bill: header details, line-item table, and totals."""
    bill = query_one(
        "SELECT b.*, c.customer_name, c.contact_person, c.phone, c.email, c.address "
        "FROM Bill b JOIN Customers c ON b.customer_id = c.customer_id "
        "WHERE b.bill_id = ?",
        (bill_id,),
    )
    if not bill:
        return "<p>Bill not found.</p>"

    items = get_bill_items(bill_id)
    advance = amount_paid(bill_id)
    jw_no = f"JW-{bill_id:04d}"
    created = bill["job_time"] or ""
    date_txt, time_txt = (created[:10], created[11:16]) if len(created) >= 16 else (created[:10], "")

    rows, total_bill = [], 0.0
    for i, it in enumerate(items, start=1):
        rate = it["rate"] or 0
        amount = rate * it["quantity"]
        total_bill += amount
        rate_txt = f"{rate:,.2f}" if it["rate"] is not None else "—"
        amt_txt = f"{amount:,.2f}" if it["rate"] is not None else "—"
        rows.append(
            f"<tr><td class='c'>{i}</td><td>{it['item_name']}</td>"
            f"<td>{it['color'] or '—'}</td>"
            f"<td class='r'>{int(it['quantity'])} {it['unit_of_measure'] or ''}</td>"
            f"<td class='r'>{rate_txt}</td><td class='r'>{amt_txt}</td></tr>"
        )
    rows_html = "\n".join(rows) or "<tr><td colspan='6' class='c'>No items.</td></tr>"
    # If no item rates are set, fall back to the bill's order value so it isn't blank.
    if total_bill == 0:
        total_bill = bill["total_amount"] or 0
    grand_total = total_bill - advance

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{jw_no}</title>
<style>
  body {{ font-family: Arial, sans-serif; color:#222; max-width:760px; margin:24px auto; padding:0 16px; }}
  .head {{ text-align:center; border-bottom:2px solid #333; padding-bottom:8px; }}
  .head h1 {{ margin:0; font-size:22px; }}
  .head .sub {{ color:#666; font-size:12px; }}
  .meta {{ display:flex; justify-content:space-between; margin-top:14px; font-size:13px; gap:24px; }}
  .meta .col {{ line-height:1.6; }}
  .meta b {{ display:inline-block; min-width:110px; color:#444; }}
  table {{ border-collapse:collapse; width:100%; margin-top:18px; font-size:13px; }}
  th, td {{ border:1px solid #bbb; padding:7px 9px; }}
  th {{ background:#f0f0f0; text-align:left; }}
  td.r, th.r {{ text-align:right; }}
  td.c, th.c {{ text-align:center; }}
  .totals {{ margin-top:14px; width:320px; margin-left:auto; font-size:14px; }}
  .totals div {{ display:flex; justify-content:space-between; padding:4px 2px; }}
  .totals .grand {{ font-weight:bold; font-size:16px; border-top:2px solid #333;
                    margin-top:4px; padding-top:7px; }}
  .toolbar {{ text-align:center; margin:18px 0; }}
  .toolbar button {{ padding:8px 18px; font-size:14px; cursor:pointer; }}
  @media print {{ body {{ margin:0; }} .toolbar {{ display:none; }} }}
</style></head>
<body>
  <div class="toolbar"><button onclick="window.print()">🖨️ Print</button></div>

  <div class="head">
    <h1>Job-Shop ERP</h1>
    <div class="sub">Job Work Bill</div>
  </div>

  <div class="meta">
    <div class="col">
      <div><b>Job Work No:</b> {jw_no}</div>
      <div><b>Party Name:</b> {bill['customer_name']}</div>
      <div><b>Contact Person:</b> {bill['contact_person'] or '—'}</div>
      <div><b>Address:</b> {bill['address'] or '—'}</div>
    </div>
    <div class="col">
      <div><b>Date:</b> {date_txt}</div>
      <div><b>Time:</b> {time_txt or '—'}</div>
      <div><b>Phone:</b> {bill['phone'] or '—'}</div>
      <div><b>Delivery:</b> {bill['delivery_datetime'] or '—'}</div>
    </div>
  </div>

  <table>
    <thead><tr>
      <th class="c">Sr</th><th>Item Name</th><th>Color</th>
      <th class="r">Qty</th><th class="r">Rate (₹)</th><th class="r">Amount (₹)</th>
    </tr></thead>
    <tbody>{rows_html}</tbody>
  </table>

  <div class="totals">
    <div><span>Total Bill</span><span>₹{total_bill:,.2f}</span></div>
    <div><span>Advance</span><span>₹{advance:,.2f}</span></div>
    <div class="grand"><span>Grand Total</span><span>₹{grand_total:,.2f}</span></div>
  </div>
</body></html>"""


# --------------------------------------------------------------------------- #
# Enquiry  (a lightweight, free-text capture — no structured job breakdown)
# --------------------------------------------------------------------------- #
def create_enquiry(source_id, customer_name, remarks,
                   source_contact=None, status="Pending"):
    """
    Log an enquiry as free-text: who asked, how they reached out, and what they
    want (remarks). The customer name is stored as plain text — logging an enquiry
    never creates or edits a customer-master row; that happens only on the Customer
    Master page or when the enquiry is turned into a job. The breakdown into job
    types and materials happens later on Create Job. `status` is normally 'Pending'
    but can be 'Cancelled' to record a dead enquiry straight away.
    """
    return execute(
        "INSERT INTO Enquiry (enquiry_date, source_id, customer_name, "
        "status, source_contact, remarks) VALUES (?, ?, ?, ?, ?, ?)",
        (now_str()[:10], source_id, customer_name, status, source_contact, remarks),
    )


# --------------------------------------------------------------------------- #
# 1. Job stage generation  (the routing engine)
# --------------------------------------------------------------------------- #
def generate_job_stages(bill_id, selected_job_types):
    """
    Create JobStage rows for a bill from the selected job type names.

    Rules:
      * single type           -> one stage, sequence 1, "In Progress"
      * multiple types        -> ordered Print -> Binding -> Other,
                                 only stage 1 "In Progress", rest "Not Started"
      * all three types       -> additionally append a 4th stage "Binding-2"
                                 (same job_type_id as Binding, distinct label)
    Returns the list of created stage labels in order.
    """
    jtm = job_type_map()

    # Keep only recognised types, in the canonical routing order.
    ordered = [t for t in JOB_TYPE_ORDER if t in selected_job_types]
    if not ordered:
        return []

    # (label, job_type_name)
    plan = [(name, name) for name in ordered]
    if len(ordered) == 3:
        plan.append(("Binding-2", "Binding"))

    created = []
    for idx, (label, jt_name) in enumerate(plan):
        seq = idx + 1
        status = "In Progress" if idx == 0 else "Not Started"
        start = now_str() if idx == 0 else None
        # Only the active (first) stage is "assigned" at creation time.
        assigned_by = current_user() if idx == 0 else None
        execute(
            "INSERT INTO JobStage (bill_id, job_type_id, stage_label, sequence_no, "
            "stage_status, start_time, assigned_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (bill_id, jtm[jt_name], label, seq, status, start, assigned_by),
        )
        created.append(label)

    # Reflect the first stage on the bill header.
    execute(
        "UPDATE Bill SET overall_status = ? WHERE bill_id = ?",
        (f"In Progress – {created[0]}", bill_id),
    )
    return created


# --------------------------------------------------------------------------- #
# 4. Stock deduction
# --------------------------------------------------------------------------- #
def deduct_stock_for_item(item_id, quantity, bill_id=None):
    """Issue `quantity` of an item's stock and log the transaction."""
    stock = query_one("SELECT * FROM Stock WHERE item_id = ?", (item_id,))
    if not stock:
        return None
    new_qty = stock["quantity_available"] - quantity
    execute(
        "UPDATE Stock SET quantity_available = ?, last_updated = ? WHERE stock_id = ?",
        (new_qty, now_str(), stock["stock_id"]),
    )
    execute(
        "INSERT INTO StockTransaction (stock_id, bill_id, quantity_changed, "
        "transaction_type, transaction_date) VALUES (?, ?, ?, ?, ?)",
        (stock["stock_id"], bill_id, -abs(quantity), "Issue", now_str()),
    )
    return new_qty


def receive_stock(item_id, quantity, bill_id=None):
    """Manual stock-in (Receipt)."""
    stock = query_one("SELECT * FROM Stock WHERE item_id = ?", (item_id,))
    if stock:
        new_qty = stock["quantity_available"] + quantity
        execute(
            "UPDATE Stock SET quantity_available = ?, last_updated = ? WHERE stock_id = ?",
            (new_qty, now_str(), stock["stock_id"]),
        )
        stock_id = stock["stock_id"]
    else:
        default_reorder = get_config_int("stock_reorder_default", 10)
        stock_id = execute(
            "INSERT INTO Stock (item_id, quantity_available, reorder_level, last_updated) "
            "VALUES (?, ?, ?, ?)",
            (item_id, quantity, default_reorder, now_str()),
        )
    execute(
        "INSERT INTO StockTransaction (stock_id, bill_id, quantity_changed, "
        "transaction_type, transaction_date) VALUES (?, ?, ?, ?, ?)",
        (stock_id, bill_id, abs(quantity), "Receipt", now_str()),
    )


# --------------------------------------------------------------------------- #
# 2. Stage progression
# --------------------------------------------------------------------------- #
def complete_stage(stage_id):
    """
    Mark a stage complete, issue that stage's own materials, and advance the bill.

    Stock is deducted from the BillItem line items belonging to *this stage*
    (e.g. the Print stage issues print materials, the Binding stage issues
    binding materials) — not from a single bill-level item.

    Returns a small summary dict the UI can surface to the user.
    """
    stage = query_one("SELECT * FROM JobStage WHERE stage_id = ?", (stage_id,))
    if not stage or stage["stage_status"] == "Completed":
        return {"ok": False, "message": "Stage not found or already completed."}

    # Close out this stage.
    execute(
        "UPDATE JobStage SET stage_status = 'Completed', end_time = ? WHERE stage_id = ?",
        (now_str(), stage_id),
    )

    # Issue the line items attached to this stage and record what happened.
    issued = []
    for bi in get_bill_items(stage["bill_id"], stage["stage_label"]):
        remaining = deduct_stock_for_item(bi["item_id"], bi["quantity"], bill_id=stage["bill_id"])
        issued.append(
            {
                "item_name": bi["item_name"],
                "quantity": bi["quantity"],
                "unit_of_measure": bi["unit_of_measure"],
                "remaining": remaining,
            }
        )

    # Advance to the next stage by sequence.
    nxt = query_one(
        "SELECT * FROM JobStage WHERE bill_id = ? AND sequence_no > ? "
        "ORDER BY sequence_no LIMIT 1",
        (stage["bill_id"], stage["sequence_no"]),
    )
    if nxt:
        # Whoever completes this stage assigns/routes the next one.
        execute(
            "UPDATE JobStage SET stage_status = 'In Progress', start_time = ?, "
            "assigned_by = ? WHERE stage_id = ?",
            (now_str(), current_user(), nxt["stage_id"]),
        )
        new_overall = f"In Progress – {nxt['stage_label']}"
        execute("UPDATE Bill SET overall_status = ? WHERE bill_id = ?",
                (new_overall, stage["bill_id"]))
        next_label = nxt["stage_label"]
    else:
        execute("UPDATE Bill SET overall_status = 'Completed' WHERE bill_id = ?",
                (stage["bill_id"],))
        new_overall = "Completed"
        next_label = None

    return {
        "ok": True,
        "completed_label": stage["stage_label"],
        "next_label": next_label,
        "overall_status": new_overall,
        "issued": issued,
    }


# --------------------------------------------------------------------------- #
# 3. Payments
# --------------------------------------------------------------------------- #
def amount_paid(bill_id):
    row = query_one("SELECT COALESCE(SUM(amount), 0) AS paid FROM Payments WHERE bill_id = ?",
                    (bill_id,))
    return row["paid"] if row else 0


def amount_due(bill_id):
    bill = query_one("SELECT total_amount FROM Bill WHERE bill_id = ?", (bill_id,))
    total = bill["total_amount"] if bill else 0
    return max(total - amount_paid(bill_id), 0)


def recompute_payment_status(bill_id):
    bill = query_one("SELECT total_amount FROM Bill WHERE bill_id = ?", (bill_id,))
    total = bill["total_amount"] if bill else 0
    paid = amount_paid(bill_id)
    if total > 0 and paid >= total:
        status = "Paid"
    elif paid > 0:
        status = "Partial"
    else:
        status = "Unpaid"
    execute("UPDATE Bill SET payment_status = ? WHERE bill_id = ?", (status, bill_id))
    return status


def record_payment(bill_id, amount, payment_mode, payment_date=None):
    payment_date = payment_date or datetime.now().strftime("%Y-%m-%d")
    execute(
        "INSERT INTO Payments (bill_id, amount, payment_date, payment_mode) "
        "VALUES (?, ?, ?, ?)",
        (bill_id, amount, payment_date, payment_mode),
    )
    return recompute_payment_status(bill_id)


# --------------------------------------------------------------------------- #
# Bills / Enquiries
# --------------------------------------------------------------------------- #
def create_bill(customer_id, item_id, job_description, delivery_datetime,
                total_amount, selected_job_types, enquiry_id=None):
    """Create a Bill header and generate its job stages in one call."""
    bill_id = execute(
        "INSERT INTO Bill (enquiry_id, customer_id, item_id, job_description, job_time, "
        "delivery_datetime, total_amount, payment_status, overall_status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'Unpaid', 'New')",
        (enquiry_id, customer_id, item_id, job_description, now_str(),
         delivery_datetime, total_amount),
    )
    generate_job_stages(bill_id, selected_job_types)
    return bill_id


def bill_for_enquiry(enquiry_id):
    """The bill already created from an enquiry, if any — used to block duplicate jobs."""
    return query_one(
        "SELECT bill_id, overall_status FROM Bill WHERE enquiry_id = ? "
        "ORDER BY bill_id LIMIT 1",
        (enquiry_id,),
    )


def convert_enquiry(enquiry_id):
    execute("UPDATE Enquiry SET status = 'Converted' WHERE enquiry_id = ?", (enquiry_id,))


def cancel_enquiry(enquiry_id):
    execute("UPDATE Enquiry SET status = 'Cancelled' WHERE enquiry_id = ?", (enquiry_id,))


# --------------------------------------------------------------------------- #
# 5. Enquiry aging
# --------------------------------------------------------------------------- #
def days_pending(enquiry_date):
    """Whole days between an enquiry_date string (YYYY-MM-DD...) and today."""
    if not enquiry_date:
        return 0
    try:
        d = datetime.strptime(enquiry_date[:10], "%Y-%m-%d")
    except ValueError:
        return 0
    return (datetime.now().date() - d.date()).days


def is_enquiry_overdue(enquiry_date):
    threshold = get_config_int("enquiry_pending_days_threshold", 3)
    return days_pending(enquiry_date) > threshold


# --------------------------------------------------------------------------- #
# Dashboard helpers
# --------------------------------------------------------------------------- #
def count_pending_enquiries():
    return query_one("SELECT COUNT(*) AS n FROM Enquiry WHERE status = 'Pending'")["n"]


def count_overdue_enquiries():
    rows = query("SELECT enquiry_date FROM Enquiry WHERE status = 'Pending'")
    return sum(1 for r in rows if is_enquiry_overdue(r["enquiry_date"]))


def count_jobs_in_progress_by_department():
    """In-progress stage counts keyed by department label (Print/Binding/Other)."""
    rows = query(
        "SELECT jt.job_type_name AS dept, COUNT(*) AS n "
        "FROM JobStage js JOIN JobTypes jt ON js.job_type_id = jt.job_type_id "
        "WHERE js.stage_status = 'In Progress' GROUP BY jt.job_type_name"
    )
    counts = {"Print": 0, "Binding": 0, "Other": 0}
    for r in rows:
        counts[r["dept"]] = r["n"]
    return counts


def count_unpaid_bills():
    return query_one(
        "SELECT COUNT(*) AS n FROM Bill WHERE payment_status != 'Paid' "
        "AND overall_status != 'Completed'"
    )["n"]


def low_stock_items():
    return query(
        "SELECT s.*, i.item_name, i.unit_of_measure "
        "FROM Stock s JOIN Items i ON s.item_id = i.item_id "
        "WHERE s.quantity_available <= s.reorder_level "
        "ORDER BY i.item_name"
    )
