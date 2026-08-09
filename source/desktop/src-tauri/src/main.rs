#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{net::TcpStream, sync::Mutex, thread, time::Duration};
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_shell::{process::CommandChild, ShellExt};

struct BackendProcess(Mutex<Option<CommandChild>>);

fn wait_until_ready() -> bool {
    for _ in 0..240 {
        if TcpStream::connect("127.0.0.1:8787").is_ok() {
            return true;
        }
        thread::sleep(Duration::from_millis(250));
    }
    false
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_process::init())
        .manage(BackendProcess(Mutex::new(None)))
        .setup(|app| {
            let data_dir = app.path().app_local_data_dir()?;
            std::fs::create_dir_all(&data_dir)?;
            let command = app
                .shell()
                .sidecar("cinenode-backend")?
                .env("CINENODE_HOME", data_dir.to_string_lossy().to_string())
                .env("CINENODE_HOST", "127.0.0.1")
                .env("CINENODE_PORT", "8787")
                .args(["run", "--no-browser"]);
            let (_events, child) = command.spawn()?;
            *app.state::<BackendProcess>().0.lock().expect("backend mutex") = Some(child);
            let handle = app.handle().clone();
            thread::spawn(move || {
                if wait_until_ready() {
                    let _ = WebviewWindowBuilder::new(
                        &handle,
                        "main",
                        WebviewUrl::External("http://127.0.0.1:8787".parse().expect("local URL")),
                    )
                    .title("Avangard Visual")
                    .inner_size(1440.0, 920.0)
                    .min_inner_size(1024.0, 700.0)
                    .build();
                }
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if let Some(child) = window.app_handle().state::<BackendProcess>().0.lock().expect("backend mutex").take() {
                    let _ = child.kill();
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("failed to run Avangard Visual");
}
