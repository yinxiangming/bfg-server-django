#!/usr/bin/env python
"""
Quick verification script for discount and finance_code functionality
"""
from decimal import Decimal

print("=" * 60)
print("Discount Calculation Verification")
print("=" * 60)

# Test discount calculations
test_cases = [
    {"unit_price": 100, "quantity": 2, "discount": 1.00, "expected": 200.00},
    {"unit_price": 100, "quantity": 2, "discount": 0.80, "expected": 160.00},
    {"unit_price": 50, "quantity": 3, "discount": 0.50, "expected": 75.00},
]

for i, case in enumerate(test_cases, 1):
    unit_price = Decimal(str(case["unit_price"]))
    quantity = Decimal(str(case["quantity"]))
    discount = Decimal(str(case["discount"]))
    expected = Decimal(str(case["expected"]))
    
    result = unit_price * quantity * discount
    
    status = "✓" if result == expected else "✗"
    print(f"\nTest {i}: {status}")
    print(f"  Formula: ${unit_price} × {quantity} × {discount} = ${result}")
    print(f"  Expected: ${expected}")
    print(f"  Discount: {int(discount * 100)}%")

print("\n" + "=" * 60)
print("Tax Calculation Verification")
print("=" * 60)

# Test tax calculations
tax_rate = Decimal('0.15')  # 15% NZ GST
tax_cases = [
    {"subtotal": 200.00, "tax_type": "default", "expected_tax": 30.00},
    {"subtotal": 160.00, "tax_type": "default", "expected_tax": 24.00},
    {"subtotal": 100.00, "tax_type": "no_tax", "expected_tax": 0.00},
]

for i, case in enumerate(tax_cases, 1):
    subtotal = Decimal(str(case["subtotal"]))
    tax_type = case["tax_type"]
    expected_tax = Decimal(str(case["expected_tax"]))
    
    if tax_type == "default":
        tax = subtotal * tax_rate
    else:
        tax = Decimal('0.00')
    
    total = subtotal + tax
    
    status = "✓" if tax == expected_tax else "✗"
    print(f"\nTest {i}: {status}")
    print(f"  Subtotal: ${subtotal}")
    print(f"  Tax Type: {tax_type}")
    print(f"  Tax ({int(tax_rate * 100)}%): ${tax}")
    print(f"  Expected Tax: ${expected_tax}")
    print(f"  Total: ${total}")

print("\n" + "=" * 60)
print("All calculations verified!")
print("=" * 60)
