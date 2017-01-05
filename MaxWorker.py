import json
import logging
import multiprocessing
import time

from maxcube.connection import MaxCubeConnection
from maxcube.cube import MaxCube
from maxcube.device import \
    MAX_THERMOSTAT, \
    MAX_THERMOSTAT_PLUS, \
    MAX_WALL_THERMOSTAT


class MaxWorker(multiprocessing.Process):
    def __init__(self, messageQ, commandQ, config):
        self.logger = logging.getLogger('Max!-MQTT.MaxWorker')

        self.logger.info("Starting...")
        multiprocessing.Process.__init__(self)

        self.__messageQ = messageQ
        self.__commandQ = commandQ

        self.topology = {}
        self.desired_temperatures = {}
        try:
            with open('topology.json') as json_data:
                d = json.load(json_data)
                self.topology = d
                self.logger.info("topology initial load suceeded")
        except Exception as e:
            self.logger.error("Topology initial load failed")
        self.__max_cube_connection = None

        self.cube_ip_adress = config['max_cube_ip_adress']
        self.topology_refresh_period = config['max_topology_refresh_period']
        self.mqtt_update_period = config['max_mqtt_update_period']
        self.cube_duty_cycle_reset_interval = config['max_cube_duty_cycle_reset_interval']
        self.enable_sanity_check = config['max_perform_sanity_check']

        self.topology_last_refresh = 0
        self.mqtt_last_refresh = 0
        self.cube_duty_cycle = 0
        self.cube_duty_cycle_reset = 0

    def refresh_topology(self):
        self.logger.debug('Starting topology refresh')

        if time.time() > (self.mqtt_last_refresh + self.mqtt_update_period):
            update_mqtt = True
        else:
            update_mqtt = False
        try:
            self.connect()
            cube = MaxCube(self.__max_cube_connection)
            #TODO report cube values to the broker
            # self.__messageQ.put(self.prepare_output('cube', 'free_mem_slots', cube.free_mem_slots))
            # self.__messageQ.put(self.prepare_output('cube', 'duty_cycle', cube.duty_cycle))
            for device in cube.devices:
                device_id = device.serial
                if not device_id in self.topology:
                    self.topology[device_id] = {}
                self.topology[device_id]['rf_address'] = device.rf_address
                self.topology[device_id]['name'] = device.name
                self.topology[device_id]['room_id'] = device.room_id
                self.topology[device_id]['room_name'] = device.room_name

                self.topology[device_id]['type'] = device.device_type_name()
                self.topology[device_id]['serial'] = device.serial
                self.update_device(device, 'link_ok')
                self.update_device(device, 'battery_ok')

                if device.type in (MAX_THERMOSTAT, MAX_THERMOSTAT_PLUS, MAX_WALL_THERMOSTAT):
                    self.topology[device_id]['mode'] = device.device_mode_name()
                    if device.actual_temperature:
                        self.update_device(device, 'actual_temperature')
                    self.update_device(device, 'target_temperature')
                    self.update_device(device, 'valve_position')

                    if update_mqtt:
                        # TODO put restriction on duty_cycle (if more than threshold, do not perform sanity check
                        if self.enable_sanity_check \
                                and (device_id in self.desired_temperatures) \
                                and (self.desired_temperatures[device_id] != device.target_temperature):
                            try:
                                self.logger.info("Correcting temperature for device :%s (%s/%s) from:%s to:%s" % (
                                    device_id, device.room_name, device.name, device.target_temperature,
                                    self.desired_temperatures[device_id]))
                                cube.set_target_temperature(device, self.desired_temperatures[device_id])
                                self.logger.info("Command result:%s" % cube.command_result)
                                if cube.command_success:
                                    self.__messageQ.put(self.prepare_output(
                                        device_id, 'target_temperature',
                                        self.topology[device_id]['target_temperature']))
                                    self.__messageQ.put(self.prepare_output(
                                        'cube', 'free_mem_slots', cube.free_mem_slots))
                                    self.__messageQ.put(self.prepare_output(''
                                                                            'cube', 'duty_cycle', cube.duty_cycle))
                                    self.cube_duty_cycle = cube.duty_cycle
                                    self.cube_duty_cycle_reset = time.time()

                            except Exception as e:
                                self.logger.error("Set error:%s" % (format(e)))

                        self.logger.debug("Refreshing data in MQTT for device :%s (%s/%s)" %
                                          (device_id, device.room_name, device.name))
                        self.__messageQ.put(self.prepare_output(
                            device_id, 'actual_temperature', self.topology[device_id].get('actual_temperature', None)))
                        self.__messageQ.put(self.prepare_output(
                            device_id, 'target_temperature', self.topology[device_id]['target_temperature']))
                        self.__messageQ.put(self.prepare_output(
                            device_id, 'link_ok', self.topology[device_id]['link_ok']))
                        self.__messageQ.put(self.prepare_output(
                            device_id, 'battery_ok', self.topology[device_id]['battery_ok']))
                        self.__messageQ.put(self.prepare_output(
                            device_id, 'valve_position', self.topology[device_id]['valve_position']))
                        self.__messageQ.put(self.prepare_output(
                            device_id, 'mode', self.topology[device_id]['mode']))

        except Exception as e:
            self.logger.error(format(e))
        self.logger.debug('Finished topology refresh')
        if update_mqtt:
            self.mqtt_last_refresh = time.time()
            try:
                with open('topology.json', 'w') as outfile:
                    json.dump(self.topology, outfile, ensure_ascii=False)
            except Exception as e:
                self.logger.error(format(e))
        return (True)

    def update_device(self, device, param):
        device_id = device.serial
        try:
            if self.topology[device_id].get(param, None) != device.__dict__[param]:
                self.topology[device_id][param] = device.__dict__[param]
                self.__messageQ.put(self.prepare_output(device_id, param,
                                                        self.topology[device_id].get(param, None)))
        except Exception as e:
            self.logger.error("problem while udating param %s in device %s" % (param, device_id))

    def prepare_output(self, device_id, param_name, param_value):
        out = {
            'method': 'publish',
            'deviceId': device_id,
            'param': param_name,
            'payload': param_value,
            'qos': 1,
            'timestamp': time.time()
        }
        return out

    def connect(self):
        if self.__max_cube_connection is None:
            self.__max_cube_connection = MaxCubeConnection(self.cube_ip_adress, 62910)
            self.logger.info('Connecting to Max!Cube')

    def close(self):
        if not self.__max_cube_connection is None:
            self.__max_cube_connection.disconnect()
            self.__max_cube_connection = None
            self.logger.debug('Connection to Max!Cube closed')

    def run(self):

        self.refresh_topology()
        self.topology_last_refresh = time.time()

        while True:
            if time.time() > (self.cube_duty_cycle_reset + self.cube_duty_cycle_reset_interval):
                self.cube_duty_cycle = 0
                self.cube_duty_cycle_reset = time.time()

            if not self.__commandQ.empty():
                try:
                    self.connect()
                    cube = MaxCube(self.__max_cube_connection)
                    while not self.__commandQ.empty():
                        task = self.__commandQ.get()
                        if task['method'] == 'command':
                            if task['param'] == 'target_temperature':
                                device = self.topology[task['deviceId']]
                                self.desired_temperatures[task['deviceId']] = float(task['payload'])
                                if float(device['target_temperature']) != float(task['payload']):
                                    rf_id = device['rf_address']
                                    try:
                                        self.logger.debug("Setting temperature for %s  (%s/%s) to:%s" %
                                                          (task['deviceId'], device['room_name'], device['name'],
                                                           task["payload"]))
                                        cube.set_target_temperature(cube.device_by_rf(rf_id), float(task['payload']))
                                        self.logger.info("Command result:%s" % (cube.command_result))
                                        if cube.command_success:
                                            self.__messageQ.put(self.prepare_output(
                                                'cube', 'free_mem_slots', cube.free_mem_slots))
                                            self.__messageQ.put(self.prepare_output(
                                                'cube', 'duty_cycle', cube.duty_cycle))
                                            self.__messageQ.put(self.prepare_output(
                                                task['deviceId'], 'target_temperature', task['payload']))
                                    except Exception as ex:
                                        self.logger.error("Send error:%s" % (format(ex)))
                            self.logger.debug("Executing command:" % (task))
                except Exception as e:
                    self.logger.error(format(e))

            if time.time() > (self.topology_last_refresh + self.topology_refresh_period):
                self.refresh_topology()
                self.topology_last_refresh = time.time()
            self.close()
