# Venus OS Driver for Tesla Wall Connector 3 (TWC3)

This program regularly polls a Tesla Wall Connector 3 on the
local network and creates a dbus device for an AC charging
station.

The charging station will only show up properly in the GX remote
control window as no visualization is provided by Victron in
the VRM portal.

To still show the status the driver creates a secondary
temperature device which is used to communiate the state of
the wallbox.

There is no control logic part of this driver. This is just
providing the data on the dbus.

## Installation (Supervise)

If you want to run the script on the GX device, proceed like
this 
```
cd /data/
git clone http://github.com/trixing/venus.dbus-twc3
chmod +x /data/venus.dbus-twc3/service/run
chmod +x /data/venus.dbus-twc3/service/log/run
```

If you are on Venus OS < 2.80 you need to also install the
python3 libraries:
```
opkg install python3 python3-requests
```

### Configuration

To configure the service (e.g. provide a fixed IP instead of
the default MDNS name) edit `/data/venus.dbus-twc3/service/run`.

### Start the service

Finally activate the service
```
ln -s /data/venus.dbus-twc3/service /service/venus.dbus-twc3
```
If you are on Venus OS 2.9+ this line needs to be added to
[/data/rc.local](see https://www.victronenergy.com/live/ccgx:root_access)
as well.

Create the file if it does not exist.


## Possible improvements

- [ ] Allow for control of charging once Tesla adds an API for this.
