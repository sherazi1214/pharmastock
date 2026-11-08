# Phase 3 implementation notes

Implemented: suppliers and supplier history, purchases with batch/expiry, atomic stock receiving, supplier payments allocated oldest-invoice-first, stock status controls, adjustment/damaged/return movements, movement history and printable purchase summaries.

Security/data boundaries: API queries filter on the authenticated `business_id`; purchase mutations use an explicit SQLite write transaction; stock cost/value is omitted when the user lacks `view_purchase_price`; batch status is owner-only.

Not included: sales/POS, customer credit, FEFO sales deduction, offline queue/cloud sync, and automated XLSX upload (as specified for later phases).
