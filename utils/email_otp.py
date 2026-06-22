import random
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from flask_mail import Message


def generate_numeric_otp(length=6):
    """Generate a numeric OTP of a given length."""
    if length < 4:
        raise ValueError("OTP length must be at least 4 digits.")
    return "".join(str(random.randint(0, 9)) for _ in range(length))


def send_otp_email(mail, sender, recipient, otp, purpose="OTP"):
    """Send an OTP email using Flask-Mail."""
    subject = f"SmartCart {purpose} OTP"
    body = (
        f"Your SmartCart {purpose} OTP is: {otp}\n\n"
        "Enter this code on the website to continue. Do not share this OTP with anyone."
    )
    html = (
        f"<p>Your SmartCart {purpose} OTP is: <strong>{otp}</strong></p>"
        "<p>Enter this code on the website to continue. Do not share this OTP with anyone.</p>"
    )
    message = Message(subject, sender=sender, recipients=[recipient])
    message.body = body
    message.html = html
    message.reply_to = sender
    mail.send(message)


def generate_password_reset_token(secret_key, email, salt="password-reset"):
    """Generate a time-limited password reset token."""
    serializer = URLSafeTimedSerializer(secret_key)
    return serializer.dumps(email, salt=salt)


def verify_password_reset_token(secret_key, token, expires_sec=3600, salt="password-reset"):
    """Verify a password reset token and return the email if valid."""
    serializer = URLSafeTimedSerializer(secret_key)
    try:
        email = serializer.loads(token, salt=salt, max_age=expires_sec)
        return email
    except (SignatureExpired, BadSignature):
        return None


def send_password_reset_link(mail, sender, recipient, reset_url, purpose="Password Reset"):
    """Send a password reset link email using Flask-Mail."""
    subject = f"SmartCart {purpose}"
    body = (
        "You requested a password reset for your SmartCart account.\n\n"
        f"Click the link below to reset your password:\n{reset_url}\n\n"
        "This link will expire in 60 minutes. If you did not request a reset, ignore this email."
    )
    html = (
        "<p>You requested a password reset for your SmartCart account.</p>"
        f"<p><a href=\"{reset_url}\">Reset your password</a></p>"
        "<p>This link will expire in 60 minutes. If you did not request a reset, ignore this email.</p>"
    )
    message = Message(subject, sender=sender, recipients=[recipient])
    message.body = body
    message.html = html
    message.reply_to = sender
    mail.send(message)


def send_contact_email(mail, sender, recipient, name, email, message):
    """Send a contact form message to the admin using Flask-Mail."""
    subject = f"SmartCart Support Message from {name}"
    body = (
        f"You received a new message from the contact form:\n\n"
        f"Name: {name}\n"
        f"Email: {email}\n\n"
        f"Message:\n{message}"
    )
    html = (
        f"<p>You received a new message from the contact form:</p>"
        f"<p><strong>Name:</strong> {name}<br>"
        f"<strong>Email:</strong> {email}</p>"
        f"<p><strong>Message:</strong><br>{message}</p>"
    )
    msg = Message(subject, sender=sender, recipients=[recipient])
    msg.body = body
    msg.html = html
    msg.reply_to = email
    mail.send(msg)

