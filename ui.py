"""
Shared Streamlit UI helpers.

Keeps page files short and the three department screens DRY — they all call
render_department_page() with their own name.
"""

import pandas as pd
import streamlit as st

from database import bootstrap, query, query_one
import logic

PAY_ICON = {"Paid": "🟢 Paid", "Partial": "🟡 Partial", "Unpaid": "🔴 Unpaid"}


def page_setup(title, icon="🧾"):
    """First Streamlit call on every page: set config, ensure DB, show title."""
    st.set_page_config(page_title=f"{title} · Job-Shop ERP", page_icon=icon, layout="wide")
    bootstrap()
    st.title(f"{icon} {title}")


def pay_label(status):
    return PAY_ICON.get(status, status)


def get_department_stages(department):
    """In-progress JobStage rows for one department, enriched with bill/customer."""
    return query(
        """
        SELECT js.stage_id, js.stage_label, js.sequence_no, js.start_time, js.assigned_by,
               b.bill_id, b.payment_status, b.delivery_datetime, b.job_description,
               c.customer_name, e.employee_name
        FROM JobStage js
        JOIN Bill b      ON js.bill_id = b.bill_id
        JOIN Customers c ON b.customer_id = c.customer_id
        LEFT JOIN Employees e ON js.assigned_to = e.employee_id
        WHERE js.job_type_id = (SELECT job_type_id FROM JobTypes WHERE job_type_name = ?)
          AND js.stage_status = 'In Progress'
        ORDER BY b.delivery_datetime
        """,
        (department,),
    )


def render_department_page(department, icon):
    page_setup(f"{department} Department", icon)

    # Flash message (survives the rerun) so the worker sees where the job went next.
    flash_key = f"dept_flash_{department}"
    if flash_key in st.session_state:
        st.success(st.session_state.pop(flash_key))

    rows = get_department_stages(department)
    if not rows:
        st.info(f"No {department} jobs are currently in progress. 🎉")
        st.caption("Jobs appear here when their stage becomes the active one in the routing order.")
        return

    st.caption("Jobs whose **current** active stage belongs to this department. "
               "**Materials** shows what *this* stage will issue from stock on completion.")

    # ---- Overview table ----
    table = []
    for r in rows:
        stage_display = r["stage_label"]
        if r["stage_label"] == "Binding-2":
            stage_display = "🔁 Binding-2 (2nd pass)"
        table.append(
            {
                "Bill #": r["bill_id"],
                "Stage": stage_display,
                "Customer": r["customer_name"],
                "Materials": logic.bill_items_summary(r["bill_id"], r["stage_label"]),
                "Job": r["job_description"],
                "Delivery": r["delivery_datetime"],
                "Payment": pay_label(r["payment_status"]),
                "Assigned by": r["assigned_by"] or "—",
                "Worker": r["employee_name"] or "—",
            }
        )
    st.dataframe(pd.DataFrame(table), width="stretch", hide_index=True)

    # ---- Per-job action cards ----
    st.markdown("### ✅ Mark a job stage complete")

    for r in rows:
        badge = pay_label(r["payment_status"])
        stage_tag = "  ·  🔁 Binding-2" if r["stage_label"] == "Binding-2" else ""
        header = f"Bill #{r['bill_id']} — {r['customer_name']}  ·  {badge}{stage_tag}"

        with st.expander(header, expanded=False):
            c1, c2 = st.columns(2)
            c1.markdown(f"**Customer:** {r['customer_name']}")
            c1.markdown(f"**Stage:** {r['stage_label']} (seq {r['sequence_no']})")
            c1.markdown(f"**Job:** {r['job_description']}")
            c2.markdown(f"**Delivery:** {r['delivery_datetime']}")
            c2.markdown(f"**Started:** {r['start_time'] or '—'}")
            c2.markdown(f"**Assigned by:** {r['assigned_by'] or '—'}")
            c2.markdown(f"**Worker:** {r['employee_name'] or '—'}")

            # Materials this stage will issue from stock on completion.
            items = logic.get_bill_items(r["bill_id"], r["stage_label"])
            st.markdown("**Materials to issue on completion:**")
            if items:
                st.dataframe(
                    pd.DataFrame(
                        [
                            {"Item": it["item_name"], "Qty": int(it["quantity"]),
                             "UOM": it["unit_of_measure"] or "units"}
                            for it in items
                        ]
                    ),
                    width="stretch", hide_index=True,
                )
            else:
                st.caption("No materials linked to this stage — nothing will be deducted.")

            # Payment is shown for information only — it's collected at the front desk
            # (Payments page), never here. It does not block completing the work.
            if r["payment_status"] != "Paid":
                st.warning(f"🔴 Payment: **{r['payment_status']}** — for info only; "
                           "collected at the front desk, not here.")

            if st.button("✅ Mark Complete", key=f"complete_{r['stage_id']}"):
                result = logic.complete_stage(r["stage_id"])
                if result["ok"]:
                    msg = f"Completed **{result['completed_label']}** for Bill #{r['bill_id']}. "
                    if result["next_label"]:
                        msg += f"➡️ Now with **{result['next_label']}** — open that department's screen."
                    else:
                        msg += "🎉 Bill is now **Completed**."
                    issued = "  ".join(
                        f"(−{int(i['quantity'])} {i['item_name']})" for i in result["issued"]
                    )
                    st.session_state[flash_key] = msg + (f"  Stock issued: {issued}" if issued else "")
                    st.rerun()
                else:
                    st.error(result["message"])
