#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod commands;

use std::path::PathBuf;

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(commands::AppState {
            // CARGO_MANIFEST_DIR resolves to src-tauri/ at compile time;
            // its parent is the repo root containing medical_rag_project/.
            project_root: PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .parent()
                .expect("Cannot resolve repo root from CARGO_MANIFEST_DIR")
                .to_path_buf(),
        })
        .invoke_handler(tauri::generate_handler![
            commands::get_config,
            commands::create_project,
            commands::delete_project,
            commands::set_active_project,
            commands::set_pdf_path,
            commands::get_project_status,
            commands::run_pipeline_step,
            commands::get_chunks,
            commands::search_chunks,
            commands::pick_pdf,
            commands::get_env_config,
            commands::save_env_config,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
