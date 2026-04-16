use std::process::Command;

#[tauri::command]
fn get_project_root() -> String {
    // In dev: cwd is desktop/, project root is parent
    // In production: cwd is the app bundle location
    let cwd = std::env::current_dir().unwrap_or_default();
    let root = if cwd.ends_with("desktop") || cwd.ends_with("src-tauri") {
        cwd.ancestors()
            .find(|p| p.join("prompts").exists() || p.join(".kiro/agents").exists())
            .unwrap_or(&cwd)
            .to_path_buf()
    } else {
        cwd
    };
    root.to_string_lossy().to_string()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    if !check_libreoffice() {
        eprintln!("WARNING: LibreOffice not found. Preview and PPTX generation will not work.");
    }

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_fs::init())
        .invoke_handler(tauri::generate_handler![get_project_root])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

fn check_libreoffice() -> bool {
    if Command::new("libreoffice")
        .arg("--version")
        .output()
        .is_ok_and(|o| o.status.success())
    {
        return true;
    }
    #[cfg(target_os = "macos")]
    if std::path::Path::new("/Applications/LibreOffice.app").exists() {
        return true;
    }
    #[cfg(target_os = "windows")]
    if std::path::Path::new(r"C:\Program Files\LibreOffice\program\soffice.exe").exists() {
        return true;
    }
    false
}
