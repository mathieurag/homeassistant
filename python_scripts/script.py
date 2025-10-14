import tinytuya
d = tinytuya.OutletDevice('bfb19d42320870b8629s7m', '192.168.68.146', 'k`Fos)^daoT1-uH:')
d.set_version(3.5)
d.set_socketPersistent(True)
print(d.status())
