fn main() {
    println!("cargo:rerun-if-env-changed=WIFI_SSID");
    println!("cargo:rerun-if-env-changed=WIFI_PASSWORD");
    println!("cargo:rerun-if-changed=.env");

    let ssid = std::env::var("WIFI_SSID").unwrap_or_default();
    let password = std::env::var("WIFI_PASSWORD").unwrap_or_default();

    println!("cargo:rustc-env=WIFI_SSID={ssid}");
    println!("cargo:rustc-env=WIFI_PASSWORD={password}");
}
