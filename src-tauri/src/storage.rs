//! Where the app's data lives, per platform.
//!
//! Both apps work on one copy of the data: the app's iCloud Drive container
//! (shown as "RAGCreator" in iCloud Drive). The desktop app runs the pipeline
//! straight into it and the iOS app reads from it, so nothing has to be pushed
//! from one to the other.
//!
//! Code stays out of iCloud. The pipeline needs `medical_rag_project/scripts`,
//! the Python venv, `.env` and the git-tracked `guidelines_registry.json`, so
//! on desktop those are resolved against the repo checkout (`code_root`) while
//! everything the pipeline produces lives under the data root (`data_root`).
//!
//! Both roots have the same `medical_rag_project/...` layout underneath, which
//! is what lets every path helper and read-only command in `commands.rs` stay
//! platform-agnostic.
//!
//! Fallbacks, when the container is not there: desktop keeps using the repo
//! checkout, iOS its own Documents folder (visible in the Files app).

use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use std::time::{Duration, Instant};

/// The app's iCloud Drive container. Must match `identifier` in
/// tauri.conf.json prefixed with `iCloud.`, and the entitlement in
/// `src-tauri/gen/apple/project.yml`.
pub const ICLOUD_CONTAINER: &str = "iCloud.com.ragcreator.app";

/// Folder name inside the container, mirroring the desktop layout so the same
/// path helpers work on both platforms.
pub const MED_DIR: &str = "medical_rag_project";

/// Everything under `medical_rag_project/` that is data rather than code.
///
/// `rag_config.json` comes last on purpose: a migration copies in this order,
/// and a config on the iCloud side is what marks the move as finished.
#[cfg(desktop)]
const DATA_ENTRIES: [&str; 4] = ["projects", "normalized", "data", "rag_config.json"];

/// Where a migration leaves the repo's copy of the data, inside
/// `medical_rag_project/`. Moved aside rather than deleted: it is the only
/// backup until iCloud has uploaded everything.
#[cfg(desktop)]
pub const BACKUP_DIR: &str = ".pre-icloud-backup";

/// Ask Foundation for the iCloud container's on-disk location.
///
/// Returns `None` when iCloud is unavailable: signed out, the entitlement is
/// missing, or the container has not been provisioned yet. Callers must have a
/// fallback — this is a normal outcome, not an error.
///
/// Apple documents this call as potentially slow on first use (it may have to
/// create the container), so it must not run on the main thread; every caller
/// reaches it through `resolve_blocking`.
#[cfg(any(target_os = "ios", target_os = "macos"))]
fn ubiquity_container() -> Option<PathBuf> {
    use objc2::rc::autoreleasepool;
    use objc2::runtime::AnyObject;
    use objc2::{class, msg_send};
    use std::ffi::{CStr, CString};

    let id = CString::new(ICLOUD_CONTAINER).ok()?;

    autoreleasepool(|_| unsafe {
        let ns_id: *mut AnyObject =
            msg_send![class!(NSString), stringWithUTF8String: id.as_ptr()];
        if ns_id.is_null() {
            return None;
        }

        let manager: *mut AnyObject = msg_send![class!(NSFileManager), defaultManager];
        let url: *mut AnyObject = msg_send![manager, URLForUbiquityContainerIdentifier: ns_id];
        if url.is_null() {
            return None;
        }

        let ns_path: *mut AnyObject = msg_send![url, path];
        if ns_path.is_null() {
            return None;
        }

        let utf8: *const std::os::raw::c_char = msg_send![ns_path, UTF8String];
        if utf8.is_null() {
            return None;
        }

        let path = CStr::from_ptr(utf8).to_str().ok()?;
        Some(PathBuf::from(path).join("Documents"))
    })
}

#[cfg(not(any(target_os = "ios", target_os = "macos")))]
fn ubiquity_container() -> Option<PathBuf> {
    None
}

/// The path iCloud Drive mirrors a container to inside a Mac's home directory.
///
/// The Foundation call above returns `None` for an unsigned dev build with no
/// iCloud entitlement, which is exactly how the desktop app is built — but the
/// directory itself is an ordinary path in the user's home that any process
/// may write to.
#[cfg(target_os = "macos")]
fn mirrored_container() -> Option<PathBuf> {
    // "iCloud.com.ragcreator.app" is stored on disk as "iCloud~com~ragcreator~app".
    let folder = ICLOUD_CONTAINER.replace('.', "~");
    std::env::var_os("HOME").map(|home| {
        PathBuf::from(home)
            .join("Library/Mobile Documents")
            .join(folder)
            .join("Documents")
    })
}

/// The container's Documents folder on this Mac, once iCloud has created it.
///
/// The container folder only appears after the iOS app has run once with the
/// iCloud entitlement. Until then the desktop app does not create it by hand:
/// iCloud does not sync a folder it never provisioned, so data written there
/// would look safe while living on this Mac only.
#[cfg(desktop)]
fn desktop_container() -> Option<PathBuf> {
    #[cfg(target_os = "macos")]
    {
        let docs = ubiquity_container().or_else(mirrored_container)?;
        docs.parent().filter(|c| c.is_dir())?;
        Some(docs)
    }
    #[cfg(not(target_os = "macos"))]
    {
        None
    }
}

/// The repo checkout holding `medical_rag_project/scripts`, the venv and `.env`.
#[cfg(desktop)]
pub fn code_root() -> PathBuf {
    // CARGO_MANIFEST_DIR resolves to src-tauri/ at compile time; its parent is
    // the repo root containing medical_rag_project/.
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("Cannot resolve repo root from CARGO_MANIFEST_DIR")
        .to_path_buf()
}

/// Documents directory inside the app's own sandbox.
///
/// The iOS fallback when iCloud is unavailable. `UIFileSharingEnabled` and
/// `LSSupportsOpeningDocumentsInPlace` expose it in the Files app, so a user
/// without iCloud can still drop project folders in by hand.
#[cfg(target_os = "ios")]
fn local_documents() -> PathBuf {
    std::env::var_os("HOME")
        .map(|home| PathBuf::from(home).join("Documents"))
        .unwrap_or_else(|| PathBuf::from("/Documents"))
}

// ── Moving the desktop data into iCloud ──────────────────────────────────────

/// Copy a file or directory tree, returning the bytes copied.
#[cfg(desktop)]
fn copy_tree(from: &Path, to: &Path) -> Result<u64, String> {
    if from.is_dir() {
        std::fs::create_dir_all(to).map_err(|e| format!("{}: {}", to.display(), e))?;
        let mut bytes = 0;
        let entries = std::fs::read_dir(from).map_err(|e| format!("{}: {}", from.display(), e))?;
        for entry in entries.flatten() {
            if entry.file_name() == ".DS_Store" {
                continue;
            }
            bytes += copy_tree(&entry.path(), &to.join(entry.file_name()))?;
        }
        Ok(bytes)
    } else {
        if let Some(parent) = to.parent() {
            std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        std::fs::copy(from, to).map_err(|e| format!("{} → {}: {}", from.display(), to.display(), e))
    }
}

/// Move the desktop's data out of the repo into the iCloud container, once.
///
/// `from` and `to` are the two `medical_rag_project/` folders. Nothing happens
/// when iCloud already has a config (moved before, or filled from elsewhere) or
/// when the repo has nothing to move. The originals are only moved aside after
/// every copy succeeded, so an interrupted run leaves the repo intact and is
/// simply repeated on the next launch.
///
/// Returns a line for the settings screen when something moved.
#[cfg(desktop)]
fn migrate(from: &Path, to: &Path) -> Result<Option<String>, String> {
    std::fs::create_dir_all(to.join("projects"))
        .map_err(|e| format!("Kon {} niet aanmaken: {}", to.display(), e))?;

    if to.join("rag_config.json").exists() || !from.join("rag_config.json").exists() {
        return Ok(None);
    }

    let mut bytes = 0;
    for entry in DATA_ENTRIES {
        let src = from.join(entry);
        if src.exists() {
            bytes += copy_tree(&src, &to.join(entry))?;
        }
    }

    // Everything is in iCloud now. Moving the repo copy aside keeps the app and
    // the scripts from ever reading stale data from it.
    let backup = from.join(BACKUP_DIR);
    let mut left_behind = vec![];
    for entry in DATA_ENTRIES {
        let src = from.join(entry);
        if !src.exists() {
            continue;
        }
        let moved = std::fs::create_dir_all(&backup)
            .and_then(|_| std::fs::rename(&src, backup.join(entry)));
        if moved.is_err() {
            left_behind.push(entry);
        }
    }

    let mut note = format!(
        "{:.1} MB van de repo naar iCloud verplaatst. De oude kopie staat in {}.",
        bytes as f64 / 1024.0 / 1024.0,
        backup.display()
    );
    if !left_behind.is_empty() {
        note.push_str(&format!(
            " Niet opzijgezet (wordt niet meer gebruikt): {}.",
            left_behind.join(", ")
        ));
    }
    Ok(Some(note))
}

// ── Files iCloud has not downloaded ──────────────────────────────────────────
//
// iCloud leaves `.name.icloud` in place of a file it has not downloaded yet or
// has evicted to free space. Code that checks `exists()` reads that as "no
// file", and a save would then write a fresh file over data that is only
// temporarily absent. On current macOS iCloud Drive downloads on first read and
// these placeholders do not appear, but iOS still uses them.

/// How long a read waits for iCloud to deliver a single file.
const DOWNLOAD_WAIT: Duration = Duration::from_secs(30);

fn placeholder_for(path: &Path) -> Option<PathBuf> {
    let name = path.file_name()?.to_str()?;
    Some(path.with_file_name(format!(".{}.icloud", name)))
}

/// The file a `.name.icloud` placeholder stands for, or `None` for any other path.
pub fn real_path_of(placeholder: &Path) -> Option<PathBuf> {
    let name = placeholder.file_name()?.to_str()?;
    let inner = name.strip_prefix('.')?.strip_suffix(".icloud")?;
    if inner.is_empty() {
        return None;
    }
    Some(placeholder.with_file_name(inner))
}

/// Ask iCloud to download `path`. Returns immediately; the file arrives later.
#[cfg(any(target_os = "ios", target_os = "macos"))]
fn request_download(path: &Path) {
    use objc2::rc::autoreleasepool;
    use objc2::runtime::AnyObject;
    use objc2::{class, msg_send};
    use std::ffi::CString;

    let Some(c_path) = path.to_str().and_then(|s| CString::new(s).ok()) else {
        return;
    };

    autoreleasepool(|_| unsafe {
        let ns_path: *mut AnyObject =
            msg_send![class!(NSString), stringWithUTF8String: c_path.as_ptr()];
        if ns_path.is_null() {
            return;
        }
        let url: *mut AnyObject = msg_send![class!(NSURL), fileURLWithPath: ns_path];
        if url.is_null() {
            return;
        }
        let manager: *mut AnyObject = msg_send![class!(NSFileManager), defaultManager];
        // A failure here shows up as the file still missing after the wait.
        let _: bool = msg_send![
            manager,
            startDownloadingUbiquitousItemAtURL: url,
            error: std::ptr::null_mut::<*mut AnyObject>()
        ];
    });
}

#[cfg(not(any(target_os = "ios", target_os = "macos")))]
fn request_download(_path: &Path) {}

/// Poll until every path exists or `timeout` passes; returns how many are missing.
fn wait_for(paths: &[PathBuf], timeout: Duration) -> usize {
    let start = Instant::now();
    loop {
        let missing = paths.iter().filter(|p| !p.exists()).count();
        if missing == 0 || start.elapsed() >= timeout {
            return missing;
        }
        std::thread::sleep(Duration::from_millis(250));
    }
}

fn collect_placeholders(dir: &Path, out: &mut Vec<PathBuf>) {
    let Ok(entries) = std::fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            collect_placeholders(&path, out);
        } else if let Some(real) = real_path_of(&path) {
            out.push(real);
        }
    }
}

/// Make sure `path` is on disk if iCloud has it, downloading it first.
///
/// Returns whether the file exists afterwards. Costs one `stat` when the file
/// is already there, so it is safe to call before every read.
pub fn ensure_local(path: &Path) -> bool {
    if path.exists() {
        return true;
    }
    match placeholder_for(path) {
        Some(placeholder) if placeholder.exists() => {
            request_download(path);
            wait_for(&[path.to_path_buf()], DOWNLOAD_WAIT) == 0
        }
        _ => false,
    }
}

/// True when iCloud has `path` but it is not on disk (yet).
///
/// Writers check this after `ensure_local`: writing then would replace real
/// data with whatever the writer thinks an empty file should hold.
pub fn is_pending(path: &Path) -> bool {
    !path.exists() && placeholder_for(path).map_or(false, |p| p.exists())
}

/// Download everything iCloud is holding back under `dir`.
///
/// Waits up to `timeout` and returns how many files are still pending.
pub fn ensure_tree(dir: &Path, timeout: Duration) -> usize {
    let mut pending = vec![];
    collect_placeholders(dir, &mut pending);
    if pending.is_empty() {
        return 0;
    }
    for path in &pending {
        request_download(path);
    }
    wait_for(&pending, timeout)
}

// ── Resolving the root ───────────────────────────────────────────────────────

static ROOT: OnceLock<PathBuf> = OnceLock::new();

/// Whether `ROOT` came from iCloud rather than a local fallback. Recorded while
/// resolving so nothing has to make the slow Foundation call twice.
static ROOT_IS_ICLOUD: OnceLock<bool> = OnceLock::new();

/// Why the data is not in iCloud, or what the migration did. For the UI.
static NOTE: OnceLock<Option<String>> = OnceLock::new();

/// Resolve the data root once, blocking as long as Foundation needs.
///
/// Call from a blocking context (see `commands::init_storage`); afterwards
/// `data_root` is a cheap lookup.
pub fn resolve_blocking() -> PathBuf {
    ROOT.get_or_init(|| {
        #[cfg(target_os = "ios")]
        {
            let cloud = ubiquity_container();
            ROOT_IS_ICLOUD.set(cloud.is_some()).ok();
            let root = cloud.unwrap_or_else(local_documents);
            // The container's Documents folder does not exist until something
            // writes to it, and every read below joins onto it.
            std::fs::create_dir_all(root.join(MED_DIR).join("projects")).ok();
            root
        }

        #[cfg(desktop)]
        {
            let repo = code_root();
            let (root, cloud, note) = match desktop_container() {
                None => (
                    repo,
                    false,
                    Some(
                        "De iCloud-map van RAGCreator bestaat nog niet op deze Mac, dus de \
                         data staat nog in de repo. Start de iOS-app één keer met iCloud \
                         aan; bij de volgende start verhuist de data vanzelf."
                            .to_string(),
                    ),
                ),
                // Tests must never move the real data around; they only follow
                // it into iCloud once the app has moved it there.
                Some(cloud) if cfg!(test) => {
                    if cloud.join(MED_DIR).join("rag_config.json").exists() {
                        (cloud, true, None)
                    } else {
                        (repo, false, None)
                    }
                }
                Some(cloud) => match migrate(&repo.join(MED_DIR), &cloud.join(MED_DIR)) {
                    Ok(note) => (cloud, true, note),
                    Err(e) => (
                        repo,
                        false,
                        Some(format!(
                            "Verhuizen naar iCloud is mislukt, de app werkt nog vanuit de \
                             repo: {}",
                            e
                        )),
                    ),
                },
            };
            ROOT_IS_ICLOUD.set(cloud).ok();
            NOTE.set(note).ok();
            root
        }
    })
    .clone()
}

/// The data root, resolving it on first use if `resolve_blocking` has not run.
pub fn data_root() -> PathBuf {
    resolve_blocking()
}

/// True when the data root came from iCloud rather than a local fallback.
pub fn using_icloud() -> bool {
    resolve_blocking();
    *ROOT_IS_ICLOUD.get().unwrap_or(&false)
}

/// Why the data is not in iCloud, or what the migration moved.
pub fn note() -> Option<String> {
    resolve_blocking();
    NOTE.get().cloned().flatten()
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A scratch directory that cleans itself up.
    struct Temp(PathBuf);

    impl Temp {
        fn new(tag: &str) -> Self {
            let dir = std::env::temp_dir().join(format!(
                "ragcreator-storage-{}-{}",
                tag,
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap()
                    .as_nanos()
            ));
            std::fs::create_dir_all(&dir).unwrap();
            Temp(dir)
        }
    }

    impl Drop for Temp {
        fn drop(&mut self) {
            std::fs::remove_dir_all(&self.0).ok();
        }
    }

    /// A repo-side `medical_rag_project/` with data and code side by side.
    fn make_repo(root: &Path) -> PathBuf {
        let med = root.join(MED_DIR);
        let project = med.join("projects").join("ESC HF");
        std::fs::create_dir_all(&project).unwrap();
        std::fs::write(project.join("rag_chunks.json"), "[{\"id\":\"r1\"}]").unwrap();
        std::fs::write(project.join("qa_pairs.json"), "[]").unwrap();
        std::fs::create_dir_all(med.join("normalized")).unwrap();
        std::fs::write(med.join("normalized").join("esc-hf.embeddings.json"), "[]").unwrap();
        std::fs::write(med.join("rag_config.json"), "{\"active\":\"ESC HF\"}").unwrap();
        std::fs::create_dir_all(med.join("scripts")).unwrap();
        std::fs::write(med.join("scripts").join("step.py"), "").unwrap();
        std::fs::write(med.join(".env"), "OPENAI_API_KEY=sk-x").unwrap();
        std::fs::write(med.join("guidelines_registry.json"), "{}").unwrap();
        med
    }

    #[test]
    fn migration_moves_all_data_and_leaves_code_and_secrets() {
        let repo = Temp::new("repo");
        let cloud = Temp::new("cloud");
        let from = make_repo(&repo.0);
        let to = cloud.0.join(MED_DIR);

        let note = migrate(&from, &to).unwrap();
        assert!(note.is_some());

        assert!(to.join("rag_config.json").exists());
        assert!(to.join("projects/ESC HF/rag_chunks.json").exists());
        assert!(to.join("projects/ESC HF/qa_pairs.json").exists());
        assert!(to.join("normalized/esc-hf.embeddings.json").exists());
        assert!(!to.join("scripts").exists());
        assert!(!to.join(".env").exists());
        assert!(!to.join("guidelines_registry.json").exists());

        // The repo copy is out of the way but not gone.
        assert!(!from.join("projects").exists());
        assert!(!from.join("rag_config.json").exists());
        assert!(from.join(BACKUP_DIR).join("projects/ESC HF/rag_chunks.json").exists());
        assert!(from.join("scripts/step.py").exists());
        assert!(from.join(".env").exists());
    }

    #[test]
    fn migration_never_overwrites_data_already_in_icloud() {
        let repo = Temp::new("repo2");
        let cloud = Temp::new("cloud2");
        let from = make_repo(&repo.0);
        let to = cloud.0.join(MED_DIR);
        std::fs::create_dir_all(&to).unwrap();
        std::fs::write(to.join("rag_config.json"), "{\"active\":\"iCloud\"}").unwrap();

        assert!(migrate(&from, &to).unwrap().is_none());
        assert_eq!(
            std::fs::read_to_string(to.join("rag_config.json")).unwrap(),
            "{\"active\":\"iCloud\"}"
        );
        assert!(from.join("projects").exists(), "repo data must stay put");
    }

    /// The iOS app creates `projects/` in the container on first launch; that
    /// alone must not count as "already migrated".
    #[test]
    fn an_empty_container_from_the_ios_app_still_gets_the_data() {
        let repo = Temp::new("repo3");
        let cloud = Temp::new("cloud3");
        let from = make_repo(&repo.0);
        let to = cloud.0.join(MED_DIR);
        std::fs::create_dir_all(to.join("projects")).unwrap();

        assert!(migrate(&from, &to).unwrap().is_some());
        assert!(to.join("projects/ESC HF/rag_chunks.json").exists());
    }

    #[test]
    fn placeholders_map_to_the_file_they_stand_for() {
        let dir = Path::new("/x/projects/ESC HF");
        assert_eq!(
            real_path_of(&dir.join(".rag_chunks.json.icloud")),
            Some(dir.join("rag_chunks.json"))
        );
        assert_eq!(
            placeholder_for(&dir.join("qa_pairs.json")),
            Some(dir.join(".qa_pairs.json.icloud"))
        );
        assert_eq!(real_path_of(&dir.join(".DS_Store")), None);
        assert_eq!(real_path_of(&dir.join("..icloud")), None);
    }

    #[test]
    fn a_missing_file_without_placeholder_returns_at_once() {
        let dir = Temp::new("missing");
        let start = Instant::now();
        assert!(!ensure_local(&dir.0.join("rag_chunks.json")));
        assert!(start.elapsed() < Duration::from_secs(1));
    }

    /// objc2 checks message signatures in debug builds; a wrong argument or
    /// return type would panic here rather than on a phone.
    #[test]
    fn requesting_a_download_outside_icloud_is_harmless() {
        let dir = Temp::new("download");
        let file = dir.0.join("plain.json");
        std::fs::write(&file, "{}").unwrap();
        request_download(&file);
        request_download(&dir.0.join("missing.json"));
        assert_eq!(ensure_tree(&dir.0, Duration::from_millis(10)), 0);
    }

    #[test]
    fn container_maps_to_its_on_disk_folder_name() {
        assert_eq!(
            ICLOUD_CONTAINER.replace('.', "~"),
            "iCloud~com~ragcreator~app"
        );
    }
}
