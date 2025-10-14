import requests
import re
import logging
from bs4 import BeautifulSoup

IP = "192.168.178.10"
USERNAME = "admin"
PASSWORD = "ih1h1kbh"

def fetch_system_info(ip, username, password):
    """Fetch system info from the TP-Link switch web interface."""
    session = requests.Session()
    data = {"logon": "Login", "username": username, "password": password}

    # Login to the switch
    session.post(f"http://{ip}/logon.cgi", data=data)
    
    # Get system info page
    response = session.get(f"http://{ip}/SystemInfoRpm.htm")
    
    if response.status_code != 200:
        print(f"⚠️ Failed to fetch system info (HTTP {response.status_code})")
        return {}

    soup = BeautifulSoup(response.text, "html.parser")

    # Extract JavaScript block containing system info
    script_tag = soup.find("script")
    if not script_tag or not script_tag.string:
        print("⚠️ No script block found in SystemInfoRpm.htm")
        return {}

    script_text = script_tag.string

    # Debug: Print full script text
    print("📜 System Info Script Block:")
    print(script_text)

    # Extract system info safely
    def extract_value(pattern):
        match = re.search(pattern, script_text, re.DOTALL)  # Use DOTALL to match across lines
        return match.group(1).strip() if match else "Unknown"

    info = {
        "device_model": extract_value(r'descriStr:\[\s*"([^"]+)"\s*\]'),
        "mac_address": extract_value(r'macStr:\[\s*"([^"]+)"\s*\]'),
        "ip_address": extract_value(r'ipStr:\[\s*"([^"]+)"\s*\]'),
        "subnet_mask": extract_value(r'netmaskStr:\[\s*"([^"]+)"\s*\]'),
        "default_gateway": extract_value(r'gatewayStr:\[\s*"([^"]+)"\s*\]'),
        "firmware_version": extract_value(r'firmwareStr:\[\s*"([^"]+)"\s*\]'),
        "hardware_version": extract_value(r'hardwareStr:\[\s*"([^"]+)"\s*\]')
}


    return info


result = fetch_system_info(IP, USERNAME, PASSWORD)
print(result)
