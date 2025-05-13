import asyncio
from refosslib.discovery import Discovery
from refosslib.device_manager import async_build_base_device

async def main():
    discovery = Discovery()
    await discovery.initialize()
    devices = await discovery.broadcast_msg()

    if not devices:
        print("❌ Aucun appareil Refoss trouvé.")
        return

    for i, dev in enumerate(devices):
        print(f"[{i}] Appareil trouvé : {dev.device_type} | {dev.device_id}")

    # Choix du premier appareil détecté
    device = await async_build_base_device(devices[0])
    await device.async_handle_update()

    print(f"\n🔍 Appareil : {device.device_type} | Canaux : {device.channels}")
    for ch in device.channels:
        power = device.get_value(ch, "power") / 1000  # en W
        pf = device.get_value(ch, "factor")
        voltage = device.get_value(ch, "voltage")
        print(f"Canal {ch} : {power:.1f} W | Tension : {voltage} V | PF : {pf}")

asyncio.run(main())
