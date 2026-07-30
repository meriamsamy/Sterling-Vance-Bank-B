INSERT INTO customers (customer_id, name, national_id, risk_level, created_at)
VALUES (1, 'Ahmed Ali', '29001234567', 'low', '2024-01-01');


INSERT INTO customers (customer_id, name, national_id, risk_level, created_at)
VALUES (2, 'Sara Mahmoud', '29505678901', 'low', '2024-01-05');

INSERT INTO customers (customer_id, name, national_id, risk_level, created_at)
VALUES (3, 'Mostafa Nour', '29609876543', 'high', '2024-01-10');

INSERT INTO accounts (account_id, customer_id, account_number, account_type, balance, created_at)
VALUES (1, 1, 'ACC123456', 'savings', 5000.00, '2024-01-02');

INSERT INTO accounts (account_id, customer_id, account_number, account_type, balance, created_at)
VALUES (2, 2, 'ACC123457', 'checking', 10000.00, '2024-01-06');

INSERT INTO accounts (account_id, customer_id, account_number, account_type, balance, created_at)
VALUES (3, 3, 'ACC123458', 'savings', 15000.00, '2024-01-11');

INSERT INTO transactions (transaction_id, account_id, type, amount, source, timestamp)
VALUES (1, 3, 'deposit', 4800.00, 'cash', '2024-02-01');

INSERT INTO transactions (transaction_id, account_id, type, amount, source, timestamp)
VALUES (2, 3, 'deposit', 4900.00, 'cash', '2024-02-02');

INSERT INTO transactions (transaction_id, account_id, type, amount, source, timestamp)
VALUES (3, 3, 'deposit', 4700.00, 'cash', '2024-02-03');

INSERT INTO transactions (transaction_id, account_id, type, amount, source, timestamp)
VALUES (4, 1, 'deposit', 2000.00, 'salary', '2024-02-10');

INSERT INTO transactions (transaction_id, account_id, type, amount, source, timestamp)
VALUES (5, 1, 'withdrawal', 500.00, 'atm', '2024-02-15');

INSERT INTO transactions (transaction_id, account_id, type, amount, source, timestamp)
VALUES (6, 2, 'deposit', 3000.00, 'salary', '2024-02-09');

INSERT INTO employees (employee_id, name, role, related_customer_id)
VALUES (1, 'John Smith', 'compliance_officer', NULL);

INSERT INTO employees (employee_id, name, role, related_customer_id)
VALUES (2, 'Jane Doe', 'fraud_investigator', NULL);

INSERT INTO employees (employee_id, name, role, related_customer_id)
VALUES (3, 'Emily Johnson', 'teller', 2);

INSERT INTO employees (employee_id, name, role, related_customer_id)
VALUES (4, 'Omar Hassan', 'teller', NULL);

INSERT INTO sanctions_list (country_code, reason, last_updated)
VALUES ('IR', 'UN sanctions', '2024-01-01');

INSERT INTO sanctions_list (country_code, reason, last_updated)
VALUES ('KP', 'UN sanctions', '2024-01-01');

INSERT INTO sanctions_list (country_code, reason, last_updated)
VALUES ('SY', 'US sanctions', '2024-01-01');

INSERT INTO wire_transfers (transfer_id, source_account_id, destination_account_num, destination_country, amount, status, flag_reason, initiated_by, approved_by, timestamp)
VALUES (1, 2, 'FR-9988776655', 'FR', 3000.00, 'approved', NULL, 4, NULL, '2024-03-01');

INSERT INTO wire_transfers (transfer_id, source_account_id, destination_account_num, destination_country, amount, status, flag_reason, initiated_by, approved_by, timestamp)
VALUES (2, 1, 'IR-1122334455', 'IR', 7000.00, 'flagged', 'sanctions', 4, NULL, '2024-03-02');

INSERT INTO wire_transfers (transfer_id, source_account_id, destination_account_num, destination_country, amount, status, flag_reason, initiated_by, approved_by, timestamp)
VALUES (3, 3, 'US-5544332211', 'US', 14000.00, 'flagged', 'structuring', 4, NULL, '2024-03-05');

INSERT INTO wire_transfers (transfer_id, source_account_id, destination_account_num, destination_country, amount, status, flag_reason, initiated_by, approved_by, timestamp)
VALUES (4, 1, 'EG-1231231234', 'EG', 6000.00, 'flagged', 'self_dealing', 3, NULL, '2024-03-10');

INSERT INTO compliance_reviews (review_id, transfer_id, reviewer_id, decision, notes, timestamp)
VALUES (1, 2, 1, 'denied', 'Destination country is under UN sanctions', '2024-03-03');

INSERT INTO compliance_reviews (review_id, transfer_id, reviewer_id, decision, notes, timestamp)
VALUES (2, 3, 1, 'denied', 'Transaction flagged for structuring', '2024-03-06');

INSERT INTO compliance_reviews (review_id, transfer_id, reviewer_id, decision, notes, timestamp)
VALUES (3, 4, 2, 'denied', 'Transaction flagged for self_dealing', '2024-03-11');
INSERT INTO transactions (transaction_id, account_id, type, amount, source, timestamp)
VALUES
(10, 1, 'incoming', 9000, 'external_customer_A', '2024-02-01'),
(11, 1, 'incoming', 8500, 'external_customer_B', '2024-02-02'),
(12, 1, 'incoming', 7000, 'external_customer_C', '2024-02-03'),
(13, 1, 'outgoing', 23000, 'international_wire', '2024-02-04');
