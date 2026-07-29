PRAGMA foreign_keys = ON;
CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    national_id TEXT,
    risk_level TEXT,
    created_at TEXT
);

CREATE TABLE accounts (
    account_id INTEGER PRIMARY KEY,
    customer_id INTEGER,
    account_number TEXT,
    account_type TEXT,
    balance REAL,
    created_at TEXT,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);

CREATE TABLE transactions (
    transaction_id INTEGER PRIMARY KEY,
    account_id INTEGER,
    type TEXT,
    amount REAL,
    source TEXT,
    timestamp TEXT,
    FOREIGN KEY (account_id) REFERENCES accounts(account_id)
);

CREATE TABLE employees (
    employee_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT,
    related_customer_id INTEGER,
    FOREIGN KEY (related_customer_id) REFERENCES customers(customer_id)
);

CREATE TABLE wire_transfers (
    transfer_id INTEGER PRIMARY KEY,
    source_account_id INTEGER,
    destination_account_num TEXT,
    destination_country TEXT,
    amount REAL,
    status TEXT,
    flag_reason TEXT,
    initiated_by INTEGER,
    approved_by INTEGER,
    timestamp TEXT,
    FOREIGN KEY (source_account_id) REFERENCES accounts(account_id),
    FOREIGN KEY (initiated_by) REFERENCES employees(employee_id),
    FOREIGN KEY (approved_by) REFERENCES employees(employee_id)
);

CREATE TABLE sanctions_list (
    country_code TEXT PRIMARY KEY,
    reason TEXT,
    last_updated TEXT
);

CREATE TABLE compliance_reviews (
    review_id INTEGER PRIMARY KEY,
    transfer_id INTEGER,
    reviewer_id INTEGER,
    decision TEXT,
    notes TEXT,
    timestamp TEXT,
    FOREIGN KEY (transfer_id) REFERENCES wire_transfers(transfer_id),
    FOREIGN KEY (reviewer_id) REFERENCES employees(employee_id)
);





