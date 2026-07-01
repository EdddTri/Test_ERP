import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import streamlit as st

from ui import page_setup, pay_label
from database import query
import logic

page_setup("Payments", "💰")

bills = query(
    """
    SELECT b.bill_id, c.customer_name, i.item_name, b.total_amount,
           b.payment_status, b.overall_status
    FROM Bill b
    JOIN Customers c ON b.customer_id = c.customer_id
    JOIN Items i     ON b.item_id = i.item_id
    ORDER BY b.bill_id DESC
    """
)

# --------------------------------------------------------------------------- #
# Bills + amounts due
# --------------------------------------------------------------------------- #
st.subheader("📋 Bills & balances")
if bills:
    rows = []
    for b in bills:
        paid = logic.amount_paid(b["bill_id"])
        due = logic.amount_due(b["bill_id"])
        rows.append(
            {
                "Bill #": b["bill_id"],
                "Customer": b["customer_name"],
                "Item": b["item_name"],
                "Total": f"₹{b['total_amount']:,.0f}",
                "Paid": f"₹{paid:,.0f}",
                "Due": f"₹{due:,.0f}",
                "Payment": pay_label(b["payment_status"]),
                "Job status": b["overall_status"],
            }
        )
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
else:
    st.info("No bills yet.")

# --------------------------------------------------------------------------- #
# Record a payment
# --------------------------------------------------------------------------- #
st.subheader("➕ Record a payment")
open_bills = [b for b in bills if b["payment_status"] != "Paid"]
if not open_bills:
    st.success("All bills are fully paid. 🎉")
else:
    with st.form("record_payment", clear_on_submit=True):
        bill = st.selectbox(
            "Bill",
            open_bills,
            format_func=lambda b: (
                f"#{b['bill_id']} · {b['customer_name']} · "
                f"due ₹{logic.amount_due(b['bill_id']):,.0f} ({b['payment_status']})"
            ),
        )
        due_now = logic.amount_due(bill["bill_id"])
        c1, c2 = st.columns(2)
        amount = c1.number_input("Amount (₹)", min_value=1.0,
                                 value=float(due_now) if due_now else 1.0, step=500.0)
        mode = c2.selectbox("Payment mode", ["Cash", "Bank Transfer", "UPI", "Card", "Cheque"])
        if st.form_submit_button("Record payment"):
            new_status = logic.record_payment(bill["bill_id"], float(amount), mode)
            st.success(
                f"Recorded ₹{amount:,.0f} ({mode}) against Bill #{bill['bill_id']}. "
                f"Payment status is now **{new_status}**."
            )
            st.rerun()

# --------------------------------------------------------------------------- #
# Payment history
# --------------------------------------------------------------------------- #
st.subheader("🧾 Payment history")
payments = query(
    """
    SELECT p.payment_id, p.payment_date, p.amount, p.payment_mode,
           p.bill_id, c.customer_name
    FROM Payments p
    JOIN Bill b      ON p.bill_id = b.bill_id
    JOIN Customers c ON b.customer_id = c.customer_id
    ORDER BY p.payment_date DESC, p.payment_id DESC
    """
)
if payments:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Date": p["payment_date"],
                    "Bill #": p["bill_id"],
                    "Customer": p["customer_name"],
                    "Amount": f"₹{p['amount']:,.0f}",
                    "Mode": p["payment_mode"],
                }
                for p in payments
            ]
        ),
        width="stretch",
        hide_index=True,
    )
else:
    st.info("No payments recorded yet.")
