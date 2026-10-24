# Classic ESP32 firmware

`esp32.flex` is a native Flexscript firmware for the original ESP32-WROOM/LX6.
It boots directly through the chip ROM, maps its controller code from flash,
and runs the shared Puppybot controller on CPU0. UART2 drives the existing
STServo adapter at 1 Mbaud, TX GPIO17 / RX GPIO16. UART0 uses the board's USB serial
bridge at 115200 baud for commands and telemetry. No Rust or C application runtime,
Linux syscalls, Python process, radio stack or external inference engine runs on
the board. The Xtensa linker only resolves the cached-flash layout.

This initial hardware target provides serial control. Wi-Fi, WebSocket, mDNS,
BLE/Android control and calibration persistence are separate work. Rear DC motor
outputs retain the existing controller limitations.
The camera detector stays on the companion computer. ESP32-S3/C3/C6 and modules
that use GPIO16/17 for PSRAM need their own board adapter.

## Build

Use the sibling Flexscript source/compiler, as for the Linux port. On Linux
x86-64, optional pinned tool preparation downloads a checksum-verified Espressif
linker into the ignored build directory:

```sh
python3 flex/scripts/prepare-esp32-tools.py --qemu
./flex/scripts/build-esp32.sh
```

An existing linker can be selected with `ESP32_LD=/path/to/xtensa-esp32-elf-ld`.
`FLEXSCRIPT_COMPILER` and `FLEXSCRIPT_SOURCE` select the compiler and the
link tooling checkout, respectively. Platform source imports follow the sibling
checkout convention as the rest of this port. The build does not fetch tools,
open devices or install anything. It produces:

- `build/flex/esp32/puppybot.bin`: ROM image and cached code, written at `0x1000`.
- `build/flex/esp32/puppybot.elf`: fully linked Xtensa ELF with no unresolved symbols.
- `build/flex/esp32/puppybot.map`: link map.
- `build/flex/esp32/puppybot.json`: independent image checksum/mapping report.

`inspect-esp32.py` checks the chip ID, entry point, load bounds, XOR checksum,
SHA256, unresolved symbols and correspondence between ELF code and flash bytes.
The ROM-loaded image occupies less than 15 KiB IRAM and 2 KiB static DRAM in the
current build; about 444 KiB of controller/software-math code executes from flash.
The controller and transport allocate about 14 KiB once from the 32 KiB native heap.
No per-tick allocation occurs. This target keeps the ROM's clock configuration
and uses an APB timer with an explicit 80 MHz/80 prescaler for microseconds.

## Calibration and command handling

The root [puppybot.json](../../puppybot.json), beside `puppybot.flex`, is shared
with the PC runtime. It mirrors the physical runtime calibration from
`puppybot/runtime/puppybot.json` at master commit `fc82225`: servo IDs 1..4,
wrapped physical limits, reference positions/angles, motor signs and coordinate
signs. `PUPPYBOT_ESP32_CONFIG=/path/to/config.json` embeds another reviewed v1
profile. The generated factory is checked by the actual native controller
validator before the firmware is compiled. Config changes require rebuilding.

Boot starts in **monitor** mode: feedback reads only, no servo-register writes.
`enable` requires recent valid position and temperature feedback from all four
arm servos, with no temperature above 80°C. Enabled mode
uses the same queued protocol v1 events, wheel-mode acknowledgements, limits,
feedback/stall faults and motion logic as the shared controller. The embedded
command lease is 500 ms, matching the latest Rust firmware; continuous jogs stop
when it expires. Position targets retain the existing controller semantics.
Fake/Gym callers retain the existing 1000 ms lease.

PC hardware mode now uses the same policy in `core/interlock.flex`, including
the 500 ms lease and explicit enable; fake/Gym retain their existing behavior.
Every physical enable resets mode readiness so a speed write must follow fresh
wheel-mode acknowledgements, even when monitor polling previously failed them.

Each feedback transaction reads eight bytes from STS/SMS registers 56..63:
position is the first two bytes and temperature is the final byte. The intervening
speed/load/voltage bytes are currently unused. This replaces the two-byte position
read and adds no extra bus transaction. Temperature receipt times use the actual
reply time, rather than the start of a potentially delayed control cycle.

Any temperature above 80°C, missing/failed/short status, or temperature sample
older than 250 ms stops the whole arm and finishes disabling output. A fault
clears queued movement and cancels pending output before another UART poll can
transmit it. Cooling/recovered feedback alone never resumes movement: all four
samples must be fresh and at most 80°C, followed by explicit `enable`. A missing
temperature is reported as unavailable, never as zero degrees. The existing
per-joint temperature guard remains active inside the shared controller too.

Cycles are scheduled at 20 ms without overlapping an active bus cycle. Each UART
write has a 10 ms bound, each response has the existing 50 ms bound, and wrong-ID
retransmissions cannot extend that deadline. A slow/missing servo can extend a
cycle. Status exposes last/max cycle time, overruns, UART/serial failures and
dropped output frames. These are measurements of the supplied clock, not a
guarantee that real hardware meets 20 ms under every motion workload.

`stop` clears queued motion, cancels the in-flight exchange, and schedules zero
speeds. `disable` additionally finishes a stop cycle before returning to monitor
mode; status reports `stopping` during that cycle. UART0 receive errors also
initiate disabling. An unreachable/disconnected servo cannot acknowledge a stop.
Other controller commands cannot change wiring or calibration in this release.

## Flash and communicate

For a classic 4 MiB board with the existing STServo adapter on GPIO17/16, install
`esptool` in a tooling environment. Select the exact board port:

```sh
./flex/scripts/flash-esp32.sh /dev/serial/by-id/YOUR-ESP32
python3 flex/scripts/esp32-command.py --port /dev/serial/by-id/YOUR-ESP32 ping
python3 flex/scripts/esp32-command.py --port /dev/serial/by-id/YOUR-ESP32 console
```

The flash script first reads the original full 4 MiB flash into a timestamped
backup plus SHA256 file, then writes the verified image at `0x1000`. It does not
erase the full chip. Restore a backup with `python3 -m esptool --chip esp32
--port PORT write_flash 0x0 BACKUP.bin`. Backups can contain existing device
configuration and should be kept private.

The persistent console accepts `ping`, `status`, `state`, `enable`, `stop`,
`disable`, `raw HEX` and `quit`. Start with `state` to inspect feedback and
calibration, then use `enable` to allow output. `raw` carries an unchanged v1
command; an acknowledgement means it was queued, not that motion completed.
Quitting the console disables output and waits for monitor mode. The tool uses
only Python's standard library and never enumerates or chooses a device. It
does not deliberately toggle RTS/DTR; board/driver reset behavior on opening or
closing a serial port is independent. One-shot commands are also supported.

## Serial envelope

All fields use little-endian encoding. Each frame is `PB`, version byte 1, kind
byte, payload length:u16, payload up to 256 bytes, CRC16-CCITT:u16. The CRC starts
at `0xffff`, polynomial `0x1021`, and covers version through payload. An incomplete
input frame expires after a 100 ms inter-byte gap. Payloads are bounded before
copying. Ordinary boot-ROM text is ignored by the host parser.

| Kind | Direction | Payload |
| --- | --- | --- |
| 1 | Host to device | Existing v1 command bytes |
| 2 | Device to host | Existing v1 response bytes |
| 3 | Device to host | Existing v1 arm telemetry, at most 10 Hz when subscribed |
| 4 | Host to device | One byte: 1 enable, 0 disable |
| 5 | Host to device | Empty status request |
| 6 | Device to host | 80 byte status record; decoded by the host tool |
| 7 | Device to host | Signed 32-bit errno |
| 8 | Device to host | Command byte, queued event count |

Status retains the original 48 byte prefix. Byte 1 now reports the last thermal
interlock: 0 none, 1 unavailable, 2 stale, 3 over-temperature. Four 8 byte records
follow in joint order: validity:u8, temperature°C:u8, two reserved bytes and
age_ms:u32 (`0xffffffff` for unavailable). The host tool displays these as
`temperatures` and `temperatureInterlock`; it also accepts older 48 byte status
replies. The existing v1 arm telemetry format is unchanged.

## Verification

```sh
./flex/scripts/test.sh
python3 flex/tests/esp32.py \
  --qemu "$PWD/build/flex/esp32/tools/qemu/bin/qemu-system-xtensa"
```

The ordinary suite includes independent CRC/framing/bounds/timeout fixtures and
the production UART adapter under a register/interrupt model. The temperature
suite feeds actual combined status packets through the production parser and
checks malformed lengths, checksum/status errors, timeouts, 80/81°C and 250/251 ms
boundaries, pending-command cancellation and explicit re-enable after cooling.
It runs with hardware and portable numerical lowering. The optional
QEMU suite boots the exact linked image through Espressif's original ESP32 ROM,
executes the Xtensa controller and polled UART driver, and connects UART2 to an
independent STServo peer. It checks read-only boot, calibration/positions, enable
gating, jog/deadman stops, telemetry, serial fragmentation/CRC recovery, wrong
IDs, corrupt/missing responses, responsive USB and disabling. It also drives
actual 81°C/short-temperature replies over UART2 while another joint is moving,
checks zero speeds and inhibited enable, then verifies fresh cooling plus a new
explicit enable before movement can resume. Firmware flash
must remain byte-identical throughout. Reports are in `build/flex/esp32/`.

No physical board has been flashed or moved by this implementation. Electrical
wiring, real bus waveforms and control-loop timing still require board testing.
The ROM image is specific to classic ESP32, not an ESP-IDF application partition
or an OTA update for the existing Rust installation.

Register provenance: [Espressif ESP-IDF v5.5.1 UART registers](https://github.com/espressif/esp-idf/blob/v5.5.1/components/soc/esp32/register/soc/uart_reg.h)
and [GPIO signal map](https://github.com/espressif/esp-idf/blob/v5.5.1/components/soc/esp32/include/soc/gpio_sig_map.h).
