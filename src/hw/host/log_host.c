#include "log.h"

#include <stdarg.h>
#include <stdio.h>
#include <time.h>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#else
#include <sys/time.h>
#endif

static void format_timestamp(char *buffer, size_t size) {
#ifdef _WIN32
	SYSTEMTIME st;
	GetLocalTime(&st);
	snprintf(buffer, size, "%04u-%02u-%02u %02u:%02u:%02u.%03u", st.wYear,
	         st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond,
	         st.wMilliseconds);
#else
	struct timeval tv;
	gettimeofday(&tv, NULL);
	time_t seconds = tv.tv_sec;
	struct tm tm_info;
	localtime_r(&seconds, &tm_info);
	snprintf(buffer, size, "%04d-%02d-%02d %02d:%02d:%02d.%03ld",
	         tm_info.tm_year + 1900, tm_info.tm_mon + 1, tm_info.tm_mday,
	         tm_info.tm_hour, tm_info.tm_min, tm_info.tm_sec,
	         tv.tv_usec / 1000L);
#endif
}

static void log_message(const char *level, const char *tag, const char *format,
                        va_list args) {
	char timestamp[32];
	format_timestamp(timestamp, sizeof(timestamp));

	FILE *stream = stdout;
	if (level[0] == 'E') {
		stream = stderr;
	}

	fprintf(stream, "[%s] %s/%s: ", timestamp, level, tag ? tag : "PUPPY");
	vfprintf(stream, format, args);
	fprintf(stream, "\n");
	fflush(stream);
}

void log_info(const char *tag, const char *format, ...) {
	va_list args;
	va_start(args, format);
	log_message("INFO", tag, format, args);
	va_end(args);
}

void log_warn(const char *tag, const char *format, ...) {
	va_list args;
	va_start(args, format);
	log_message("WARN", tag, format, args);
	va_end(args);
}

void log_error(const char *tag, const char *format, ...) {
	va_list args;
	va_start(args, format);
	log_message("ERROR", tag, format, args);
	va_end(args);
}
