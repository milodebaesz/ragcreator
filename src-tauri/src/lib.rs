//! Entry point of the desktop app. `main.rs` is a one-line shim.
//!
//! The iPhone app is a separate native project (`ios/`); both work on the same
//! files in the app's iCloud Drive container — see `storage.rs`.

mod commands;
mod storage;

pub fn run() {
    tauri::Builder::default()
        .manage(commands::AppState)
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            commands::init_storage,
            commands::get_config,
            commands::create_project,
            commands::delete_project,
            commands::set_active_project,
            commands::set_pdf_path,
            commands::get_project_status,
            commands::get_guideline_info,
            commands::run_pipeline_step,
            commands::get_chunks,
            commands::get_qa_pairs,
            commands::search_chunks,
            commands::save_chunk,
            commands::delete_chunk,
            commands::pick_pdf,
            commands::get_env_config,
            commands::save_env_config,
            commands::open_external,
            commands::open_project_pdf,
            commands::locate_in_pdf,
            commands::export_chunks,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
