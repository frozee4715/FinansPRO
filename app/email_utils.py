"""E-posta yardımcı modülü — fatura bildirimi gönderme."""
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import current_app


def send_invoice_email(
    to_email: str,
    to_name: str,
    fatura_no: str,
    pdf_path: str = None,
) -> tuple:
    """Faturayı e-posta ile gönderir.

    Returns:
        (bool_basari, hata_mesaji) — başarıysa (True, ""), hata varsa (False, mesaj).
    """
    smtp_host = current_app.config.get("SMTP_HOST", "")
    smtp_port = int(current_app.config.get("SMTP_PORT", 587))
    smtp_user = current_app.config.get("SMTP_USER", "")
    smtp_pass = current_app.config.get("SMTP_PASS", "")
    from_name = current_app.config.get("APP_NAME", "FinansPro")

    if not smtp_host or not smtp_user:
        return (
            False,
            "SMTP ayarları yapılandırılmamış. Ayarlar > E-posta bölümünden yapılandırın.",
        )

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"{fatura_no} No'lu Faturanız"
        msg["From"] = f"{from_name} <{smtp_user}>"
        msg["To"] = f"{to_name} <{to_email}>"

        html_body = f"""
        <html><body style="font-family:Arial,sans-serif;color:#333;">
        <h2 style="color:#7c3aed;">Fatura Bildirimi</h2>
        <p>Sayın <strong>{to_name}</strong>,</p>
        <p><strong>{fatura_no}</strong> numaralı faturanız oluşturulmuştur.</p>
        <p>Detayları için sisteme giriş yapınız.</p>
        <hr>
        <small style="color:#999;">{from_name} tarafından gönderilmiştir.</small>
        </body></html>
        """
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        context = ssl.create_default_context()
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls(context=context)
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, to_email, msg.as_string())

        return True, ""
    except Exception as e:
        return False, str(e)
