use std::process::Command;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // Check LibreOffice on startup
    if !check_libreoffice() {
        eprintln!("WARNING: LibreOffice not found. Preview and PPTX generation will not work.");
        eprintln!("Run: desktop/scripts/install-libreoffice.sh (macOS/Linux) or .ps1 (Windows)");
    }

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

fn check_libreoffice() -> bool {
    // Check `libreoffice --version`
    if Command::new("libreoffice")
        .arg("--version")
        .output()
        .is_ok_and(|o| o.status.success())
    {
        return true;
    }
    // macOS: check /Applications
    #[cfg(target_os = "macos")]
    if std::path::Path::new("/Applications/LibreOffice.app").exists() {
        return true;
    }
    // Windows: check Program Files
    #[cfg(target_os = "windows")]
    if std::path::Path::new(r"C:\Program Files\LibreOffice\program\soffice.exe").exists() {
        return true;
    }
    false
}
