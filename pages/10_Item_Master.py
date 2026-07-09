import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import streamlit as st

from ui import page_setup
from database import query
import logic

page_setup("Item Master", "📑")

st.caption("Manage the item catalogue. Items are job-type-specific — they drive the "
           "type-filtered pickers on Enquiry and Create Job. Stock quantities are "
           "managed on the **Stock** page; here you set the reorder level.")

job_types = query("SELECT job_type_id, job_type_name FROM JobTypes ORDER BY job_type_id")
jtm = logic.job_type_map()
JT_NAMES = [r["job_type_name"] for r in job_types]


def _s(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


# --------------------------------------------------------------------------- #
# Add an item
# --------------------------------------------------------------------------- #
st.subheader("➕ Add an item")
with st.form("add_item", clear_on_submit=True):
    c1, c2, c3 = st.columns(3)
    name = c1.text_input("Item name *")
    jt = c2.selectbox("Job type", job_types, format_func=lambda r: r["job_type_name"])
    uom = c3.text_input("Unit of measure", value="Units")
    c4, c5, c6 = st.columns(3)
    qty = c4.number_input("Opening stock qty", min_value=0, value=0, step=10)
    reorder = c5.number_input("Reorder level", min_value=0, value=10, step=5)
    rate = c6.number_input(
        "Rate (₹) — optional", min_value=0.0, value=None, step=1.0,
        placeholder="e.g. 50.00",
        help="Per-unit rate. Optional — surfaced only as a suggestion when pricing jobs.",
    )
    if st.form_submit_button("Add item"):
        if not name.strip():
            st.error("Item name is required.")
        else:
            logic.create_item(name, jt["job_type_id"], uom or "Units",
                              initial_qty=qty, reorder_level=reorder, rate=rate)
            st.success(f"Added '{name.strip()}' under {jt['job_type_name']}.")
            st.rerun()

# --------------------------------------------------------------------------- #
# List + inline edit
# --------------------------------------------------------------------------- #
st.subheader("📋 Items")
items = query(
    """
    SELECT i.item_id, i.item_name, i.unit_of_measure, i.rate, jt.job_type_name,
           COALESCE(s.quantity_available, 0) AS qty, COALESCE(s.reorder_level, 0) AS reorder,
           (SELECT COUNT(DISTINCT bill_id)    FROM BillItem bi   WHERE bi.item_id = i.item_id) AS bills
    FROM Items i
    JOIN JobTypes jt ON i.job_type_id = jt.job_type_id
    LEFT JOIN Stock s ON s.item_id = i.item_id
    ORDER BY jt.job_type_id, i.item_name
    """
)

if not items:
    st.info("No items yet — add one above.")
else:
    st.caption("Edit name / job type / unit / **rate** / reorder inline, then **Save changes**. "
               "Rate is optional (leave blank if not priced yet). Available stock and usage "
               "counts are read-only.")
    df = pd.DataFrame(
        [
            {
                "ID": it["item_id"],
                "Item": it["item_name"],
                "Job type": it["job_type_name"],
                "Unit": it["unit_of_measure"] or "",
                "Rate": it["rate"],
                "Available": it["qty"],
                "Reorder": it["reorder"],
                "Bills": it["bills"],
            }
            for it in items
        ]
    )
    edited = st.data_editor(
        df,
        column_config={
            "ID": st.column_config.NumberColumn("ID", disabled=True),
            "Item": st.column_config.TextColumn("Item", required=True),
            "Job type": st.column_config.SelectboxColumn("Job type", options=JT_NAMES, required=True),
            "Unit": st.column_config.TextColumn("Unit"),
            "Rate": st.column_config.NumberColumn("Rate (₹)", min_value=0, format="%.2f",
                                                  help="Per-unit rate — a suggestion when pricing jobs"),
            "Available": st.column_config.NumberColumn("Available", disabled=True,
                                                       help="Manage stock on the Stock page"),
            "Reorder": st.column_config.NumberColumn("Reorder", min_value=0, step=5),
            "Bills": st.column_config.NumberColumn("Bills", disabled=True),
        },
        num_rows="fixed", hide_index=True, width="stretch", key="item_editor",
    )

    if st.button("💾 Save changes"):
        if any(not _s(row["Item"]) for _, row in edited.iterrows()):
            st.error("Item name cannot be blank.")
        else:
            for _, row in edited.iterrows():
                logic.update_item(
                    item_id=int(row["ID"]),
                    item_name=_s(row["Item"]),
                    job_type_id=jtm[row["Job type"]],
                    unit_of_measure=_s(row["Unit"]) or "Units",
                    reorder_level=float(row["Reorder"] or 0),
                    rate=(None if pd.isna(row["Rate"]) else float(row["Rate"])),
                )
            st.success("Item changes saved.")
            st.rerun()
