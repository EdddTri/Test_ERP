import base64
import os
import sys
from datetime import datetime, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from ui import page_setup, pay_label
from database import query, query_one
import logic

page_setup("Create Job / Bill", "🧾")

customers = query("SELECT customer_id, customer_name FROM Customers ORDER BY customer_name")
jtm = logic.job_type_map()

# --------------------------------------------------------------------------- #
# Enquiries — review logged enquiries and note the ID to convert
# --------------------------------------------------------------------------- #
st.subheader("📨 Enquiries")
st.caption("Review the logged enquiries below and note the **ID**. Enter that ID in the "
           "**Enquiry ID** box when creating the job — linking a job to its enquiry "
           "auto-fills the customer & description and prevents a duplicate job for the "
           "same enquiry.")

enq_rows = query(
    """
    SELECT e.enquiry_id, e.enquiry_date, e.status, e.remarks,
           e.customer_name, s.source_name,
           (SELECT b.bill_id FROM Bill b WHERE b.enquiry_id = e.enquiry_id
            ORDER BY b.bill_id LIMIT 1) AS bill_id
    FROM Enquiry e
    JOIN Sources s ON e.source_id = s.source_id
    WHERE e.status != 'Cancelled'
    ORDER BY CASE WHEN e.status = 'Pending' THEN 0 ELSE 1 END,
             e.enquiry_date DESC, e.enquiry_id DESC
    """
)
if enq_rows:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "ID": e["enquiry_id"],
                    "Date": e["enquiry_date"],
                    "Customer": e["customer_name"],
                    "Source": e["source_name"],
                    "Remarks": e["remarks"],
                    "Status": e["status"],
                    "Job #": e["bill_id"] if e["bill_id"] else "—",
                }
                for e in enq_rows
            ]
        ),
        width="stretch", hide_index=True,
    )
else:
    st.info("No enquiries logged yet — log one on the Enquiry page.")


# --------------------------------------------------------------------------- #
# Optional: link this job to an enquiry (prevents duplicate jobs)
# --------------------------------------------------------------------------- #
# The "Convert to Job" button on the Enquiry page pre-fills this field.
if "prefill_enquiry" in st.session_state:
    st.session_state["cj_enquiry_id"] = int(st.session_state.pop("prefill_enquiry"))

enquiry_id_input = st.number_input(
    "Enquiry ID (optional)", min_value=0, step=1, key="cj_enquiry_id",
    help="Leave 0 for a walk-up job with no enquiry. Enter an enquiry's ID to link it "
         "— the customer and description are pre-filled and the enquiry is marked "
         "Converted on save.",
)

link_id = int(enquiry_id_input) if enquiry_id_input else 0
prefill = None
link_error = None
if link_id:
    prefill = query_one("SELECT * FROM Enquiry WHERE enquiry_id = ?", (link_id,))
    if not prefill:
        prefill, link_error = None, f"No enquiry #{link_id} found."
    else:
        existing = logic.bill_for_enquiry(link_id)
        if existing:
            link_error = (f"Enquiry #{link_id} is already converted to "
                          f"Job #{existing['bill_id']} — creating another would duplicate it.")
        elif prefill["status"] == "Cancelled":
            link_error = f"Enquiry #{link_id} was cancelled — reopen it before converting."

existing_names = {c["customer_name"] for c in customers}
enquiry_customer_is_new = bool(prefill and prefill["customer_name"] not in existing_names)

if link_error:
    prefill = None
    st.error(link_error)
elif prefill:
    st.success(f"Linking **Enquiry #{link_id}** — customer & description pre-filled; "
               "it'll be marked **Converted** on save.")
    if (prefill["remarks"] or "").strip():
        st.caption(f"📝 Enquiry note: *{prefill['remarks'].strip()}*")
    if enquiry_customer_is_new:
        st.caption(f"🆕 **{prefill['customer_name']}** isn't in the customer master yet — "
                   "it's added automatically when you create this job.")

# Pre-fill the customer box from the linked enquiry — once per linked id, so the
# user's own later edits stick. Only an *existing* master customer is injected (safe);
# a brand-new enquiry name is left for the submit-time fallback below to add to the
# master. Enquiries themselves never touch the master.
if prefill and st.session_state.get("_cj_linked_for") != link_id:
    st.session_state["_cj_linked_for"] = link_id
    match = next((c for c in customers if c["customer_name"] == prefill["customer_name"]), None)
    if match:
        st.session_state["cj_customer"] = match
    else:
        st.session_state.pop("cj_customer", None)
elif not prefill:
    st.session_state.pop("_cj_linked_for", None)

# --------------------------------------------------------------------------- #
# New bill form
# --------------------------------------------------------------------------- #
st.subheader("➕ Create a job / bill")

# Printing method comes first. Only "Digital" opens the Print / Binding / Other
# stages for now; "Offset" and "Other" are selectable placeholders (nothing follows).
method = st.radio(
    "Printing method",
    ["Digital", "Offset", "Other"],
    index=None, horizontal=True, key="cj_method",
    help="Pick how the job is produced. **Digital** opens the Print / Binding / Other "
         "stages below. Offset and Other aren't set up yet.",
)

if method is None:
    st.info("Choose a printing method to start building the job.")
elif method != "Digital":
    st.info(f"**{method}** jobs aren't set up yet — coming soon. "
            "Pick **Digital** to create a job for now.")
else:
    st.caption("Tick the **job type(s)**, then list the **materials each stage will use** "
               "(each stage consumes its own items). Routing runs Print → Binding → Other; "
               "all three adds a final **Binding-2** pass.")

    # Job-type checkboxes live OUTSIDE the form so the per-stage editors react live.
    j1, j2, j3 = st.columns(3)
    want_print = j1.checkbox("🖨️ Print", key="cj_print")
    want_binding = j2.checkbox("📚 Binding", key="cj_binding")
    want_other = j3.checkbox("✨ Other", key="cj_other")

    # Canonical Print → Binding → Other order; all three appends Binding-2.
    selected = [n for n, want in
                [("Print", want_print), ("Binding", want_binding), ("Other", want_other)] if want]
    stage_labels = list(selected)
    if set(selected) == {"Print", "Binding", "Other"}:
        stage_labels.append("Binding-2")

    # Per-stage material editors (one per stage in the route), OUTSIDE the form.
    editor_results = {}
    if stage_labels:
        st.markdown("**Materials per stage** — add one row per material; quantities issue from stock when that stage completes.")
        st.caption("Only catalogued items appear here — add missing ones on the **Item Master** page first.")
    for label in stage_labels:
        type_name = "Binding" if label == "Binding-2" else label
        type_id = jtm[type_name]
        type_items = logic.items_for_job_types([type_id])
        name_to_id = {it["item_name"]: it["item_id"] for it in type_items}
        options = list(name_to_id.keys())

        default_df = pd.DataFrame(columns=["Item", "Color", "Qty"])

        tag = " 🔁 (2nd binding pass)" if label == "Binding-2" else ""
        st.markdown(f"**{label}{tag} materials**")
        edited = st.data_editor(
            default_df,
            column_config={
                "Item": st.column_config.SelectboxColumn("Item", options=options, required=True),
                "Color": st.column_config.TextColumn("Color", help="Optional — printed on the bill"),
                "Qty": st.column_config.NumberColumn("Qty", min_value=1, step=1, default=1),
            },
            num_rows="dynamic", width="stretch", hide_index=True,
            key=f"items_editor_{label}",
        )
        editor_results[label] = (edited, name_to_id, type_id)

    # Suggested order value from item rates (a hint — never auto-fills the field).
    item_rate = {r["item_id"]: r["rate"] for r in query("SELECT item_id, rate FROM Items")}
    suggested_total = 0.0
    for _label, (_edited, _name_to_id, _tid) in editor_results.items():
        for _, _row in _edited.iterrows():
            _nm, _qty = _row.get("Item"), _row.get("Qty")
            if _nm in _name_to_id and _qty and not pd.isna(_qty) and _qty > 0:
                suggested_total += (item_rate.get(_name_to_id[_nm]) or 0) * int(_qty)

    with st.form("new_bill"):
        c1, c2 = st.columns(2)
        cust = c1.selectbox("Customer", customers, index=None, key="cj_customer",
                            format_func=lambda r: r["customer_name"],
                            accept_new_options=True,
                            placeholder="Select a customer, or type a new name…")
        total = c2.number_input("Order value (₹)", min_value=0, value=0, step=500)
        if suggested_total > 0:
            st.caption(f"💡 Suggested from item rates: ₹{suggested_total:,.2f} "
                       "(rate × qty) — a hint, not applied automatically.")
        job_desc = st.text_area("Job description", value=(prefill["remarks"] if prefill else ""))

        c3, c4 = st.columns(2)
        d_date = c3.date_input("Delivery date", value=datetime.now().date())
        d_time = c4.time_input("Delivery time", value=time(17, 0))

        submitted = st.form_submit_button("Create job")

        if submitted:
            # Gather line items from each stage's editor.
            collected, any_item, primary_item_id = {}, False, None
            for label, (edited, name_to_id, type_id) in editor_results.items():
                lines = []
                for _, row in edited.iterrows():
                    name, qty = row.get("Item"), row.get("Qty")
                    if name in name_to_id and qty and not pd.isna(qty) and qty > 0:
                        iid = name_to_id[name]
                        color = row.get("Color")
                        color = None if (color is None or pd.isna(color) or not str(color).strip()) \
                            else str(color).strip()
                        lines.append((type_id, iid, int(qty), color))
                        any_item = True
                        primary_item_id = primary_item_id or iid
                collected[label] = lines

            # Effective customer name: the box value, or (for a converted enquiry whose
            # new customer wasn't injected into the box) fall back to the enquiry's name —
            # so converting a job ALWAYS carries the customer into the master.
            if isinstance(cust, dict):
                cust_name = cust["customer_name"]
            elif isinstance(cust, str) and cust.strip():
                cust_name = cust.strip()
            elif prefill:
                cust_name = prefill["customer_name"]
            else:
                cust_name = None

            is_new_customer = bool(cust_name and cust_name not in existing_names)
            cust_id = logic.resolve_customer(cust_name)  # adds the master row if the name is new
            if link_error:
                st.error(link_error)
            elif not selected:
                st.error("Tick at least one job type (above the form).")
            elif not cust_id:
                st.error("Select or type a customer.")
            elif not any_item:
                st.error("Add at least one material line item to a stage.")
            else:
                delivery = datetime.combine(d_date, d_time).strftime("%Y-%m-%d %H:%M:%S")
                bill_id = logic.create_bill(
                    customer_id=cust_id,
                    item_id=primary_item_id,
                    job_description=job_desc,
                    delivery_datetime=delivery,
                    total_amount=total,
                    selected_job_types=selected,
                    enquiry_id=link_id or None,
                )
                for label, lines in collected.items():
                    for type_id, iid, qty, color in lines:
                        logic.add_bill_item(bill_id, label, type_id, iid, qty, color)
                if link_id:
                    logic.convert_enquiry(link_id)

                stages = [s["stage_label"] for s in query(
                    "SELECT stage_label FROM JobStage WHERE bill_id = ? ORDER BY sequence_no",
                    (bill_id,))]
                success_msg = (
                    f"Created Bill #{bill_id} with stages: {' → '.join(stages)}. "
                    f"First stage **{stages[0]}** is now In Progress."
                )
                if link_id:
                    success_msg += f" 🔗 Linked to Enquiry #{link_id}, now marked Converted."
                if is_new_customer:
                    success_msg += (f" 🆕 New customer **{cust_name}** added to the "
                                    "customer master.")
                st.success(success_msg)

# --------------------------------------------------------------------------- #
# All bills
# --------------------------------------------------------------------------- #
st.subheader("📋 All bills")
st.caption("Once a bill is **fully paid** it drops off this active list — it's still kept "
           "in the records (open **Paid / closed bills** below to see it).")
bills = query(
    """
    SELECT b.bill_id, c.customer_name, b.job_description,
           b.delivery_datetime, b.total_amount, b.payment_status, b.overall_status
    FROM Bill b
    JOIN Customers c ON b.customer_id = c.customer_id
    ORDER BY b.bill_id DESC
    """
)


def _bill_row(b):
    stages = query(
        "SELECT stage_label, stage_status FROM JobStage WHERE bill_id = ? ORDER BY sequence_no",
        (b["bill_id"],),
    )
    route = " → ".join(
        f"{s['stage_label']}{'✓' if s['stage_status'] == 'Completed' else ''}"
        for s in stages
    )
    return {
        "Bill #": b["bill_id"],
        "Customer": b["customer_name"],
        "Materials": logic.bill_items_summary(b["bill_id"]),
        "Overall status": b["overall_status"],
        "Payment": pay_label(b["payment_status"]),
        "Value": f"₹{b['total_amount']:,.0f}",
        "Paid": f"₹{logic.amount_paid(b['bill_id']):,.0f}",
        "Due": f"₹{logic.amount_due(b['bill_id']):,.0f}",
        "Route": route,
        "Delivery": b["delivery_datetime"],
    }


# Fully-paid bills are removed from the active list but retained in the DB (master).
active_bills = [b for b in bills if b["payment_status"] != "Paid"]
paid_bills = [b for b in bills if b["payment_status"] == "Paid"]

if active_bills:
    st.dataframe(pd.DataFrame([_bill_row(b) for b in active_bills]),
                 width="stretch", hide_index=True)
elif bills:
    st.success("No outstanding bills — every bill is fully paid. 🎉")
else:
    st.info("No bills yet.")

if paid_bills:
    with st.expander(f"📁 Paid / closed bills ({len(paid_bills)}) — retained for records",
                     expanded=False):
        st.dataframe(pd.DataFrame([_bill_row(b) for b in paid_bills]),
                     width="stretch", hide_index=True)

# --------------------------------------------------------------------------- #
# Print a bill  (dataframes can't host buttons, so pick a bill here to print it)
# --------------------------------------------------------------------------- #
st.subheader("🖨️ Print a bill")
if bills:
    pick = st.selectbox(
        "Select a bill", bills,
        format_func=lambda b: f"#{b['bill_id']} · {b['customer_name']} · {b['overall_status']}",
    )
    doc = logic.bill_document_html(pick["bill_id"])

    # "Print" opens the filled bill in a NEW TAB (decoded from base64 so ₹ / unicode survive).
    b64 = base64.b64encode(doc.encode("utf-8")).decode("ascii")
    opener = f"""
        <button id="printbtn" style="padding:8px 18px;font-size:14px;cursor:pointer;">
          🖨️ Print bill (opens new tab)
        </button>
        <script>
          document.getElementById("printbtn").onclick = function() {{
            const bytes = Uint8Array.from(atob("{b64}"), c => c.charCodeAt(0));
            const html = new TextDecoder("utf-8").decode(bytes);
            const w = window.open("", "_blank");
            w.document.open(); w.document.write(html); w.document.close();
          }};
        </script>
    """
    components.html(opener, height=56)

    with st.expander("Preview the bill", expanded=False):
        components.html(doc, height=560, scrolling=True)

    st.download_button(
        "⬇️ Or download it (HTML)", data=doc,
        file_name=f"{('JW-%04d' % pick['bill_id'])}.html", mime="text/html",
    )
else:
    st.caption("Create a bill first, then you can print it here.")
