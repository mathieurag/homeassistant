from refoss_ha.discovery import Discovery
from refoss_ha.device_manager import async_build_base_device

async def get_power_data():
    discovery = Discovery()
    await discovery.initialize()
    devices = await discovery.broadcast_msg()
    
    device = await async_build_base_device(devices[0])  # à ajuster si plusieurs
    await device.async_handle_update()

    for channel in device.channels:
        power = device.get_value(channel, "power")
        pf = device.get_value(channel, "factor")
        print(f"Channel {channel} : {power / 1000} W, PF = {pf}")
