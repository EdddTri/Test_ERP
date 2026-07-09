-- Print / Binding Job-Shop ERP — SQLite schema
-- All tables use IF NOT EXISTS so init is idempotent.

-- ---------- Lookups ----------
CREATE TABLE IF NOT EXISTS JobTypes (
    job_type_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type_name TEXT NOT NULL UNIQUE          -- Print / Binding / Other
);

CREATE TABLE IF NOT EXISTS Sources (
    source_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT NOT NULL UNIQUE            -- Email / WhatsApp / Phone Call / Walk-in
);

-- ---------- Master data ----------
CREATE TABLE IF NOT EXISTS Customers (
    customer_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_name  TEXT NOT NULL,                            -- party name
    contact_person TEXT,
    phone          TEXT,
    email          TEXT,
    address        TEXT
);

CREATE TABLE IF NOT EXISTS Items (
    item_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    item_name       TEXT NOT NULL,
    job_type_id     INTEGER REFERENCES JobTypes(job_type_id),
    unit_of_measure TEXT,
    rate            REAL                                     -- per-unit rate (nullable; a suggestion, not enforced)
);

CREATE TABLE IF NOT EXISTS Employees (
    employee_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_name TEXT NOT NULL,
    department    TEXT                            -- Print / Binding / Other
);

-- ---------- Stock ----------
CREATE TABLE IF NOT EXISTS Stock (
    stock_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id            INTEGER REFERENCES Items(item_id),
    quantity_available REAL NOT NULL DEFAULT 0,
    reorder_level      REAL NOT NULL DEFAULT 0,
    last_updated       TEXT
);

CREATE TABLE IF NOT EXISTS StockTransaction (
    transaction_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_id         INTEGER REFERENCES Stock(stock_id),
    bill_id          INTEGER REFERENCES Bill(bill_id),       -- nullable (manual receipts)
    quantity_changed REAL NOT NULL,                          -- negative for Issue, positive for Receipt
    transaction_type TEXT NOT NULL,                          -- Issue / Receipt
    transaction_date TEXT
);

-- ---------- Config ----------
CREATE TABLE IF NOT EXISTS AlertConfig (
    config_key   TEXT PRIMARY KEY,                           -- e.g. enquiry_pending_days_threshold
    config_value TEXT
);

-- ---------- Enquiry (free-text capture — the structured job breakdown happens at Create Job) ----------
-- Note: customer is stored as free text here, NOT a FK. Enquiries never touch the
-- customer master; the master row is created/updated only on the Customer Master page
-- or when the enquiry is turned into a job on Create Job.
CREATE TABLE IF NOT EXISTS Enquiry (
    enquiry_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    enquiry_date  TEXT,
    source_id     INTEGER REFERENCES Sources(source_id),
    customer_name TEXT,                                      -- free-text party name (no master link)
    status        TEXT DEFAULT 'Pending',                    -- Pending / Converted / Cancelled
    source_contact TEXT,                                     -- email / number captured for the source
    remarks       TEXT                                       -- what the customer asked about (free text)
);

-- ---------- Bill (job header) ----------
CREATE TABLE IF NOT EXISTS Bill (
    bill_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    enquiry_id        INTEGER REFERENCES Enquiry(enquiry_id), -- nullable
    customer_id       INTEGER REFERENCES Customers(customer_id),
    item_id           INTEGER REFERENCES Items(item_id),
    job_description   TEXT,
    job_time          TEXT,
    delivery_datetime TEXT,
    total_amount      REAL DEFAULT 0,                         -- order value (drives amount-due / payment status)
    payment_status    TEXT DEFAULT 'Unpaid',                  -- Unpaid / Partial / Paid
    overall_status    TEXT DEFAULT 'New'
);

-- ---------- JobStage (routing engine) ----------
CREATE TABLE IF NOT EXISTS JobStage (
    stage_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id      INTEGER REFERENCES Bill(bill_id),
    job_type_id  INTEGER REFERENCES JobTypes(job_type_id),
    stage_label  TEXT,                                        -- Print / Binding / Other / Binding-2
    sequence_no  INTEGER,
    stage_status TEXT DEFAULT 'Not Started',                  -- Not Started / In Progress / Completed
    assigned_to  INTEGER REFERENCES Employees(employee_id),   -- the worker doing the stage
    assigned_by  TEXT,                                        -- who assigned/routed the stage (auth user later)
    start_time   TEXT,
    end_time     TEXT
);

-- ---------- BillItem (line items — materials consumed per stage) ----------
CREATE TABLE IF NOT EXISTS BillItem (
    bill_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id      INTEGER REFERENCES Bill(bill_id),
    job_type_id  INTEGER REFERENCES JobTypes(job_type_id),
    stage_label  TEXT,                                        -- Print / Binding / Other / Binding-2
    item_id      INTEGER REFERENCES Items(item_id),
    quantity     REAL NOT NULL DEFAULT 1,
    color        TEXT
);

-- ---------- Payments ----------
CREATE TABLE IF NOT EXISTS Payments (
    payment_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id      INTEGER REFERENCES Bill(bill_id),
    amount       REAL NOT NULL,
    payment_date TEXT,
    payment_mode TEXT
);
