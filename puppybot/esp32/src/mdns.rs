use core::net::Ipv4Addr;

use embassy_net::{
    IpAddress, IpEndpoint, Ipv4Address, Stack,
    udp::{PacketMetadata, UdpSocket},
};
use embassy_time::{Duration, Timer};

const HOSTNAME: &str = "puppybot";
const INSTANCE_NAME: &str = "PuppyBot";
const SERVICE_TYPE: &str = "_ws._tcp.local";
const PORT: u16 = 80;
const TTL_SECONDS: u32 = 120;
const ADDR: Ipv4Addr = Ipv4Addr::new(224, 0, 0, 251);
const ENDPOINT: IpEndpoint = IpEndpoint::new(IpAddress::Ipv4(ADDR), 5353);

struct MdnsWriter<'a> {
    buf: &'a mut [u8],
    pos: usize,
}

impl<'a> MdnsWriter<'a> {
    fn new(buf: &'a mut [u8]) -> Self {
        Self { buf, pos: 0 }
    }

    fn len(&self) -> usize {
        self.pos
    }

    fn u8(&mut self, value: u8) -> Result<(), ()> {
        self.bytes(&[value])
    }

    fn u16(&mut self, value: u16) -> Result<(), ()> {
        self.bytes(&value.to_be_bytes())
    }

    fn u32(&mut self, value: u32) -> Result<(), ()> {
        self.bytes(&value.to_be_bytes())
    }

    fn bytes(&mut self, value: &[u8]) -> Result<(), ()> {
        let end = self.pos.checked_add(value.len()).ok_or(())?;
        if end > self.buf.len() {
            return Err(());
        }
        self.buf[self.pos..end].copy_from_slice(value);
        self.pos = end;
        Ok(())
    }

    fn name(&mut self, name: &str) -> Result<(), ()> {
        for label in name.trim_end_matches('.').split('.') {
            self.label(label)?;
        }
        self.u8(0)
    }

    fn label(&mut self, label: &str) -> Result<(), ()> {
        if label.is_empty() || label.len() > 63 {
            return Err(());
        }
        self.u8(label.len() as u8)?;
        self.bytes(label.as_bytes())
    }

    fn labels(&mut self, labels: &[&str]) -> Result<(), ()> {
        for label in labels {
            self.label(label)?;
        }
        self.u8(0)
    }

    fn host_name(&mut self) -> Result<(), ()> {
        self.labels(&[HOSTNAME, "local"])
    }

    fn instance_service_name(&mut self) -> Result<(), ()> {
        self.labels(&[INSTANCE_NAME, "_ws", "_tcp", "local"])
    }

    fn with_rdata(
        &mut self,
        write: impl FnOnce(&mut MdnsWriter<'_>) -> Result<(), ()>,
    ) -> Result<(), ()> {
        let len_pos = self.pos;
        self.u16(0)?;
        let data_start = self.pos;
        write(self)?;
        let data_len = self.pos.checked_sub(data_start).ok_or(())?;
        if data_len > u16::MAX as usize {
            return Err(());
        }
        self.buf[len_pos..len_pos + 2].copy_from_slice(&(data_len as u16).to_be_bytes());
        Ok(())
    }
}

fn write_a_record(writer: &mut MdnsWriter<'_>, address: Ipv4Address) -> Result<(), ()> {
    writer.host_name()?;
    writer.u16(1)?;
    writer.u16(0x8001)?;
    writer.u32(TTL_SECONDS)?;
    writer.with_rdata(|writer| writer.bytes(&address.octets()))
}

fn write_txt_record(writer: &mut MdnsWriter<'_>) -> Result<(), ()> {
    writer.instance_service_name()?;
    writer.u16(16)?;
    writer.u16(0x8001)?;
    writer.u32(TTL_SECONDS)?;
    writer.with_rdata(|writer| writer.u8(0))
}

fn write_srv_record(writer: &mut MdnsWriter<'_>) -> Result<(), ()> {
    writer.instance_service_name()?;
    writer.u16(33)?;
    writer.u16(0x8001)?;
    writer.u32(TTL_SECONDS)?;
    writer.with_rdata(|writer| {
        writer.u16(0)?;
        writer.u16(0)?;
        writer.u16(PORT)?;
        writer.host_name()
    })
}

fn write_ptr_record(writer: &mut MdnsWriter<'_>) -> Result<(), ()> {
    writer.name(SERVICE_TYPE)?;
    writer.u16(12)?;
    writer.u16(1)?;
    writer.u32(TTL_SECONDS)?;
    writer.with_rdata(|writer| writer.instance_service_name())
}

fn build_response(buf: &mut [u8], address: Ipv4Address) -> Result<usize, ()> {
    let mut writer = MdnsWriter::new(buf);

    writer.u16(0)?;
    writer.u16(0x8400)?;
    writer.u16(0)?;
    writer.u16(4)?;
    writer.u16(0)?;
    writer.u16(0)?;

    write_ptr_record(&mut writer)?;
    write_srv_record(&mut writer)?;
    write_txt_record(&mut writer)?;
    write_a_record(&mut writer, address)?;

    Ok(writer.len())
}

#[embassy_executor::task]
pub async fn responder(stack: Stack<'static>, address: Ipv4Address) {
    if let Err(err) = stack.join_multicast_group(ADDR) {
        log::warn!("failed to join mDNS multicast group: {:?}", err);
    }

    let mut rx_meta = [PacketMetadata::EMPTY; 4];
    let mut socket_rx_buffer = [0u8; 1024];
    let mut tx_meta = [PacketMetadata::EMPTY; 2];
    let mut tx_buffer = [0u8; 1024];
    let mut recv_buffer = [0u8; 1024];
    let mut socket = UdpSocket::new(
        stack,
        &mut rx_meta,
        &mut socket_rx_buffer,
        &mut tx_meta,
        &mut tx_buffer,
    );

    socket.set_hop_limit(Some(255));
    if let Err(err) = socket.bind(5353) {
        log::warn!("failed to bind mDNS socket: {:?}", err);
        return;
    }

    let mut packet = [0u8; 768];
    let mut announce_timer = Timer::after(Duration::from_secs(1));

    log::info!(
        "advertising mDNS service {}._ws._tcp.local on {}.local:{}",
        INSTANCE_NAME,
        HOSTNAME,
        PORT
    );

    loop {
        let recv = socket.recv_from(&mut recv_buffer);
        embassy_futures::select::select(recv, &mut announce_timer).await;

        match build_response(&mut packet, address) {
            Ok(len) => {
                if let Err(err) = socket.send_to(&packet[..len], ENDPOINT).await {
                    log::warn!("failed to send mDNS response: {:?}", err);
                }
            }
            Err(()) => log::warn!("failed to build mDNS response"),
        }

        announce_timer = Timer::after(Duration::from_secs(30));
    }
}
