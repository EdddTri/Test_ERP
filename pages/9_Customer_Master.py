import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import streamlit as st

from ui import page_setup
from database import query, execute

page_setup("Customer Master", "👥")

st.caption("Manage the customer list used across Enquiries, Jobs and Payments.")


def _s(v):
    """Normalise a cell to a clean string ('' for None/NaN)."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


# --------------------------------------------------------------------------- #
# Add a customer
# --------------------------------------------------------------------------- #
st.subheader("➕ Add a customer")
with st.form("add_customer", clear_on_submit=True):
    c1, c2 = st.columns(2)
    name = c1.text_input("Customer / party name *")
    contact = c2.text_input("Contact person")
    c3, c4 = st.columns(2)
    phone = c3.text_input("Phone")
    email = c4.text_input("Email")
    address = st.text_area("Address")
    if st.form_submit_button("Add customer"):
        if not name.strip():
            st.error("Customer name is required.")
        else:
            execute(
                "INSERT INTO Customers (customer_name, contact_person, phone, email, address) "
                "VALUES (?, ?, ?, ?, ?)",
                (name.strip(), contact.strip(), phone.strip(), email.strip(), address.strip()),
            )
            st.success(f"Added customer '{name.strip()}'.")
            st.rerun()

# --------------------------------------------------------------------------- #
# List + inline edit
# --------------------------------------------------------------------------- #
st.subheader("📋 Customers")
customers = query(
    """
    SELECT c.customer_id, c.customer_name, c.contact_person, c.phone, c.email, c.address,
           (SELECT COUNT(*) FROM Enquiry e WHERE e.customer_name = c.customer_name) AS enquiries,
           (SELECT COUNT(*) FROM Bill b    WHERE b.customer_id = c.customer_id) AS bills
    FROM Customers c
    ORDER BY c.customer_name
    """
)

if not customers:
    st.info("No customers yet — add one above.")
else:
    st.caption("Edit name / contact / phone / email / address inline, then **Save changes**. "
               "ID and usage counts are read-only.")
    df = pd.DataFrame(
        [
            {
                "ID": c["customer_id"],
                "Customer": c["customer_name"],
                "Contact person": c["contact_person"] or "",
                "Phone": c["phone"] or "",
                "Email": c["email"] or "",
                "Address": c["address"] or "",
                "Enquiries": c["enquiries"],
                "Bills": c["bills"],
            }
            for c in customers
        ]
    )
    edited = st.data_editor(
        df,
        column_config={
            "ID": st.column_config.NumberColumn("ID", disabled=True),
            "Customer": st.column_config.TextColumn("Customer", required=True),
            "Contact person": st.column_config.TextColumn("Contact person"),
            "Phone": st.column_config.TextColumn("Phone"),
            "Email": st.column_config.TextColumn("Email"),
            "Address": st.column_config.TextColumn("Address", width="large"),
            "Enquiries": st.column_config.NumberColumn("Enquiries", disabled=True),
            "Bills": st.column_config.NumberColumn("Bills", disabled=True),
        },
        num_rows="fixed", hide_index=True, width="stretch", key="cust_editor",
    )

    if st.button("💾 Save changes"):
        if any(not _s(row["Customer"]) for _, row in edited.iterrows()):
            st.error("Customer name cannot be blank.")
        else:
            for _, row in edited.iterrows():
                execute(
                    "UPDATE Customers SET customer_name = ?, contact_person = ?, phone = ?, "
                    "email = ?, address = ? WHERE customer_id = ?",
                    (_s(row["Customer"]), _s(row["Contact person"]), _s(row["Phone"]),
                     _s(row["Email"]), _s(row["Address"]), int(row["ID"])),
                )
            st.success("Customer changes saved.")
            st.rerun()
