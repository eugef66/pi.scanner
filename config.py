import os

# Uncomment the line below to use RPI emulator and change path to emulators module
# sys.path.append("../pi.emulators")

USE_ARP_SCAN = True
ALERT_NEW_DEVICE = True
ALERT_DOWN_DEVICE = True

SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587
SMTP_USERNAME = 'user@gmail.com'
SMTP_PASSWORD = 'password'
EMAIL_TO = "user@gmail.com"

APP_PATH = os.path.dirname(os.path.abspath(__file__))