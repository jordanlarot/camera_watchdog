# Camera Watchdog

A Python-based watchdog service that monitors USB camera devices and automatically recovers them when they become unresponsive or disconnected.

## Overview

This script monitors camera devices configured in `/opt/frodobots/teleop.ini` and automatically rebinds them through the USB subsystem when they go missing. It's designed to handle common USB camera issues like:

- Device freezes or becomes unresponsive
- Temporary disconnections
- Driver errors requiring rebinding
- Port re-enumeration 

## Quickstart 
1.	Clone and enter the repo
```bash
git clone https://github.com/jordanlarot/camera-watchdog.git
cd camera-watchdog
```

2.	Run in test mode (check your config & cameras)
```bash
sudo python3 camera_watchdog.py --test
```

3.	Start the watchdog
```bash
sudo python3 camera_watchdog.py
```

4.	(Optional) Run as a service
```bash
sudo nano /etc/systemd/system/camera_watchdog.service
```

```
sudo systemctl daemon-reload
sudo systemctl enable camera_watchdog
sudo systemctl start camera_watchdog
```


## How It Works

### 1. **Device Discovery**
   - Parses `/opt/frodobots/teleop.ini` to extract camera device paths (e.g., `/dev/video0`)
   - Uses `udevadm` to map each device to its USB bus ID (e.g., `3-2:1.0`)
   - Caches these mappings in `/tmp/camera_watchdog_cache.json`

### 2. **Monitoring Loop**
   - Continuously checks if configured camera devices exist and are accessible
   - Runs every 5 seconds by default
   - Validates both regular device paths and symlinks

### 3. **Automatic Recovery**
   - When a device goes missing, the watchdog:
     1. Unbinds the device from the `uvcvideo` driver
     2. Waits 2 seconds
     3. Rebinds the device to the driver
     4. Waits 3 seconds for re-enumeration
   - Logs all recovery actions for troubleshooting in `/var/log/camera_watchdog.log`

### 4. **Smart Caching**
   - Stores device-to-busid mappings for persistence across reboots
   - Uses cached IDs when devices are temporarily unavailable
   - Auto-updates cache when devices reconnect or change

## Features

✅ **Automatic configuration** - Reads from existing `/opt/frodobots/teleop.ini`  
✅ **USB rebinding** - Recovers frozen cameras without physical reconnection  
✅ **Persistent mappings** - Caches device bus IDs for reliability  
✅ **Test mode** - Verify configuration without running the watchdog  
✅ **Comprehensive logging** - Logs to both file and console  
✅ **Symlink support** - Handles both direct device paths and symlinks  

## Usage

### Test Mode
Before running the watchdog, verify your configuration:

```bash
sudo python3 camera_watchdog.py --test
```

This will:
- Parse your camera configuration
- Build the device-to-busid map
- Show the current status of all cameras
- Display whether each device exists and its bus ID

### Run Watchdog
Start the monitoring service:

```bash
sudo python3 camera_watchdog.py
```

**Note:** Requires `sudo` for USB device rebinding operations.

### Running as a Systemd Service
To make the camera watchdog start automatically on boot, you can set it up as a systemd service.

1. Create the service file

Save the following as:
`sudo nano /etc/systemd/system/camera_watchdog.service`

```ini
[Unit]
Description=Camera Watchdog - Monitor and rebind USB cameras
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /home/<username>/camera-watchdog/camera_watchdog.py # change to user
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# Run as root (needed for USB rebinding)
User=root

# Working directory
WorkingDirectory=/home/<username> # change to user

[Install]
WantedBy=multi-user.target
```

**Note:** Replace <username> with your actual Linux username.
If you need USB rebinding, the service must run as root.

2.	Reload and enable the service

```bash
sudo systemctl daemon-reload
sudo systemctl enable camera_watchdog
sudo systemctl start camera_watchdog
```

3.	View logs (live)
```bash
sudo journalctl -u camera_watchdog -f
```

## Configuration

The script reads camera configurations from `/opt/frodobots/teleop.ini`. It expects entries like:

```ini
[plugin]
camera1 = v4l2src device=/dev/video0 ! ...
camera2 = v4l2src device=/dev/video1 ! ...
```

The watchdog automatically extracts device paths from these entries.

## Files

- **`/tmp/camera_watchdog_cache.json`** - Device-to-busid mapping cache
- **`/var/log/camera_watchdog.log`** - Log file with watchdog activity
- **`/opt/frodobots/teleop.ini`** - Camera configuration source

## How USB Rebinding Works

The script uses Linux's USB driver binding system:

```
/sys/bus/usb/drivers/uvcvideo/
├── bind    ← Write bus ID here to bind
└── unbind  ← Write bus ID here to unbind
```

This forces the `uvcvideo` driver to reset its connection to the camera without physically unplugging/replugging the device.

## Limitations

1. ⚠️ **Same-Port Reconnection Only**

This script currently handles camera failures only when the device stays connected to the same physical USB port. Cross-port reconnects aren’t supported yet – that’s expected and can be solved later using persistent device IDs or udev rules.

**What this means:**
- ✅ **Works:** Camera freezes, device becomes unresponsive while plugged into the same USB port
- ❌ **Doesn't work:** Camera unplugged and reconnected to a *different* USB port

**Why:** 
The script uses USB bus IDs (like `3-2:1.0`) which are tied to physical USB ports. If you reconnect a camera to a different port, it gets a new bus ID, breaking the mapping.

**Future Solutions:**
- Use persistent device identifiers (serial numbers, vendor/product IDs)
- Implement udev rules for cross-port tracking


2. ⚠️ **Manual Refresh Required After Rebind**

Even when the watchdog successfully rebinds a camera, the teleop software won’t automatically reinitialize the video stream.
You’ll need to manually refresh or restart the teleop interface to restore the live feed.

**Why:**
The rebind resets the USB driver connection at the OS level, but the teleop software still holds the old file descriptor to the previous /dev/videoX stream. Until it’s reopened, no new frames are received.

**Workaround:**
- After a rebind event, refresh or restart the teleop website.
- Long-term fix: add automatic stream reinitialization logic in the teleop layer.

## Requirements

- Python 3.6+
- Linux with `uvcvideo` driver
- `udevadm`
- Root/sudo privileges for USB operations

## Dependencies

All dependencies are part of Python standard library:
- `configparser` - Parse INI files
- `subprocess` - Execute system commands
- `logging` - Log management
- `json` - Cache file handling
- `re` - Regular expression parsing

## Troubleshooting

### Camera not detected
- Run `--test` mode to see if the device is found in `teleop.ini`
- Check that the device path exists: `ls -la /dev/video*`
- Verify udev path: `udevadm info -q path -n /dev/video0`

### Rebinding fails
- Ensure you're running with `sudo`
- Check if `uvcvideo` driver is loaded: `lsmod | grep uvcvideo`
- Verify bus ID format in logs

### Cache issues
- Delete `/tmp/camera_watchdog_cache.json` to rebuild from scratch
- Cache will auto-rebuild when devices are detected

## Example Output

```
2025-10-04 10:30:15 - INFO - Camera watchdog started...
2025-10-04 10:30:15 - INFO - Found 2 camera devices: ['/dev/video0', '/dev/video2']
2025-10-04 10:30:15 - INFO -   /dev/video0 → 3-2:1.0
2025-10-04 10:30:15 - INFO -   /dev/video2 → 3-3:1.0
2025-10-04 10:30:15 - INFO - Monitoring cameras: ['/dev/video0', '/dev/video2']
2025-10-04 10:35:22 - WARNING - /dev/video0 missing → rebinding 3-2:1.0
2025-10-04 10:35:22 - INFO - Rebinding 3-2:1.0...
2025-10-04 10:35:27 - INFO - Done rebinding 3-2:1.0.
```

## Author

Created by Jordan Larot


