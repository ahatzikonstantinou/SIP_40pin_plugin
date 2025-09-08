#!/usr/bin/env python

# Python 2/3 compatibility imports
from __future__ import print_function
from six.moves import range

# standard library imports
import json
import time

import gpiod
import sys
import signal

# local module imports
from blinker import signal as blinker_signal
import gv  # Get access to SIP's settings, gv = global variables
from sip import template_render
from urls import urls  # Get access to SIP's URLs
import web
from webpages import ProtectedPage

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

use_gpiod = True
params = {}
line_requests = {}

# Read in the parameters for this plugin from it's JSON file
def load_params():
    global params
    try:
        with open(DATAFILE, u"r") as f:  # Read the settings from file
            params = json.load(f)
            params["pins"] = sorted(
                params.get("pins", []),
                key=lambda pin: (pin["order"] is None, pin["order"])
            )
    except IOError:  #  If file does not exist create file with defaults.
        params = {u"active": u"low"}
        with open(DATAFILE, u"w") as f:
            json.dump(params, f, indent=4, sort_keys=True)
    return params


load_params()

if params[u"enabled"] == u"on":
    gv.use_gpio_pins = False  # Signal SIP to not use GPIO pins

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
                print(f"Before relay_pins[{i}]={relay_pins[i]}")
                relay_pins[i] = gv.pin_map[relay_pins[i]]
                print(f"After relay_pins[{i}]={relay_pins[i]}")
            except:
                relay_pins[i] = 0
        pin_rain_sense = gv.pin_map[8]
        pin_relay = gv.pin_map[10]
    else:
        print(u"pin plugin only supported on pi.")
except:
    print(u"pin: GPIO pins not set")
    pass


#### setup GPIO pins as output and either high or low ####
def init_pins():
    global pi
    
    try:
        release_all_lines()
        for i in relay_pins:
            print(f"Initialising pin GPIO{i}, free line:{(CHIP, i)}, enabled: {get_enabled_status(params,i)}")
            if is_line_free(CHIP, i) and get_enabled_status(params,i):
                chip = gpiod.Chip(CHIP)
                line = chip.get_line(i)
                line.request(consumer="40pin-plugin", type=gpiod.LINE_REQ_DIR_OUT)
                line_requests[i] = line                
            time.sleep(0.1)
        
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
    except:
        pass


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
    if gpio_pin in line_requests:
        line_requests[gpio_pin].set_value(value)
    else:
        raise Exception(f"GPIO{gpio_pin} not available in line_requests.")


#### change outputs when blinker signal received ####
def on_zone_change(arg):  #  arg is just a necessary placeholder.
    """ Switch relays when core program signals a change in zone state."""

    global pi

    with gv.output_srvals_lock:
        # for i in range(params[u"relays"]):
        for pin_number in [p["pin"] for p in params["pins"]]:
            i = gv.pin_map[pin_number]
            if i == 0:
                continue
            print(f"Setting pin {pin_number} - GPIO{i}")
            try:
                # if station is set to on and pin is enabled
                if gv.output_srvals[i] and get_enabled_status(params, i):  
                    if (
                        params[u"active"] == u"low"
                    ):  # if the relay type is active low, set the output low
                        if use_gpiod:
                            set_pin(i, 0)
                        elif gv.use_pigpio:
                            pi.write(relay_pins[i], 0)
                        else:
                            GPIO.output(relay_pins[i], GPIO.LOW)
                    else:  # otherwise set it high
                        if use_gpiod:
                            set_pin(i, 1)
                        elif gv.use_pigpio:
                            pi.write(relay_pins[i], 1)
                        else:
                            GPIO.output(relay_pins[i], GPIO.HIGH)
                else:  # station is set to off
                    if (
                        params[u"active"] == u"low"
                    ):  # if the relay type is active low, set the output high
                        if use_gpiod:
                            set_pin(i, 1)
                        elif gv.use_pigpio:
                            pi.write(relay_pins[i], 1)
                        else:
                            GPIO.output(relay_pins[i], GPIO.HIGH)
                    else:  # otherwise set it low
                        if use_gpiod:
                            set_pin(i, 0)
                        elif gv.use_pigpio:
                            pi.write(relay_pins[i], 0)
                        else:
                            GPIO.output(relay_pins[i], GPIO.LOW)
            except Exception as e:
                print(u"Problem switching relays", e, relay_pins[i])
                pass


init_pins()

zones = blinker_signal(u"zone_change")
zones.connect(on_zone_change)

def cleanup(signum, frame):
    print("Caught CTRL-C, will release all GPIO lines...")
    release_all_lines()

def release_all_lines():
    print("Releasing GPIO lines...")
    for pin, line in line_requests.items():
        try:
            line.release()
            print(f"Released GPIO pin {pin}")
        except Exception as e:
            print(f"Error releasing pin {pin}: {e}")
    sys.exit(0)

signal.signal(signal.SIGINT, cleanup)

################################################################################
# Web pages:                                                                   #
################################################################################


class settings(ProtectedPage):
    """Load an html page for entering relay board adjustments"""

    def GET(self):
        with open(DATAFILE, u"r") as f:  # Read the settings from file
            params = json.load(f)
        return getattr(template_render, "40pin")(params, json.dumps(rpi_pins))
        # raise web.seeother(u"/40pin", json.dumps(params, indent=2), json.dumps(rpi_pins, indent=2))


class update(ProtectedPage):
    """Save user input to 40pin.json file"""

    def POST(self):
        form_data = web.input()
        print(f"Saving 40pin data: {json.dumps(form_data, indent=2)}")
        
        changed = False
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
                "order": form_data.get(f"order_{i}", "")
            }
            pins.append(pin_data)
        print(f"New pins {json.dumps(pins, indent=2)}")

        # Compare pin-by-pin
        if len(params.get("pins", [])) != len(pins):
            params["pins"] = pins
            changed = True
        else:
            for original, submitted in zip(params.get("pins", []), pins):   #works only if both non-empty
                print(f"Comparing original {json.dumps(original)} with submitted {json.dumps(submitted)}")
                if original.get("pin") == submitted.get("pin"):
                    if self.normalize_order(original.get("order")) != self.normalize_order(submitted.get("order")):
                        changed = True
                        break

        if params[u"active"] != str(
            form_data[u"active"]
        ):  # since changing active could turn all the relays on, disable all the relay channels
            params[u"active"] = str(form_data[u"active"])            
            for pin in params.get("pins", []):
                pin["enabled"] = False
            changed = True

        print(f"Changed: {changed}")
        if changed:
            init_pins()
            with open(DATAFILE, u"w") as f:  # write the settings to file
                json.dump(params, f, indent=4, sort_keys=True)

        raise web.seeother(u"/40pin")


    def normalize_order(self, value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
