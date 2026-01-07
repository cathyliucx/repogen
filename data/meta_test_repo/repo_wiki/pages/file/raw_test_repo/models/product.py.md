# File: raw_test_repo/models/product.py

The product.py module defines the core product entity (Item) and supporting functions for managing vendable items in an automated retail system. It ensures inventory integrity and product validity by enforcing stock availability and expiry checks before sales, and safely managing quantity reductions during transactions.

## Workflows
- Validate product eligibility for sale using check() function
- Safely reduce inventory quantity using mod() function during sales
- Track and manage product lifecycle via Item class attributes (name, price, quantity, expiry, category)

## Functions / Methods
### def check(...)

Ensures a product is eligible for sale by confirming it has available quantity and has not expired, preventing unsellable items from being offered to customers.

**Business Rules**
- A product is sellable only if its inventory count is greater than zero.
- A product is unsellable if the current date exceeds its expiry date.

**Key Terms**
- Product
- Inventory Slot
- Product Expiry Date
- Decimal Amount

### def mod(...)

Ensures safe reduction of product inventory quantity in a vending machine, preventing negative stock levels during sales transactions.

**Business Rules**
- Inventory quantity can only be decremented if current quantity is greater than or equal to the requested decrement value.
- A decrement operation returns true if successful, false if insufficient inventory exists.
- The decrement value must be a positive integer (minimum 1).
- Inventory quantity must never drop below zero after any decrement operation.

**Key Terms**
- Product
- Inventory Slot
- count
- Slot Number

### class Item

An Item represents a vendable product in an automated retail system, uniquely identified and tracked by attributes including its name, price, quantity, expiry date, and category. It enables inventory management, validity checks, and lifecycle control within vending machine operations.

**Business Rules**
- A Product must have a unique code (Slot Number) that identifies its inventory location.
- A Product's quantity (count) must be a non-negative integer and cannot be less than zero.
- A Product is unsellable if its expiry date (Product Expiry Date) has passed.
- A Product's value (price) must be represented as a Decimal Amount to ensure precise financial calculations.
- A Product must be assigned to a Product Category for reporting and inventory organization.

**Key Terms**
- code → Product ID
- label → Product Name
- val → Price
- count → Quantity
- exp → Product Expiry Date
- grp → Product Category
