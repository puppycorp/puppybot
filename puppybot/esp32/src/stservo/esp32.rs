use puppybot_core::stservo::SerialBus;

pub struct EspUartBus<Dm>
where
    Dm: esp_hal::DriverMode,
{
    uart: esp_hal::uart::Uart<'static, Dm>,
}

impl<Dm> EspUartBus<Dm>
where
    Dm: esp_hal::DriverMode,
{
    pub fn new(uart: esp_hal::uart::Uart<'static, Dm>) -> Self {
        Self { uart }
    }
}

impl<Dm> SerialBus for EspUartBus<Dm>
where
    Dm: esp_hal::DriverMode,
{
    type Error = esp_hal::uart::IoError;

    fn write(&mut self, bytes: &[u8]) -> Result<usize, Self::Error> {
        self.uart.write(bytes).map_err(esp_hal::uart::IoError::Tx)
    }

    fn flush(&mut self) -> Result<(), Self::Error> {
        self.uart.flush().map_err(esp_hal::uart::IoError::Tx)
    }

    fn read_buffered(&mut self, bytes: &mut [u8]) -> Result<usize, Self::Error> {
        self.uart
            .read_buffered(bytes)
            .map_err(esp_hal::uart::IoError::Rx)
    }
}
