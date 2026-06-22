import sys
import os

# Add workspace root to python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, generate_pdf
from flask import render_template

# Create dummy order and items data
mock_order = {
    'order_id': 999,
    'user_id': 42,
    'username': 'Jane Doe Test',
    'address': '123 Main St, Apartment 4B, Landmark: Near Metro, Metropolis, NY, USA - 10001 | Phone: +1-555-0199',
    'razorpay_payment_id': 'pay_mock123456',
    'payment_status': 'paid',
    'amount': 1598.00,
    'created_at': '2026-06-20 10:00:00'
}

mock_items = [
    {
        'product_name': 'Premium Leather Wallet',
        'quantity': 1,
        'price': 799.00
    },
    {
        'product_name': 'Designer Sunglasses',
        'quantity': 1,
        'price': 799.00
    }
]

with app.test_request_context():
    try:
        # Render the HTML template
        html = render_template('user/invoice.html', order=mock_order, items=mock_items)
        print("HTML rendered successfully!")
        
        # Generate the PDF
        pdf_buffer = generate_pdf(html)
        if pdf_buffer:
            output_path = os.path.join(os.path.dirname(__file__), 'test_invoice.pdf')
            with open(output_path, 'wb') as f:
                f.write(pdf_buffer.getvalue())
            print(f"PDF generated successfully and saved to: {output_path}")
        else:
            print("PDF generation returned None!")
    except Exception as e:
        print("Error during PDF generation:", e)
        import traceback
        traceback.print_exc()
