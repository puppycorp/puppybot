#include <stdint.h>

// Opaque timer handle - platform-specific implementation
typedef void *timer_t;

// Create a one-shot timer with callback
// Returns NULL on failure
timer_t timer_create(void (*callback)(void *arg), void *arg, const char *name);

// Start timer with timeout in microseconds
// Returns 0 on success, non-zero on error
int timer_start_once(timer_t timer, uint64_t timeout_us);

// Stop a running timer
// Returns 0 on success, non-zero on error
int timer_stop(timer_t timer);

// Delete a timer and free resources
void timer_delete(timer_t timer);
