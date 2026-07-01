import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

from ui import page_setup
import logic

page_setup("Settings", "⚙️")

st.caption("Tunable thresholds used across the app. Values are stored in the **AlertConfig** table.")

# Friendly labels/help for the known config keys.
META = {
    "enquiry_pending_days_threshold": (
        "Enquiry aging threshold (days)",
        "Pending enquiries older than this many days are flagged ⚠️ on the Enquiry page.",
    ),
    "stock_reorder_default": (
        "Default reorder level for new stock items",
        "Used when receiving stock for an item that has no stock record yet.",
    ),
    "default_stock_issue_qty": (
        "Default quantity issued per completed stage",
        "Pre-filled quantity deducted from stock when a department marks a stage complete.",
    ),
}

configs = logic.all_config()

with st.form("settings"):
    new_values = {}
    for cfg in configs:
        key = cfg["config_key"]
        label, help_text = META.get(key, (key, None))
        try:
            current = int(cfg["config_value"])
            new_values[key] = st.number_input(label, min_value=0, value=current,
                                               step=1, help=help_text, key=f"cfg_{key}")
        except (TypeError, ValueError):
            new_values[key] = st.text_input(label, value=cfg["config_value"],
                                            help=help_text, key=f"cfg_{key}")

    if st.form_submit_button("💾 Save settings"):
        for key, value in new_values.items():
            logic.set_config(key, value)
        st.success("Settings saved.")
        st.rerun()

st.divider()
st.subheader("Current values")
st.table([{"Setting": c["config_key"], "Value": c["config_value"]} for c in logic.all_config()])
