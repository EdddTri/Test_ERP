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
# Prefill from a converted enquiry (set on the Enquiry page)
# --------------------------------------------------------------------------- #
prefill = None
prefill_enquiry_id = st.session_state.get("prefill_enquiry")
pre_types = []
if prefill_enquiry_id:
    prefill = query_one("SELECT * FROM Enquiry WHERE enquiry_id = ?", (prefill_enquiry_id,))
    if prefill:
        pre_types = logic.enquiry_job_types(prefill_enquiry_id)
        st.info(
            f"Pre-filled from Enquiry **#{prefill_enquiry_id}** "
            f"({', '.join(pre_types) or '—'}) — its job types and materials are carried over. "
            "It will be marked **Converted** on save."
        )

def _index(rows, key, value):
    for i, r in enumerate(rows):
        if r[key] == value:
            return i
    return 0

# No prefill -> start blank (index=None); with prefill, pre-select the enquiry's customer.
cust_idx = _index(customers, "customer_id", prefill["customer_id"]) if prefill else None

# --------------------------------------------------------------------------- #
# New bill form
# --------------------------------------------------------------------------- #
st.subheader("➕ Create a job / bill")
st.caption("Tick the **job type(s)**, then list the **materials each stage will use** "
           "(each stage consumes its own items). Routing runs Print → Binding → Other; "
           "all three adds a final **Binding-2** pass.")

# Job-type checkboxes live OUTSIDE the form so the per-stage editors react live.
j1, j2, j3 = st.columns(3)
want_print = j1.checkbox("🖨️ Print", value=("Print" in pre_types), key="cj_print")
want_binding = j2.checkbox("📚 Binding", value=("Binding" in pre_types), key="cj_binding")
want_other = j3.checkbox("✨ Other", value=("Other" in pre_types), key="cj_other")

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

    # Prefill from the enquiry's materials for this type (Binding-2 starts empty).
    default_rows = []
    if prefill and label != "Binding-2":
        for ei in logic.get_enquiry_items(prefill_enquiry_id, type_id):
            if ei["item_name"] in name_to_id:
                default_rows.append({"Item": ei["item_name"], "Color": "", "Qty": int(ei["quantity"])})
    default_df = pd.DataFrame(default_rows, columns=["Item", "Color", "Qty"])

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
    cust = c1.selectbox("Customer", customers, index=cust_idx,
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

        existing_names = {c["customer_name"] for c in customers}
        is_new_customer = (isinstance(cust, str) and cust.strip()
                           and cust.strip() not in existing_names)
        cust_id = logic.resolve_customer(cust)
        if not selected:
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
                enquiry_id=prefill_enquiry_id if prefill else None,
            )
            for label, lines in collected.items():
                for type_id, iid, qty, color in lines:
                    logic.add_bill_item(bill_id, label, type_id, iid, qty, color)
            if prefill:
                logic.convert_enquiry(prefill_enquiry_id)
                st.session_state.pop("prefill_enquiry", None)

            stages = [s["stage_label"] for s in query(
                "SELECT stage_label FROM JobStage WHERE bill_id = ? ORDER BY sequence_no",
                (bill_id,))]
            success_msg = (
                f"Created Bill #{bill_id} with stages: {' → '.join(stages)}. "
                f"First stage **{stages[0]}** is now In Progress."
            )
            if is_new_customer:
                success_msg += (f" 🆕 New customer **{cust.strip()}** added to the "
                                "customer master.")
            st.success(success_msg)

# --------------------------------------------------------------------------- #
# All bills
# --------------------------------------------------------------------------- #
st.subheader("📋 All bills")
bills = query(
    """
    SELECT b.bill_id, c.customer_name, b.job_description,
           b.delivery_datetime, b.total_amount, b.payment_status, b.overall_status
    FROM Bill b
    JOIN Customers c ON b.customer_id = c.customer_id
    ORDER BY b.bill_id DESC
    """
)
if bills:
    rows = []
    for b in bills:
        stages = query(
            "SELECT stage_label, stage_status FROM JobStage WHERE bill_id = ? ORDER BY sequence_no",
            (b["bill_id"],),
        )
        route = " → ".join(
            f"{s['stage_label']}{'✓' if s['stage_status'] == 'Completed' else ''}"
            for s in stages
        )
        rows.append(
            {
                "Bill #": b["bill_id"],
                "Customer": b["customer_name"],
                "Materials": logic.bill_items_summary(b["bill_id"]),
                "Overall status": b["overall_status"],
                "Payment": pay_label(b["payment_status"]),
                "Value": f"₹{b['total_amount']:,.0f}",
                "Route": route,
                "Delivery": b["delivery_datetime"],
            }
        )
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
else:
    st.info("No bills yet.")

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
