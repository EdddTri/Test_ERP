import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import streamlit as st

from ui import page_setup
from database import query
import logic

page_setup("Enquiry", "📨")

# Flash message that survives the post-save rerun.
if "enq_flash" in st.session_state:
    st.success(st.session_state.pop("enq_flash"))

sources = query("SELECT source_id, source_name FROM Sources ORDER BY source_name")
customers = query("SELECT customer_id, customer_name FROM Customers ORDER BY customer_name")
jtm = logic.job_type_map()

# --------------------------------------------------------------------------- #
# Add new enquiry  (multiple job types, with materials per type)
# --------------------------------------------------------------------------- #
st.subheader("➕ Log a new enquiry")
st.caption("Tick **every job type** this enquiry covers (e.g. Print *and* Binding), "
           "then list the items per type. Items are filtered to each type.")

# Job-type checkboxes live OUTSIDE the form so the per-type editors react live.
j1, j2, j3 = st.columns(3)
want_print = j1.checkbox("🖨️ Print", key="enq_print")
want_binding = j2.checkbox("📚 Binding", key="enq_binding")
want_other = j3.checkbox("✨ Other", key="enq_other")
selected = [n for n, want in
            [("Print", want_print), ("Binding", want_binding), ("Other", want_other)] if want]

# Per-type material editors (one per ticked job type), OUTSIDE the form.
editor_results = {}
if selected:
    st.markdown("**Items per job type** — add one row per item the customer asked about.")
    st.caption("Only catalogued items appear here — add missing ones on the **Item Master** page first.")
for name in selected:
    type_id = jtm[name]
    type_items = logic.items_for_job_types([type_id])
    name_to_id = {it["item_name"]: it["item_id"] for it in type_items}
    options = list(name_to_id.keys())

    st.markdown(f"**{name} items**")
    edited = st.data_editor(
        pd.DataFrame(columns=["Item", "Qty"]),
        column_config={
            "Item": st.column_config.SelectboxColumn("Item", options=options, required=True),
            "Qty": st.column_config.NumberColumn("Qty", min_value=1, step=1, default=1),
        },
        num_rows="dynamic", width="stretch", hide_index=True,
        key=f"enq_items_{name}",
    )
    editor_results[name] = (edited, name_to_id, type_id)

# Source is an MCQ — picking one reveals the matching contact field. It lives
# OUTSIDE the form so the field appears the moment you choose a source.
source_names = [s["source_name"] for s in sources]
src_name = st.radio("Source — how did the enquiry come in?", source_names,
                    index=None, horizontal=True, key="enq_source")

contact, contact_required = "", False
if src_name == "Email":
    contact = st.text_input("Email address", key="enq_contact", placeholder="name@example.com")
    contact_required = True
elif src_name == "WhatsApp":
    contact = st.text_input("WhatsApp number", key="enq_contact", placeholder="+91 …")
    contact_required = True
elif src_name == "Phone Call":
    contact = st.text_input("Phone number", key="enq_contact", placeholder="+91 …")
    contact_required = True
elif src_name == "Walk-in":
    st.caption("Walk-in — no contact detail needed.")

with st.form("new_enquiry", clear_on_submit=True):
    c1, c2 = st.columns(2)
    cust = c1.selectbox(
        "Customer", customers, index=None, format_func=lambda r: r["customer_name"],
        accept_new_options=True,
        placeholder="Select a customer, or type a new name…",
    )
    remarks = c2.text_area("Remarks", placeholder="What does the customer need?")
    status = st.radio("Status", ["Pending", "Cancelled"], index=0, horizontal=True,
                      help="Record a dead / declined enquiry as Cancelled — it's still "
                           "logged in the enquiry table (job types & items optional).")
    submitted = st.form_submit_button("Save enquiry")

    if submitted:
        is_cancelled = status == "Cancelled"
        line_items = []
        for name, (edited, name_to_id, type_id) in editor_results.items():
            for _, row in edited.iterrows():
                nm, qty = row.get("Item"), row.get("Qty")
                if nm in name_to_id and qty and not pd.isna(qty) and qty > 0:
                    line_items.append((type_id, name_to_id[nm], int(qty)))

        existing_names = {c["customer_name"] for c in customers}
        is_new_customer = (isinstance(cust, str) and cust.strip()
                           and cust.strip() not in existing_names)
        cust_id = logic.resolve_customer(cust)
        src_id = next((s["source_id"] for s in sources if s["source_name"] == src_name), None)
        contact_value = (contact or "").strip()

        if not src_name:
            st.error("Select how the enquiry came in (source).")
        elif contact_required and not is_cancelled and not contact_value:
            st.error(f"Enter the {src_name} contact detail.")
        elif not cust_id:
            st.error("Select or type a customer.")
        elif not is_cancelled and not selected:
            st.error("Tick at least one job type (above the form).")
        elif not is_cancelled and not line_items:
            st.error("Add at least one item to a job type.")
        else:
            logic.create_enquiry(src_id, cust_id, remarks, line_items,
                                 source_contact=contact_value or None, status=status)
            logic.apply_enquiry_contact(cust_id, src_name, contact_value)
            msg = "🚫 Cancelled enquiry recorded." if is_cancelled else "Enquiry logged."
            if is_new_customer:
                msg += (f" 🆕 New customer **{cust.strip()}** added to the customer master "
                        "— they'll be suggested next time.")
            # Reset the inputs for the next entry.
            for k in ["enq_print", "enq_binding", "enq_other", "enq_source", "enq_contact"] + \
                     [f"enq_items_{n}" for n in selected]:
                st.session_state.pop(k, None)
            st.session_state["enq_flash"] = msg
            st.rerun()

# --------------------------------------------------------------------------- #
# All enquiries
# --------------------------------------------------------------------------- #
st.subheader("📋 All enquiries")
threshold = logic.get_config_int("enquiry_pending_days_threshold", 3)
st.caption(f"Pending enquiries older than **{threshold} days** are flagged ⚠️ "
           "(edit the threshold on the Settings page).")

enquiries = query(
    """
    SELECT e.enquiry_id, e.enquiry_date, e.status, e.remarks, e.source_contact,
           s.source_name, c.customer_name
    FROM Enquiry e
    JOIN Sources s    ON e.source_id = s.source_id
    JOIN Customers c  ON e.customer_id = c.customer_id
    ORDER BY e.enquiry_date DESC, e.enquiry_id DESC
    """
)

if enquiries:
    table = []
    for e in enquiries:
        dp = logic.days_pending(e["enquiry_date"])
        alert = ("⚠️" if dp > threshold else "") if e["status"] == "Pending" else ""
        table.append(
            {
                "ID": e["enquiry_id"],
                "Date": e["enquiry_date"],
                "Customer": e["customer_name"],
                "Job types": ", ".join(logic.enquiry_job_types(e["enquiry_id"])) or "—",
                "Items": logic.enquiry_items_summary(e["enquiry_id"]),
                "Source": e["source_name"],
                "Via": e["source_contact"] or "—",
                "Status": e["status"],
                "Days pending": str(dp) if e["status"] == "Pending" else "—",
                "Alert": alert,
                "Remarks": e["remarks"],
            }
        )
    st.dataframe(pd.DataFrame(table), width="stretch", hide_index=True)
else:
    st.info("No enquiries yet.")

# --------------------------------------------------------------------------- #
# Actions on pending enquiries
# --------------------------------------------------------------------------- #
pending = [e for e in enquiries if e["status"] == "Pending"]
if pending:
    st.subheader("⚙️ Act on a pending enquiry")
    for e in pending:
        dp = logic.days_pending(e["enquiry_date"])
        flag = " ⚠️" if dp > threshold else ""
        types = ", ".join(logic.enquiry_job_types(e["enquiry_id"])) or "—"
        mats = logic.enquiry_items_summary(e["enquiry_id"])
        with st.container(border=True):
            c1, c2, c3 = st.columns([4, 1, 1])
            c1.markdown(
                f"**#{e['enquiry_id']} · {e['customer_name']}** — {types}{flag}  \n"
                f"{mats}  \n*{e['remarks'] or 'No remarks'}* · {dp} days pending"
            )
            if c2.button("➡️ Convert to Job", key=f"conv_{e['enquiry_id']}"):
                st.session_state["prefill_enquiry"] = e["enquiry_id"]
                st.switch_page("pages/2_Create_Job.py")
            if c3.button("✖️ Cancel", key=f"cancel_{e['enquiry_id']}"):
                logic.cancel_enquiry(e["enquiry_id"])
                st.rerun()
