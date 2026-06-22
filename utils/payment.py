from typing import Dict, Any
import datetime
import random


def process_payment(payment_data: Dict[str, Any]) -> Dict[str, Any]:
    """Simulate a modern payment gateway integration.

    Replace this stub with a real gateway call to Razorpay, Stripe, PayPal, or another provider.
    """
    gateway = payment_data.get('payment_method', 'card')
    transaction_id = f"{gateway.upper()}-{random.randint(10000000, 99999999)}"
    status = 'success'
    message = 'Payment completed securely using SmartCart Checkout.'

    if gateway == 'upi':
        message = 'UPI payment accepted. Your transaction is complete.'
    elif gateway == 'netbanking':
        message = 'Net banking authentication completed successfully.'
    elif gateway == 'card':
        message = 'Card payment approved by the secure gateway.'

    return {
        'status': status,
        'amount': payment_data.get('amount', 0),
        'currency': payment_data.get('currency', 'INR'),
        'transaction_id': transaction_id,
        'message': message,
        'processed_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
