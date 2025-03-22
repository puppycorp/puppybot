#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "test.h"

#define COLOR_RESET "\x1b[0m"
#define COLOR_GREEN "\x1b[32m"
#define COLOR_RED "\x1b[31m"
#define COLOR_YELLOW "\x1b[33m"
#define COLOR_CYAN "\x1b[36m"

typedef struct TestFailure {
    char *test_name;
    const char *expr;
    const char *file;
    int line;
    struct TestFailure *next;
} TestFailure;

const char *current_test = NULL;
Test *test_list = NULL;
TestFailure *failure_list = NULL;
int total_tests_run = 0, total_tests_failed = 0, current_test_failed = 0;

void record_failure(const char *test_name, const char *expr, const char *file, int line) {
    if (!current_test_failed) { total_tests_failed++; current_test_failed = 1; }
    TestFailure *f = malloc(sizeof(TestFailure));
    f->test_name = (char *)test_name;
    f->expr = expr;
    f->file = file;
    f->line = line;
    f->next = failure_list;
    failure_list = f;
}

void register_test(char *name, TestFunc func) {
    Test *t = malloc(sizeof(Test));
    t->name = name;
    t->func = func;
    t->next = test_list;
    test_list = t;
}

int fnmatch(const char *pattern, const char *string, int flags) {
    if (!pattern || pattern[0] == '\0')
        return 0;
    return (strstr(string, pattern) != NULL) ? 0 : 1;
}

int main(int argc, char **argv) {
    printf(COLOR_CYAN "running tests\n" COLOR_RESET);
    char *filter = (argc > 1) ? argv[1] : "";
	if (strlen(filter) > 0) printf(COLOR_YELLOW "filter: %s\n" COLOR_RESET, filter);
    int max_name_len = 0;
    for (Test *t = test_list; t; t = t->next) {
        int len = strlen(t->name);
        if (len > max_name_len) {
            max_name_len = len;
        }
    }
    clock_t total_start = clock();
    int test_index = 1;
    for (Test *t = test_list; t; t = t->next) {
        if (fnmatch(filter, t->name, 0) == 0) {
            current_test = t->name;
            current_test_failed = 0;
            printf(COLOR_CYAN "[%d] Running %-*s ... " COLOR_RESET, test_index, max_name_len, t->name);
            clock_t start = clock();
            t->func();
            clock_t end = clock();
            double elapsed = (double)(end - start) / CLOCKS_PER_SEC * 1000;
            total_tests_run++;
            printf(current_test_failed ? COLOR_RED "FAIL" : COLOR_GREEN "PASS");
            if (elapsed > 1.0) {
                printf(" (%.2f ms)", elapsed);
            }
            printf("\n" COLOR_RESET);
            test_index++;
        }
    }
    if (total_tests_run == 0) {
        printf(COLOR_RED "No tests matched filter: %s\n" COLOR_RESET, filter);
        return 1;
    }
    if (failure_list) {
        printf("\n" COLOR_RED "Failures:\n" COLOR_RESET);
        for (TestFailure *f = failure_list; f; f = f->next)
            printf(COLOR_RED "%s: %s, in %s:%d\n" COLOR_RESET, f->test_name, f->expr, f->file, f->line);
    }
    clock_t total_end = clock();
    double total_elapsed = (double)(total_end - total_start) / CLOCKS_PER_SEC * 1000;
    int total_passed = total_tests_run - total_tests_failed;
    printf("\nSummary: Total: %d, " COLOR_GREEN "Passed: %d" COLOR_RESET ", " COLOR_RED "Failed: %d" COLOR_RESET "\n", total_tests_run, total_passed, total_tests_failed);
    printf("Total time: %.2f ms\n", total_elapsed);
    if (total_tests_failed == 0) printf("\n" COLOR_GREEN "ALL TESTS PASSED!\n" COLOR_RESET);
    return failure_list ? 1 : 0;
}