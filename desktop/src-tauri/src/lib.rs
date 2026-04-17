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

#[tauri::command]
fn open_path(path: String) -> Result<(), String> {
    open::that(&path).map_err(|e| e.to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    if !check_libreoffice() {
        eprintln!("WARNING: LibreOffice not found. Preview and PPTX generation will not work.");
    }

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_fs::init())
        .invoke_handler(tauri::generate_handler![get_project_root, open_path])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

fn check_libreoffice() -> bool {
    // Try: libreoffice on PATH, /Applications/LibreOffice.app (macOS), Program Files (Windows)
    let candidates: Vec<String> = {
        let mut v = vec!["libreoffice".to_string()];
        #[cfg(target_os = "macos")]
        v.push("/Applications/LibreOffice.app/Contents/MacOS/soffice".to_string());
        #[cfg(target_os = "windows")]
        v.push(r"C:\Program Files\LibreOffice\program\soffice.exe".to_string());
        v
    };
    for cmd in &candidates {
        if let Ok(out) = Command::new(cmd).arg("--version").output() {
            if out.status.success() {
                let s = String::from_utf8_lossy(&out.stdout);
                // Parse "LibreOffice 25.8.6.2 ..." -> (25, 8, 6)
                if let Some(ver) = s.split_whitespace().find(|p| p.contains('.') && p.chars().next().is_some_and(|c| c.is_ascii_digit())) {
                    let parts: Vec<&str> = ver.split('.').collect();
                    if parts.len() >= 3 {
                        let (ma, mi, pa) = (
                            parts[0].parse::<u32>().unwrap_or(0),
                            parts[1].parse::<u32>().unwrap_or(0),
                            parts[2].parse::<u32>().unwrap_or(0),
                        );
                        // Require 25.8.6+ (multi-slide SVG export fix)
                        let ok = ma > 25 || (ma == 25 && mi > 8) || (ma == 25 && mi == 8 && pa >= 6);
                        if !ok {
                            eprintln!("WARNING: LibreOffice {ver} is too old. Requires 25.8.6+ for SVG multi-slide export.");
                        }
                        return ok;
                    }
                }
                return true;
            }
        }
    }
    false
}
