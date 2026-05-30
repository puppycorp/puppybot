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

For a debug build:

```sh
./scripts/build.sh debug
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
