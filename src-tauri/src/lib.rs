//! Shared entry point for the desktop app and the iOS app.
//!
//! iOS launches a library, not a binary, so the whole setup lives here and
//! `main.rs` is a one-line shim for desktop. The two builds differ only in
//! which commands they expose: desktop gets the full pipeline, mobile gets a
//! read-only viewer over the project files synced to iCloud Drive.

mod commands;
mod storage;
#[cfg(desktop)]
mod sync;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let builder = tauri::Builder::default().manage(commands::AppState);

    #[cfg(desktop)]
    let builder = builder
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
            commands::get_guideline_outline,
            commands::get_guideline_section,
            commands::search_guideline,
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
            commands::get_pdf_location,
            commands::locate_in_pdf,
            commands::export_chunks,
            sync::sync_to_icloud,
            sync::get_icloud_status,
        ]);

    // No pipeline, no editing, no file dialogs: iOS has neither Python nor a
    // writable copy of the project it should be changing behind the desktop's
    // back. Leaving those commands out of the handler entirely means a stray
    // frontend call fails loudly instead of half-working.
    #[cfg(mobile)]
    let builder = builder
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            commands::init_storage,
            commands::get_config,
            commands::get_project_status,
            commands::get_guideline_info,
            commands::get_guideline_outline,
            commands::get_guideline_section,
            commands::search_guideline,
            commands::get_chunks,
            commands::get_qa_pairs,
            commands::search_chunks,
            commands::get_pdf_location,
            commands::open_external,
        ]);

    builder
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
