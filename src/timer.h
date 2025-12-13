#ifndef PUPPYBOT_TIMER_H
#define PUPPYBOT_TIMER_H

#include <stdint.h>

// ---------------------------------------------------------------------------
// Platform timer HAL (periodic timers in milliseconds)
// ---------------------------------------------------------------------------

typedef void *platform_timer_handle_t;

platform_timer_handle_t platform_timer_create(void (*callback)(void *arg),
                                              void *arg, uint32_t interval_ms);
int platform_timer_start(platform_timer_handle_t timer);
int platform_timer_stop(platform_timer_handle_t timer);
void platform_timer_delete(platform_timer_handle_t timer);

// Blocking delay in milliseconds.
void platform_delay_ms(uint32_t ms);

// ---------------------------------------------------------------------------
// App-level timers (one-shot timers in microseconds)
// ---------------------------------------------------------------------------

// Opaque one-shot timer handle - platform-specific implementation.
// Named to avoid conflicts with libc's `timer_t` / `timer_create`.
typedef void *puppy_timer_t;

// Create a one-shot timer with callback
// Returns NULL on failure
puppy_timer_t puppy_timer_create(void (*callback)(void *arg), void *arg,
                                 const char *name);

// Start timer with timeout in microseconds
// Returns 0 on success, non-zero on error
int puppy_timer_start_once(puppy_timer_t timer, uint64_t timeout_us);

// Stop a running timer
// Returns 0 on success, non-zero on error
int puppy_timer_stop(puppy_timer_t timer);

// Delete a timer and free resources
void puppy_timer_delete(puppy_timer_t timer);

#endif // PUPPYBOT_TIMER_H
