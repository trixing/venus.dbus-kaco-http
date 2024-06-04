#!/usr/bin/env python

"""
Created by Jan Dittmer <jdi@l4x.org> in 2021

Losely Based on DbusDummyService and RalfZim/venus.dbus-fronius-smartmeter
"""
try:
  import gobject
except ImportError:
  from gi.repository import GLib as gobject
import argparse
import platform
import json
import logging
import sys
import os
import requests # for http GET
import time
import traceback
try:
    import thread   # for daemon = True
except ImportError:
    pass

import dbus

# our own packages
sys.path.insert(1, os.path.join(os.path.dirname(__file__), '../ext/velib_python'))
sys.path.insert(1, os.path.join(os.path.dirname(__file__), '../velib_python'))
sys.path.insert(1, os.path.join(os.path.dirname(__file__), '/opt/victronenergy/dbus-systemcalc-py/ext/velib_python'))
from vedbus import VeDbusService

from settingsdevice import SettingsDevice


log = logging.getLogger("DbusKacoHttp")


class SystemBus(dbus.bus.BusConnection):
    def __new__(cls):
        return dbus.bus.BusConnection.__new__(cls, dbus.bus.BusConnection.TYPE_SYSTEM)

class SessionBus(dbus.bus.BusConnection):
    def __new__(cls):
        return dbus.bus.BusConnection.__new__(cls, dbus.bus.BusConnection.TYPE_SESSION)


def dbusconnection():
    return SessionBus() if 'DBUS_SESSION_BUS_ADDRESS' in os.environ else SystemBus()



class DbusKacoHttpService:

  def _getdev(self, device=None):
    url = self.url + '/getdev.cgi?device=' + (str(device) or '0')
    log.info("Connecting to %s " % url)
    r = requests.get(url, timeout=10)
    return r.json() 

  def __init__(self, ip, servicename, deviceinstance,
               productname='KacoInverter', name='Kaco Inverter',
               dryrun=False):
    self._name = name
    self._retries = 0
    ip = ip
    self.url = 'http://' + ip + ':8484'
    inverters = self._getdev(2)
    log.info('Inverter data %r' % repr(inverters))
    self.strings = {}
    n = 0
    for inv in inverters['inv']:
        sn = inv['isn']
        devdata = self._getdevdata(sn)
        print(devdata)
        self.strings[sn] = []
        if len(devdata['vpv']) != 2:
            raise Exception("Incorrect amount of MPPT trackers detected")

        for i in range(len(devdata['vpv'])):
            name = '%s_%s_%i' % (servicename, sn.replace('.', '_'), i)
            self.strings[sn].append(
                    DbusKacoString(name,
                                   productname,
                                   deviceinstance + n,
                                   ip,
                                   i,
                                   inv))
            n += 1
    gobject.timeout_add(5000, self._safe_update)

  def _safe_update(self):
    try:
        self._update()
        if self._retries > 0:
            log.warn('Connecting')
            for sn in self.strings:
                for string in self.strings[sn]:
                    string.connect()
        self._retries = 0
    except Exception as exc:
        tb_str = traceback.format_exception(etype=type(exc), value=exc, tb=exc.__traceback__)

        log.error('Error running update, try %d: %s' % (self._retries, tb_str))
        self._retries += 1
        if self._retries == 12:
            log.warn('Disconnecting')
            for sn in self.strings:
                for string in self.strings[sn]:
                    string.disconnect()
    return True

  def _update(self):
    for sn in self.strings:
        devdata = self._getdevdata(sn)
        ipv_total = sum(devdata['ipv'])
        n = len(self.strings[sn])
        for i in range(n):
            string = self.strings[sn][i]
            data = devdata.copy()
            if ipv_total > 0:
                ratio = devdata['ipv'][i] / ipv_total
            else:
                ratio = 0
            data['iac'] = [phase * ratio for phase in devdata['iac']]
            data['pac'] = devdata['pac'] * ratio
            data['sac'] = devdata['sac'] * ratio
            data['qac'] = devdata['qac'] * ratio
            data['ipv'] = devdata['ipv'][i]
            data['vpv'] = devdata['vpv'][i]
            data['eto'] = devdata['eto'] / n
            data['etd'] = devdata['etd'] / n
            print(data)
            string.update(data)


  def _getdevdata(self, sn):
    url = self.url + '/getdevdata.cgi?device=2&sn=' + sn
#    print(url)
    r = requests.get(url, timeout=2)
    return r.json() 


class DbusKacoString:


  def __init__(self, servicename, productname, deviceinstance, ip, string, inv):
    bus = dbusconnection()
    self._dbusservice = VeDbusService(servicename, bus=bus)
    self._settings = SettingsDevice(bus=bus, supportedSettings={}, eventCallback=self._handle_changed_setting)
    unique_name = 'kaco_http_%s_%i' % (inv['isn'].replace('.', '_'), string)
    self.device_instance = self._set_up_device_instance(unique_name, deviceinstance)
    paths=[
      '/Ac/L1/Power',
      '/Ac/L1/Voltage',
      '/Ac/L1/Current',
      '/Ac/L1/Energy/Forward',
      '/Ac/L2/Power',
      '/Ac/L2/Voltage',
      '/Ac/L2/Current',
      '/Ac/L2/Energy/Forward',
      '/Ac/L3/Power',
      '/Ac/L3/Voltage',
      '/Ac/L3/Current',
      '/Ac/L3/Energy/Forward',
      '/Ac/Energy/Forward',
      '/Ac/Frequency',
      #'/Ac/Voltage',
      #'/Ac/Current',
      '/Ac/MaxPower',
      '/Ac/Power',
      '/Ac/PowerLimit',
      '/Position',
      '/StatusCode',
      '/ErrorCode',
      '/Temperature',
    ]

    logging.info("Registered %s  with DeviceInstance = %d" % (servicename, self.device_instance))

    # Create the management objects, as specified in the ccgx dbus-api document
    self._dbusservice.add_path('/Mgmt/ProcessName', __file__)
    self._dbusservice.add_path('/Mgmt/ProcessVersion', 'Unkown version, and running on Python ' + platform.python_version())
    self._dbusservice.add_path('/Mgmt/Connection', ip)

    # Create the mandatory objects
    self._dbusservice.add_path('/DeviceInstance', self.device_instance)
    self._dbusservice.add_path('/ProductId', 16)
    self._dbusservice.add_path('/ProductName', productname + ' - ' + inv['isn'])
    self._dbusservice.add_path('/FirmwareVersion', inv['ssw'])
    self._dbusservice.add_path('/HardwareVersion', inv['msw'])
    self._dbusservice.add_path('/MaxPower', inv['rate'])
    self._dbusservice.add_path('/Serial', inv['isn'])
    self._dbusservice.add_path('/String', string)
    self._dbusservice.add_path('/Connected', 1)

    self._dbusservice.add_path('/CustomName', 'KACO %s MPPT %i' % (inv['isn'][-5:], string))


    _kwh = lambda p, v: (str(v) + 'kWh')
    _a = lambda p, v: (str(v) + 'A')
    _w = lambda p, v: (str(int(v)) + 'W')
    _v = lambda p, v: (str(v) + 'V')
    _c = lambda p, v: (str(v) + 'C')


    for path in paths:
      cb = None
      if path.endswith('Power'):
          cb = _w
      elif path.endswith('Current'):
          cb = _a
      elif path.endswith('Voltage'):
          cb = _v
      elif path.endswith('Forward'):
          cb = _kwh
      self._dbusservice.add_path(path, None, gettextcallback=cb)


    self._dbusservice['/Position'] = 0  # AC-In
    self._dbusservice['/ErrorCode'] = 0  # No Error
    # self._tempservice = self.add_temp_service(deviceinstance, dryrun)


    self._retries = 0

  def _set_up_device_instance(self, servicename, instance):
       settings_device_path = "/Settings/Devices/{}/ClassAndVrmInstance".format(servicename)
       requested_device_instance = "{}:{}".format('pvinverter', instance)
       r = self._settings.addSetting(settings_device_path, requested_device_instance, "", "")
       _s, _di = r.get_value().split(':') # Return the allocated ID provided from dbus SettingDevices
       return int(_di)

  def _handle_changed_setting(self, setting, oldvalue, newvalue):
      logging.info("Setting changed, setting: %s, old: %s, new: %s", setting, oldvalue, newvalue)
      return True

  def add_temp_service(self, instance, dryrun):

      ds = VeDbusService('com.victronenergy.temperature.twc3' + ('_dryrun' if dryrun else ''),
                         bus=dbusconnection())
      # Create the management objects, as specified in the ccgx dbus-api document
      ds.add_path('/Mgmt/ProcessName', __file__)
      ds.add_path('/Mgmt/ProcessVersion', 'Unkown version, and running on Python ' + platform.python_version())
      ds.add_path('/Mgmt/Connection', 'local')

      # Create the mandatory objects
      ds.add_path('/DeviceInstance', instance + (100 if dryrun else 0))
      ds.add_path('/ProductId', 0)
      ds.add_path('/ProductName', 'dbus-twc3')
      ds.add_path('/FirmwareVersion', 0)
      ds.add_path('/HardwareVersion', 0)
      ds.add_path('/Connected', 1)

      ds.add_path('/CustomName', self._name)
      ds.add_path('/TemperatureType', 2)  # 0=battery, 1=fridge, 2=generic
      ds.add_path('/Temperature', 0)
      ds.add_path('/Status', 0)  # 0=ok, 1=disconnected, 2=short circuit
      return ds

  def disconnect(self):
      self._dbusservice['/Connected'] = 0

  def connect(self):
      self._dbusservice['/Connected'] = 1

  def update(self, d):
    ds = self._dbusservice
    def _r(v, n=1):
        return round(v, n)

    if d['err'] != 0:
         ds['/StatusCode'] = 10 # Error
         ds['/ErrorCode'] = d['err']
    else:
         ds['/ErrorCode'] = 0

         if d['pac'] == 0:
            ds['/StatusCode'] = 8  # Standby
         else:
            ds['/StatusCode'] = 7  # Running

    energy_total = d['eto'] / 10

    for phase in range(3):
        ds['/Ac/L%d/Power' % (phase + 1)] = _r(d['pac']/3, 0) # Watt
        ds['/Ac/L%d/Current' % (phase + 1)] = _r(d['iac'][phase]/10) # 100mA
        ds['/Ac/L%d/Voltage' % (phase + 1)] = _r(d['vac'][phase]/10) # 0.1V
        # if energy_total > 0:
        #   ds['/Ac/L%d/Energy/Forward' % (phase + 1)] = _r(energy_total/3) # 0.1kWh

    ds['/Ac/Power'] = _r(d['pac'], 0)
    ds['/Ac/Frequency'] = d['fac']/100
    # etd would be daily
    # if energy_total > 0:
    #   ds['/Ac/Energy/Forward'] = _r(energy_total)

    ds['/Temperature'] = _r(d['tmp'] / 10)


    return d


def main():
  #logging.basicConfig(level=logging.INFO)

  root = logging.getLogger()
  root.setLevel(logging.INFO)

  handler = logging.StreamHandler(sys.stdout)
  handler.setLevel(logging.INFO)
  formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
  handler.setFormatter(formatter)
  root.addHandler(handler)

  log.info('Startup')

  parser = argparse.ArgumentParser()
  parser.add_argument('--ip', default='127.0.0.1', help='IP Address of Station')
  parser.add_argument('--service', default='com.victronenergy.pvinverter.kaco', help='Service Name, e.g. for testing')
  parser.add_argument('--instance', default=42, help='Instance on DBUS, will be incremented by 100 in dryrun mode')
  parser.add_argument('--dryrun', dest='dryrun', action='store_true')
  parser.add_argument('--name', default='Kaco', help='User visible name of the Inverter')
  args = parser.parse_args()
  if args.ip:
      log.info('User supplied IP: %s' % args.ip)

  try:
    thread.daemon = True # allow the program to quit
  except NameError:
    pass

  from dbus.mainloop.glib import DBusGMainLoop
  # Have a mainloop, so we can send/receive asynchronous calls to and from dbus
  DBusGMainLoop(set_as_default=True)

  instances = {}
  for ip in args.ip.split(','):
    try:
      instances[ip] = DbusKacoHttpService(
        servicename=args.service + ('_dryrun' if args.dryrun else ''),
        deviceinstance=int(args.instance) + (100 if args.dryrun else 0),
        ip=ip,
        name=args.name,
        dryrun=args.dryrun)
      log.info("Connected to Kaco on ip %s" % ip)
    except requests.exceptions.ConnectionError as e:
        print(e)
        log.info("Failed to connect to Kaco on ip %s" % ip)
        time.sleep(1)

  log.info('Connected to dbus, and switching over to gobject.MainLoop() (= event based)')
  mainloop = gobject.MainLoop()
  mainloop.run()

if __name__ == "__main__":
  main()
