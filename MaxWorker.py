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
        self.load_topology()
        self.__max_cube_connection = None

        self.cube_ip_adress = config['max_cube_ip_adress']
        self.topology_refresh_period = config['max_topology_refresh_interval']
        self.mqtt_update_period = config['max_mqtt_update_interval']
        self.cube_duty_cycle_reset_interval = config['max_cube_duty_cycle_reset_interval']
        self.enable_sanity_check = config['max_perform_sanity_check']


        self.topology_last_refresh = 0
        self.mqtt_last_refresh = 0
        self.cube_duty_cycle = 0
        self.cube_duty_cycle_reset = 0

    def update_timer_elapsed(self):
        if time.time() > (self.mqtt_last_refresh + self.mqtt_update_period):
            return True
        else:
            return False

    def load_topology(self):
        try:
            with open('topology.json') as json_data:
                d = json.load(json_data)
                self.topology = d
                self.logger.info("topology initial load suceeded")
        except Exception as e:
            self.logger.error("Topology initial load failed")

    def refresh_topology(self):
        time.sleep(0.01)
        self.logger.debug('Starting topology refresh')
        try:
            self.connect()
            cube = MaxCube(self.__max_cube_connection)
            #TODO report cube values to the broker
            # self.__messageQ.put(self.prepare_output('cube', 'free_mem_slots', cube.free_mem_slots))
            # self.__messageQ.put(self.prepare_output('cube', 'duty_cycle', cube.duty_cycle))
            for device in cube.devices:
                device_id = self.update_device(device)
                if device.type in (MAX_THERMOSTAT, MAX_THERMOSTAT_PLUS, MAX_WALL_THERMOSTAT) \
                        and self.enable_sanity_check \
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
        except Exception as e:
            self.logger.error(format(e))
        self.logger.debug('Finished topology refresh')
        if self.update_timer_elapsed():
            self.mqtt_last_refresh = time.time()
            self.dump_topology()
        return (True)

    def update_device(self, device):
        device_id = device.serial
        if not device_id in self.topology:
            self.topology[device_id] = {}

        self.topology[device_id]['rf_address'] = device.rf_address
        self.topology[device_id]['name'] = device.name
        self.topology[device_id]['room_id'] = device.room_id
        self.topology[device_id]['room_name'] = device.room_name
        self.topology[device_id]['type'] = device.device_type_name()
        self.topology[device_id]['serial'] = device.serial
        self.update_device_metric(device, 'link_ok')
        self.update_device_metric(device, 'battery_ok')

        # metrics available only for specific device types
        if device.type in (MAX_THERMOSTAT, MAX_THERMOSTAT_PLUS, MAX_WALL_THERMOSTAT):
            self.topology[device_id]['mode'] = device.device_mode_name()
            if device.actual_temperature:
                self.update_device_metric(device, 'actual_temperature')
            self.update_device_metric(device, 'target_temperature')
            self.update_device_metric(device, 'valve_position')

        # send data to MQTT
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
        return device_id

    def dump_topology(self):
        try:
            with open('topology.json', 'w') as outfile:
                json.dump(self.topology, outfile, ensure_ascii=False)
        except Exception as e:
            self.logger.error(format(e))

    def update_device_metric(self, device, param):
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
            try:
                self.__max_cube_connection = MaxCubeConnection(self.cube_ip_adress, 62910)
                self.logger.info('Connecting to Max!Cube')
            except Exception as e:
                self.logger.error('Problem opening connection')

    def close(self):
        if not self.__max_cube_connection is None:
            try:
                self.__max_cube_connection.disconnect()
            except:
                self.logger.error('Problem closing connection')
            self.__max_cube_connection = None
            self.logger.debug('Connection to Max!Cube closed')

    def set_temperature(self, cube, device_id, target_temperature):
        device = self.topology[device_id]
        self.desired_temperatures[device_id] = float(target_temperature)
        if float(device['target_temperature']) != float(target_temperature):
            rf_id = device['rf_address']
            try:
                self.logger.debug("Setting temperature for %s  (%s/%s) to:%s" %
                                  (device_id, device['room_name'], device['name'],
                                   target_temperature))
                cube.set_target_temperature(cube.device_by_rf(rf_id), float(target_temperature))
                self.logger.info("Command result:%s" % (cube.command_result))
                if cube.command_success:
                    self.update_cube_stats(cube)
                    self.__messageQ.put(self.prepare_output(
                        device_id, 'target_temperature', target_temperature))
            except Exception as ex:
                self.logger.error("Send error:%s" % (format(ex)))
        return

    def update_cube_stats(self, cube):
        self.__messageQ.put(self.prepare_output(
            'cube', 'free_mem_slots', cube.free_mem_slots))
        self.__messageQ.put(self.prepare_output(
            'cube', 'duty_cycle', cube.duty_cycle))

    def set_mode(self, cube,device_id, target_mode):

        modes={'AUTO':0, 'MANUAL':1, 'VACATION':2, 'BOOST':3}

        device = self.topology[device_id]
        if device['mode'] != target_mode:
            rf_id = device['rf_address']
            try:
                self.logger.debug("Setting mode for %s  (%s/%s) to:%s" %
                                  (device_id, device['room_name'], device['name'],
                                   target_mode))
                cube.set_mode(cube.device_by_rf(rf_id), modes[target_mode])
                self.logger.info("Command result:%s" % (cube.command_result))
                if cube.command_success:
                    self.__messageQ.put(self.prepare_output(
                        'cube', 'free_mem_slots', cube.free_mem_slots))
                    self.__messageQ.put(self.prepare_output(
                        'cube', 'duty_cycle', cube.duty_cycle))
                    self.__messageQ.put(self.prepare_output(
                        device_id, 'mode', target_mode))
            except Exception as ex:
                self.logger.error("Send error:%s" % (format(ex)))
        return

    def run(self):

        self.refresh_topology()
        self.topology_last_refresh = time.time()


        while True:
            time.sleep(0.01)
            # resetting internal duty cycle metric
            if time.time() > (self.cube_duty_cycle_reset + self.cube_duty_cycle_reset_interval):
                self.cube_duty_cycle = 0
                self.cube_duty_cycle_reset = time.time()
                self.__messageQ.put(self.prepare_output(
                    'cube', 'duty_cycle', self.cube_duty_cycle))

            # processing incoming data
            if not self.__commandQ.empty():
                try:
                    self.connect()
                    cube = MaxCube(self.__max_cube_connection)
                    while not self.__commandQ.empty():
                        task = self.__commandQ.get()
                        if task['method'] == 'command':
                            if task['param'] == 'target_temperature':
                                self.set_temperature(cube,task['deviceId'],task['payload'])
                            elif task['param'] == 'mode':
                                self.set_mode(cube,task['deviceId'],task['payload'])
                            self.logger.debug("Executing command:%s" % (task))
                except Exception as e:
                    self.logger.error(format(e))
            # refreshing topology
            if self.update_timer_elapsed():
                self.refresh_topology()
                self.topology_last_refresh = time.time()
            self.close()
