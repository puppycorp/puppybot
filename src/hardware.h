#ifndef HARDWARE_H
#define HARDWARE_H

#include <stdint.h>

#define PO_CPU_FREQ_80MHZ   80
#define PO_CPU_FREQ_160MHZ  160
#define PO_CPU_FREQ_240MHZ  240
#define PO_WAKEUP_TIMER  (1 << 0)  // Wake-up from RTC timer
#define PO_WAKEUP_GPIO   (1 << 1)  // Wake-up from external GPIO
#define PO_WAKEUP_TOUCH  (1 << 2)  // Wake-up from touch sensor
#define PO_WAKEUP_UART   (1 << 3)  // Wake-up from UART data
#define PO_WAKEUP_WIFI   (1 << 4)  // Wake-up from Wi-Fi (Light Sleep only)
#define PO_WAKEUP_EXT1   (1 << 5)  // Wake-up from multiple GPIOs (EXT1)

#define PO_RST_POWERON   0  // Power-on reset
#define PO_RST_EXTERNAL  1  // External reset (via reset pin)
#define PO_RST_SOFTWARE  3  // Software reset (e.g., via ESP.restart())
#define PO_RST_WDT       4  // Watchdog timer reset
#define PO_RST_DEEPSLEEP 5  // Wakeup from deep sleep reset
#define PO_RST_BROWNOUT  6  // Brownout reset (low voltage)
#define PO_RST_UNKNOWN   7  // Unknown reset cause

typedef volatile int mutex_t;

int po_mutex_init(mutex_t *mutex);
int po_mutex_lock(mutex_t *mutex);
int po_mutex_unlock(mutex_t *mutex);

int po_pwm_init();
int po_pwm_deinit();
int po_pwm_set_freq(int channel, int freq);
int po_pwm_set_duty(int channel, int duty);

int pc_add_task(void (*task)(void));

int po_tcp_init(const char *ip, int port);
int po_tcp_deinit(int socket);
int po_tcp_send(int socket, uint8_t *data, int size);

int po_udp_init(const char *ip, int port);
int po_udp_deinit(int socket);
int po_udp_send(int socket, uint8_t *data, int size);

int po_gpio_init(int pin, int mode);
int po_gpio_deinit(int pin);
int po_gpio_read(int pin);
int po_gpio_write(int pin, int value);

// GPIO interrupt function declarations
void po_gpio_isr_handler(void* arg);
int po_gpio_set_interrupt(int pin, int mode, void (*handler)(void*));
int po_gpio_clear_interrupt(int pin);     // Disable GPIO interrupt

// Timer interrupt function declarations
void po_timer_isr_handler(void* arg);
int po_timer_init(int timer_id, int timeout_ms, void (*handler)(void*));
int po_timer_start(int timer_id);
int po_timer_stop(int timer_id);
int po_timer_clear_interrupt(int timer);  // Disable timer interrupt

// Software interrupt function declarations
void po_software_isr(void* arg);
int po_software_interrupt_init(void (*handler)(void*));
int po_software_interrupt_trigger();

// Wi-Fi event interrupt function declarations
void po_wifi_event_handler(void *arg, int event_id);
int po_wifi_register_event(void (*handler)(void*, int));

// Touch interrupt function declarations
void po_touch_isr_handler(void* arg);
int po_touch_set_interrupt(int pad, void (*handler)(void*));

// UART interrupt function declarations
void po_uart_isr_handler(void* arg);
int po_uart_set_interrupt(int uart_num, void (*handler)(void*));
int po_uart_clear_interrupt(int uart_num); // Disable UART interrupt

// ADC interrupt function declarations
void po_adc_isr_handler(void* arg);
int po_adc_set_interrupt(int channel, int threshold, void (*handler)(void*));

// Watchdog Timer interrupt function declarations
void po_watchdog_isr_handler(void* arg);
int po_watchdog_set_interrupt(void (*handler)(void*));

// I2C and SPI interrupt function declarations
void po_i2c_isr_handler(void* arg);
int po_i2c_set_interrupt(int bus, void (*handler)(void*));

void po_spi_isr_handler(void* arg);
int po_spi_set_interrupt(int bus, void (*handler)(void*));

int po_power_set_cpu_freq(int freq_mhz);  // Use PO_CPU_FREQ_* constants
int po_power_light_sleep(int wakeup_sources);
int po_power_deep_sleep(int wakeup_sources);
int po_power_hibernate(int wakeup_sources);

// RTC memory storage function declarations
int po_rtc_store(uint32_t key, uint32_t value);
uint32_t po_rtc_retrieve(uint32_t key);

// EEPROM/Flash storage function declarations
int po_flash_write(uint32_t address, uint8_t *data, int size);
int po_flash_read(uint32_t address, uint8_t *buffer, int size);

// Temperature and voltage monitoring function declarations
int po_temp_read();
int po_voltage_read();
int po_cpu_freq_read();
int po_get_reset_reason();

#endif // HARDWARE_H