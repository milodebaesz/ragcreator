//! Where the app's data lives, per platform.
//!
//! Desktop keeps working straight out of the repo checkout: the pipeline needs
//! `medical_rag_project/scripts` and the Python venv next to it, so the root is
//! the repo itself.
//!
//! iOS has no repo and no Python. It reads a copy of the project files that the
//! desktop app pushes into the app's iCloud Drive container (see `sync.rs`), so
//! the root there is that container's Documents directory. Both roots have the
//! same `medical_rag_project/...` layout underneath, which is what lets every
//! path helper and read-only command in `commands.rs` stay platform-agnostic.

use std::path::PathBuf;
use std::sync::OnceLock;

/// The app's iCloud Drive container. Must match `identifier` in
/// tauri.conf.json prefixed with `iCloud.`, and the entitlement in
/// `src-tauri/gen/apple/RAGCreator_iOS/RAGCreator_iOS.entitlements`.
pub const ICLOUD_CONTAINER: &str = "iCloud.com.ragcreator.app";

/// Folder name inside the container, mirroring the desktop layout so the same
/// path helpers work on both platforms.
pub const MED_DIR: &str = "medical_rag_project";

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
/// iCloud entitlement, which is exactly how RAGCreator is built during
/// development — but the directory itself is an ordinary path in the user's
/// home that any process may write to. Deriving it keeps `sync_to_icloud`
/// working without provisioning the desktop build.
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

/// The iCloud location the desktop app syncs *into*.
///
/// Desktop-only: on iOS the container is the data root itself, reached through
/// `data_root`.
#[cfg(desktop)]
pub fn icloud_target() -> Result<PathBuf, String> {
    if let Some(path) = ubiquity_container() {
        return Ok(path);
    }
    #[cfg(target_os = "macos")]
    if let Some(path) = mirrored_container() {
        return Ok(path);
    }
    Err("iCloud Drive is niet beschikbaar. Log in met je Apple-account en zet \
         iCloud Drive aan in Systeeminstellingen."
        .into())
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

static ROOT: OnceLock<PathBuf> = OnceLock::new();

/// Whether `ROOT` came from iCloud rather than a local fallback. Recorded while
/// resolving so nothing has to make the slow Foundation call twice.
static ROOT_IS_ICLOUD: OnceLock<bool> = OnceLock::new();

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

        #[cfg(not(target_os = "ios"))]
        {
            ROOT_IS_ICLOUD.set(false).ok();
            // CARGO_MANIFEST_DIR resolves to src-tauri/ at compile time;
            // its parent is the repo root containing medical_rag_project/.
            PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .parent()
                .expect("Cannot resolve repo root from CARGO_MANIFEST_DIR")
                .to_path_buf()
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

#[cfg(test)]
mod tests {
    use super::*;

    /// Exercises the Foundation call for real. Its result depends on the
    /// machine's iCloud state, so the assertion is only that it does not crash
    /// and that macOS always ends up with a usable target.
    #[test]
    #[cfg(target_os = "macos")]
    fn icloud_target_resolves_on_macos() {
        let target = icloud_target().expect("macOS always has the mirrored path");
        assert!(target.ends_with("Documents"), "got {}", target.display());
        assert!(target.is_absolute());
    }

    #[test]
    fn container_maps_to_its_on_disk_folder_name() {
        assert_eq!(
            ICLOUD_CONTAINER.replace('.', "~"),
            "iCloud~com~ragcreator~app"
        );
    }
}
