#include "platform.h"
#include "timer.h"

#include "log.h"

#include <errno.h>
#include <limits.h>
#include <stdio.h>
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

#ifndef PUPPYBOT_BUILD_VERSION
#define PUPPYBOT_BUILD_VERSION "host-unknown"
#endif

static char g_host_bot_id[PLATFORM_BOT_ID_MAX_LEN];
static int g_host_bot_id_cached;

static char g_host_bot_id_file_path[PATH_MAX];
static int g_host_bot_id_file_initialized;

static const char *host_data_file(void) {
	if (g_host_bot_id_file_initialized) {
		return g_host_bot_id_file_path;
	}
	const char *env_path = getenv("PUPPYBOT_DATA_FILE");
	if (env_path && env_path[0]) {
		strncpy(g_host_bot_id_file_path, env_path,
		        sizeof(g_host_bot_id_file_path) - 1);
		g_host_bot_id_file_path[sizeof(g_host_bot_id_file_path) - 1] = '\0';
	} else {
		strncpy(g_host_bot_id_file_path, "puppybot.dat",
		        sizeof(g_host_bot_id_file_path) - 1);
		g_host_bot_id_file_path[sizeof(g_host_bot_id_file_path) - 1] = '\0';
	}
	g_host_bot_id_file_initialized = 1;
	return g_host_bot_id_file_path;
}

static void host_load_bot_id(void) {
	if (g_host_bot_id_cached) {
		return;
	}
	g_host_bot_id[0] = '\0';

	const char *file_path = host_data_file();
	if (file_path && file_path[0]) {
		FILE *file = fopen(file_path, "r");
		if (file) {
			char line[256];
			while (fgets(line, sizeof(line), file)) {
				char *newline = line;
				line[strcspn(line, "\r\n")] = '\0';
				while (newline[0] && newline[0] == ' ')
					newline++;
				if (newline[0] == '\0' || newline[0] == '#')
					continue;
				char *eq = strchr(newline, '=');
				if (!eq)
					continue;
				*eq = '\0';
				char *key = newline;
				char *value = eq + 1;
				while (*value == ' ')
					value++;
				if (strcmp(key, "bot_id") == 0) {
					size_t len = strnlen(value, PLATFORM_BOT_ID_MAX_LEN - 1);
					if (len > 0) {
						strncpy(g_host_bot_id, value,
						        sizeof(g_host_bot_id) - 1);
						g_host_bot_id[sizeof(g_host_bot_id) - 1] = '\0';
						break;
					}
				}
			}
			fclose(file);
		}
	}

	if (g_host_bot_id[0]) {
		g_host_bot_id_cached = 1;
		return;
	}

	const char *env_id = getenv("PUPPYBOT_BOT_ID");
	if (!env_id || env_id[0] == '\0') {
		env_id = getenv("PUPPYBOT_CLIENT_ID");
	}
	if (!env_id || env_id[0] == '\0') {
		env_id = "host";
	}
	size_t len = strnlen(env_id, PLATFORM_BOT_ID_MAX_LEN - 1);
	strncpy(g_host_bot_id, env_id, len);
	g_host_bot_id[len] = '\0';
	g_host_bot_id_cached = 1;
}

static int host_store_bot_id_to_file(const char *bot_id) {
	const char *file_path = host_data_file();
	if (!file_path || file_path[0] == '\0') {
		return -1;
	}
	FILE *file = fopen(file_path, "w");
	if (!file) {
		log_error(TAG,
		          "Failed to open bot ID file %s: %s",
		          file_path,
		          strerror(errno));
		return -1;
	}
	size_t len = strnlen(bot_id, PLATFORM_BOT_ID_MAX_LEN - 1);
	if (fprintf(file, "%.*s\n", (int)len, bot_id) < 0) {
		log_error(TAG, "Failed to write bot ID to %s", file_path);
		fclose(file);
		return -1;
	}
	fclose(file);
	return 0;
}

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
	if (env_version && env_version[0]) {
		return env_version;
	}
	return PUPPYBOT_BUILD_VERSION;
}

const char *platform_get_server_uri(void) {
	const char *uri = getenv("PUPPYBOT_SERVER_URI");
	if (uri && uri[0] != '\0') {
		return uri;
	}
	return NULL;
}

const char *platform_get_bot_id(void) {
	host_load_bot_id();
	return g_host_bot_id;
}

int platform_store_bot_id(const char *bot_id) {
	if (!bot_id || bot_id[0] == '\0') {
		return -1;
	}
	size_t len = strnlen(bot_id, PLATFORM_BOT_ID_MAX_LEN - 1);
	if (len == 0) {
		return -1;
	}
	char sanitized[PLATFORM_BOT_ID_MAX_LEN];
	memcpy(sanitized, bot_id, len);
	sanitized[len] = '\0';
	if (host_store_bot_id_to_file(sanitized) != 0) {
		return -1;
	}
	strncpy(g_host_bot_id, sanitized, sizeof(g_host_bot_id) - 1);
	g_host_bot_id[sizeof(g_host_bot_id) - 1] = '\0';
	g_host_bot_id_cached = 1;
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

int bluetooth_start(void) {
	log_info(TAG, "Skipping Bluetooth startup (host environment)");
	return 0;
}

PuppybotStatus platform_init(void) {
	log_info(TAG, "Initializing platform subsystems (host stubs)");
	return PUPPYBOT_OK;
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
