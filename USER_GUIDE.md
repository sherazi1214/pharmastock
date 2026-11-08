# PharmaStock - User Guide (simple steps)

Big blue menu on the left. Nine buttons: Dashboard, Products, Purchase, Sales, Stock, Suppliers, Customers, Reports, Settings.
You only see what your role allows. If a message is red, read it - it says what to fix. Nothing is saved when a red message appears.

## A. Receive medicine from a supplier (Purchase)
1. Suppliers -> add the supplier once (name, phone).
2. Purchase -> choose the supplier, type the supplier's invoice number, today's date.
3. Scan the medicine box, or type its name and pick it.
4. Choose the unit (Box / Strip / Tablet), quantity and the price you paid.
5. Type the **batch number** and **expiry date** printed on the box. Expired dates are refused.
6. Type how much you paid now. The rest becomes "we owe the supplier".
7. Press Save. Stock goes up. Print the purchase summary if you want.

## B. Sell medicine (Sales)
1. Sales -> press **Retail Sale** or **Wholesale Sale** (wholesale needs a customer).
2. Scan the medicine or type its name. Choose the unit and quantity (2 strips + 5 tablets = add two lines).
3. The price appears by itself. Discount only if you are allowed.
4. Choose how the customer pays. If they pay less than the total, the rest is credit (only for customers allowed credit, within their limit).
5. Press Save, then Print (A4 invoice or small receipt).
If the screen says "Not enough stock", the medicine is finished, expired, recalled or blocked. Expired and recalled medicine can never be sold.
Wrong sale? Sales -> Past sales and returns -> Return, choose "Put back in stock" or "Write off", and type the reason.

## C. Find a medicine or add a new one (Products)
1. Products -> type a name, or scan the box.
2. Unknown barcode: the screen says so and saves nothing. Press add product, or attach the barcode to an existing product.
3. Prices: retail price must not be above MRP. Prices are for the biggest pack (one Box).
4. Many products at once: Products -> Import, download the template, fill it, upload, read the preview, then confirm.

## D. Customer pays what they owe (Customers)
1. Customers -> **Account & payments** next to the customer.
2. You see what they owe and the unpaid invoices.
3. Type the amount received, choose cash/bank, press Save payment. The oldest invoice is paid first.

## E. End of day
1. Dashboard: today's sales, purchases, low stock, near-expiry.
2. Reports: choose a report, press Show, then Print or Save as Excel.
3. Settings -> Backup and sync -> **Make backup now**. Wait until it says "Backed up and verified". If it says FAILED, call your admin.
4. Copy the backup file to a USB drive once a week.

## Small badge "Local only / Pending / Error"
- Local only: everything is saved on this computer (normal).
- Pending: the server was not reachable; items are saved and will be sent automatically. Do not enter them again.
- Error: the server refused something. Open Settings -> Backup and sync to see why.
