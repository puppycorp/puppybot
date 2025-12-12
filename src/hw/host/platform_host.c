#include "platform.h"

#include "log.h"

#include <stdlib.h>
#include <string.h>
#include <time.h>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <process.h>
#include <windows.h>
#else
#include <pthread.h>
#include <sys/time.h>
#include <unistd.h>
#endif

typedef struct platform_timer {
	void (*callback)(void *arg);
	void *arg;
	uint32_t interval_ms;
	int running;
	int stop_requested;
#ifdef _WIN32
	HANDLE thread;
	CRITICAL_SECTION lock;
#else
	pthread_t thread;
	pthread_mutex_t lock;
#endif
} platform_timer_t;

static const char *TAG = "PLATFORM";

uint32_t platform_get_time_ms(void) {
#ifdef _WIN32
	static LARGE_INTEGER frequency = {0};
	if (frequency.QuadPart == 0) {
		QueryPerformanceFrequency(&frequency);
	}
	LARGE_INTEGER counter;
	QueryPerformanceCounter(&counter);
	return (uint32_t)((counter.QuadPart * 1000ULL) / frequency.QuadPart);
#else
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	uint64_t ms = (uint64_t)ts.tv_sec * 1000ULL + ts.tv_nsec / 1000000ULL;
	return (uint32_t)ms;
#endif
}

const char *platform_get_firmware_version(void) {
	const char *env_version = getenv("PUPPYBOT_FW_VERSION");
	return env_version && env_version[0] ? env_version : "host-0.1.0";
}

const char *platform_get_server_uri(void) {
	const char *uri = getenv("PUPPYBOT_SERVER_URI");
	if (uri && uri[0] != '\0') {
		return uri;
	}
	return NULL;
}

int storage_init(void) {
	log_info(TAG, "Using host storage (no-op)");
	return 0;
}

const char *instance_name(void) {
	static char name[64];
	static int initialized = 0;
	if (!initialized) {
		const char *env_name = getenv("PUPPYBOT_INSTANCE_NAME");
		if (env_name && env_name[0] != '\0') {
			strncpy(name, env_name, sizeof(name) - 1);
			name[sizeof(name) - 1] = '\0';
		} else {
			strncpy(name, "puppybot-host", sizeof(name) - 1);
			name[sizeof(name) - 1] = '\0';
		}
		initialized = 1;
	}
	return name;
}

int wifi_init(void) {
	log_info(TAG, "Skipping WiFi initialization (host environment)");
	return 0;
}

int mdns_service_init(void) {
	log_info(TAG, "Skipping mDNS setup (host environment)");
	return 0;
}

void motor_init(void) { log_info(TAG, "Initializing motor subsystem (stub)"); }

int bluetooth_start(void) {
	log_info(TAG, "Skipping Bluetooth startup (host environment)");
	return 0;
}

#ifdef _WIN32
static unsigned __stdcall platform_timer_thread(void *arg) {
	platform_timer_t *timer = (platform_timer_t *)arg;
	while (1) {
		EnterCriticalSection(&timer->lock);
		int stop_requested = timer->stop_requested;
		uint32_t interval_ms = timer->interval_ms;
		LeaveCriticalSection(&timer->lock);

		if (stop_requested) {
			break;
		}

		Sleep(interval_ms);

		EnterCriticalSection(&timer->lock);
		stop_requested = timer->stop_requested;
		void (*callback)(void *) = timer->callback;
		void *cb_arg = timer->arg;
		LeaveCriticalSection(&timer->lock);

		if (stop_requested) {
			break;
		}
		if (callback) {
			callback(cb_arg);
		}
	}

	EnterCriticalSection(&timer->lock);
	timer->running = 0;
	LeaveCriticalSection(&timer->lock);
	return 0;
}
#else
static void *platform_timer_thread(void *arg) {
	platform_timer_t *timer = (platform_timer_t *)arg;
	while (1) {
		pthread_mutex_lock(&timer->lock);
		int stop_requested = timer->stop_requested;
		uint32_t interval_ms = timer->interval_ms;
		pthread_mutex_unlock(&timer->lock);

		if (stop_requested) {
			break;
		}

		usleep(interval_ms * 1000);

		pthread_mutex_lock(&timer->lock);
		stop_requested = timer->stop_requested;
		void (*callback)(void *) = timer->callback;
		void *cb_arg = timer->arg;
		pthread_mutex_unlock(&timer->lock);

		if (stop_requested) {
			break;
		}
		if (callback) {
			callback(cb_arg);
		}
	}

	pthread_mutex_lock(&timer->lock);
	timer->running = 0;
	pthread_mutex_unlock(&timer->lock);
	return NULL;
}
#endif

platform_timer_handle_t platform_timer_create(void (*callback)(void *arg),
                                              void *arg, uint32_t interval_ms) {
	if (!callback || interval_ms == 0) {
		log_error(TAG, "Invalid timer configuration");
		return NULL;
	}

	platform_timer_t *timer = (platform_timer_t *)calloc(1, sizeof(*timer));
	if (!timer) {
		log_error(TAG, "Failed to allocate timer");
		return NULL;
	}

	timer->callback = callback;
	timer->arg = arg;
	timer->interval_ms = interval_ms;
#ifdef _WIN32
	InitializeCriticalSection(&timer->lock);
#else
	pthread_mutex_init(&timer->lock, NULL);
#endif

	return (platform_timer_handle_t)timer;
}

int platform_timer_start(platform_timer_handle_t handle) {
	if (!handle) {
		return -1;
	}

	platform_timer_t *timer = (platform_timer_t *)handle;
#ifdef _WIN32
	EnterCriticalSection(&timer->lock);
	if (timer->running) {
		timer->stop_requested = 1;
		LeaveCriticalSection(&timer->lock);
		WaitForSingleObject(timer->thread, INFINITE);
		CloseHandle(timer->thread);
		EnterCriticalSection(&timer->lock);
	}
	timer->stop_requested = 0;
	timer->running = 1;
	uintptr_t thread =
	    _beginthreadex(NULL, 0, platform_timer_thread, timer, 0, NULL);
	if (thread == 0) {
		timer->running = 0;
		LeaveCriticalSection(&timer->lock);
		return -1;
	}
	timer->thread = (HANDLE)thread;
	LeaveCriticalSection(&timer->lock);
#else
	pthread_mutex_lock(&timer->lock);
	if (timer->running) {
		timer->stop_requested = 1;
		pthread_mutex_unlock(&timer->lock);
		pthread_join(timer->thread, NULL);
		pthread_mutex_lock(&timer->lock);
	}
	timer->stop_requested = 0;
	timer->running = 1;
	if (pthread_create(&timer->thread, NULL, platform_timer_thread, timer) !=
	    0) {
		timer->running = 0;
		pthread_mutex_unlock(&timer->lock);
		return -1;
	}
	pthread_mutex_unlock(&timer->lock);
#endif
	return 0;
}

int platform_timer_stop(platform_timer_handle_t handle) {
	if (!handle) {
		return -1;
	}

	platform_timer_t *timer = (platform_timer_t *)handle;

#ifdef _WIN32
	EnterCriticalSection(&timer->lock);
	if (!timer->running) {
		LeaveCriticalSection(&timer->lock);
		return 0;
	}
	timer->stop_requested = 1;
	LeaveCriticalSection(&timer->lock);

	WaitForSingleObject(timer->thread, INFINITE);
	CloseHandle(timer->thread);
	timer->thread = NULL;

	EnterCriticalSection(&timer->lock);
	timer->running = 0;
	LeaveCriticalSection(&timer->lock);
#else
	pthread_mutex_lock(&timer->lock);
	if (!timer->running) {
		pthread_mutex_unlock(&timer->lock);
		return 0;
	}
	timer->stop_requested = 1;
	pthread_mutex_unlock(&timer->lock);

	pthread_join(timer->thread, NULL);

	pthread_mutex_lock(&timer->lock);
	timer->running = 0;
	pthread_mutex_unlock(&timer->lock);
#endif
	return 0;
}

void platform_timer_delete(platform_timer_handle_t handle) {
	if (!handle) {
		return;
	}

	platform_timer_t *timer = (platform_timer_t *)handle;
	platform_timer_stop(handle);

#ifdef _WIN32
	DeleteCriticalSection(&timer->lock);
#else
	pthread_mutex_destroy(&timer->lock);
#endif
	free(timer);
}

void platform_delay_ms(uint32_t ms) {
#ifdef _WIN32
	Sleep(ms);
#else
	usleep(ms * 1000);
#endif
}
