#!/usr/bin/env python

# Python 2/3 compatibility imports
from __future__ import print_function
from six.moves import range

# standard library imports
import json
import time

# import gpiod
import sys
import signal

import threading    # for pin release (cleanup)
import atexit       # for pin release (cleanup)

# local module imports
from blinker import signal as blinker_signal
import gv  # Get access to SIP's settings, gv = global variables
from sip import template_render
from urls import urls  # Get access to SIP's URLs
import web
from webpages import ProtectedPage

from gpio_client import GPIOClient
from gpio_types import Direction

CHIP = "/dev/gpiochip0"

DATAFILE = u"./data/40pin.json"
# Load the Raspberry Pi GPIO (General Purpose Input Output) library
try:
    if gv.use_pigpio:
        import pigpio
        pi = pigpio.pi()
        print("Using pigpio")
    else:
        import RPi.GPIO as GPIO
        print("Using legacy RPi.GPIO")
        pi = 0
except IOError:
    pass

# Add a new url to open the data entry page.
# fmt: off
urls.extend(
    [
        u"/40pin", u"plugins.40pin.settings",
        u"/40pinu", u"plugins.40pin.update",
    ]
)
# fmt: on

# Add this plugin to the home page plugins menu
gv.plugin_menu.append([_(u"40pin"), u"/40pin"])

client_id="sip.40pin_plugin"
client = GPIOClient(client_id)

use_gpiod = True
params = {}


# GPIO server manipulates all pins. SIP should not touch them
gv.use_gpio_pins = False  # Signal SIP to not use GPIO pins
gv.use_shift_register = False # Signal SIP to not use GPIO pins for shift register either

rpi_pins = [
    [1, False, "3.3V"],
    [2, False, "5V"],
    [3, True, "GPIO2"],
    [4, False, "5V"],
    [5, True, "GPIO3"],
    [6, False, "GND"],
    [7, True, "GPIO4"],
    [8, True, "GPIO14"],
    [9, False, "GND"],
    [10, True, "GPIO15"],
    [11, True, "GPIO17"],
    [12, True, "GPIO18"],
    [13, True, "GPIO27"],
    [14, False, "GND"],
    [15, True, "GPIO22"],
    [16, True, "GPIO23"],
    [17, False, "3.3V"],
    [18, True, "GPIO24"],
    [19, True, "GPIO10"],
    [20, False, "GND"],
    [21, True, "GPIO9"],
    [22, True, "GPIO25"],
    [23, True, "GPIO11"],
    [24, True, "GPIO8"],
    [25, False, "GND"],
    [26, True, "GPIO7"],
    [27, True, "GPIO0"],
    [28, True, "GPIO1"],
    [29, True, "GPIO5"],
    [30, False, "GND"],
    [31, True, "GPIO6"],
    [32, True, "GPIO12"],
    [33, True, "GPIO13"],
    [34, False, "GND"],
    [35, True, "GPIO19"],
    [36, True, "GPIO16"],
    [37, True, "GPIO26"],
    [38, True, "GPIO20"],
    [39, False, "GND"],
    [40, True, "GPIO21"]
]

# for debugging only
def convert_sets(obj):
    if isinstance(obj, set):
        return list(obj)
    elif isinstance(obj, dict):
        return {k: convert_sets(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_sets(i) for i in obj]
    else:
        return obj
    
def assign_missing_orders(items):
    n = len(items)

    # Collect already assigned orders
    assigned = {item['order'] for item in items if item['order'] is not None}
    print(f"assigned = {json.dumps(convert_sets(assigned), indent=2)}")

    # Determine available orders
    available = sorted(set(range(1, n + 1)) - assigned)
    print(f"available = {json.dumps(convert_sets(available), indent=2)}")

    # Assign missing orders
    i = 0
    for item in items:
        print(f"Processing pin {item['pin']}")
        match = next((rp for rp in rpi_pins if rp[0] == item['pin'] and isinstance(rp[2], str) and rp[2].startswith("GPIO")), None)
        if match and item['order'] is None:
            print(f"pin {item['pin']} has order = None")
            item['order'] = available[i]
            print(f"now pin {item['pin']} has order {item['order']}")
            i += 1

    return items

# Read in the parameters for this plugin from it's JSON file
initial_load_params_complete = threading.Event()
def load_params():
    global params
    try:
        with open(DATAFILE, u"r") as f:  # Read the settings from file
            params = json.load(f)
            params["pins"] = assign_missing_orders(params["pins"])
            params["pins"] = sorted(
                params.get("pins", []),
                key=lambda pin: (
                    pin["order"] is None,  # True for None → sorts last
                    pin["order"] if pin["order"] is not None else float('inf')
                )
            )
            print(f'Params pins after loading: {json.dumps(params.get("pins", []), indent=2)}')

    except IOError:  #  If file does not exist create file with defaults.
        params = {u"active": u"low"}
        with open(DATAFILE, u"w") as f:
            json.dump(params, f, indent=4, sort_keys=True)
    print(f"About to finish loading params")
    initial_load_params_complete.set()
    print(f"Finished loading params")
    return params

load_params()

#### define the GPIO pins that will be used ####
try:
    if gv.platform == u"pi":  # If this will run on Raspberry Pi:
        print(f"gv.use_pigpio: {gv.use_pigpio}")
        if not gv.use_pigpio:
            GPIO.setmode(
                GPIO.BOARD
            )  # IO channels are identified by header connector pin numbers. Pin numbers are
        # relay_pins = [18, 22, 24, 26, 32, 36, 38, 40, 19, 21, 23, 29, 31, 33, 35, 37]
        relay_pins = [pin[0] for pin in rpi_pins if pin[2].startswith("GPIO")]

        print(f"gv_pin_map={json.dumps(gv.pin_map)}")
        for i in range(len(relay_pins)):
            try:
                # print(f"Before relay_pins[{i}]={relay_pins[i]}")
                relay_pins[i] = gv.pin_map[relay_pins[i]]
                # print(f"After relay_pins[{i}]={relay_pins[i]}")
            except:
                relay_pins[i] = 0
        pin_rain_sense = gv.pin_map[8]
        pin_relay = gv.pin_map[10]
    else:
        print(u"pin plugin only supported on pi.")
except:
    print(u"pin: GPIO pins not set")
    pass


def cleanup(signum, frame):
    print("Caught CTRL-C, will release all GPIO lines...")
    cleanup_thread = threading.Thread(target=release_all_lines)
    cleanup_thread.start()
    cleanup_thread.join(timeout=5)  # Wait for cleanup to finish before exiting

atexit.register(cleanup, None, None)   # instead of SIGINT due to eventlet and flask

def release_all_lines():
    print("Releasing GPIO lines...")
    for pin_data in params.get("pins", []):
        pin_num = pin_data.get("pin")
        print(f"Releasing pin {pin_num} GPIO{gv.pin_map[pin_num]}")

        # if not pin_data.get("enabled"):
        #     print(f"Pin {pin_num} GPIO{gv.pin_map[pin_num]} is not enabled, no need to release")
        #     continue
        # else:
        try:
            resp = client.release_pin(gv.pin_map[pin_num])
            print(f"Released pin {pin_num}: {resp}")
        except Exception as e:
            print(f"Error releasing pin {pin_num}: {e}")
    print("Finsihed releasing GPIO lines")
    

#### setup GPIO pins as output and either high or low ####
initial_init_pins_complete = threading.Event()
def init_pins():
    global pi
    
    print(f"Init pins starting...")        

    try:
        print(f"Will release all pins")
        release_all_lines()
        print(f"All pins released and now starting requests")
        for i in relay_pins:
            # print(f"Initialising pin GPIO{i}, enabled: {get_enabled_status(params,i)}")

            if get_enabled_status(params,i):
                resp = client.request_pin(i, Direction.OUT)    # sip only writes, never reads            
                if resp.get("success"):
                    print(f"Pin {i} successfully requested.")
                else:
                    m = f"Failed to request pin {i}: {resp.get('message')}"
                    print(m)
                    raise Exception(m)
                time.sleep(0.1)
        print(f"About to finish initialising pins")        
        initial_init_pins_complete.set()         
        print(f"Finished initialising pins")        

        # for i in range(params[u"relays"]):
        #     if gv.use_pigpio:
        #         pi.set_mode(relay_pins[i], pigpio.OUTPUT)
        #     else:
        #         GPIO.setup(relay_pins[i], GPIO.OUT)
        #     if params[u"active"] == u"low":
        #         if gv.use_pigpio:
        #             pi.write(relay_pins[i], 1)
        #         else:
        #             GPIO.output(relay_pins[i], GPIO.HIGH)
        #     else:
        #         if gv.use_pigpio:
        #             pi.write(relay_pins[i], 0)
        #         else:
        #             GPIO.output(relay_pins[i], GPIO.LOW)
        #     time.sleep(0.1)
    except Exception as e:
        raise e
        pass

#obsolete
def is_line_free(chip_path, line_num):
    try:
        chip = gpiod.Chip(chip_path)
        line = chip.get_line(line_num)
        line.request(consumer="gpio-checker", type=gpiod.LINE_REQ_DIR_IN)
        line.release()
        return True
    except OSError as e:
        if e.errno == 16:  # Device or resource busy
            return False
        raise

def get_enabled_status(params, gpio_pin_number):
    for pin in params.get("pins", []):
        if gv.pin_map[pin.get("pin")] == gpio_pin_number:
            return pin.get("enabled")
    return None

def set_pin(gpio_pin, value):
    print(f"Setting GPIO{gpio_pin} to '{value}'")
    try:
        resp = client.write_pin(gpio_pin, value)
        if resp.get("success"):
            print(f"GPIO{gpio_pin} successfully updated.")
        else:
            m = f"Failed to update GPIO{gpio_pin}: {resp.get('message')}"
            print(m)
            raise Exception(m)
    except Exception as e:
                print(f"Error updating GPIO{gpio_pin}: {e}")



#### change outputs when blinker signal received ####
def on_zone_change(arg):  #  arg is just a necessary placeholder.
    """ Switch relays when core program signals a change in zone state."""
    
    global pi
    
    print(f"Waiting for load params")
    initial_load_params_complete.wait()
    print(f"Load params done at least once")

    print(f"Waiting for init pins")
    initial_init_pins_complete.wait()
    print(f"Init pins done at least once")

    with gv.output_srvals_lock:
        # for i in range(params[u"relays"]):
        # for pin_number in [p["pin"] for p in params["pins"]]:
        print(f"Will iterate over params['pins']:")
        print(f"{json.dumps(params['pins'], indent=2)}")
        for s in range(len(gv.output_srvals)):  # iterate as many times as there are stations
            pin = next((p for p in params.get("pins", []) if p.get("order") == s+1), None)
            print(f"Pin with order {s+1} is: {json.dumps(pin)}")            
            if not pin:
                # raise Exception(f"There is no pin with order {s}")
                continue
            #find the position in relays pin where this gpio is stored
            #i do it this way to maintain compatibility with existing code
            #that works with gpiod and GPIO
            i = next((p for p, val in enumerate(relay_pins) if val == gv.pin_map[pin.get("pin")]), None) 

            print(f"Setting GPIO{relay_pins[i]}")
            try:
                # skip disabled pins
                if not get_enabled_status(params, relay_pins[i]):
                    print(f"GPIO{relay_pins[i]} is NOT enabled")
                    continue
                print(f"GPIO{relay_pins[i]} IS enabled")
                # if station is set to on and pin is enabled
                if gv.output_srvals[s]:
                    if (
                        params[u"active"] == u"low"
                    ):  # if the relay type is active low, set the output low
                        if use_gpiod:
                            set_pin(relay_pins[i], 0)
                        elif gv.use_pigpio:
                            pi.write(relay_pins[i], 0)
                        else:
                            GPIO.output(relay_pins[i], GPIO.LOW)
                    else:  # otherwise set it high
                        if use_gpiod:
                            set_pin(relay_pins[i], 1)
                        elif gv.use_pigpio:
                            pi.write(relay_pins[i], 1)
                        else:
                            GPIO.output(relay_pins[i], GPIO.HIGH)
                else:  # station is set to off
                    if (
                        params[u"active"] == u"low"
                    ):  # if the relay type is active low, set the output high
                        if use_gpiod:
                            set_pin(relay_pins[i], 1)
                        elif gv.use_pigpio:
                            pi.write(relay_pins[i], 1)
                        else:
                            GPIO.output(relay_pins[i], GPIO.HIGH)
                    else:  # otherwise set it low
                        if use_gpiod:
                            set_pin(relay_pins[i], 0)
                        elif gv.use_pigpio:
                            pi.write(relay_pins[i], 0)
                        else:
                            GPIO.output(relay_pins[i], GPIO.LOW)
            except Exception as e:
                print(f"Problem switching relays for GPIO{relay_pins[i]}: {e}")
                raise e
                pass


init_pins()

zones = blinker_signal(u"zone_change")
zones.connect(on_zone_change)

# signal.signal(signal.SIGINT, cleanup)

################################################################################
# Web pages:                                                                   #
################################################################################


class settings(ProtectedPage):
    """Load an html page for entering relay board adjustments"""

    def GET(self):
        # with open(DATAFILE, u"r") as f:  # Read the settings from file
        #     params = json.load(f)
        initial_load_params_complete.wait()
        initial_init_pins_complete.wait()

        return getattr(template_render, "40pin")(params, json.dumps(rpi_pins))
        # raise web.seeother(u"/40pin", json.dumps(params, indent=2), json.dumps(rpi_pins, indent=2))


class update(ProtectedPage):
    """Save user input to 40pin.json file"""

    def POST(self):
        form_data = web.input()
        print(f"Saving 40pin data: {json.dumps(form_data, indent=2)}")
        
        changed = False
        reinit = False
        # if params[u"enabled"] != (form_data[u"enabled"]):
        #     params[u"enabled"] = form_data[u"enabled"]
        #     changed = True

        # Validate for duplicate order values
        order_values = []
        for i in range(1, 41):
            order_val = form_data.get(f"order_{i}")
            if order_val:
                order_values.append(order_val)

        duplicates = [val for val in set(order_values) if order_values.count(val) > 1]
        if duplicates:
            return f"Error: Duplicate order values detected → {', '.join(duplicates)}"

        # Build per-pin data
        pins = []
        for i in range(1, 41):
            pin_data = {
                "pin": i,
                "notes": form_data.get(f"notes_{i}", ""),
                "enabled": form_data.get(f"enable_{i}", "off") == "on",
                "order": int(form_data.get(f"order_{i}")) if form_data.get(f"order_{i}") and form_data.get(f"order_{i}").strip() else None
            }
            pins.append(pin_data)
        print(f"New pins {json.dumps(pins, indent=2)}")

        pins = assign_missing_orders(pins) # this is here only as safeguard, it should never change anything
        # Compare pin-by-pin
        if len(params.get("pins", [])) != len(pins):
            params["pins"] = pins
            changed = True
            reinit = True
        else:
            for original, submitted in zip(params.get("pins", []), pins):   #works only if both non-empty
                print(f"Comparing original {json.dumps(original)} with submitted {json.dumps(submitted)}")
                if original.get("pin") == submitted.get("pin"):
                    if( self.normalize_order(original.get("order")) != self.normalize_order(submitted.get("order")) 
                       or original.get("enabled") != submitted.get("enabled") 
                    ):
                        changed = True
                        reinit = True
                        break
                    if original.get("notes") != submitted.get("notes") :
                        changed = True

        if changed or reinit:
            params["pins"] = pins
                

        if params[u"active"] != str(
            form_data[u"active"]
        ):  # since changing active could turn all the relays on, disable all the relay channels
            params[u"active"] = str(form_data[u"active"])            
            for pin in params.get("pins", []):
                pin["enabled"] = False
            changed = True
            reinit = True

        print(f"Changed: {changed}, reinit: {reinit}")
        if changed:
            if reinit:
               init_pins()
            with open(DATAFILE, u"w") as f:  # write the settings to file
                json.dump(params, f, indent=4, sort_keys=True)

        raise web.seeother(u"/40pin")


    def normalize_order(self, value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
