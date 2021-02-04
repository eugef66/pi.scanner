#!/usr/bin/env python
import os
import json
import sys
import uuid
import requests
import subprocess
import re
import time
import smtplib
import sqlite3

from subprocess import Popen, PIPE
from datetime import datetime


DB = None
DHCP_RESERVATIONS = {}
LOCAL_DNS = {}

APP_PATH = os.path.dirname(os.path.abspath(__file__))

if (sys.version_info > (3, 0)):
    exec(open(APP_PATH + "/app.conf").read())
else:
    execfile(APP_PATH + "/app.conf")


# Scan for new devices
def scan_network():
    if (DB == None):
        _load_db()

    # Step 1. Scan online devices using arp-scan

    online_devices = _load_arp_scan()
    # compare output with DB to find new and trigger "offline alert"
    for device in online_devices:
        mac = device["mac"]
        ip = device["ip"]
        vendor = device["vendor"]
        if (mac in DB):
            if (DB[mac]["alert_down"]):
                _send_down_alert(mac)
        create_update_device(False, mac=mac, ip=ip,
                             is_online=True, vendor=vendor)

    # Step 2. Get current dhcp_lease from PIHOLE DHCP

    if (PIHOLE_DHCP_ENABLED):
        dhcp_leases = _load_DHCP_leases()
        for device in dhcp_leases:
            mac = device["mac"]
            ip = device["ip"]
            hostname = device["hostname"]
            create_update_device(False, mac=mac, ip=ip, hostname=hostname)
    # Step 3. Get current pihole network devices
    if (PIHOLE_ENABLED):
        print("--- Scanning PIHOLE Network ---")
        clients = _load_pihole_network()
        for device in clients:
            mac = device["mac"]
            ip = device["ip"]
            vendor = device["vendor"]
            create_update_device(False, mac=mac, ip=ip, vendor=vendor)

    _save_db()
    return


def get_default_device_name(mac, ip):
    mac = mac.upper()
    ip = _ip_last_number(ip)
    if (mac in DHCP_RESERVATIONS):
        return DHCP_RESERVATIONS[mac]["hostname"]
    elif (ip in LOCAL_DNS):
        return LOCAL_DNS[ip]
    return "(new device)"
# Get Vendor Name by MAC


def get_vendor_by_mac(mac):
    vendor = ""
    try:
        # https://api.macvendors.com/d8:eb:97:22:e6:4b
        time.sleep(1)
        url = "https://api.macvendors.com/" + mac
        mlr = requests.get(url)
        if mlr.status_code == 200:
            vendor = mlr.content
        return vendor.decode("utf-8")
    except:
        return "(Vendor Lookup Error)"


def create_update_device(save_to_db, mac, ip, is_online=None, description=None, alert_down=None, hostname=None, vendor=None, is_new=None):
    if DB == None:
        _load_db()

    ip4 = None
    ip6 = None
    if (":" in ip):
        ip6 = ip
    else:
        ip4 = ip

    if (mac not in DB):
        default_device_name = get_default_device_name(mac, ip)
        if (is_new == None):
            isnew = True
        if (description == None):
            description = default_device_name
        if (hostname == None):
            hostname = get_default_device_name(mac, ip)
        if (alert_down == None):
            alert_down = False
        if (is_online == None):
            is_online = False
        if (vendor == None):
            vendor = get_vendor_by_mac(mac)
        print("--- Creating New Device ---")
        print("--- --- " + mac + " | " + vendor + " | " + description + " | " + ip)
        if (ALERT_NEW_DEVICE):
            _send_new_alert(mac)
    else:
        if (ip4 == None):
            ip4 = DB[mac]["ip"]
        if (ip6 == None):
            ip6 = DB[mac]["ip6"]
        if (is_new == None):
            isnew = DB[mac]["is_new"]
        if (description == None):
            description = DB[mac]["description"]
        if (hostname == None):
            hostname = DB[mac]["hostname"]
        if (alert_down == None):
            alert_down = DB[mac]["alert_down"]
        if (is_online == None):
            is_online = DB[mac]["is_online"]
        if (vendor == None):
            vendor = DB[mac]["vendor"]
        if (DB[mac]["alert_down"] and not is_online):
            _send_down_alert(mac)
        print("--- Updating Existing Device ---")
        print("--- --- " + mac + " | " + vendor + " | " + description + " | " + ip)

    DB[mac] = {"ip": ip4,
               "ip6": ip6,
               "is_online": is_online,
               "description": description,
               "vendor": vendor,
               "hostname": hostname,
               "alert_down": alert_down,
               "updateTS": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
               "is_new": isnew
               }
    if (save_to_db):
        _save_db()
    return


def _load_arp_scan():
    devices = []
    arpscan_output = subprocess.check_output(
        ['sudo', 'arp-scan', '--localnet', '--ignoredups', '--retry=1'], universal_newlines=True)
    lineindex = 1
    number_of_cleints = len(arpscan_output.splitlines())-2
    for line in arpscan_output.splitlines():
        lineindex += 1
        if lineindex < 4 or lineindex > number_of_cleints:
            continue
        device = line.split('\t')
        devices.append({"ip": device[0],
                        "mac": device[1],
                        "vendor": device[2]})
    return devices


def _load_pihole_network():
    clients = []
    conn = sqlite3.connect(PIHOLE_NETWORK_DB)
    cur = conn.cursor()
    cur.execute(
        "SELECT hwaddr, macVendor, ip FROM network n INNER JOIN network_addresses na ON n.id=na.network_id")
    rows = cur.fetchall()

    for row in rows:
        clients.append({"mac": row[0], "vendor": row[1], "ip": row[2]})
    conn.close()

    # remove mac dulicates with ipv6 addresess
    return clients


def _load_DHCP_leases():
    dhcp_leases = []
    with open(PIHOLE_DHCP_LEASE_FILE, "r") as dhcp_file:
        for line in dhcp_file.readlines():
            device = line.split(' ')
            dhcp_leases.append(
                {"mac": device[1], "ip": device[2], "hostname": device[3]})

    return dhcp_leases


def _load_db():
    print("--- loading database ---")
    global DB
    if (os.path.exists(APP_PATH + "/db.json")):
        with open(APP_PATH + '/db.json', 'r') as db_file:
            DB = json.load(db_file)
    else:
        DB = {}
        _save_db()

    # Load MetaData

    global DHCP_RESERVATIONS
    global LOCAL_DNS
    if (PIHOLE_DHCP_ENABLED and os.path.exists(PIHOLE_DHCP_RES_FILE)):
        # load DHCP Reservations

        with open(PIHOLE_DHCP_RES_FILE, 'r') as dres_file:
            for line in dres_file.readlines():
                device = line.split(",")
                if (len(device) >= 3):
                    mac = device[0].replace("dhcp-host=", "").upper()
                    ip = device[1]
                    hostname = device[2].replace("\n", "")
                    DHCP_RESERVATIONS[mac] = {"ip": ip, "hostname": hostname}

    # load Local DNS custom list
    if (os.path.exists(PIHOLE_LOCAL_DNS_FILE)):
        with open(PIHOLE_LOCAL_DNS_FILE, 'r') as dres_file:
            for line in dres_file.readlines():
                device = line.split(" ")
                if(len(device) >= 2):
                    ip = _ip_last_number(device[0])
                    hostname = device[1].replace("\n", "")
                    LOCAL_DNS[ip] = hostname
    return


def _save_db():
    with open(APP_PATH + "/db.json", "w+") as db_file:
        db_file.write(json.dumps(DB, indent=4))
    return


def _send_down_alert(mac):
    print ("Sending Down Alert")
    return


def _send_new_alert(mac):
    print ("Sending New Device Alert")
    return


def _ip_last_number(ip):
    return int(ip.split(".")[3])
# Default process when no method argument provides


def send_email(subject, text):

    #msg = MIMEMultipart('alternative')
    #msg['Subject'] = 'Pi.Alert Report'
    #msg['From'] = REPORT_FROM
    #msg['To'] = REPORT_TO
    #msg.attach (MIMEText (pText, 'plain'))
    #msg.attach (MIMEText (pHTML, 'html'))

    header = "To: " + EMAIL_TO + "\nFrom: " + \
        SMTP_USERNAME + "\n" + "Subject: " + subject
    body = text

    s = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
    s.ehlo()
    s.starttls()
    s.ehlo()
    s.login(SMTP_USERNAME, SMTP_PASSWORD)
    # print body + "\n==================================="
    s.sendmail(SMTP_USERNAME, EMAIL_TO, header + '\n\n' + body)
    s.quit()


def main():
    _load_db()
    scan_network()


if __name__ == '__main__':
    sys.exit(main())
