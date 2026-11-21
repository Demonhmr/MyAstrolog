"""
mailer.py — письма с кодом входа.

Отправка через почтовый сервер на этом же VPS (exim, 127.0.0.1:25 без пароля, как у Волпеня):
exim подписывает письмо DKIM по домену отправителя (/etc/exim4/dkim/zvezditsa.ru.private).
Контейнер сервера приложения работает в сети хоста, поэтому 127.0.0.1 — это exim.
"""

import logging
import os
import smtplib
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

logger = logging.getLogger("zvezditsa.mail")


def mail_from() -> str:
    return os.getenv("MAIL_FROM", "no-reply@zvezditsa.ru")


def send_login_code(email: str, code: str) -> bool:
    msg = EmailMessage()
    msg["From"] = f"Звездица <{mail_from()}>"
    msg["To"] = email
    msg["Subject"] = f"Код для входа в Звездицу: {code}"
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=mail_from().split("@")[-1])
    msg.set_content(
        f"Ваш код для входа в Звездицу: {code}\n\n"
        "Код действует 10 минут. Введите его на странице входа.\n\n"
        "Если вы не входили в Звездицу, просто удалите это письмо — без кода в аккаунт не войти.\n\n"
        "— Звездица, https://zvezditsa.ru\n"
    )
    host = os.getenv("MAIL_HOST", "127.0.0.1")
    port = int(os.getenv("MAIL_PORT", "25"))
    try:
        with smtplib.SMTP(host, port, timeout=15) as s:
            s.send_message(msg)
        return True
    except Exception as e:
        # адрес в журнал не пишем
        logger.error("login mail failed: %s", type(e).__name__)
        return False
