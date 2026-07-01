import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import streamlit as st

from ui import page_setup
from database import query
import logic

page_setup("Stock", "📦")

# --------------------------------------------------------------------------- #
# Current stock levels
# --------------------------------------------------------------------------- #
st.subheader("📊 Current stock levels")
stock = query(
    """
    SELECT s.stock_id, s.quantity_available, s.reorder_level, s.last_updated,
           i.item_name, i.unit_of_measure
    FROM Stock s JOIN Items i ON s.item_id = i.item_id
    ORDER BY i.item_name
    """
)

if stock:
    rows = []
    for s in stock:
        low = s["quantity_available"] <= s["reorder_level"]
        rows.append(
            {
                "Item": s["item_name"],
                "Available": s["quantity_available"],
                "UOM": s["unit_of_measure"],
                "Reorder level": s["reorder_level"],
                "Status": "🔴 Reorder" if low else "🟢 OK",
                "Last updated": s["last_updated"],
            }
        )
    df = pd.DataFrame(rows)

    def _highlight(row):
        color = "background-color: #5c1a1a" if row["Status"].startswith("🔴") else ""
        return [color] * len(row)

    st.dataframe(df.style.apply(_highlight, axis=1), width="stretch", hide_index=True)

    low_items = [s for s in stock if s["quantity_available"] <= s["reorder_level"]]
    if low_items:
        st.warning("🔴 " + ", ".join(s["item_name"] for s in low_items) +
                   " — at or below reorder level.")
else:
    st.info("No stock records.")

# --------------------------------------------------------------------------- #
# Manual stock-in
# --------------------------------------------------------------------------- #
st.subheader("➕ Receive stock (manual stock-in)")
items = query("SELECT item_id, item_name, unit_of_measure FROM Items ORDER BY item_name")
with st.form("stock_in", clear_on_submit=True):
    c1, c2 = st.columns([3, 1])
    item = c1.selectbox(
        "Item", items,
        format_func=lambda r: f"{r['item_name']} ({r['unit_of_measure']})",
    )
    qty = c2.number_input("Quantity", min_value=1, value=100, step=10)
    if st.form_submit_button("Receive stock"):
        logic.receive_stock(item["item_id"], int(qty))
        st.success(f"Received {qty} {item['unit_of_measure']} of {item['item_name']}.")
        st.rerun()

# --------------------------------------------------------------------------- #
# Transaction history
# --------------------------------------------------------------------------- #
st.subheader("🧾 Stock transaction history")
txns = query(
    """
    SELECT t.transaction_id, t.transaction_date, t.transaction_type,
           t.quantity_changed, t.bill_id, i.item_name
    FROM StockTransaction t
    JOIN Stock s ON t.stock_id = s.stock_id
    JOIN Items i ON s.item_id = i.item_id
    ORDER BY t.transaction_date DESC, t.transaction_id DESC
    """
)
if txns:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Date": t["transaction_date"],
                    "Item": t["item_name"],
                    "Type": ("📤 Issue" if t["transaction_type"] == "Issue" else "📥 Receipt"),
                    "Qty change": t["quantity_changed"],
                    "Bill #": str(t["bill_id"]) if t["bill_id"] else "—",
                }
                for t in txns
            ]
        ),
        width="stretch",
        hide_index=True,
    )
else:
    st.info("No stock transactions yet.")
