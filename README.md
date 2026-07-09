# Print / Binding Job-Shop ERP — Demo

A working demo ERP for a print/binding job shop, built with **Streamlit** (UI),
**SQLite** (storage), and plain **Python** (business logic). It walks the
end-to-end shop-floor workflow: enquiry → job/bill → routed department stages
→ payments → stock → completion.

> This is a demo for stakeholder walkthroughs — it favours clarity over
> production hardening (no auth, no migrations).

## Run it

```bash
pip install -r requirements.txt
streamlit run Home.py
```

The SQLite database (`db/erp.db`) **auto-creates and seeds itself on first run**,
so the app opens to a realistic, mid-workflow state — no manual setup. To reset
the demo, just delete `db/erp.db` and rerun.

## ⚠️ Master data must be maintained (Items & Customers)

Items and customers are **master data** — keep them current or workflows break:

- **Items — strict.** The materials grids on **Enquiry** and **Create Job** only
  offer **catalogued** items; you **cannot** type a new item there. If an item is
  missing, add it on the **Item Master** page *first* (set its job type, unit,
  opening stock and reorder level). There is no inline item-add anymore — the Item
  Master is the single source of truth.
- **Customers — flexible.** The customer field on Enquiry / Create Job suggests
  existing customers from the DB **and** lets you **type a new name** to keep moving.
  A typed name is saved as a lightweight **stub** (name only) so the enquiry/bill can
  reference it; complete its phone/email later on the **Customer Master** page.

## Project structure

```
Home.py                 # entry point + Dashboard
ui.py                   # shared Streamlit helpers (incl. the department screen)
logic.py                # ALL business logic (routing, progression, payments, stock, aging)
database.py             # SQLite connection + idempotent bootstrap()
db/
  schema.sql            # table definitions
  seed.py               # sample data (runs once when the DB is empty)
  erp.db                # created on first run
pages/
  1_Enquiry.py
  2_Create_Job.py
  3_Print_Department.py
  4_Binding_Department.py
  5_Other_Department.py
  6_Stock.py
  7_Payments.py
  8_Settings.py
  9_Customer_Master.py   # add / edit customers (master data)
  10_Item_Master.py      # add / edit items + reorder levels (master data)
requirements.txt
```

## Core logic (all in `logic.py`)

- **`generate_job_stages(bill_id, selected_job_types)`** — the routing engine.
  One type → a single in-progress stage. Multiple → ordered **Print → Binding →
  Other**, only the first in progress. All three → a 4th **Binding-2** stage is
  appended (same job type as Binding, distinct label).
- **`complete_stage(stage_id, qty)`** — closes a stage, deducts stock, starts the
  next stage by `sequence_no`, and flips the bill to `Completed` when the route
  ends.
- **`record_payment` / `recompute_payment_status`** — payments roll up against the
  bill's `total_amount` into Unpaid / Partial / Paid.
- **Payment visibility (not a gate)** — department screens flag non-paid jobs 🔴
  for **information only**. Payment is collected at the front desk (Payments page);
  completing the work never changes it and is never blocked by it. So an Unpaid job
  stays Unpaid through the whole shop floor until a payment is recorded.
- **Stock deduction** — each stage has its **own** materials (`BillItem` line items),
  so completing the Print stage issues print stock, Binding issues binding stock, etc.
  Every issue is logged in `StockTransaction`; low stock is highlighted.
- **Enquiry aging** — pending enquiries older than
  `enquiry_pending_days_threshold` (editable in **Settings**) are flagged ⚠️.

## Suggested demo walkthrough

1. **Enquiry** — an aged, **multi-type** enquiry (Print + Binding) is flagged ⚠️.
   Click **Convert to Job**: its two types arrive pre-ticked with their materials —
   add **Other** to make it all three.
2. **Print Department** — the job appears; **Mark Complete**.
3. **Binding Department** — it moves here; note the 🔴 payment warning.
4. **Payments** — record a payment, then return and complete **Binding**.
5. **Other Department** → back to **Binding-2**; complete it.
6. The bill's **overall status** flips to **Completed**.
7. **Stock** drops with each completion; the **Dashboard** reflects it all.

## Notes on the schema

Two sensible additions to the prompt's schema:

- **`Bill.total_amount`** — the Payments screen needs an order value to compute
  "amount due" and to derive Partial vs Paid automatically.
- **`Items.rate`** — an optional per-unit rate set on the **Item Master**. It is
  never an enforced default: on Create Job it only powers a faint *"suggested order
  value"* hint (rate × qty), leaving the order value a manual field.
- **`Customers.contact_person` / `Customers.address`** and **`BillItem.color`** —
  fields that appear on the printable **Job Work Bill**.

## Printing a bill

On **Create Job**, the *Print a bill* section renders a **Job Work Bill** — header
(job work no, party name, contact person, address, date/time), a line-item table
(Sr · Item · Color · Qty · Rate · Amount), and **Total Bill / Advance / Grand Total**.
The **🖨️ Print** button opens the filled bill in a **new browser tab** (then Ctrl/Cmd+P),
with a download fallback. The total is the sum of line amounts (rate × qty); it falls
back to the bill's order value if items aren't priced.
- **`BillItem`** (line items: `bill_id, stage_label, job_type_id, item_id, quantity`)
  — because items are job-type-specific, a multi-stage job (Print + Binding + Other)
  consumes *different* materials at each stage. Items are attached **per stage**, and
  each stage issues its own materials on completion. `Bill.item_id` is kept only as a
  representative "primary item" for header displays.
- **`Enquiry`** is a lightweight, **free-text** capture — customer, source/contact,
  and a remarks note of what they want. It intentionally carries **no** job-type or
  material structure; that breakdown is decided later on **Create Job**. On "Convert
  to Job" the customer is pre-selected and the enquiry note flows into the job
  description, but the operator picks the job type(s) and materials fresh.
