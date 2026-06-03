# Puppybot ESP32 Rust Bare Metal

Minimal Rust firmware project for a classic ESP32 using `esp-hal`.

## Setup

Install the Espressif Rust toolchain and flashing dependencies. This is still
a bare-metal project: it targets `xtensa-esp32-none-elf` and does not use
ESP-IDF or FreeRTOS.

```sh
./scripts/install.sh
```

If the board is visible but the serial port cannot be opened, add your user to
the serial port group:

```sh
sudo usermod -aG dialout "$USER"
newgrp dialout
```

## Build

```sh
./scripts/build.sh
```

To build firmware that connects to Wi-Fi, provide credentials at build time:

```sh
WIFI_SSID="your-network" WIFI_PASSWORD="your-password" ./scripts/build.sh
```

Or put them in a local `.env` file:

```sh
cp .env.example .env
```

Then edit `.env`:

```sh
WIFI_SSID=your-network
WIFI_PASSWORD=your-password
```

Without those variables the firmware still runs, but Wi-Fi is disabled.
When Wi-Fi is enabled and DHCP succeeds, the firmware advertises
`PuppyBot._ws._tcp.local` on port 80 with hostname `puppybot.local`.
The HTTP server responds on port 80, and WebSocket clients can connect to
`ws://puppybot.local/ws`. The Rust firmware currently accepts command frames
and replies to protocol pings; motor/arm command execution still needs the
Rust hardware control layer.

For a debug build:

```sh
./scripts/build.sh debug
```

## Host simulator

The Rust app can also run on the PC with the host feature. It uses the same
arm controller and STServo packet code, backed by a fake byte-level servo bus,
and exposes the Android-compatible WebSocket endpoint on `/ws`.

```sh
./scripts/run-host.sh
```

By default it listens on `0.0.0.0:8080`, so the WebSocket URL is
`ws://<pc-ip>:8080/ws`. To bind a different address:

```sh
PUPPYBOT_HOST_ADDR=127.0.0.1:8081 ./scripts/run-host.sh
```

## Flash

```sh
./scripts/flash.sh
```

To flash a Wi-Fi-enabled build:

```sh
WIFI_SSID="your-network" WIFI_PASSWORD="your-password" ./scripts/flash.sh
```

If `.env` exists, `./scripts/flash.sh` will use it automatically.
