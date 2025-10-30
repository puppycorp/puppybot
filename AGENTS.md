after changes run ./format.sh

if you make changes fleet folder run tests and build

if you make changes to esp32 code please run the build script also if you
make or modify tests in src folder run tests with test.sh. Also you should
setup the espidf environment by running . deps/espidf/export.sh
when making changes to esp32 code you should also consider making unit tests
with the test framework provided in test.h and test_main.c
dont use #ifdef \_\_cplusplus
extern "C" {
#endif we are pure c code.

If you make changes to android folder run the build.
