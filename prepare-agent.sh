sudo apt update
sudo apt-get update
sudo apt-get install -y git wget flex bison gperf python3 python3-pip \
     python3-venv cmake ninja-build ccache libffi-dev libssl-dev \
     dfu-util libusb-1.0-0 clang-format

mkdir -p ~/esp && cd ~/esp
git clone -b v5.4.1 --recursive https://github.com/espressif/esp-idf.git
cd ~/esp/esp-idf
./install.sh esp32
. $HOME/esp/esp-idf/export.sh