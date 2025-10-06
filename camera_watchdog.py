#!/usr/bin/env python3

import os
import subprocess
import sys
import time
import re
import json
import configparser
import logging
from datetime import datetime

# Cache file to store device-to-busid mappings
CACHE_FILE = "/tmp/camera_watchdog_cache.json"

# Log file
LOG_FILE = "/var/log/camera_watchdog.log"


# Set up logging
def setup_logging():
    """Configure logging to both file and console."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)],
    )


def parse_camera_devices(ini_path="/opt/frodobots/teleop.ini"):
    """Parse teleop.ini to extract camera video device paths."""
    devices = []

    try:
        config = configparser.ConfigParser()
        config.read(ini_path)

        if "plugin" in config:
            for key, value in config["plugin"].items():
                if key.startswith("camera"):
                    # Extract device path from: v4l2src device=/dev/video0 ! ...
                    match = re.search(r"device=([^\s!]+)", value)
                    if match:
                        devices.append(match.group(1))

        logging.info(f"Found {len(devices)} camera devices: {devices}")
        return devices

    except Exception as e:
        logging.error(f"Error parsing {ini_path}: {e}")
        return []


def load_cache():
    """Load cached device-to-busid mappings."""
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        logging.warning(f"Warning: Could not load cache: {e}")
    return {}


def save_cache(cache):
    """Save device-to-busid mappings to cache."""
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        logging.warning(f"Warning: Could not save cache: {e}")


def get_bus_id(device_path):
    """Extract USB bus ID from a video device using udevadm."""
    try:
        result = subprocess.run(
            ["udevadm", "info", "-q", "path", "-n", device_path],
            capture_output=True,
            text=True,
            check=True,
        )

        # Parse output like: /devices/.../usb3/3-2/3-2:1.0/video4linux/video0
        # Extract bus ID pattern: X-Y:Z.W or X-Y.Z:W.V
        path = result.stdout.strip()

        # Look for pattern like "3-2:1.0" in the path
        match = re.search(r"(\d+-[\d.]+:\d+\.\d+)", path)
        if match:
            return match.group(1)

        logging.warning(f"Warning: Could not extract bus ID from path: {path}")
        return None

    except subprocess.CalledProcessError as e:
        logging.error(f"Error getting bus ID for {device_path}: {e}")
        return None
    except Exception as e:
        logging.error(f"Unexpected error for {device_path}: {e}")
        return None


def build_camera_map():
    """Build camera map from parsed devices and auto-detected/cached bus IDs."""
    devices = parse_camera_devices()
    cache = load_cache()

    camera_map = {}
    cache_updated = False

    for device in devices:
        bus_id = None

        if device_exists(device):
            # Device exists - detect its bus ID
            bus_id = get_bus_id(device)
            if bus_id:
                camera_map[device] = bus_id
                logging.info(f"  {device} → {bus_id}")

                # Update cache if changed
                if cache.get(device) != bus_id:
                    cache[device] = bus_id
                    cache_updated = True
            else:
                logging.warning(f"Warning: Could not detect bus ID for {device}")
        else:
            # Device missing - try to use cached bus ID
            if device in cache:
                bus_id = cache[device]
                camera_map[device] = bus_id
                logging.info(f"  {device} → {bus_id} (from cache, device missing)")
            else:
                logging.warning(
                    f"Warning: {device} does not exist and no cached bus ID available"
                )

    # Save cache if updated
    if cache_updated:
        save_cache(cache)

    return camera_map


def rebind_device(bus_id):
    """Rebind a USB device by unbinding and binding it."""
    logging.info(f"Rebinding {bus_id}...")

    try:
        # Try to unbind (might already be unbound)
        subprocess.run(
            f'echo "{bus_id}" | sudo tee /sys/bus/usb/drivers/uvcvideo/unbind',
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,  # Don't raise exception if unbind fails
        )
        time.sleep(2)

        # Bind
        subprocess.run(
            f'echo "{bus_id}" | sudo tee /sys/bus/usb/drivers/uvcvideo/bind',
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        time.sleep(3)  # Give device time to re-enumerate

        logging.info(f"Done rebinding {bus_id}.")
        return True

    except subprocess.CalledProcessError as e:
        logging.error(f"Error rebinding {bus_id}: {e}")
        return False


def device_exists(device_path):
    """
    Check if a device exists and is accessible.
    For symlinks, resolve to the real path first.
    """
    try:
        # First check if the path exists at all
        if not os.path.exists(device_path):
            return False

        # If it's a symlink, resolve it and check the target
        if os.path.islink(device_path):
            real_path = os.path.realpath(device_path)
            if not os.path.exists(real_path):
                return False

        # Try to access the device to ensure it's functional - doesn't require opening the device
        os.stat(device_path)
        return True
    except (OSError, FileNotFoundError):
        return False


def test_mode():
    """Test mode: show configuration without running watchdog."""
    logging.info("=" * 60)
    logging.info("TEST MODE - Camera Watchdog Configuration")
    logging.info("=" * 60)

    # Test parsing
    logging.info("\n1. Parsing /opt/frodobots/teleop.ini...")
    devices = parse_camera_devices()

    if not devices:
        logging.error("   ❌ No devices found!")
        return

    logging.info(f"   ✓ Successfully parsed {len(devices)} camera(s)")

    # Test camera map building
    logging.info("\n2. Building camera map...")
    CAMERA_MAP = build_camera_map()

    if not CAMERA_MAP:
        logging.error("   ❌ No cameras mapped!")
        return

    logging.info(f"   ✓ Mapped {len(CAMERA_MAP)} camera(s)")

    # Show status
    logging.info("\n3. Current camera status:")
    logging.info("-" * 60)
    for dev, bus_id in CAMERA_MAP.items():
        exists = device_exists(dev)
        status = "✓ EXISTS" if exists else "❌ MISSING"
        # Show resolved path if it's a symlink
        if os.path.islink(dev):
            try:
                real_path = os.path.realpath(dev)
                logging.info(f"   {dev:20} → {bus_id:15} [{status}]")
                logging.info(f"     ↳ symlink to: {real_path}")
            except:
                logging.info(f"   {dev:20} → {bus_id:15} [{status}]")
        else:
            logging.info(f"   {dev:20} → {bus_id:15} [{status}]")

    logging.info("\n" + "=" * 60)
    logging.info("Test complete! Run without --test to start watchdog.")
    logging.info("=" * 60)


def main():
    """Main watchdog loop."""
    setup_logging()

    # Check for test mode
    if "--test" in sys.argv:
        test_mode()
        return

    logging.info("Camera watchdog started...")

    # Build camera map from teleop.ini
    CAMERA_MAP = build_camera_map()

    if not CAMERA_MAP:
        logging.error("No cameras found in configuration. Exiting.")
        return

    logging.info(f"Monitoring cameras: {list(CAMERA_MAP.keys())}")

    while True:
        for dev, bus_id in CAMERA_MAP.items():
            if not device_exists(dev):
                logging.warning(f"{dev} missing → rebinding {bus_id}")
                rebind_device(bus_id)

        time.sleep(5)  # check interval (adjust as needed)


if __name__ == "__main__":
    main()
