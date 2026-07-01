"""
Job-Shop ERP — demo entry point / Dashboard.

Run with:  streamlit run Home.py
The SQLite DB auto-creates and seeds itself on first run.
"""

import pandas as pd
import streamlit as st

from ui import page_setup, pay_label
from database import query
import logic

page_setup("Dashboard", "🏭")

st.caption("Print / Binding job-shop — end-to-end demo. Use the sidebar to walk the workflow.")

# --------------------------------------------------------------------------- #
# Top-line metrics
# --------------------------------------------------------------------------- #
pending = logic.count_pending_enquiries()
overdue = logic.count_overdue_enquiries()
dept = logic.count_jobs_in_progress_by_department()
unpaid = logic.count_unpaid_bills()
low_stock = logic.low_stock_items()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Pending enquiries", pending, delta=f"{overdue} overdue ⚠️" if overdue else None,
          delta_color="inverse")
c2.metric("Jobs in progress", sum(dept.values()))
c3.metric("Unpaid / partial jobs", unpaid)
c4.metric("Low-stock items", len(low_stock))

st.divider()

# --------------------------------------------------------------------------- #
# Department workload + active jobs
# --------------------------------------------------------------------------- #
left, right = st.columns([1, 2])

with left:
    st.subheader("🛠️ Department workload")
    d1, d2, d3 = st.columns(3)
    d1.metric("🖨️ Print", dept["Print"])
    d2.metric("📚 Binding", dept["Binding"])
    d3.metric("✨ Other", dept["Other"])

    if low_stock:
        st.subheader("📉 Low stock")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Item": r["item_name"],
                        "Available": r["quantity_available"],
                        "Reorder ≤": r["reorder_level"],
                        "UOM": r["unit_of_measure"],
                    }
                    for r in low_stock
                ]
            ),
            width="stretch",
            hide_index=True,
        )

with right:
    st.subheader("📋 Active jobs")
    bills = query(
        """
        SELECT b.bill_id, c.customer_name, i.item_name, b.job_description,
               b.delivery_datetime, b.overall_status, b.payment_status, b.total_amount
        FROM Bill b
        JOIN Customers c ON b.customer_id = c.customer_id
        JOIN Items i     ON b.item_id = i.item_id
        ORDER BY (b.overall_status = 'Completed'), b.delivery_datetime
        """
    )
    if bills:
        rows = []
        for b in bills:
            due = logic.amount_due(b["bill_id"])
            rows.append(
                {
                    "Bill #": b["bill_id"],
                    "Customer": b["customer_name"],
                    "Item": b["item_name"],
                    "Status": b["overall_status"],
                    "Payment": pay_label(b["payment_status"]),
                    "Amount due": f"₹{due:,.0f}",
                    "Delivery": b["delivery_datetime"],
                }
            )
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    else:
        st.info("No bills yet. Create one from the **Create Job** page.")

st.divider()
with st.expander("ℹ️ Suggested demo walkthrough"):
    st.markdown(
        """
1. **Enquiry** — note the aged enquiry flagged with ⚠️, then **Convert to Job** selecting *all three* job types.
2. **Print Department** — the new job appears; mark it complete.
3. **Binding Department** — it moves here; note the 🔴 payment warning if unpaid.
4. **Payments** — record a payment, then return and complete Binding.
5. **Other Department** → back to **Binding** for the **Binding-2** pass; complete it.
6. The bill's overall status flips to **Completed**.
7. **Stock** levels drop with each completion; the **Dashboard** reflects everything.
        """
    )
