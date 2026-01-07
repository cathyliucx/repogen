# File: raw_test_repo/vending_machine.py

The vending_machine.py file implements an automated retail system that manages product inventory, processes secure payments, and handles transaction workflows including purchase, cancellation, and fund addition. It ensures financial precision and enforces product expiry rules to maintain integrity in self-service retail operations.

## Workflows
- Customer adds money to ongoing transaction via add_money()
- System lists available non-expired products via ls()
- Customer selects product via pick() or buy(), validating availability and expiry, processing payment, and updating inventory
- Transaction is canceled via cancel(), reverting inventory and payment states
- System initializes with inventory and payment controls via __init__()
- System errors are captured and handled via SysErr class to maintain robust operation

## Functions / Methods
### def add_money(...)

Allows a customer to add funds to an ongoing purchase via cash, updating the payment transaction state to reflect the new amount while ensuring financial precision.

**Business Rules**
- Cash can only be added to a payment transaction in 'pending' state.
- The total payment amount must be represented as a Decimal Amount to avoid rounding errors.
- Adding money cannot exceed the product price plus allowable change limit.
- Each cash addition must be recorded as part of the same Payment Transaction.

**Key Terms**
- CashPayment
- Payment Transaction
- PaymentStatus
- Decimal Amount
- Vending Machine

### def ls(...)

The method retrieves a list of all products currently available in the vending machine, organized by their inventory slots, ensuring only non-expired items are included for sale.

**Business Rules**
- Only products with an expiry date on or after today's date may be listed as available.
- Each listed product must be associated with a valid slot number.
- Product details must include name, price, quantity, category, and expiry date.
- The list must not include products with zero quantity.

**Key Terms**
- Product
- Inventory Slot
- Slot Number
- Product Expiry Date
- Product Category
- Decimal Amount
- Quantity

### def pick(...)

The pick method selects a product from a specified inventory slot, validates its availability and expiry, processes payment, and updates inventory upon successful transaction.

**Business Rules**
- A product can only be picked if its inventory slot has quantity greater than zero.
- A product cannot be picked if its expiry date is before the current date.
- Payment must be completed before the product is dispensed.
- The slot number must correspond to a valid inventory slot in the vending machine.
- Inventory quantity must be decremented by one after a successful payment transaction.

**Key Terms**
- Product
- Inventory Slot
- Slot Number
- Product Expiry Date
- Payment Transaction
- PaymentStatus
- Vending Machine

### def cancel(...)

Cancels an ongoing payment transaction in the vending machine, reverting inventory and payment states to their pre-transaction conditions to ensure financial and inventory integrity.

**Business Rules**
- A payment transaction can only be cancelled if its status is 'pending'.
- Cancelling a payment must restore the product quantity in its inventory slot to the pre-purchase state.
- Cancelling a payment must update the payment transaction status to 'failed'.
- No monetary value may be transferred to the merchant when a payment is cancelled.
- Product expiry dates must still be enforced after cancellation; expired products cannot be reinstated for sale.

**Key Terms**
- Payment Transaction
- PaymentStatus
- Inventory Slot
- Product
- Product Expiry Date

### def __init__(...)

Initializes a vending machine system to manage product inventory, process payments, and coordinate sales transactions while enforcing product expiry and precise financial calculations.

**Business Rules**
- A vending machine must assign each product to a unique slot number for retrieval.
- A product cannot be sold if its expiry date has passed.
- Payment transactions must be tracked with one of three valid states: pending, completed, or failed.
- All monetary amounts must be handled as decimal values to avoid rounding errors.
- Inventory slots must be updated only after a payment transaction is marked as completed.

**Key Terms**
- Product
- Inventory Slot
- Payment Transaction
- PaymentStatus
- Vending Machine
- Product Expiry Date
- Decimal Amount
- Product Category
- Slot Number

### class Sys

The Vending Machine system automates product selection, payment processing, and inventory management to enable self-service retail transactions while enforcing product expiry rules and precise financial handling.

**Business Rules**
- A product cannot be sold if its expiry date has passed.
- A payment transaction must be in 'completed' state before dispensing a product.
- Inventory slots must be uniquely identified by a slot number to ensure correct product retrieval.
- All monetary amounts must be processed as decimal values to avoid rounding errors.
- Products must be categorized to support reporting and inventory filtering.

**Key Terms**
- Product
- Inventory Slot
- Payment Transaction
- PaymentStatus
- CashPayment
- Vending Machine
- Product Expiry Date
- Decimal Amount
- Product Category
- Slot Number

### class SysErr

System error handling module for Automated Retail Systems, ensuring robust operation of vending machines during product selection, payment, and inventory updates.

**Business Rules**
- A system error must be logged when a product selection references an invalid slot number.
- A system error must be raised if a payment transaction state is not one of: pending, completed, or failed.
- A system error must occur if an attempt is made to vend a product past its expiry date.
- A system error must be triggered when inventory slot quantity is insufficient for a requested purchase.
- A system error must be thrown if a cash payment amount is not a valid decimal amount.

**Key Terms**
- SysErr
- Slot Number
- PaymentStatus
- Product Expiry Date
- Inventory Slot
- Decimal Amount
- CashPayment

### def buy(...)

A customer selects a product via its slot number, initiates a payment, and if successful, the vending machine dispenses the product and updates inventory, ensuring the product is not expired and payment is completed.

**Business Rules**
- A product can only be dispensed if its expiry date is on or after the current date.
- A payment transaction must reach 'completed' status before a product is dispensed.
- The inventory slot must contain at least one unit of the selected product to fulfill the purchase.
- The payment amount must exactly match the product's listed price.
- After a successful purchase, the product quantity in the assigned slot is decremented by one.

**Key Terms**
- Product
- Inventory Slot
- Payment Transaction
- PaymentStatus
- Vending Machine
- Product Expiry Date
- Slot Number
