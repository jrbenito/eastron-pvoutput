#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import requests
import pymodbus.client.sync
import logging
import struct
from datetime import datetime
from pytz import timezone
from time import sleep, time
from configobj import ConfigObj, ConfigObjError
from validate import Validator


# Local time with timezone
def localnow():
    return datetime.now(tz=localnow.LocalTZ)


class PVOutputAPI(object):

    def __init__(self, API, system_id=None):
        self._API = API
        self._systemID = system_id
        self._wh_today_last = 0

    def add_status(self, payload, system_id=None):
        """Add live output data. Data should contain the parameters as described
        here: http://pvoutput.org/help.html#api-addstatus ."""
        sys_id = system_id if system_id is not None else self._systemID
        self.__call("https://pvoutput.org/service/r2/addstatus.jsp", payload, sys_id)

    def add_output(self, payload, system_id=None):
        """Add end of day output information. Data should be a dictionary with
        parameters as described here: http://pvoutput.org/help.html#api-addoutput ."""
        sys_id = system_id if system_id is not None else self._systemID
        self.__call("http://pvoutput.org/service/r2/addoutput.jsp", payload, sys_id)

    def __call(self, url, payload, system_id=None):
        # system_id might be set during object creation or passed
        # as parameter to this function. Will not proceed without it.
        sys_id = system_id if system_id is None else self._systemID
        if sys_id is None:
            print('Warnning: Missing system_id, doing nothing')
            return False

        headers = {
            'X-Pvoutput-Apikey': self._API,
            'X-Pvoutput-SystemId': system_id,
            'X-Rate-Limit': '1'
        }

        # Make tree attempts
        for i in range(3):
            try:
                r = requests.post(url, headers=headers, data=payload, timeout=10)
                reset = round(float(r.headers['X-Rate-Limit-Reset']) - time())
                if int(r.headers['X-Rate-Limit-Remaining']) < 10:
                    print("Only {} requests left, reset after {} seconds".format(
                        r.headers['X-Rate-Limit-Remaining'],
                        reset))
                if r.status_code == 403:
                    print("Forbidden: " + r.reason)
                    sleep(reset + 1)
                else:
                    r.raise_for_status()
                    break
            except requests.exceptions.HTTPError as errh:
                print(localnow().strftime('%Y-%m-%d %H:%M'), " Http Error:", errh)
            except requests.exceptions.ConnectionError as errc:
                print(localnow().strftime('%Y-%m-%d %H:%M'), "Error Connecting:", errc)
            except requests.exceptions.Timeout as errt:
                print(localnow().strftime('%Y-%m-%d %H:%M'), "Timeout Error:", errt)
            except requests.exceptions.RequestException as err:
                print(localnow().strftime('%Y-%m-%d %H:%M'), "OOps: Something Else", err)

            sleep(5)
        else:
            print(localnow().strftime('%Y-%m-%d %H:%M'),
                  "Failed to call PVOutput API after {} attempts.".format(i))

    def send_status(self, date, energy_gen=None, power_gen=None, energy_imp=None,
                    power_imp=None, temp=None, vdc=None, cumulative=False, vac=None,
                    temp_inv=None, energy_life=None, comments=None, power_vdc=None,
                    system_id=None):
        # format status payload
        payload = {
            'd': date.strftime('%Y%m%d'),
            't': date.strftime('%H:%M'),
        }

        # Only report total energy if it has changed since last upload
        # this trick avoids avg power to zero with inverter that reports
        # generation in 100 watts increments (Growatt and Canadian solar)
        if (energy_gen is not None):
            if (self._wh_today_last < energy_gen):
                payload['v1'] = int(energy_gen)
            self._wh_today_last = int(energy_gen)

        if power_gen is not None:
            payload['v2'] = float(power_gen)
        if energy_imp is not None:
            payload['v3'] = int(energy_imp)
        if power_imp is not None:
            payload['v4'] = float(power_imp)
        if temp is not None:
            payload['v5'] = float(temp)
        if vdc is not None:
            payload['v6'] = float(vdc)
        if cumulative is True:
            payload['c1'] = 1
        else:
            payload['c1'] = 0
        if vac is not None:
            payload['v8'] = float(vac)
        if temp_inv is not None:
            payload['v9'] = float(temp_inv)
        if energy_life is not None:
            payload['v10'] = int(energy_life)
        if comments is not None:
            payload['m1'] = str(comments)[:30]
        # calculate efficiency
        if ((power_vdc is not None) and (power_vdc > 0) and (power_gen is not None)):
            payload['v12'] = float(power_gen) / float(power_vdc)

        # Send status
        self.add_status(payload, system_id)


class ModBus(object):
    def __init__(self, port='/dev/ttyUSB0', baudrate=2400, parity='N', stopbits=1, timeout=0.125):
        self.client = pymodbus.client.sync.ModbusSerialClient(
            'rtu',
            port=port,
            baudrate=baudrate,
            parity=parity,
            stopbits=stopbits,
            timeout=timeout)
        self.client.connect()

    def read_register(self, register, unit=1):
        res = self.client.read_input_registers(register, 2, unit=unit)

        if type(res) != pymodbus.register_read_message.ReadInputRegistersResponse:
            logger.error('got type %s !!!', type(res))
            return None
        else:
            value = struct.unpack('>f', struct.pack('>HH', *res.registers))[0]
            return value

    def close(self):
        self.client.close()


class Eastron_SDM(object):
    # http://www.eastrongroup.com/data/uploads/Eastron_SDM230-Modbus_protocol_V1_2.pdf
    registers = {
            0: 'Voltage (V)',
            6: 'Current (A)',
            12: 'Active Power (W)',
            18: 'Apparent Power (VA)',
            24: 'Reactive Power (VAr)',
            30: u'Power Factor (cosθ)',
            36: 'Phase Angle (degrees)',
            70: 'Frequency (Hz)',
            72: 'Import Active Energy (kWh)',
            74: 'Export Active Energy (kWh)',
            76: 'Import Reactive Energy (kVARh)',
            78: 'Export Reactive Energy (kVARh)',
            84: 'Total system power demand (W)',
            86: 'Maximum total system power demand (W)',
            88: 'Current system positive power demand (W)',
            90: 'Maximum system positive power demand (W)',
            92: 'Current system reverse power demand (W)',
            94: 'Maximum system reverse power demand (W)',
            258: 'Current demand (A)',
            264: 'Maximum current demand (A)',
            342: 'Total Active Energy (kWh)',
            344: 'Total Reactive Energy (kVARh)',
            384: 'Current resettable total active energy (kWh)',
            386: 'Current resettable total reactive energy (kVARh)', }

    def __init__(self, modbus, address=1):
        self.modbus = modbus
        self.address = address

    def read_register(self, register):
        reg = self.modbus.read_register(register=register, unit=self.address)
        if reg is None:
            raise RuntimeError
        return reg

    # this is missname since energy and power are different things
    # keep this since this code was copied, later you deal with that
    def read_energy(self):
        values = {12: self.read_register(12)}  # Active Power (W)
        return values

    def read_all(self):
        values = {}
        for reg in self.registers:
            values[reg] = self.read_register(reg)
        return values


def main_loop():

    # start and stop monitoring (hour of the day)
    shStart = 5
    shStop = 21
    # Loop until end of universe
    while True:
        if shStart <= localnow().hour < shStop:

            # get readings from inverter, if success send  to pvoutput
            v1 = meter.read_register(74)
            v2 = meter.read_register(12)
            vac = meter.read_register(0)

            pvo.send_status(date=localnow(),
                            energy_gen=v1*1000,
                            power_gen=v2,
                            vac=vac,
                            cumulative=True,
                            system_id=config['pvoutput']['systemID'])

            # All inverters sent data so
            # sleep until next multiple of 5 minutes
            minutes = 5 - localnow().minute % 5
            sleep(minutes*60 - localnow().second)
        else:
            # it is too late or too early, let's sleep until next shift
            hour = localnow().hour
            minute = localnow().minute
            if 24 > hour >= shStop:
                # before midnight
                snooze = (((shStart - hour) + 24) * 60) - minute
            elif shStart > hour >= 0:
                # after midnight
                snooze = ((shStart - hour) * 60) - minute
            print(localnow().strftime('%Y-%m-%d %H:%M') + ' - Next shift starts in ' +
                  str(snooze) + ' minutes')
            sys.stdout.flush()
            snooze = snooze * 60  # seconds
            sleep(snooze)


if __name__ == '__main__':
    logger = logging.getLogger(__name__)

    # set objects
    try:
        config = ConfigObj("pvoutput.conf",
                           configspec="pvoutput-configspec.ini")
        validator = Validator()
        if not config.validate(validator):
            raise ConfigObjError
    except ConfigObjError:
        print('Could not read config or configspec file', ConfigObjError)
        sys.exit(1)

    # FIXME: is this the most pythonic code?
    localnow.LocalTZ = timezone(config['timezone'])

    # init clients
    try:
        modbus = ModBus(port=config['meter']['port'], baudrate=9600)
        meter = Eastron_SDM(modbus, address=int(config['meter']['addresses'][0], 16))
    except ValueError as e:
        print('Could not initialize inverter object: {}'.format(e))
        sys.exit(1)

    if ((config['pvoutput']['APIKEY'] is not None) and
       (config['pvoutput']['systemID'] is not None)):
        # multiple system id are not supported by pvoutput calss
        sys_id = None
        if len(config['pvoutput']['systemID']) == 1:
            sys_id = config['pvoutput']['systemID'][0]
        pvo = PVOutputAPI(config['pvoutput']['APIKEY'], sys_id)
    else:
        print('Need pvoutput APIKEY and systemID to work')
        sys.exit(1)

    try:
        main_loop()
    except KeyboardInterrupt:
        print >> sys.stderr, '\nExiting by user request.\n'
        sys.exit(0)
