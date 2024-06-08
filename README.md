# Venus OS Driver for Kaco NX3 Inverters using HTTP protocol

This program regularly polls a Kaco NX3 inverter via HTTP
local network and creates several dbus devices for it:

- One PV inverter per string, this allows monitoring of
  power of individual strings.

- One temperature device.

I have found the HTTP method to be more reliable and stable
than the modbus polling.

Caveats with exposing per string inverters is that the energy
produces is just split in equal parts as the inverter isn't
able to track per-mppt energy production. That means that
instantanous power production will be accurate but history
energy wrong. There is no easy fix for this unfortunately.

## Installation (Supervise)

If you want to run the script on the GX device, proceed like
this
```
cd /data/
git clone http://github.com/trixing/venus.dbus-trixing-lib
git clone http://github.com/trixing/venus.dbus-kaco-http
chmod +x /data/venus.dbus-kaco-http/service/run
chmod +x /data/venus.dbus-kaco-http/service/log/run
```

### Configuration

To configure the service (e.g. change the IP or installation path)
edit `/data/venus.dbus-kaco-http/service/run`.

### Start the service

Finally activate the service
```
ln -sf /data/venus.dbus-kaco-http/service /service/venus.dbus-kaco-http
```
Tis line needs to be added to
[/data/rc.local](see https://www.victronenergy.com/live/ccgx:root_access)
as well to automatically start the service.

Create the rc.local file if it does not exist.


## Possible improvements

- [ ] Better documentation
- [ ] Better energy tracking
