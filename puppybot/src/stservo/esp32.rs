use super::SerialBus;

impl<Dm> SerialBus for esp_hal::uart::Uart<'_, Dm>
where
    Dm: esp_hal::DriverMode,
{
    type Error = esp_hal::uart::IoError;

    fn write(&mut self, bytes: &[u8]) -> Result<usize, Self::Error> {
        self.write(bytes).map_err(esp_hal::uart::IoError::Tx)
    }

    fn flush(&mut self) -> Result<(), Self::Error> {
        self.flush().map_err(esp_hal::uart::IoError::Tx)
    }

    fn read_buffered(&mut self, bytes: &mut [u8]) -> Result<usize, Self::Error> {
        self.read_buffered(bytes)
            .map_err(esp_hal::uart::IoError::Rx)
    }
}
