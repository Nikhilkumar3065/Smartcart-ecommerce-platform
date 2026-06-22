from flask import Flask, make_response, render_template, request, redirect, send_file, session, flash, url_for
from flask_mail import Mail, Message
import pymysql
import bcrypt
import random
import datetime
import os
import razorpay
import traceback

import reportlab.pdfgen # type: ignore
from io import BytesIO

from werkzeug.utils import secure_filename
from utils.email_otp import (
    generate_numeric_otp,
    send_contact_email,
    send_otp_email,
    generate_password_reset_token,
    verify_password_reset_token,
    send_password_reset_link,
)
from utils.payment import process_payment
import config 

#==========
#razor pay 
#==========
razorpay_client = razorpay.Client(auth=(config.RAZORPAY_KEY_ID, config.RAZORPAY_KEY_SECRET))

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads', 'item_images')
ADMIN_UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads', 'admin_profiles')
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
OTP_EXPIRY_MINUTES = 10

#============
# mail config
#==============
app = Flask(__name__)
app.secret_key = config.SECRET_KEY

app.config['MAIL_SERVER'] = config.MAIL_SERVER
app.config['MAIL_PORT'] = config.MAIL_PORT
app.config['MAIL_USE_TLS'] = config.MAIL_USE_TLS
app.config['MAIL_USE_SSL'] = config.MAIL_USE_SSL
app.config['MAIL_DEBUG'] = app.debug
app.config['MAIL_USERNAME'] = config.MAIL_USERNAME.strip()
app.config['MAIL_PASSWORD'] = config.MAIL_PASSWORD.replace(' ', '').strip()
app.config['MAIL_DEFAULT_SENDER'] = config.MAIL_DEFAULT_SENDER
app.config['MAIL_SUPPRESS_SEND'] = False
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['ADMIN_UPLOAD_FOLDER'] = ADMIN_UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 4 * 1024 * 1024  # 4 MB

mail = Mail(app)

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(ADMIN_UPLOAD_FOLDER, exist_ok=True)


def current_year():
    return datetime.datetime.now().year


@app.context_processor
def inject_common_data():
    cart = session.get('cart', {})
    return {
        'current_year': current_year(),
        'cart_count': sum(cart.values()) if cart else 0,
        'user_name': session.get('user_name'),
        'admin_name': session.get('admin_name'),
    }


def get_cart():
    return session.get('cart', {})


def save_cart(cart):
    session['cart'] = cart


def get_cart_items_and_total():
    cart = get_cart()
    items = []
    total = 0
    if not cart:
        return items, total

    product_ids = [int(pid) for pid in cart.keys()]
    placeholders = ','.join(['%s'] * len(product_ids))
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            f'SELECT product_id AS item_id, name, price, image FROM products WHERE product_id IN ({placeholders})',
            tuple(product_ids),
        )
        products = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    for product in products:
        quantity = int(cart.get(str(product['item_id']), 0))
        price = float(product['price'])
        line_total = price * quantity
        total += line_total
        items.append({
            'item_id': product['item_id'],
            'name': product['name'],
            'price': price,
            'image': product['image'],
            'quantity': quantity,
            'line_total': line_total,
        })

    return items, total


def normalize_order(order):
    if not order:
        return order

    try:
        order['total'] = float(order.get('total', 0))
    except (TypeError, ValueError):
        order['total'] = 0.0

    for item in order.get('items', []):
        try:
            item['price'] = float(item.get('price', 0))
        except (TypeError, ValueError):
            item['price'] = 0.0

        try:
            item['quantity'] = int(item.get('quantity', 0))
        except (TypeError, ValueError):
            item['quantity'] = 0

        try:
            item['line_total'] = float(item.get('line_total', 0))
        except (TypeError, ValueError):
            item['line_total'] = 0.0

    return order

#=========
# sql connection
#=============
def get_db_connection():
    return pymysql.connect(
        host=config.DB_HOST,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME,
        cursorclass=pymysql.cursors.DictCursor
    )


def verify_password(password, hashed_password):
    if not password or not hashed_password:
        return False

    if isinstance(hashed_password, str):
        hashed_password = hashed_password.strip().encode('utf-8')

    try:
        return bcrypt.checkpw(password.encode('utf-8'), hashed_password)
    except ValueError:
        app.logger.warning('Invalid bcrypt hash provided during login verification.')
        return False


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def has_column(table, column):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SHOW COLUMNS FROM %s LIKE %s' % (table, '%s'), (column,))
        return cursor.fetchone() is not None
    finally:
        cursor.close()
        conn.close()

from utils.pdf_generator import generate_pdf

# ============================================================================
# Home page
# ============================================================================
@app.route('/')
def index():
    return render_template('user/home.html')


# ============================================================================
# About page
# ============================================================================
@app.route('/about')
def about():
    return render_template('user/about.html')


# ============================================================================
#  user Contact page
# ============================================================================
@app.route('/contact', methods=['GET', 'POST'])
def contact():

    if request.method == 'GET':
        return render_template('user/contact.html')

    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()
    message = request.form.get('message', '').strip()

    if not name or not email or not message:
        flash('All fields are required.', 'warning')
        return redirect(url_for('contact'))

    try:
        send_contact_email(
            mail,
            sender=config.MAIL_DEFAULT_SENDER,
            recipient=config.MAIL_DEFAULT_SENDER,
            name=name,
            email=email,
            message=message
        )

        flash('Message sent successfully!', 'success')

    except Exception as e:
        print("EMAIL ERROR:", e)
        flash('Message received but email failed.', 'warning')

    return redirect(url_for('contact'))
#============
# admin contact page 
#===========================
@app.route('/admin/contact', methods=['GET', 'POST'])
def admin_contact():

    if 'admin_id' not in session:
        flash('Please login first.', 'danger')
        return redirect(url_for('admin_login'))

    if request.method == 'GET':
        return render_template('Admin/contact.html')

    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()
    message = request.form.get('message', '').strip()

    if not name or not email or not message:
        flash('All fields are required.', 'warning')
        return redirect(url_for('admin_contact'))

    try:
        send_contact_email(
            mail,
            sender=config.MAIL_DEFAULT_SENDER,
            recipient=config.MAIL_DEFAULT_SENDER,
            name=name,
            email=email,
            message=message
        )

        flash('Message sent successfully!', 'success')

    except Exception as e:
        print("EMAIL ERROR:", e)
        flash('Message failed to send.', 'danger')

    return redirect(url_for('admin_contact'))
# ============================================================================
#  user Password reset request
# ============================================================================
@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():

    # GET request → show page
    if request.method == 'GET':
        return render_template('user/forgot_password.html')

    # POST request → handle email
    email = request.form.get('email', '').strip()

    if not email:
        flash('Please enter your email.', 'warning')
        return redirect(url_for('forgot_password'))

    conn = None
    cursor = None
    account_type = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # check USER table first
        cursor.execute('SELECT user_id FROM users WHERE email=%s', (email,))
        user = cursor.fetchone()

        if user:
            account_type = 'user'
        else:
            # check ADMIN table (optional fallback)
            cursor.execute('SELECT admin_id FROM admin WHERE email=%s', (email,))
            admin = cursor.fetchone()

            if admin:
                account_type = 'admin'

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    # If email exists in system
    if account_type:

        token = generate_password_reset_token(config.SECRET_KEY, email)
        reset_url = url_for('reset_password', token=token, _external=True)

        try:
            send_password_reset_link(
                mail,
                sender=config.MAIL_DEFAULT_SENDER,
                recipient=email,
                reset_url=reset_url,
            )

            flash('If that email is registered, a password reset link has been sent.', 'success')

        except Exception:
            app.logger.exception('Password reset email failed')
            flash('Unable to send reset email. Please try again later.', 'danger')
            return redirect(url_for('forgot_password'))

    else:
        # security: same message always (prevents email enumeration)
        flash('If that email is registered, a password reset link has been sent.', 'info')

    return redirect(url_for('forgot_password'))

# ============================================================================
# Password reset form
# ============================================================================
@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    email = verify_password_reset_token(config.SECRET_KEY, token)
    if not email:
        flash('The reset link is invalid or has expired. Please request a new one.', 'danger')
        return redirect(url_for('forgot_password'))

    if request.method == 'GET':
        conn = None
        cursor = None
        is_admin = False
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT admin_id FROM admin WHERE email=%s', (email,))
            is_admin = cursor.fetchone() is not None
        except Exception as e:
            print("RESET PASSWORD DB CHECK ERROR:", e)
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

        if is_admin:
            return render_template('Admin/reset_password.html', token=token)
        else:
            return render_template('user/reset_password.html', token=token)

    password = request.form.get('password', '')
    confirm = request.form.get('confirm_password', '')
    if not password or not confirm:
        flash('Please fill out all fields.', 'warning')
        return redirect(url_for('reset_password', token=token))
    if password != confirm:
        flash('Passwords do not match.', 'danger')
        return redirect(url_for('reset_password', token=token))

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        cursor.execute('SELECT user_id FROM users WHERE email=%s', (email,))
        user = cursor.fetchone()
        if user:
            cursor.execute('UPDATE users SET password=%s WHERE email=%s', (hashed_password, email))
            next_route = 'login'
        else:
            cursor.execute('SELECT admin_id FROM admin WHERE email=%s', (email,))
            admin = cursor.fetchone()
            if admin:
                cursor.execute('UPDATE admin SET password=%s WHERE email=%s', (hashed_password, email))
                next_route = 'admin_login'
            else:
                flash('No account found for this reset link.', 'danger')
                return redirect(url_for('forgot_password'))
        conn.commit()
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()

    flash('Password has been reset. You can now login.', 'success')
    return redirect(url_for(next_route))


# ============================================================================
# User login
# ============================================================================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('user/login.html')

    email = request.form.get('email', '').strip()
    password = request.form.get('password', '').strip()

    if not email or not password:
        flash('Email and password are required.', 'danger')
        return redirect(url_for('login'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE email=%s', (email,))
        user = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

    if not user:
        flash('No account found with this email.', 'danger')
        return redirect(url_for('login'))

    if verify_password(password, user['password']):
        session['user_id'] = user['user_id']
        session['user_name'] = user['name']
        flash('Welcome back! You are now logged in.', 'success')
        return redirect(url_for('shop'))

    flash('Invalid password.', 'danger')
    return redirect(url_for('login'))


# ============================================================================
# User registration
# ============================================================================
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'GET':
        return render_template('user/register.html')

    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '').strip()

    if not name or not email or not password:
        flash('Name, email, and password are required.', 'danger')
        return redirect(url_for('register'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM users WHERE email=%s', (email,))
        if cursor.fetchone():
            flash('This email is already registered. Please login instead.', 'warning')
            return redirect(url_for('login'))

        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        cursor.execute(
            'INSERT INTO users (name, email, password) VALUES (%s, %s, %s)',
            (name, email, hashed_password),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    flash('Your account has been created. Please login.', 'success')
    return redirect(url_for('login'))

# ============================================================================
# User logout
# ============================================================================
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('user_name', None)
    session.pop('cart', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

# ============================================================================
# Product shop / listing
# ============================================================================
@app.route('/shop')
def shop():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get search and filter parameters
        search_query = request.args.get('search', '').strip()
        category_filter = request.args.get('category', '').strip()
        
        # Build query dynamically
        query = 'SELECT product_id AS item_id, name, category, price, image FROM products WHERE 1=1'
        params = []
        
        if search_query:
            query += ' AND name LIKE %s'
            params.append(f'%{search_query}%')
        
        if category_filter:
            query += ' AND category = %s'
            params.append(category_filter)
        
        query += ' ORDER BY product_id DESC'
        
        cursor.execute(query, params)
        items = cursor.fetchall()
        
        # Get distinct categories for filter dropdown
        cursor.execute('SELECT DISTINCT category FROM products ORDER BY category')
        categories = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return render_template('user/user_home.html', items=items, categories=categories, search_query=search_query, category_filter=category_filter)


# ============================================================================
# Product detail
# ============================================================================
@app.route('/product/<int:product_id>')
def product_detail(product_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT product_id AS item_id, name, description, category, price, image FROM products WHERE product_id=%s',
            (product_id,),
        )
        product = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

    if not product:
        flash('Product not found.', 'warning')
        return redirect(url_for('shop'))

    return render_template('user/product_details.html', product=product)


# ============================================================================
# Add item to cart
# ============================================================================
@app.route('/add-to-cart/<int:product_id>')
def add_to_cart(product_id):
    if 'user_id' not in session:
        flash('Please login to add items to your cart.', 'warning')
        return redirect(url_for('login'))

    cart = get_cart()
    cart[str(product_id)] = cart.get(str(product_id), 0) + 1
    save_cart(cart)
    flash('Item added to cart.', 'success')
    return redirect(request.referrer or url_for('shop'))

# ============================================================================
# Buy now
# ============================================================================
@app.route('/buy-now/<int:product_id>')
def buy_now(product_id):
    if 'user_id' not in session:
        flash('Please login to checkout.', 'warning')
        return redirect(url_for('login'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT product_id FROM products WHERE product_id=%s', (product_id,))
        product = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

    if not product:
        flash('Product not found.', 'warning')
        return redirect(url_for('shop'))

    cart = get_cart()
    cart[str(product_id)] = cart.get(str(product_id), 0) + 1
    save_cart(cart)
    flash('Item added to cart.', 'success')
    return redirect(url_for('cart'))


# ============================================================================
# Remove item from cart
# ============================================================================
@app.route('/remove-from-cart/<int:product_id>')
def remove_from_cart(product_id):
    cart = get_cart()
    key = str(product_id)

    if key in cart:
        cart.pop(key)   # Remove entire product from cart
        save_cart(cart)
        flash('Product removed from cart.', 'success')

    return redirect(url_for('cart'))

#======================
# user cart view
#====================
@app.route('/cart')
def cart():
    cart = get_cart()
    items = []
    total = 0
    if cart:
        product_ids = [int(pid) for pid in cart.keys()]
        placeholders = ','.join(['%s'] * len(product_ids))
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                f'SELECT product_id AS item_id, name, price, image FROM products WHERE product_id IN ({placeholders})',
                tuple(product_ids),
            )
            products = cursor.fetchall()
        finally:
            cursor.close()
            conn.close()

        for product in products:
            quantity = cart.get(str(product['item_id']), 0)
            line_total = product['price'] * quantity
            total += line_total
            items.append({
                'item_id': product['item_id'],
                'name': product['name'],
                'price': product['price'],
                'image': product['image'],
                'quantity': quantity,
                'line_total': line_total,
            })

    return render_template('user/cart.html', items=items, total=total)

#===================
# increase cart quantity
#====================
@app.route('/cart/increase/<int:product_id>')
def increase_cart_quantity(product_id):

    if 'user_id' not in session:
        flash('Please login first.', 'warning')
        return redirect(url_for('login'))

    cart = get_cart()

    key = str(product_id)
    cart[key] = cart.get(key, 0) + 1

    save_cart(cart)

    return redirect(url_for('cart'))
#===================
# decrease cart quantity
#====================
@app.route('/cart/decrease/<int:product_id>')
def decrease_cart_quantity(product_id):

    if 'user_id' not in session:
        flash('Please login first.', 'warning')
        return redirect(url_for('login'))

    cart = get_cart()

    key = str(product_id)

    if key in cart:
        cart[key] -= 1

        if cart[key] <= 0:
            del cart[key]

        save_cart(cart)

    return redirect(url_for('cart'))


# ============================================================================
# Checkout start
# ============================================================================
@app.route('/checkout', methods=['POST'])
def checkout():
    if 'user_id' not in session:
        flash('Please login to checkout.', 'warning')
        return redirect(url_for('login'))

    cart = get_cart()
    if not cart:
        flash('Your cart is empty.', 'warning')
        return redirect(url_for('cart'))

    return redirect(url_for('address'))


# ============================================================================
# Shipping address collection
# ============================================================================
@app.route('/address', methods=['GET', 'POST'])
def address():
    if 'user_id' not in session:
        flash('Please login to continue checkout.', 'warning')
        return redirect(url_for('login'))

    cart_items, total = get_cart_items_and_total()
    if not cart_items:
        flash('Your cart is empty.', 'warning')
        return redirect(url_for('cart'))

    saved_address = session.get('checkout_address', {})
    if request.method == 'POST':
        address = {
            'full_name': request.form.get('full_name', '').strip(),
            'email': request.form.get('email', '').strip(),
            'phone': request.form.get('phone', '').strip(),
            'country': request.form.get('country', '').strip(),
            'state': request.form.get('state', '').strip(),
            'city': request.form.get('city', '').strip(),
            'postal_code': request.form.get('postal_code', '').strip(),
            'address_line1': request.form.get('address_line1', '').strip(),
            'address_line2': request.form.get('address_line2', '').strip(),
            'landmark': request.form.get('landmark', '').strip(),
        }

        if not all([address['full_name'], address['email'], address['phone'], address['country'], address['state'], address['city'], address['postal_code'], address['address_line1']]):
            flash('Please complete all required shipping fields.', 'warning')
            return render_template('user/address.html', cart_items=cart_items, total=total, address=address)

        session['checkout_address'] = address
        return redirect(url_for('user_pay'))

    return render_template('user/address.html', cart_items=cart_items, total=total, address=saved_address)

# =================================================================
# ROUTE: CREATE RAZORPAY ORDER
# =================================================================
@app.route('/user/pay')
def user_pay():

    if 'user_id' not in session:
        flash("Please login first!", "danger")
        return redirect(url_for('login'))

    cart = get_cart()

    if not cart:
        flash("Your cart is empty!", "warning")
        return redirect(url_for('cart'))

    total_amount = 0

    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        product_ids = [int(pid) for pid in cart.keys()]

        placeholders = ','.join(['%s'] * len(product_ids))

        cursor.execute(
            f"""
            SELECT product_id, price
            FROM products
            WHERE product_id IN ({placeholders})
            """,
            tuple(product_ids)
        )

        products = cursor.fetchall()

        for product in products:

            quantity = cart.get(str(product['product_id']), 0)

            total_amount += float(product['price']) * quantity

    finally:
        if cursor:
            cursor.close()

        if conn:
            conn.close()

    razorpay_amount = int(total_amount * 100)  # convert to paise

    try:

        razorpay_order = razorpay_client.order.create({
            "amount": razorpay_amount,
            "currency": "INR",
            "payment_capture": "1"
        })

        session['razorpay_order_id'] = razorpay_order['id']

        return render_template(
            'user/payment.html',
            amount=total_amount,
            key_id=config.RAZORPAY_KEY_ID,
            order_id=razorpay_order['id']
        )

    except Exception as e:

        app.logger.exception("Razorpay Order Creation Failed")

        flash(
            "Unable to initialize payment. Please try again.",
            "danger"
        )

        return redirect(url_for('cart'))


# ------------------------------
# Route: Verify Payment and Store Order
# ------------------------------
@app.route('/verify-payment', methods=['POST'])
def verify_payment():

    if 'user_id' not in session:
        flash("Please login to complete the payment.", "danger")
        return redirect(url_for('login'))

    razorpay_payment_id = request.form.get('razorpay_payment_id')
    razorpay_order_id = request.form.get('razorpay_order_id')
    razorpay_signature = request.form.get('razorpay_signature')

    if not (razorpay_payment_id and razorpay_order_id and razorpay_signature):
        flash("Payment verification failed.", "danger")
        return redirect(url_for('cart'))

    payload = {
        'razorpay_order_id': razorpay_order_id,
        'razorpay_payment_id': razorpay_payment_id,
        'razorpay_signature': razorpay_signature
    }

    try:
        razorpay_client.utility.verify_payment_signature(payload)

    except Exception as e:
        app.logger.error(f"Razorpay Verification Failed: {e}")
        flash("Payment verification failed.", "danger")
        return redirect(url_for('cart'))

    user_id = session['user_id']
    cart = get_cart()

    if not cart:
        flash("Cart is empty.", "danger")
        return redirect(url_for('cart'))

    checkout_address = session.get('checkout_address', {})
    username = checkout_address.get('full_name', session.get('user_name', 'Guest'))
    address_parts = [
        checkout_address.get('address_line1', '').strip(),
        checkout_address.get('address_line2', '').strip(),
        f"Landmark: {checkout_address.get('landmark', '').strip()}" if checkout_address.get('landmark', '').strip() else "",
        checkout_address.get('city', '').strip(),
        checkout_address.get('state', '').strip(),
        checkout_address.get('country', '').strip(),
        checkout_address.get('postal_code', '').strip()
    ]
    address_str = ", ".join([part for part in address_parts if part])
    phone = checkout_address.get('phone', '').strip()
    if phone:
        address_str += f" | Phone: {phone}"
    if not address_str or address_str == "Guest" or address_str == "Not Provided":
        address_str = "Not Provided"

    conn = None
    cursor = None

    try:

        conn = get_db_connection()
        cursor = conn.cursor()

        product_ids = [int(pid) for pid in cart.keys()]
        placeholders = ','.join(['%s'] * len(product_ids))

        cursor.execute(
            f"""
            SELECT product_id, name, price
            FROM products
            WHERE product_id IN ({placeholders})
            """,
            tuple(product_ids)
        )

        products = cursor.fetchall()

        total_amount = 0

        for product in products:
            quantity = cart.get(str(product['product_id']), 0)
            total_amount += float(product['price']) * quantity

        # Create Order
        cursor.execute("""
            INSERT INTO orders
            (
                user_id,
                razorpay_order_id,
                razorpay_payment_id,
                amount,
                payment_status,
                username,
                address
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s)
        """, (
            user_id,
            razorpay_order_id,
            razorpay_payment_id,
            total_amount,
            'paid',
            username,
            address_str
        ))

        order_db_id = cursor.lastrowid

        # Save Order Items
        for product in products:

            quantity = cart.get(
                str(product['product_id']),
                0
            )

            cursor.execute("""
                INSERT INTO order_items
                (
                    order_id,
                    product_id,
                    product_name,
                    quantity,
                    price
                )
                VALUES (%s,%s,%s,%s,%s)
            """, (
                order_db_id,
                product['product_id'],
                product['name'],
                quantity,
                product['price']
            ))

        conn.commit()

        session.pop('cart', None)
        session.pop('razorpay_order_id', None)

        flash(
            "Payment successful and order placed!",
            "success"
        )

        return redirect(
            f"/user/order-success/{order_db_id}"
        )

    except Exception as e:

        conn.rollback()

        app.logger.exception(
            "Order Storage Failed"
        )

        flash(
            "There was an error saving the order.",
            "danger"
        )

        return redirect(url_for('cart'))

    finally:

        if cursor:
            cursor.close()

        if conn:
            conn.close()
#=============
# Order success page
#=============
@app.route('/user/order-success/<int:order_db_id>')
def order_success(order_db_id):
    if 'user_id' not in session:
        flash("Please login!", "danger")
        return redirect('/user-login')

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT o.*, COALESCE(o.username, u.name) AS username
        FROM orders o
        JOIN users u ON o.user_id = u.user_id
        WHERE o.order_id=%s AND o.user_id=%s
    """, (order_db_id, session['user_id']))
    order = cursor.fetchone()

    cursor.execute("SELECT * FROM order_items WHERE order_id=%s", (order_db_id,))
    items = cursor.fetchall()

    cursor.close()
    conn.close()

    if not order:
        flash("Order not found.", "danger")
        return redirect('/user/products')

    return render_template("user/order_success.html", order=order, items=items)


# ============================================================================
# Order confirmation
# ============================================================================
@app.route('/confirmation')
def confirmation():
    if 'last_order_id' not in session:
        flash('No recent order was found.', 'warning')
        return redirect(url_for('shop'))

    orders = session.get('orders', [])
    order = next((o for o in orders if o['order_id'] == session['last_order_id']), None)
    if not order:
        flash('No recent order was found.', 'warning')
        return redirect(url_for('shop'))

    order = normalize_order(order)
    return render_template('user/confirmation.html', order=order)

#=============
#my orders
#==========
from pymysql.cursors import DictCursor

@app.route('/user/my-orders')
def my_orders():

    if 'user_id' not in session:
        flash("Please login first!", "danger")
        return redirect('/user-login')

    conn = get_db_connection()
    cursor = conn.cursor(DictCursor)

    try:
        cursor.execute("""
            SELECT
                o.order_id,
                o.amount,
                o.payment_status,
                o.razorpay_order_id,
                o.razorpay_payment_id,
                COALESCE(o.username, u.name) AS username,
                o.address,
                o.created_at
            FROM orders o
            JOIN users u ON o.user_id = u.user_id
            WHERE o.user_id = %s
            ORDER BY o.created_at DESC
        """, (session['user_id'],))

        orders = cursor.fetchall()
        print("My Orders Fetched:", orders)

        return render_template(
            'user/my_orders.html',
            orders=orders
        )

    except Exception as e:
        print("My Orders Error:", e)
        flash("Unable to load orders.", "danger")
        return redirect('/')

    finally:
        cursor.close()
        conn.close()

# ----------------------------
# GENERATE INVOICE PDF
# ----------------------------
@app.route("/user/download-invoice/<int:order_id>")
def download_invoice(order_id):

    if 'user_id' not in session:
        flash("Please login!", "danger")
        return redirect('/user-login')

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT o.*, COALESCE(o.username, u.name) AS username
        FROM orders o
        JOIN users u ON o.user_id = u.user_id
        WHERE o.order_id=%s AND o.user_id=%s
    """, (order_id, session['user_id']))
    order = cursor.fetchone()

    if not order:
        cursor.close()
        conn.close()
        flash("Order not found.", "danger")
        return redirect('/user/my-orders')

    cursor.execute("""
        SELECT * FROM order_items
        WHERE order_id=%s
    """, (order_id,))
    items = cursor.fetchall()

    cursor.close()
    conn.close()

    # Generate PDF using xhtml2pdf and HTML template
    rendered_html = render_template('user/invoice.html', order=order, items=items)
    pdf_buffer = generate_pdf(rendered_html)

    if not pdf_buffer:
        flash("Unable to generate PDF invoice.", "danger")
        return redirect('/user/my-orders')

    pdf_buffer.seek(0)

    return send_file(
        pdf_buffer,
        as_attachment=True,
        download_name=f"invoice_{order_id}.pdf",
        mimetype='application/pdf'
    )
# ============================================================================
# Order history
# ============================================================================
@app.route('/orders')
def orders():
    if 'user_id' not in session:
        flash('Please login to view your orders.', 'warning')
        return redirect(url_for('login'))

    orders = session.get('orders', [])
    normalized_orders = [normalize_order(order) for order in orders]
    return render_template('user/my_orders.html', orders=normalized_orders)


# ============================================================================
# Admin signup and OTP verification
# ============================================================================
@app.route('/admin-signup', methods=['GET', 'POST'])
def admin_signup():
    if request.method == 'GET':
        return render_template('Admin/admin_signup.html')

    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()

    if not name or not email:
        flash('Name and email are required.', 'danger')
        return redirect(url_for('admin_signup'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT admin_id FROM admin WHERE email=%s', (email,))
        existing_admin = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

    if existing_admin:
        flash('This email is already registered. Please login instead.', 'warning')
        return redirect(url_for('admin_login'))

    session['signup_name'] = name
    session['signup_email'] = email
    session['signup_otp'] = generate_numeric_otp(6)
    session['signup_otp_generated_at'] = datetime.datetime.now().timestamp()

    try:
        send_otp_email(
            mail,
            sender=config.MAIL_DEFAULT_SENDER,
            recipient=email,
            otp=session['signup_otp'],
            purpose='Admin Registration',
        )
    except Exception:
        flash('Unable to send OTP email. Please try again later.', 'danger')
        return redirect(url_for('admin_signup'))

    flash('OTP sent to your email.', 'success')
    return redirect(url_for('verify_otp'))


# ============================================================================
# Verify admin OTP
# ============================================================================
@app.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    if request.method == 'GET':
        return render_template('Admin/verify_otp.html', otp_expiry_minutes=OTP_EXPIRY_MINUTES)

    if 'signup_otp' not in session or 'signup_name' not in session or 'signup_email' not in session:
        flash('Please complete the signup form first.', 'warning')
        return redirect(url_for('admin_signup'))

    user_otp = request.form.get('otp', '').strip()
    password = request.form.get('password', '').strip()

    if not user_otp or not password:
        flash('OTP and password are required.', 'danger')
        return redirect(url_for('verify_otp'))

    otp_generated_at = session.get('signup_otp_generated_at')
    if not otp_generated_at:
        session.pop('signup_otp', None)
        session.pop('signup_name', None)
        session.pop('signup_email', None)
        flash('OTP session expired. Please request a new code.', 'warning')
        return redirect(url_for('admin_signup'))

    elapsed_minutes = (datetime.datetime.now().timestamp() - otp_generated_at) / 60
    if elapsed_minutes > OTP_EXPIRY_MINUTES:
        session.pop('signup_otp', None)
        session.pop('signup_otp_generated_at', None)
        session.pop('signup_name', None)
        session.pop('signup_email', None)
        flash(f'OTP expired after {OTP_EXPIRY_MINUTES} minutes. Please request a new OTP.', 'warning')
        return redirect(url_for('admin_signup'))

    if str(session['signup_otp']) != user_otp:
        flash('Invalid OTP. Try again.', 'danger')
        return redirect(url_for('verify_otp'))

    hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO admin (name, email, password) VALUES (%s, %s, %s)',
            (session['signup_name'], session['signup_email'], hashed_password),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    session.clear()
    flash('Admin registered successfully!', 'success')
    return redirect(url_for('admin_login'))


# ============================================================================
# Admin login
# ============================================================================
@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'GET':
        return render_template('Admin/admin_login.html')

    email = request.form.get('email', '').strip()
    password = request.form.get('password', '').strip()

    if not email or not password:
        flash('Email and password are required.', 'danger')
        return redirect(url_for('admin_login'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM admin WHERE email=%s', (email,))
        admin = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

    if not admin:
        flash('No account found with this email.', 'danger')
        return redirect(url_for('admin_login'))

    if verify_password(password, admin['password']):
        session['admin_id'] = admin['admin_id']
        session['admin_name'] = admin['name']
        flash('Login successful!', 'success')
        return redirect(url_for('admin_dashboard'))

    flash('Invalid password.', 'danger')
    return redirect(url_for('admin_login'))

#=======================================
# admin forgot password
#=======================================
@app.route('/admin/forgot-password', methods=['GET', 'POST'])
def admin_forgot_password():

    if request.method == 'GET':
        return render_template('admin/forgot_password.html')

    email = request.form.get('email', '').strip()

    if not email:
        flash('Please enter your email.', 'warning')
        return redirect(url_for('admin_forgot_password'))

    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT admin_id FROM admin WHERE email=%s",
            (email,)
        )

        admin = cursor.fetchone()

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    if admin:
        flash(
            'Password reset request received. Check your email.',
            'success'
        )
    else:
        flash(
            'If that email is registered, a password reset link has been sent.',
            'info'
        )

    return redirect(url_for('admin_forgot_password'))
# ============================================================================
# Admin dashboard
# ============================================================================
@app.route('/admin-dashboard')
def admin_dashboard():

    if 'admin_id' not in session:
        flash('Please login first.', 'warning')
        return redirect(url_for('admin_login'))

    profile_image_support = has_column('admin', 'profile_image')
    profile_image = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # 🔥 ADMIN INFO
        select_fields = 'admin_id, name'
        if profile_image_support:
            select_fields += ', profile_image'

        cursor.execute(
            f'SELECT {select_fields} FROM admin WHERE admin_id=%s',
            (session['admin_id'],)
        )
        admin_info = cursor.fetchone()

        # 🔥 TOTAL PRODUCTS
        cursor.execute("SELECT COUNT(*) AS total FROM products")
        total_products = cursor.fetchone()['total']

        # 🔥 TOTAL CATEGORIES
        cursor.execute("SELECT COUNT(DISTINCT category) AS total FROM products")
        total_categories = cursor.fetchone()['total']

    finally:
        cursor.close()
        conn.close()

    if admin_info and profile_image_support:
        profile_image = admin_info.get('profile_image')

    return render_template(
        'Admin/dashboard.html',
        admin_name=session['admin_name'],
        profile_image=profile_image,
        total_products=total_products,
        total_categories=total_categories
    )
# ============================================================================
# Admin logout
# ============================================================================
@app.route('/admin-logout')
def admin_logout():
    session.clear()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('admin_login'))


# ============================================================================
# Admin product list
# ============================================================================
@app.route('/admin/products', endpoint='product_list')
@app.route('/admin/items', endpoint='admin_items')
def product_list():
    if 'admin_id' not in session:
        flash('Please login first.', 'danger')
        return redirect(url_for('admin_login'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT product_id AS item_id, name, category, price, image FROM products')
        items = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return render_template('Admin/item_list.html', items=items)


# ============================================================================
# Admin product search
# ============================================================================
@app.route('/admin/items/search')
def admin_product_search():
    if 'admin_id' not in session:
        flash('Please login first.', 'danger')
        return redirect(url_for('admin_login'))

    query = request.args.get('query', '').strip()
    category = request.args.get('category', '').strip()
    max_price = request.args.get('price', '').strip()

    sql = 'SELECT product_id AS item_id, name, category, price, image FROM products WHERE 1=1'
    params = []

    if query:
        sql += ' AND name LIKE %s'
        params.append(f'%{query}%')
    if category:
        sql += ' AND category = %s'
        params.append(category)
    if max_price:
        try:
            price_value = float(max_price)
            sql += ' AND price <= %s'
            params.append(price_value)
        except ValueError:
            flash('Max price must be a number.', 'warning')

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(sql, tuple(params))
        items = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return render_template('Admin/item_list.html', items=items)

# ============================================================================
# Admin product detail
# ============================================================================
@app.route('/admin/product/<int:product_id>')
def admin_product_detail(product_id):
    if 'admin_id' not in session:
        flash('Please login first.', 'danger')
        return redirect(url_for('admin_login'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT product_id AS item_id, name, description, category, price, image FROM products WHERE product_id=%s',
            (product_id,),
        )
        product = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

    if not product:
        flash('Product not found.', 'warning')
        return redirect(url_for('product_list'))

    return render_template('Admin/item_details.html', product=product)


# ============================================================================
# Admin edit product
# ============================================================================
@app.route('/admin/edit-item/<int:product_id>', methods=['GET', 'POST'])
def edit_item(product_id):
    if 'admin_id' not in session:
        flash('Please login first.', 'danger')
        return redirect(url_for('admin_login'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT product_id AS item_id, name, description, category, price, image FROM products WHERE product_id=%s',
            (product_id,),
        )
        product = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

    if not product:
        flash('Product not found.', 'warning')
        return redirect(url_for('product_list'))

    if request.method == 'GET':
        return render_template('Admin/edit_item.html', product=product)

    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    category = request.form.get('category', '').strip()
    price = request.form.get('price', '').strip()
    image_file = request.files.get('image')

    if not name or not description or not category or not price:
        flash('All fields are required.', 'danger')
        return redirect(url_for('edit_item', product_id=product_id))

    image_name = product['image']
    if image_file and image_file.filename:
        filename = secure_filename(image_file.filename)
        if not allowed_file(filename):
            flash('Only image files are allowed.', 'danger')
            return redirect(url_for('edit_item', product_id=product_id))

        image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        image_file.save(image_path)
        image_name = filename

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE products SET name=%s, description=%s, category=%s, price=%s, image=%s WHERE product_id=%s',
            (name, description, category, price, image_name, product_id),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    flash('Product updated successfully!', 'success')
    return redirect(url_for('admin_product_detail', product_id=product_id))


# ============================================================================
# Admin delete product
# ============================================================================
@app.route('/admin/delete-item/<int:product_id>', methods=['GET', 'POST'])
def delete_item(product_id):
    if 'admin_id' not in session:
        flash('Please login first.', 'danger')
        return redirect(url_for('admin_login'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT product_id AS item_id, name, category, price, image FROM products WHERE product_id=%s',
            (product_id,),
        )
        product = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

    if not product:
        flash('Product not found.', 'warning')
        return redirect(url_for('product_list'))

    if request.method == 'GET':
        return render_template('Admin/delete_item.html', product=product)

    image_path = os.path.join(app.config['UPLOAD_FOLDER'], product['image']) if product['image'] else None
    if image_path and os.path.exists(image_path):
        os.remove(image_path)

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM products WHERE product_id=%s', (product_id,))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    flash('Product deleted successfully.', 'success')
    return redirect(url_for('product_list'))


# ============================================================================
# Admin profile
# ============================================================================
@app.route('/admin/profile', methods=['GET', 'POST'])
def admin_profile():
    if 'admin_id' not in session:
        flash('Please login first.', 'warning')
        return redirect(url_for('admin_login'))

    profile_image_support = has_column('admin', 'profile_image')

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        select_fields = 'admin_id, name, email'
        if profile_image_support:
            select_fields += ', profile_image'
        cursor.execute(f'SELECT {select_fields} FROM admin WHERE admin_id=%s', (session['admin_id'],))
        admin = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

    if not admin:
        session.clear()
        flash('Admin account not found.', 'danger')
        return redirect(url_for('admin_login'))

    if request.method == 'GET':
        return render_template('Admin/admin_profile.html', admin=admin)

    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '').strip()
    image_file = request.files.get('profile_image')

    if not name or not email:
        flash('Name and email are required.', 'danger')
        return redirect(url_for('admin_profile'))

    update_fields = ['name = %s', 'email = %s']
    params = [name, email]

    if password:
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        update_fields.append('password = %s')
        params.append(hashed_password)

    if profile_image_support and image_file and image_file.filename:
        filename = secure_filename(image_file.filename)
        if not allowed_file(filename):
            flash('Only image files are allowed for profile image.', 'danger')
            return redirect(url_for('admin_profile'))

        image_path = os.path.join(ADMIN_UPLOAD_FOLDER, filename)
        image_file.save(image_path)
        update_fields.append('profile_image = %s')
        params.append(filename)

    params.append(session['admin_id'])

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(f'UPDATE admin SET {", ".join(update_fields)} WHERE admin_id=%s', tuple(params))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    # Keep session values in sync after profile update.
    session['admin_name'] = name
    flash('Profile updated successfully.', 'success')
    return redirect(url_for('admin_profile'))


# ============================================================================
# Admin add product
# ============================================================================
@app.route('/admin/add-item', methods=['GET', 'POST'])
def add_item():
    if 'admin_id' not in session:
        flash('Please login first.', 'danger')
        return redirect(url_for('admin_login'))

    if request.method == 'GET':
        return render_template('Admin/add_item.html')

    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    category = request.form.get('category', '').strip()
    price = request.form.get('price', '').strip()
    image_file = request.files.get('image')

    if not name or not description or not category or not price:
        flash('All fields are required.', 'danger')
        return redirect(url_for('add_item'))

    if image_file is None or image_file.filename == '':
        flash('Please upload an image.', 'danger')
        return redirect(url_for('add_item'))

    filename = secure_filename(image_file.filename)
    if not allowed_file(filename):
        flash('Only image files are allowed.', 'danger')
        return redirect(url_for('add_item'))

    image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    image_file.save(image_path)

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO products (name, description, category, price, image) VALUES (%s, %s, %s, %s, %s)',
            (name, description, category, price, filename),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    flash('Product added successfully!', 'success')
    return redirect(url_for('admin_items'))


if __name__ == '__main__':
    app.run(debug=True)
