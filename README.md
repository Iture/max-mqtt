# max-mqtt

Project delivers MQTT gateway for [EQ-3 Max!](https://max.eq-3.de/login.jsp) heating control system.

##Supported Max! components:
- LAN Gateway
- wall thermostat
- radiator thermostat


##Current features:
- reporting parameters from components:
    - mode
    - target temperature
    - actual temperature
    - valve position (for thermostats)
    - battery and link status
    - duty cycle and free memory slots for cube
- setting target temperature
- maintaning set temperature (sometimes system behaves strangely, and set temperatures on its own, application can reset it to default values)


## Configuration

Whole configuration is located in config.json file.

```json
{
  "mqtt_host": "your.mqtt.broker.host",
  "mqtt_port": 1883,
  "mqtt_prefix": "/data/MaxCube",
  "mqtt_message_timeout": 60,
  "max_cube_ip_adress": "172.22.0.1",
  "max_topology_refresh_interval": 60,
  "max_mqtt_update_intervals": 300,
  "max_cube_duty_cycle_reset_interval": 3600,
  "max_perform_sanity_check" : true
}
```

config param | meaning
-------------|---------
| mqtt_host | MQTT broker host |
| mqtt_port | MQTT broker port|
| mqtt_prefix | prefix for publish and subscribe topic|
| mqtt_message_timeout | timeout for dropping obsolete messages from send queue |
| max_cube_ip | LAN gateway IP address |
| max_topology_refresh_interval | Interval of refreshing data from Max! system |
| max_mqtt_update_interval | Interval of refreshing parameters (even if they not change) in MQTT. In the same time topology of your Max! network is dumped to file topology.json and sanity check is performed.  |
| max_cube_duty_cycle_reset_interval | Time after duty_cycle counter is reset (since last operation)|
| max_perform_sanity_check | Enabling sanity check |

##Output data
Application pushes informations to MQTT broker in following format:
[mqtt_prefix]/[device_serial_number]/[parameter]

Every change should be published to topic:
[mqtt_prefix]/[device_serial_number]/[parameter]/set (currently is supported only *target_temperature*)

###Sample data




##References
- MaxCube library (little modified) https://github.com/goodfield/python-maxcube-api
- MaxCube protocol research https://github.com/Bouni/max-cube-protocol
- Max! binding for OpenHab2 https://github.com/openhab/openhab2-addons/tree/master/addons/binding/org.openhab.binding.max/src/main/java/org/openhab/binding/max
