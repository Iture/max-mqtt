MAX_CUBE = 0
MAX_THERMOSTAT = 1
MAX_THERMOSTAT_PLUS = 2
MAX_WALL_THERMOSTAT = 3
MAX_WINDOW_SHUTTER = 4
MAX_PUSH_BUTTON = 5

MAX_DEVICE_MODE_AUTOMATIC = 0
MAX_DEVICE_MODE_MANUAL = 1
MAX_DEVICE_MODE_VACATION = 2
MAX_DEVICE_MODE_BOOST = 3


class MaxDevice(object):
    def __init__(self):
        self.type = None
        self.rf_address = None
        self.room_id = None
        self.name = None
        self.battery_ok = None
        self.link_ok = None
        self.room_name = None

    def device_type_name(self):
        device_type_names = (
            'Cube', 'Thermostat', 'Thermostat Plus', 'Wall Thermostat', 'Shutter contact', 'Eco button'
        )
        if self.type < len(device_type_names):
            return device_type_names[self.type]
        return None
