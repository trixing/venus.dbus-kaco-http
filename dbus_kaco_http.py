#!/usr/bin/env python

"""
Created by Jan Dittmer <jdi@l4x.org> in 2021

Losely Based on DbusDummyService and RalfZim/venus.dbus-fronius-smartmeter
"""

from gi.repository import GLib as gobject
import argparse
import json
import logging
import sys
import os
import requests # for http GET
import time
import traceback

import dbus

sys.path.insert(1, os.path.join(os.path.dirname(__file__), '../venus.dbus-trixing-lib'))

import dbus_trixing_template as dbus_trixing

log = logging.getLogger("DbusKacoHttp")


class DbusKacoHttpService:

  def _getdev(self, device=None):
    url = self.url + '/getdev.cgi?device=' + (str(device) or '0')
    log.info("Connecting to %s " % url)
    r = requests.get(url, timeout=10)
    return r.json() 

  def __init__(self, ip, deviceinstance,
               dryrun=False):
    self._retries = 0
    ip = ip
    self.url = 'http://' + ip + ':8484'
    inverters = self._getdev(2)
    log.info('Inverter data %r' % repr(inverters))
    self.strings = {}
    self.temps = {}
    n = 0
    for inv in inverters['inv']:
        sn = inv['isn']
        devdata = self._getdevdata(sn)
        print(devdata)
        self.temps[sn] = DbusKacoTemperature(deviceinstance + 10, ip, inv)
        self.strings[sn] = []
        if len(devdata['vpv']) != 2:
            raise Exception("Incorrect amount of MPPT trackers detected")

        for i in range(len(devdata['vpv'])):
            self.strings[sn].append(
                    DbusKacoString(deviceinstance + n,
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

            for sn in self.temps:
                self.temps[sn].connect()
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
            for sn in self.temps:
                self.temps[sn].disconnect()
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
    #        print(data)
            string.update(data)

        self.temps[sn].update(devdata['tmp']/10)


  def _getdevdata(self, sn):
    url = self.url + '/getdevdata.cgi?device=2&sn=' + sn
#    print(url)
    r = requests.get(url, timeout=2)
    return r.json() 


class DbusKacoTemperature(dbus_trixing.DbusTrixingTemperature):

  def __init__(self, deviceinstance, ip, inv):
    device_name = 'kaco_http_%s_temp' % inv['isn'].replace('.', '_')
    display_name = 'KACO %s Temperature' % (inv['isn'][-5:])
    super().__init__(devicename=device_name,
                     displayname=display_name,
                     deviceinstance=deviceinstance,
                     serial=inv['isn'],
                     hardwareversion=inv['ssw'].strip(),
                     firmwareversion=inv['msw'].strip(),
                     connection=ip)

  def update(self, temperature):
    self.set_temperature(temperature)


class DbusKacoString(dbus_trixing.DbusTrixingPvInverter):

  def __init__(self, deviceinstance, ip, string, inv):
    device_name = 'kaco_http_%s_%i' % (inv['isn'].replace('.', '_'), string)
    display_name = 'KACO %s MPPT %i' % (inv['isn'][-5:], string)
    super().__init__(devicename=device_name,
                     displayname=display_name,
                     deviceinstance=deviceinstance,
                     serial=inv['isn'],
                     hardwareversion=inv['ssw'].strip(),
                     firmwareversion=inv['msw'].strip(),
                     connection=ip)

    self['/MaxPower'] = inv['rate']
    self.add_path('/String', string)


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
        if energy_total > 0:
          ds['/Ac/L%d/Energy/Forward' % (phase + 1)] = _r(energy_total/3) # 0.1kWh

    ds['/Ac/Power'] = _r(d['pac'], 0)
    ds['/Ac/Frequency'] = d['fac']/100
    # etd would be daily
    if energy_total > 0:
      ds['/Ac/Energy/Forward'] = _r(energy_total)

    return d


def main():
  dbus_trixing.prepare()
  parser = argparse.ArgumentParser()
  parser.add_argument('--ip', default='127.0.0.1', help='IP Address of Inverter')
  parser.add_argument('--instance', default=42, help='Requested Instance on DBUS')
  args = parser.parse_args()
  if args.ip:
      log.info('User supplied IP: %s' % args.ip)
  instances = {}
  for ip in args.ip.split(','):
    try:
      instances[ip] = DbusKacoHttpService(
        deviceinstance=int(args.instance),
        ip=ip)
      log.info("Connected to Kaco on ip %s" % ip)
    except requests.exceptions.ConnectionError as e:
        print(e)
        log.info("Failed to connect to Kaco on ip %s" % ip)
        time.sleep(1)

  dbus_trixing.run()

if __name__ == "__main__":
  main()
