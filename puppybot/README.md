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

For a debug build:

```sh
./scripts/build.sh debug
```

## Flash

```sh
./scripts/flash.sh
```
