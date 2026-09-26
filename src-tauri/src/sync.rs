//! Pushing a project into iCloud Drive so the iOS app can read it.
//!
//! Desktop-only: this is the writing half of the bridge. It mirrors the parts
//! of `medical_rag_project/` that the read-only iOS commands need into the
//! app's iCloud container, keeping the exact same directory layout so no path
//! logic has to differ per platform.
//!
//! Everything the pipeline needs but the viewer does not — scripts, the venv,
//! `.env`, embeddings, QA pairs — deliberately stays out of iCloud.

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use serde::Serialize;
use tauri::State;

use crate::commands::{AppState, Config, ProjectMeta};
use crate::storage::{icloud_target, MED_DIR};

/// Files copied per project.
///
/// `guideline.md` carries the reference list, `rag_chunks.json` the
/// recommendations, `pdf_pages.json` the page each recommendation was found on
/// (so iOS can deep-link into the PDF without running PyMuPDF).
const PROJECT_FILES: [&str; 4] = [
    "rag_chunks.json",
    "guideline.md",
    "pdf_pages.json",
    "extraction_report.txt",
];

/// Files copied when they happen to be there, without being reported missing
/// when they are not.
///
/// `qa_pairs.json` only exists once pipeline step 3 has run, which is optional:
/// a project can be perfectly usable on the phone without it.
const OPTIONAL_FILES: [&str; 1] = ["qa_pairs.json"];

#[derive(Serialize)]
pub struct ProjectSync {
    pub project: String,
    pub copied: Vec<String>,
    pub skipped: Vec<String>,
    pub missing: Vec<String>,
}

#[derive(Serialize)]
pub struct SyncReport {
    /// Absolute path written to, so the UI can show where the files landed.
    pub target: String,
    pub projects: Vec<ProjectSync>,
    pub bytes_copied: u64,
}

/// Copy `from` to `to` unless an identical-looking file is already there.
///
/// Size plus modification time is enough: these files are only ever produced by
/// the pipeline, never edited on the iCloud side. Skipping unchanged files
/// matters mostly for the PDFs, which are megabytes each and would otherwise be
/// re-uploaded on every sync.
fn copy_if_changed(from: &Path, to: &Path) -> Result<Option<u64>, String> {
    let src = std::fs::metadata(from).map_err(|e| format!("{}: {}", from.display(), e))?;

    if let Ok(dst) = std::fs::metadata(to) {
        let same_size = dst.len() == src.len();
        let up_to_date = match (src.modified(), dst.modified()) {
            (Ok(a), Ok(b)) => b >= a,
            _ => false,
        };
        if same_size && up_to_date {
            return Ok(None);
        }
    }

    if let Some(parent) = to.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    std::fs::copy(from, to).map_err(|e| format!("{} → {}: {}", from.display(), to.display(), e))?;
    Ok(Some(src.len()))
}

/// Mirror projects from one `medical_rag_project/` tree into another.
///
/// The command below is a thin wrapper around this; keeping the copying free of
/// `State` and `AppHandle` is what lets it be tested against real project data.
/// `pdf_for` resolves a project's source PDF, which may live anywhere on disk.
fn sync_projects(
    med_src: &Path,
    med_dst: &Path,
    config: &Config,
    wanted: &[String],
    include_pdf: bool,
    pdf_for: impl Fn(&str) -> Option<PathBuf>,
) -> Result<SyncReport, String> {
    std::fs::create_dir_all(med_dst.join("projects")).map_err(|e| {
        format!(
            "Kon de iCloud-map niet aanmaken ({}): {}",
            med_dst.display(),
            e
        )
    })?;

    let mut report = SyncReport {
        target: med_dst.to_string_lossy().into_owned(),
        projects: vec![],
        bytes_copied: 0,
    };

    // Rebuilt rather than copied: absolute pdf_path values from this Mac mean
    // nothing inside an iOS sandbox and would make the app look for a file it
    // can never reach. The iOS side finds the PDF by scanning the project dir.
    let mut mobile_meta: HashMap<String, ProjectMeta> = HashMap::new();

    for project in wanted {
        let src_dir = med_src.join("projects").join(project);
        let dst_dir = med_dst.join("projects").join(project);
        let mut entry = ProjectSync {
            project: project.clone(),
            copied: vec![],
            skipped: vec![],
            missing: vec![],
        };

        let meta = config.project_meta.get(project).cloned().unwrap_or_default();
        let mut names: Vec<String> = PROJECT_FILES.iter().map(|s| s.to_string()).collect();
        let mut pdf_name = None;

        if include_pdf {
            match pdf_for(project) {
                Some(pdf) => {
                    let name = pdf
                        .file_name()
                        .map(|n| n.to_string_lossy().into_owned())
                        .unwrap_or_else(|| format!("{}.pdf", project));
                    // The PDF may live outside the project dir (a path the user
                    // picked), so it is copied by absolute path, not by name.
                    match copy_if_changed(&pdf, &dst_dir.join(&name))? {
                        Some(bytes) => {
                            report.bytes_copied += bytes;
                            entry.copied.push(name.clone());
                        }
                        None => entry.skipped.push(name.clone()),
                    }
                    names.retain(|n| n != &name);
                    pdf_name = Some(name);
                }
                None => entry.missing.push("PDF".into()),
            }
        }

        for name in &names {
            let src = src_dir.join(name);
            if !src.exists() {
                entry.missing.push(name.clone());
                continue;
            }
            match copy_if_changed(&src, &dst_dir.join(name))? {
                Some(bytes) => {
                    report.bytes_copied += bytes;
                    entry.copied.push(name.clone());
                }
                None => entry.skipped.push(name.clone()),
            }
        }

        for name in OPTIONAL_FILES {
            let src = src_dir.join(name);
            if !src.exists() {
                continue;
            }
            match copy_if_changed(&src, &dst_dir.join(name))? {
                Some(bytes) => {
                    report.bytes_copied += bytes;
                    entry.copied.push(name.to_string());
                }
                None => entry.skipped.push(name.to_string()),
            }
        }

        mobile_meta.insert(
            project.clone(),
            ProjectMeta {
                year: meta.year.clone(),
                pdf_path: None,
                pdf_name: pdf_name.or(meta.pdf_name.clone()),
            },
        );
        report.projects.push(entry);
    }

    // Written last: until the config lists a project the iOS app ignores
    // whatever is already in its folder, so a half-finished copy is never read.
    let active = if wanted.contains(&config.active) {
        config.active.clone()
    } else {
        wanted[0].clone()
    };
    let mobile_config = Config {
        active,
        projects: wanted.to_vec(),
        project_meta: mobile_meta,
    };
    let text = serde_json::to_string_pretty(&mobile_config).map_err(|e| e.to_string())?;
    std::fs::write(med_dst.join("rag_config.json"), text).map_err(|e| e.to_string())?;

    Ok(report)
}

/// Mirror the selected projects into iCloud Drive.
///
/// `projects` defaults to every project in the config. `include_pdf` copies the
/// source PDF along too; without it the iOS app can show recommendations and
/// the guideline text but has no PDF to open in the Files app.
#[tauri::command]
pub async fn sync_to_icloud(
    state: State<'_, AppState>,
    projects: Option<Vec<String>>,
    include_pdf: bool,
) -> Result<SyncReport, String> {
    let target = icloud_target()?;
    let config = crate::commands::read_config(&state)?;

    let wanted = projects.unwrap_or_else(|| config.projects.clone());
    if wanted.is_empty() {
        return Err("Geen projecten om te synchroniseren.".into());
    }

    let mut report = sync_projects(
        &state.root().join(MED_DIR),
        &target.join(MED_DIR),
        &config,
        &wanted,
        include_pdf,
        |project| crate::commands::project_pdf_path(&state, project),
    )?;
    // The UI shows where the files landed, which is the folder the user sees in
    // iCloud Drive rather than the medical_rag_project/ level below it.
    report.target = target.to_string_lossy().into_owned();
    Ok(report)
}

/// Where a sync would write, and what is already there.
#[derive(Serialize)]
pub struct IcloudStatus {
    pub available: bool,
    pub target: Option<String>,
    pub error: Option<String>,
    pub synced_projects: Vec<String>,
}

#[tauri::command]
pub fn get_icloud_status() -> IcloudStatus {
    match icloud_target() {
        Err(e) => IcloudStatus {
            available: false,
            target: None,
            error: Some(e),
            synced_projects: vec![],
        },
        Ok(target) => {
            let synced = std::fs::read_dir(target.join(MED_DIR).join("projects"))
                .map(|entries| {
                    let mut names: Vec<String> = entries
                        .flatten()
                        .filter(|e| e.path().is_dir())
                        .map(|e| e.file_name().to_string_lossy().into_owned())
                        .collect();
                    names.sort();
                    names
                })
                .unwrap_or_default();
            IcloudStatus {
                available: true,
                target: Some(target.to_string_lossy().into_owned()),
                error: None,
                synced_projects: synced,
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::storage::MED_DIR;

    /// A scratch directory that cleans itself up.
    struct Temp(PathBuf);

    impl Temp {
        fn new(tag: &str) -> Self {
            let dir = std::env::temp_dir().join(format!(
                "ragcreator-sync-{}-{}",
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

    fn config_with(project: &str) -> Config {
        let mut project_meta = HashMap::new();
        project_meta.insert(
            project.to_string(),
            ProjectMeta {
                year: Some("2026".into()),
                // The kind of absolute path that must not reach the phone.
                pdf_path: Some("/Users/someone/iCloud/richtlijn.pdf".into()),
                pdf_name: Some("richtlijn.pdf".into()),
            },
        );
        Config {
            active: project.to_string(),
            projects: vec![project.to_string()],
            project_meta,
        }
    }

    /// Build a source tree holding the four files a sync looks for.
    fn make_source(root: &Path, project: &str) -> PathBuf {
        let dir = root.join(MED_DIR).join("projects").join(project);
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join("rag_chunks.json"), "[]").unwrap();
        std::fs::write(dir.join("guideline.md"), "## **1. Intro**\nbody").unwrap();
        std::fs::write(dir.join("pdf_pages.json"), "{}").unwrap();
        std::fs::write(dir.join("extraction_report.txt"), "ok").unwrap();
        dir
    }

    #[test]
    fn copies_the_viewer_files_and_nothing_else() {
        let src = Temp::new("src");
        let dst = Temp::new("dst");
        let dir = make_source(&src.0, "ESC HF");
        // Pipeline output the viewer has no use for; it must stay behind.
        std::fs::write(dir.join("embeddings.json"), "[]").unwrap();
        // Optional: copied when present, never reported missing when absent.
        std::fs::write(dir.join("qa_pairs.json"), "[]").unwrap();

        let report = sync_projects(
            &src.0.join(MED_DIR),
            &dst.0.join(MED_DIR),
            &config_with("ESC HF"),
            &["ESC HF".to_string()],
            false,
            |_| None,
        )
        .unwrap();

        let out = dst.0.join(MED_DIR).join("projects").join("ESC HF");
        assert!(out.join("rag_chunks.json").exists());
        assert!(out.join("guideline.md").exists());
        assert!(out.join("pdf_pages.json").exists());
        assert!(!out.join("embeddings.json").exists());
        assert!(out.join("qa_pairs.json").exists());
        assert_eq!(report.projects[0].copied.len(), 5);
        assert!(report.projects[0].missing.is_empty());
    }

    /// A project that never ran step 3 syncs cleanly: no QA file on the other
    /// side, and nothing listed as missing either.
    #[test]
    fn a_project_without_qa_pairs_syncs_without_reporting_it_missing() {
        let src = Temp::new("noqa-src");
        let dst = Temp::new("noqa-dst");
        make_source(&src.0, "ESC HF");

        let report = sync_projects(
            &src.0.join(MED_DIR),
            &dst.0.join(MED_DIR),
            &config_with("ESC HF"),
            &["ESC HF".to_string()],
            false,
            |_| None,
        )
        .unwrap();

        let out = dst.0.join(MED_DIR).join("projects").join("ESC HF");
        assert!(!out.join("qa_pairs.json").exists());
        assert!(report.projects[0].missing.is_empty());
        assert!(!report.projects[0].copied.contains(&"qa_pairs.json".to_string()));
    }

    #[test]
    fn the_synced_config_drops_this_macs_pdf_path() {
        let src = Temp::new("cfg-src");
        let dst = Temp::new("cfg-dst");
        make_source(&src.0, "ESC HF");

        sync_projects(
            &src.0.join(MED_DIR),
            &dst.0.join(MED_DIR),
            &config_with("ESC HF"),
            &["ESC HF".to_string()],
            false,
            |_| None,
        )
        .unwrap();

        let text =
            std::fs::read_to_string(dst.0.join(MED_DIR).join("rag_config.json")).unwrap();
        let written: Config = serde_json::from_str(&text).unwrap();
        let meta = &written.project_meta["ESC HF"];
        // An absolute Mac path would send the iOS app looking for a file it can
        // never open; the name is kept because the phone finds the PDF by it.
        assert_eq!(meta.pdf_path, None);
        assert_eq!(meta.pdf_name.as_deref(), Some("richtlijn.pdf"));
        assert_eq!(written.active, "ESC HF");
    }

    #[test]
    fn a_second_sync_skips_files_that_did_not_change() {
        let src = Temp::new("skip-src");
        let dst = Temp::new("skip-dst");
        let dir = make_source(&src.0, "ESC HF");

        let run = || {
            sync_projects(
                &src.0.join(MED_DIR),
                &dst.0.join(MED_DIR),
                &config_with("ESC HF"),
                &["ESC HF".to_string()],
                false,
                |_| None,
            )
            .unwrap()
        };

        let first = run();
        assert_eq!(first.projects[0].copied.len(), 4);

        // Nothing touched: re-uploading megabytes of PDF on every sync is the
        // cost this avoids.
        let second = run();
        assert_eq!(second.projects[0].copied.len(), 0);
        assert_eq!(second.projects[0].skipped.len(), 4);
        assert_eq!(second.bytes_copied, 0);

        // One file edited: only that one goes over again.
        std::fs::write(dir.join("rag_chunks.json"), "[{\"id\":\"rec_1\"}]").unwrap();
        let third = run();
        assert_eq!(third.projects[0].copied, vec!["rag_chunks.json".to_string()]);
    }

    #[test]
    fn a_missing_pdf_is_reported_rather_than_failing_the_sync() {
        let src = Temp::new("nopdf-src");
        let dst = Temp::new("nopdf-dst");
        make_source(&src.0, "ESC HF");

        let report = sync_projects(
            &src.0.join(MED_DIR),
            &dst.0.join(MED_DIR),
            &config_with("ESC HF"),
            &["ESC HF".to_string()],
            true,
            |_| None,
        )
        .unwrap();

        assert!(report.projects[0].missing.contains(&"PDF".to_string()));
        // The rest still went across, so the phone gets a usable project.
        assert!(report.projects[0].copied.contains(&"rag_chunks.json".to_string()));
    }

    /// End-to-end against the real checkout, when project data is present.
    ///
    /// The project folders are gitignored, so this asserts nothing on a fresh
    /// clone — it exists to catch a sync that silently produces an empty tree
    /// on the machine that actually has the guidelines.
    #[test]
    fn syncs_the_real_project_tree_when_one_exists() {
        let root = crate::storage::data_root();
        let med_src = root.join(MED_DIR);
        let Ok(config_text) = std::fs::read_to_string(med_src.join("rag_config.json")) else {
            return;
        };
        let config: Config = serde_json::from_str(&config_text).unwrap();
        if config.projects.is_empty() {
            return;
        }

        let dst = Temp::new("real");
        let report = sync_projects(
            &med_src,
            &dst.0.join(MED_DIR),
            &config,
            &config.projects,
            false,
            |_| None,
        )
        .unwrap();

        for entry in &report.projects {
            let out = dst.0.join(MED_DIR).join("projects").join(&entry.project);
            let chunks = out.join("rag_chunks.json");
            if !entry.copied.contains(&"rag_chunks.json".to_string()) {
                continue;
            }
            let text = std::fs::read_to_string(&chunks).unwrap();
            let parsed: Vec<serde_json::Value> = serde_json::from_str(&text).unwrap();
            assert!(!parsed.is_empty(), "{} synced no chunks", entry.project);
        }
    }
}
