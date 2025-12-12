#include "timer.h"

#include "log.h"

#include <stdint.h>
#include <stdlib.h>
#include <time.h>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <process.h>
#include <windows.h>
typedef HANDLE thread_handle_t;
#else
#include <pthread.h>
#include <unistd.h>
typedef pthread_t thread_handle_t;
#endif

typedef struct host_timer {
	void (*callback)(void *);
	void *arg;
	thread_handle_t thread;
	int active;
	int cancel_requested;
#ifdef _WIN32
	CRITICAL_SECTION lock;
#else
	pthread_mutex_t lock;
#endif
	uint64_t timeout_us;
} host_timer_t;

static const char *TAG = "TIMER_HOST";
#ifdef _WIN32
static uint64_t get_time_us(void) {
	static LARGE_INTEGER frequency = {0};
	if (frequency.QuadPart == 0) {
		QueryPerformanceFrequency(&frequency);
	}
	LARGE_INTEGER counter;
	QueryPerformanceCounter(&counter);
	return (uint64_t)((counter.QuadPart * 1000000ULL) / frequency.QuadPart);
}
#else
static uint64_t get_time_us(void) {
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (uint64_t)ts.tv_sec * 1000000ULL + (uint64_t)ts.tv_nsec / 1000ULL;
}
#endif

#ifdef _WIN32
static unsigned __stdcall timer_thread(void *arg) {
	host_timer_t *timer = (host_timer_t *)arg;
	uint64_t start = get_time_us();
	int cancelled = 0;
	void (*callback)(void *) = NULL;
	void *cb_arg = NULL;
	int expired = 0;

	while (1) {
		EnterCriticalSection(&timer->lock);
		cancelled = timer->cancel_requested;
		uint64_t timeout_us = timer->timeout_us;
		callback = timer->callback;
		cb_arg = timer->arg;
		LeaveCriticalSection(&timer->lock);

		if (cancelled) {
			break;
		}

		uint64_t now = get_time_us();
		uint64_t elapsed = now - start;
		if (elapsed >= timeout_us) {
			expired = 1;
			break;
		}

		uint64_t remaining = timeout_us - elapsed;
		DWORD sleep_ms = (DWORD)(remaining / 1000ULL);
		if (sleep_ms == 0) {
			sleep_ms = 1;
		}
		Sleep(sleep_ms);
	}

	EnterCriticalSection(&timer->lock);
	timer->active = 0;
	cancelled = timer->cancel_requested;
	callback = timer->callback;
	cb_arg = timer->arg;
	LeaveCriticalSection(&timer->lock);

	if (!cancelled && expired && callback) {
		callback(cb_arg);
	}
	return 0;
}
#else
static void *timer_thread(void *arg) {
	host_timer_t *timer = (host_timer_t *)arg;
	uint64_t start = get_time_us();
	const uint64_t slice_us = 1000; // 1 ms slices
	int cancelled = 0;
	int expired = 0;
	void (*callback)(void *) = NULL;
	void *cb_arg = NULL;

	while (1) {
		pthread_mutex_lock(&timer->lock);
		cancelled = timer->cancel_requested;
		uint64_t timeout_us = timer->timeout_us;
		callback = timer->callback;
		cb_arg = timer->arg;
		pthread_mutex_unlock(&timer->lock);

		if (cancelled) {
			break;
		}

		uint64_t now = get_time_us();
		uint64_t elapsed = now - start;
		if (elapsed >= timeout_us) {
			expired = 1;
			break;
		}

		uint64_t remaining = timeout_us - elapsed;
		uint64_t sleep_us = remaining < slice_us ? remaining : slice_us;
		struct timespec req = {.tv_sec = (time_t)(sleep_us / 1000000ULL),
		                       .tv_nsec =
		                           (long)((sleep_us % 1000000ULL) * 1000L)};
		nanosleep(&req, NULL);
	}

	pthread_mutex_lock(&timer->lock);
	timer->active = 0;
	cancelled = timer->cancel_requested;
	callback = timer->callback;
	cb_arg = timer->arg;
	pthread_mutex_unlock(&timer->lock);

	if (!cancelled && expired && callback) {
		callback(cb_arg);
	}
	return NULL;
}
#endif

timer_t timer_create(void (*callback)(void *arg), void *arg, const char *name) {
	(void)name;
	if (!callback) {
		log_error(TAG, "timer_create called with NULL callback");
		return NULL;
	}

	host_timer_t *timer = (host_timer_t *)calloc(1, sizeof(*timer));
	if (!timer) {
		log_error(TAG, "Failed to allocate host timer");
		return NULL;
	}

	timer->callback = callback;
	timer->arg = arg;
#ifdef _WIN32
	InitializeCriticalSection(&timer->lock);
#else
	pthread_mutex_init(&timer->lock, NULL);
#endif
	return (timer_t)timer;
}

int timer_start_once(timer_t handle, uint64_t timeout_us) {
	if (!handle || timeout_us == 0) {
		return -1;
	}

	host_timer_t *timer = (host_timer_t *)handle;

#ifdef _WIN32
	EnterCriticalSection(&timer->lock);
	if (timer->active) {
		timer->cancel_requested = 1;
		LeaveCriticalSection(&timer->lock);
		WaitForSingleObject(timer->thread, INFINITE);
		CloseHandle(timer->thread);
		EnterCriticalSection(&timer->lock);
	}
	timer->cancel_requested = 0;
	timer->timeout_us = timeout_us;
	timer->active = 1;
	uintptr_t thread = _beginthreadex(NULL, 0, timer_thread, timer, 0, NULL);
	if (thread == 0) {
		timer->active = 0;
		LeaveCriticalSection(&timer->lock);
		return -1;
	}
	timer->thread = (HANDLE)thread;
	LeaveCriticalSection(&timer->lock);
#else
	pthread_mutex_lock(&timer->lock);
	if (timer->active) {
		timer->cancel_requested = 1;
		pthread_mutex_unlock(&timer->lock);
		pthread_join(timer->thread, NULL);
		pthread_mutex_lock(&timer->lock);
	}
	timer->cancel_requested = 0;
	timer->timeout_us = timeout_us;
	timer->active = 1;
	if (pthread_create(&timer->thread, NULL, timer_thread, timer) != 0) {
		timer->active = 0;
		pthread_mutex_unlock(&timer->lock);
		return -1;
	}
	pthread_mutex_unlock(&timer->lock);
#endif
	return 0;
}

int timer_stop(timer_t handle) {
	if (!handle) {
		return -1;
	}

	host_timer_t *timer = (host_timer_t *)handle;

#ifdef _WIN32
	EnterCriticalSection(&timer->lock);
	if (!timer->active) {
		LeaveCriticalSection(&timer->lock);
		return 0;
	}
	timer->cancel_requested = 1;
	LeaveCriticalSection(&timer->lock);
	WaitForSingleObject(timer->thread, INFINITE);
	CloseHandle(timer->thread);
	timer->thread = NULL;

	EnterCriticalSection(&timer->lock);
	timer->active = 0;
	LeaveCriticalSection(&timer->lock);
#else
	pthread_mutex_lock(&timer->lock);
	if (!timer->active) {
		pthread_mutex_unlock(&timer->lock);
		return 0;
	}
	timer->cancel_requested = 1;
	pthread_mutex_unlock(&timer->lock);
	pthread_join(timer->thread, NULL);

	pthread_mutex_lock(&timer->lock);
	timer->active = 0;
	pthread_mutex_unlock(&timer->lock);
#endif
	return 0;
}

void timer_delete(timer_t handle) {
	if (!handle) {
		return;
	}

	host_timer_t *timer = (host_timer_t *)handle;
	timer_stop(handle);
#ifdef _WIN32
	DeleteCriticalSection(&timer->lock);
#else
	pthread_mutex_destroy(&timer->lock);
#endif
	free(timer);
}
