#include "http.h"
#include "log.h"
#include "main.h"
#include "platform.h"
#include "timer.h"

#include <signal.h>
#include <stdbool.h>
#include <stdint.h>

static volatile sig_atomic_t keep_running = 1;

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
static BOOL WINAPI console_ctrl_handler(DWORD ctrl_type) {
	(void)ctrl_type;
	keep_running = 0;
	return TRUE;
}
#else
#include <signal.h>
static void signal_handler(int signo) {
	(void)signo;
	keep_running = 0;
}
#endif

int main(void) {
#ifdef _WIN32
	SetConsoleCtrlHandler(console_ctrl_handler, TRUE);
#else
	struct sigaction sa;
	sa.sa_handler = signal_handler;
	sigemptyset(&sa.sa_mask);
	sa.sa_flags = 0;
	sigaction(SIGINT, &sa, NULL);
	sigaction(SIGTERM, &sa, NULL);
#endif

	PuppybotStatus status = puppybot_main();
	if (status != PUPPYBOT_OK) {
		log_error("MAIN", "puppybot_main failed with status %d", status);
		return 1;
	}

	log_info("MAIN", "Puppybot initialized. Press Ctrl+C to exit.");

	while (keep_running) {
		platform_delay_ms(100);
	}

	log_info("MAIN", "Shutdown signal received, stopping WebSocket client.");
	ws_client_shutdown();

	log_info("MAIN", "Goodbye.");
	return 0;
}
