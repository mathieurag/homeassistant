#!/usr/bin/env bash
source /config/python_env/bin/activate
python3 - << 'EOF'
from aiounifi import AIoUnifiClient
import asyncio
import json

async def get_unifi_data():
    async with AIoUnifiClient(
        host="192.168.68.1",
        port=443,
        username="homeassistant",
        password="Homeassistant2025",
        verify_ssl=False,
    ) as client:
        sites = await client.sites()
        site = sites[0]
        clients = await client.get_clients(site.description)
        data = {"clients_5g": len([c for c in clients if c.radio == "ng"])}
        with open("/config/unifi_stats.json", "w") as f:
            json.dump(data, f)

asyncio.run(get_unifi_data())
EOF
