use embassy_futures::select::{Either, select};
use embassy_sync::blocking_mutex::raw::CriticalSectionRawMutex;
use esp_hal::efuse::{self, InterfaceMacAddress};
use esp_radio::ble::controller::BleConnector;
use trouble_host::prelude::*;

use crate::{app::PuppybotApp, puppyarm::task::IntentChannel};

const CONNECTIONS_MAX: usize = 1;
const L2CAP_CHANNELS_MAX: usize = 3;
const COMMAND_MAX_LEN: usize = 64;
const SERVICE_UUID_LE: [u8; 16] = [
    0xfb, 0x34, 0x9b, 0x5f, 0x80, 0x00, 0x00, 0x80, 0x00, 0x10, 0x00, 0x00, 0xff, 0x00, 0x00, 0x00,
];

#[gatt_server(
    connections_max = CONNECTIONS_MAX,
    mutex_type = CriticalSectionRawMutex,
    attribute_table_size = 16
)]
struct Server {
    control: ControlService,
}

#[gatt_service(uuid = "000000ff-0000-1000-8000-00805f9b34fb")]
struct ControlService {
    #[characteristic(
        uuid = "0000ff01-0000-1000-8000-00805f9b34fb",
        write,
        write_without_response
    )]
    command: heapless::Vec<u8, COMMAND_MAX_LEN>,
}

fn bluetooth_address() -> Address {
    let mac = efuse::interface_mac_address(InterfaceMacAddress::Bluetooth);
    let mut address: [u8; 6] = mac.as_bytes().try_into().unwrap();
    address.reverse();
    address[5] |= 0xc0;
    Address::random(address)
}

async fn handle_connection<P: PacketPool>(
    connection: GattConnection<'_, '_, P>,
    server: &Server<'_>,
    intents: &'static IntentChannel,
) {
    let mut app = PuppybotApp::new(0);
    let mut telemetry_enabled = false;

    loop {
        match connection.next().await {
            GattConnectionEvent::Disconnected { reason } => {
                log::info!("BLE disconnected: {:?}", reason);
                break;
            }
            GattConnectionEvent::Gatt {
                event: GattEvent::Write(event),
            } if event.handle() == server.control.command.handle => {
                let frame = event.data();
                let output = app.handle_frame(frame, &mut telemetry_enabled, intents);
                if output.events.is_empty() && output.response.is_none() {
                    log::warn!("BLE command ignored: {} bytes", frame.len());
                }
                match event.accept() {
                    Ok(reply) => reply.send().await,
                    Err(error) => log::warn!("BLE write response failed: {:?}", error),
                }
            }
            GattConnectionEvent::Gatt { event } => match event.accept() {
                Ok(reply) => reply.send().await,
                Err(error) => log::warn!("BLE GATT response failed: {:?}", error),
            },
            _ => {}
        }
    }
}

async fn advertise(
    mut peripheral: Peripheral<
        '_,
        ExternalController<BleConnector<'static>, 10>,
        DefaultPacketPool,
    >,
    server: &Server<'_>,
    intents: &'static IntentChannel,
) -> Result<(), BleHostError<esp_radio::ble::controller::BleConnectorError>> {
    let mut advertisement_data = [0; 31];
    let advertisement_len = AdStructure::encode_slice(
        &[
            AdStructure::Flags(LE_GENERAL_DISCOVERABLE | BR_EDR_NOT_SUPPORTED),
            AdStructure::ServiceUuids128(&[SERVICE_UUID_LE]),
        ],
        &mut advertisement_data,
    )?;
    let mut scan_data = [0; 31];
    let scan_data_len = AdStructure::encode_slice(
        &[AdStructure::CompleteLocalName(b"PuppyBot")],
        &mut scan_data,
    )?;

    loop {
        log::info!("BLE advertising as PuppyBot");
        let acceptor = peripheral
            .advertise(
                &Default::default(),
                Advertisement::ConnectableScannableUndirected {
                    adv_data: &advertisement_data[..advertisement_len],
                    scan_data: &scan_data[..scan_data_len],
                },
            )
            .await?;
        let connection = acceptor.accept().await?.with_attribute_server(server)?;
        log::info!("BLE control client connected");
        handle_connection(connection, server, intents).await;
    }
}

#[embassy_executor::task]
pub async fn ble_task(connector: BleConnector<'static>, intents: &'static IntentChannel) {
    static RESOURCES: static_cell::StaticCell<
        HostResources<DefaultPacketPool, CONNECTIONS_MAX, L2CAP_CHANNELS_MAX>,
    > = static_cell::StaticCell::new();

    let controller = ExternalController::<_, 10>::new(connector);
    let address = bluetooth_address();
    let stack = trouble_host::new(controller, RESOURCES.init(HostResources::new()))
        .set_random_address(address);
    let Host {
        peripheral,
        mut runner,
        ..
    } = stack.build();
    let server = Server::new_with_config(GapConfig::Peripheral(PeripheralConfig {
        name: "PuppyBot",
        appearance: &appearance::UNKNOWN,
    }))
    .unwrap();

    log::info!("BLE host started at {address}");
    match select(runner.run(), advertise(peripheral, &server, intents)).await {
        Either::First(result) => log::error!("BLE runner stopped: {:?}", result),
        Either::Second(result) => log::error!("BLE advertiser stopped: {:?}", result),
    }
}
