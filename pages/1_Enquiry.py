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

# --------------------------------------------------------------------------- #
# Add new enquiry  (free-text capture — the job breakdown happens at Create Job)
# --------------------------------------------------------------------------- #
st.subheader("➕ Log a new enquiry")
st.caption("Just jot down who asked, how they reached out, and what they want. "
           "The job types and materials are decided later when you **Create the Job**.")

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
    status = c2.radio("Status", ["Pending", "Cancelled"], index=0, horizontal=True,
                      help="Record a dead / declined enquiry as Cancelled — it's still "
                           "logged in the enquiry table.")
    remarks = st.text_area("What does the customer need?",
                           placeholder="e.g. 5000 A4 brochures + spiral binding for the set — urgent")
    submitted = st.form_submit_button("Save enquiry")

    if submitted:
        is_cancelled = status == "Cancelled"
        # Customer is stored as free text — the enquiry never writes to the master.
        cust_name = cust["customer_name"] if isinstance(cust, dict) else (cust or "").strip()
        src_id = next((s["source_id"] for s in sources if s["source_name"] == src_name), None)
        contact_value = (contact or "").strip()

        if not src_name:
            st.error("Select how the enquiry came in (source).")
        elif contact_required and not is_cancelled and not contact_value:
            st.error(f"Enter the {src_name} contact detail.")
        elif not cust_name:
            st.error("Select or type a customer.")
        elif not (remarks or "").strip():
            st.error("Describe what the customer needs.")
        else:
            logic.create_enquiry(src_id, cust_name, remarks.strip(),
                                  source_contact=contact_value or None, status=status)
            msg = "🚫 Cancelled enquiry recorded." if is_cancelled else "Enquiry logged."
            existing_names = {c["customer_name"] for c in customers}
            if cust_name not in existing_names:
                msg += (f" ℹ️ **{cust_name}** isn't in the customer master yet — they'll be "
                        "added automatically when this enquiry is turned into a job.")
            # Reset the inputs for the next entry.
            for k in ["enq_source", "enq_contact"]:
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
           e.customer_name, s.source_name
    FROM Enquiry e
    JOIN Sources s ON e.source_id = s.source_id
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
        with st.container(border=True):
            c1, c2, c3 = st.columns([4, 1, 1])
            c1.markdown(
                f"**#{e['enquiry_id']} · {e['customer_name']}**{flag}  \n"
                f"*{e['remarks'] or 'No remarks'}* · {dp} days pending"
            )
            if c2.button("➡️ Convert to Job", key=f"conv_{e['enquiry_id']}"):
                st.session_state["prefill_enquiry"] = e["enquiry_id"]
                st.switch_page("pages/2_Create_Job.py")
            if c3.button("✖️ Cancel", key=f"cancel_{e['enquiry_id']}"):
                logic.cancel_enquiry(e["enquiry_id"])
                st.rerun()
