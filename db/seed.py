"""
Sample data for the Job-Shop ERP demo.

seed_data(conn) is called once by database.bootstrap() when the DB is empty.
It writes everything through the passed-in connection so the whole seed is one
transaction and the app opens to a realistic, mid-workflow state.
"""

from datetime import datetime, timedelta


def _d(days_offset=0):
    """A date string N days from today (negative = past)."""
    return (datetime.now() + timedelta(days=days_offset)).strftime("%Y-%m-%d")


def _dt(days_offset=0, hour=10, minute=0):
    """A datetime string N days from today at the given time."""
    base = (datetime.now() + timedelta(days=days_offset)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    return base.strftime("%Y-%m-%d %H:%M:%S")


def seed_data(conn):
    c = conn.cursor()

    # ---------- Lookups ----------
    c.executemany("INSERT INTO JobTypes (job_type_name) VALUES (?)",
                  [("Print",), ("Binding",), ("Other",)])
    PRINT, BINDING, OTHER = 1, 2, 3

    c.executemany("INSERT INTO Sources (source_name) VALUES (?)",
                  [("Email",), ("WhatsApp",), ("Phone Call",), ("Walk-in",)])
    EMAIL, WHATSAPP, PHONE, WALKIN = 1, 2, 3, 4

    # ---------- Customers ----------
    c.executemany(
        "INSERT INTO Customers (customer_name, contact_person, phone, email, address) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            ("Acme Publishing House", "Rahul Verma", "+91 98200 11111",
             "orders@acmepub.com", "12 MG Road, Andheri East, Mumbai 400069"),
            ("Bright Future School", "Mrs. Priya Iyer", "+91 98200 22222",
             "admin@brightfuture.edu", "45 Hill View, Powai, Mumbai 400076"),
            ("Mehta & Sons Stationers", "Suresh Mehta", "+91 98200 33333",
             "mehta.sons@gmail.com", "Shop 7, Market Lane, Dadar West, Mumbai 400028"),
            ("Riverside Wedding Planners", "Anjali Rao", "+91 98200 44444",
             "events@riverside.in", "3rd Flr, Riverside Plaza, Bandra, Mumbai 400050"),
        ],
    )
    ACME, SCHOOL, MEHTA, RIVERSIDE = 1, 2, 3, 4

    # ---------- Items ----------
    c.executemany(
        "INSERT INTO Items (item_name, job_type_id, unit_of_measure, rate) VALUES (?, ?, ?, ?)",
        [
            ("A4 Brochure", PRINT, "Sheets", 2.00),            # 1
            ("Business Cards", PRINT, "Boxes", 150.00),        # 2
            ("Wedding Invitation Cards", PRINT, "Pieces", 25.00),  # 3
            ("Hardcover Book Binding", BINDING, "Books", 120.00),  # 4
            ("Spiral Binding", BINDING, "Documents", 40.00),   # 5
            ("Lamination", OTHER, "Sheets", 5.00),             # 6
            ("Photo Album", OTHER, "Albums", 800.00),          # 7
        ],
    )

    # ---------- Stock (item 5 deliberately below reorder to show low-stock flag) ----------
    stock_rows = [
        (1, 3950, 1000),   # 4000 less the 50 sheets already issued to Bill #1's Print stage
        (2, 50, 20),
        (3, 800, 200),
        (4, 30, 15),
        (5, 8, 25),      # low stock
        (6, 120, 50),
        (7, 12, 10),
    ]
    c.executemany(
        "INSERT INTO Stock (item_id, quantity_available, reorder_level, last_updated) "
        "VALUES (?, ?, ?, ?)",
        [(i, q, r, _dt(-3)) for (i, q, r) in stock_rows],
    )

    # ---------- Employees ----------
    c.executemany(
        "INSERT INTO Employees (employee_name, department) VALUES (?, ?)",
        [
            ("Rajesh Kumar", "Print"),
            ("Sunita Sharma", "Print"),
            ("Amit Patel", "Binding"),
            ("Deepa Nair", "Binding"),
            ("Vikram Singh", "Other"),
        ],
    )

    # ---------- AlertConfig ----------
    c.executemany(
        "INSERT INTO AlertConfig (config_key, config_value) VALUES (?, ?)",
        [
            ("enquiry_pending_days_threshold", "3"),
            ("stock_reorder_default", "10"),
            ("default_stock_issue_qty", "5"),
        ],
    )

    # ---------- Enquiries (free-text — customer is just a name string, no master link) ----------
    c.executemany(
        "INSERT INTO Enquiry (enquiry_date, source_id, customer_name, "
        "status, source_contact, remarks) VALUES (?, ?, ?, ?, ?, ?)",
        [
            # Aged pending enquiry (6 days old) -> triggers the ⚠️ aging alert.
            (_d(-6), EMAIL, "Acme Publishing House", "Pending", "orders@acmepub.com",
             "5000 A4 brochures + spiral binding for the set — urgent"),
            # Fresh pending enquiry (1 day old)
            (_d(-1), WHATSAPP, "Riverside Wedding Planners", "Pending", "+91 98200 44444",
             "Quote requested for 300 wedding invitation cards"),
            # Already converted into Bill #1
            (_d(-9), PHONE, "Bright Future School", "Converted", "+91 98200 22222",
             "Annual yearbook — print, bind and laminate"),
        ],
    )
    ENQ_AGED, ENQ_FRESH, ENQ_CONVERTED = 1, 2, 3

    # ---------- Bill #1: mid-workflow, all-three job types ----------
    # Print done, Binding in progress, Other + Binding-2 pending. Partly paid.
    bill1 = c.execute(
        "INSERT INTO Bill (enquiry_id, customer_id, item_id, job_description, "
        "job_time, delivery_datetime, total_amount, payment_status, overall_status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ENQ_CONVERTED, SCHOOL, 4, "Annual yearbook 2026 — 200 hardcover copies",
         _dt(-2, 9, 30), _dt(3, 17, 0), 2000, "Partial", "In Progress – Binding"),
    ).lastrowid

    job_stages_bill1 = [
        # (job_type_id, label, seq, status, assigned_to, start, end)
        (PRINT, "Print", 1, "Completed", 1, _dt(-2, 9, 30), _dt(-1, 15, 0)),
        (BINDING, "Binding", 2, "In Progress", 3, _dt(-1, 15, 0), None),
        (OTHER, "Other", 3, "Not Started", None, None, None),
        (BINDING, "Binding-2", 4, "Not Started", None, None, None),
    ]
    for jt, label, seq, status, emp, start, end in job_stages_bill1:
        assigned_by = "AT" if status != "Not Started" else None
        c.execute(
            "INSERT INTO JobStage (bill_id, job_type_id, stage_label, sequence_no, "
            "stage_status, assigned_to, assigned_by, start_time, end_time) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (bill1, jt, label, seq, status, emp, assigned_by, start, end),
        )

    # Line items (materials) per stage of Bill #1.
    #   item ids: 1=A4 Brochure(Print), 4=Hardcover Book Binding(Binding), 6=Lamination(Other)
    bill1_items = [
        # (stage_label, job_type_id, item_id, qty, color)
        ("Print", PRINT, 1, 50, "Full Colour"),    # 50 sheets for printing
        ("Binding", BINDING, 4, 10, "Maroon"),     # 10 hardcover bind sets
        ("Other", OTHER, 6, 20, "Gloss"),          # 20 lamination sheets
        ("Binding-2", BINDING, 4, 5, "Maroon"),    # 5 for the second binding pass
    ]
    c.executemany(
        "INSERT INTO BillItem (bill_id, stage_label, job_type_id, item_id, quantity, color) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(bill1, label, jt, item, qty, color) for (label, jt, item, qty, color) in bill1_items],
    )

    # A partial payment already recorded against Bill #1
    c.execute(
        "INSERT INTO Payments (bill_id, amount, payment_date, payment_mode) "
        "VALUES (?, ?, ?, ?)",
        (bill1, 800, _d(-2), "Bank Transfer"),
    )

    # Stock already issued when Bill #1's Print stage completed (its Print line item:
    # 50 sheets of item 1). stock_id 1 == item 1's stock row.
    c.execute(
        "INSERT INTO StockTransaction (stock_id, bill_id, quantity_changed, "
        "transaction_type, transaction_date) VALUES (?, ?, ?, ?, ?)",
        (1, bill1, -50, "Issue", _dt(-1, 15, 0)),
    )

    # ---------- Bill #2: single Print job, unpaid (shows payment warning on Print dept) ----------
    bill2 = c.execute(
        "INSERT INTO Bill (enquiry_id, customer_id, item_id, job_description, "
        "job_time, delivery_datetime, total_amount, payment_status, overall_status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (None, MEHTA, 2, "500 premium business cards — matte finish",
         _dt(0, 11, 0), _dt(1, 18, 0), 750, "Unpaid", "In Progress – Print"),
    ).lastrowid

    c.execute(
        "INSERT INTO JobStage (bill_id, job_type_id, stage_label, sequence_no, "
        "stage_status, assigned_to, assigned_by, start_time, end_time) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (bill2, PRINT, "Print", 1, "In Progress", 2, "AT", _dt(0, 11, 0), None),
    )

    # Bill #2's single Print line item: 5 boxes of Business Cards (item 2).
    c.execute(
        "INSERT INTO BillItem (bill_id, stage_label, job_type_id, item_id, quantity, color) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (bill2, "Print", PRINT, 2, 5, "Matte Black"),
    )

    conn.commit()
