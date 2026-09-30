use std::collections::HashMap;
use std::path::{Path, PathBuf};
#[cfg(desktop)]
use std::process::Stdio;

use serde::{Deserialize, Serialize};
use tauri::State;
#[cfg(desktop)]
use tauri::{AppHandle, Emitter};
#[cfg(desktop)]
use tokio::io::AsyncBufReadExt;

use crate::storage::{self, MED_DIR};

// ── App state ────────────────────────────────────────────────────────────────

pub struct AppState;

impl AppState {
    /// Root directory containing the data under `medical_rag_project/`.
    ///
    /// The app's iCloud container on both platforms, with a local fallback —
    /// see `storage.rs`. Everything below this line is written against the
    /// layout, not the platform.
    pub fn root(&self) -> PathBuf {
        storage::data_root()
    }
}

// ── Config types ─────────────────────────────────────────────────────────────

#[derive(Serialize, Deserialize, Clone, Debug, Default)]
pub struct ProjectMeta {
    pub year: Option<String>,
    pub pdf_path: Option<String>,
    pub pdf_name: Option<String>,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct Config {
    pub active: String,
    pub projects: Vec<String>,
    #[serde(default)]
    pub project_meta: HashMap<String, ProjectMeta>,
}

// ── Event payloads ────────────────────────────────────────────────────────────

#[cfg(desktop)]
#[derive(Serialize, Clone)]
pub struct LogEvent {
    pub project: String,
    pub step: u8,
    pub line: String,
    pub is_stderr: bool,
}

#[cfg(desktop)]
#[derive(Serialize, Clone)]
pub struct DoneEvent {
    pub project: String,
    pub step: u8,
    pub success: bool,
    pub exit_code: i32,
}

// ── Project status ────────────────────────────────────────────────────────────

#[derive(Serialize)]
pub struct ProjectStatus {
    pub has_pdf: bool,
    pub has_markdown: bool,
    pub has_chunks: bool,
    pub has_qa: bool,
    pub has_embeddings: bool,
    pub chunk_count: usize,
}

// ── Chunk types ───────────────────────────────────────────────────────────────

#[derive(Serialize, Clone, Debug)]
pub struct ReferenceEntry {
    pub id: i64,
    pub text: String,
}

/// Chunk files written before references carried their number stored plain
/// strings. Accept both shapes, otherwise one stale file makes the whole
/// project fail to deserialize and the Results tab shows nothing.
impl<'de> Deserialize<'de> for ReferenceEntry {
    fn deserialize<D: serde::Deserializer<'de>>(de: D) -> Result<Self, D::Error> {
        #[derive(Deserialize)]
        #[serde(untagged)]
        enum Raw {
            Entry { id: i64, text: String },
            Text(String),
        }
        Ok(match Raw::deserialize(de)? {
            Raw::Entry { id, text } => ReferenceEntry { id, text },
            Raw::Text(text) => ReferenceEntry { id: 0, text },
        })
    }
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct ChunkMetadata {
    #[serde(rename = "type")]
    pub chunk_type: Option<String>,
    pub class: Option<String>,
    pub evidence: Option<String>,
    pub disease: Option<String>,
    pub topic: Option<String>,
    pub section: Option<String>,
    #[serde(default)]
    pub table_title: Option<String>,
    pub guideline: Option<String>,
    pub year: Option<String>,
    #[serde(default)]
    pub references: Vec<ReferenceEntry>,
    #[serde(default)]
    pub ref_ids: Vec<i64>,
    #[serde(default)]
    pub approved: bool,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct Chunk {
    pub id: String,
    pub text: String,
    pub metadata: ChunkMetadata,
}

// ── Env/API config ────────────────────────────────────────────────────────────

#[cfg(desktop)]
#[derive(Serialize, Deserialize, Clone, Debug, Default)]
pub struct EnvConfig {
    pub openai_key: String,
    pub mongodb_uri: String,
    pub mongodb_db: String,
    pub mongodb_coll: String,
}

// ── Path helpers ──────────────────────────────────────────────────────────────

fn med_root(state: &AppState) -> PathBuf {
    state.root().join(MED_DIR)
}

fn config_path(state: &AppState) -> PathBuf {
    med_root(state).join("rag_config.json")
}

fn project_data_dir(state: &AppState, project: &str) -> PathBuf {
    med_root(state).join("projects").join(project)
}

/// A file in a project folder, downloaded first if iCloud is holding it back.
///
/// Every read and write of project data goes through here: an undownloaded
/// file looks missing, and a save would then overwrite it with a fresh one.
fn project_file(state: &AppState, project: &str, name: &str) -> PathBuf {
    let path = project_data_dir(state, project).join(name);
    storage::ensure_local(&path);
    path
}

fn pending_error(path: &Path) -> String {
    format!(
        "iCloud heeft {} nog niet gedownload. Probeer het zo opnieuw.",
        path.file_name().map(|n| n.to_string_lossy()).unwrap_or_default()
    )
}

/// `medical_rag_project/` in the repo checkout: scripts, venv and `.env`.
///
/// Deliberately not the data root — code and API keys stay out of iCloud.
#[cfg(desktop)]
fn code_med_root() -> PathBuf {
    storage::code_root().join(MED_DIR)
}

#[cfg(desktop)]
fn scripts_dir() -> PathBuf {
    code_med_root().join("scripts")
}

#[cfg(desktop)]
fn python_exec() -> PathBuf {
    let venv_py = code_med_root()
        .join("venv")
        .join("bin")
        .join("python3");
    if venv_py.exists() {
        venv_py
    } else {
        PathBuf::from("python3")
    }
}

// ── Config I/O ────────────────────────────────────────────────────────────────

pub fn read_config(state: &AppState) -> Result<Config, String> {
    let path = config_path(state);
    // A config that has not downloaded yet must not read as "no projects":
    // the next write_config would then replace it with an empty one.
    if !storage::ensure_local(&path) {
        if storage::is_pending(&path) {
            return Err(pending_error(&path));
        }
        return Ok(Config {
            active: String::new(),
            projects: vec![],
            project_meta: HashMap::new(),
        });
    }
    let text = std::fs::read_to_string(&path).map_err(|e| e.to_string())?;
    serde_json::from_str(&text).map_err(|e| e.to_string())
}

#[cfg(desktop)]
fn write_config(state: &AppState, config: &Config) -> Result<(), String> {
    let path = config_path(state);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let text = serde_json::to_string_pretty(config).map_err(|e| e.to_string())?;
    std::fs::write(path, text).map_err(|e| e.to_string())
}

// ── Commands: project management ──────────────────────────────────────────────

#[tauri::command]
pub fn get_config(state: State<AppState>) -> Result<Config, String> {
    read_config(&state)
}

#[cfg(desktop)]
#[tauri::command]
pub fn create_project(
    state: State<AppState>,
    name: String,
    year: String,
) -> Result<Config, String> {
    if name.trim().is_empty() {
        return Err("Project name cannot be empty".into());
    }
    let mut config = read_config(&state)?;
    if !config.projects.contains(&name) {
        config.projects.push(name.clone());
    }
    config.project_meta.insert(
        name.clone(),
        ProjectMeta {
            year: if year.is_empty() { None } else { Some(year) },
            pdf_path: None,
            pdf_name: None,
        },
    );
    config.active = name.clone();

    let data_dir = project_data_dir(&state, &name);
    std::fs::create_dir_all(&data_dir).map_err(|e| e.to_string())?;

    write_config(&state, &config)?;
    Ok(config)
}

#[cfg(desktop)]
#[tauri::command]
pub fn delete_project(
    state: State<AppState>,
    name: String,
) -> Result<Config, String> {
    let mut config = read_config(&state)?;
    config.projects.retain(|p| p != &name);
    config.project_meta.remove(&name);
    if config.active == name {
        config.active = config.projects.first().cloned().unwrap_or_default();
    }
    write_config(&state, &config)?;
    Ok(config)
}

#[cfg(desktop)]
#[tauri::command]
pub fn set_active_project(
    state: State<AppState>,
    name: String,
) -> Result<Config, String> {
    let mut config = read_config(&state)?;
    config.active = name;
    write_config(&state, &config)?;
    Ok(config)
}

#[cfg(desktop)]
#[tauri::command]
pub fn set_pdf_path(
    state: State<AppState>,
    project: String,
    pdf_path: String,
) -> Result<(), String> {
    let mut config = read_config(&state)?;
    let meta = config.project_meta.entry(project).or_default();
    let pb = Path::new(&pdf_path);
    meta.pdf_name = pb.file_name().map(|n| n.to_string_lossy().to_string());
    meta.pdf_path = Some(pdf_path);
    write_config(&state, &config)
}

// ── Commands: project status ──────────────────────────────────────────────────

#[tauri::command]
pub fn get_project_status(
    state: State<AppState>,
    project: String,
) -> Result<ProjectStatus, String> {
    let config = read_config(&state)?;
    let meta = config.project_meta.get(&project).cloned().unwrap_or_default();
    let data_dir = project_data_dir(&state, &project);

    let has_pdf = meta
        .pdf_path
        .as_deref()
        .map(|p| Path::new(p).exists())
        .unwrap_or(false);

    let chunks_path = project_file(&state, &project, "rag_chunks.json");
    let chunk_count = if chunks_path.exists() {
        std::fs::read_to_string(&chunks_path)
            .ok()
            .and_then(|t| serde_json::from_str::<serde_json::Value>(&t).ok())
            .and_then(|v| v.as_array().map(|a| a.len()))
            .unwrap_or(0)
    } else {
        0
    };

    Ok(ProjectStatus {
        has_pdf,
        has_markdown: project_file(&state, &project, "guideline.md").exists(),
        has_chunks: chunks_path.exists(),
        has_qa: project_file(&state, &project, "qa_pairs.json").exists(),
        has_embeddings: data_dir.join("embeddings.json").exists(),
        chunk_count,
    })
}

// ── Commands: pipeline runner ─────────────────────────────────────────────────

#[cfg(desktop)]
#[tauri::command]
pub async fn run_pipeline_step(
    app: AppHandle,
    state: State<'_, AppState>,
    project: String,
    step: u8,
    openai_key: Option<String>,
    mongodb_uri: Option<String>,
    mongodb_db: Option<String>,
    mongodb_coll: Option<String>,
) -> Result<(), String> {
    let script_name = match step {
        1 => "1_pdf_to_markdown.py",
        2 => "2_extract_guideline_structure.py",
        3 => "3_generate_qa_pairs.py",
        4 => "4_embed_and_store.py",
        5 => "5_upload_to_mongodb.py",
        _ => return Err("Ongeldig stap-nummer".into()),
    };

    let config = read_config(&state)?;
    let meta = config.project_meta.get(&project).cloned().unwrap_or_default();
    let data_dir = project_data_dir(&state, &project);
    let script_path = scripts_dir().join(script_name);
    let python = python_exec();

    std::fs::create_dir_all(&data_dir).map_err(|e| e.to_string())?;

    // Python reads these straight from disk, so anything iCloud has not
    // downloaded yet has to be there before the script starts.
    let normalized_dir = med_root(&state).join("normalized");
    let pending = storage::ensure_tree(&data_dir, std::time::Duration::from_secs(60))
        + storage::ensure_tree(&normalized_dir, std::time::Duration::from_secs(60));
    if pending > 0 {
        return Err(format!(
            "iCloud heeft nog {} bestand(en) van dit project niet gedownload. \
             Probeer het over een minuut opnieuw.",
            pending
        ));
    }

    if !script_path.exists() {
        return Err(format!("Script niet gevonden: {}", script_path.display()));
    }

    // Build environment
    let mut env_vars: HashMap<String, String> = HashMap::new();
    env_vars.insert("RAG_DATA_DIR".into(), data_dir.to_string_lossy().into());
    // Where normalized/ and the other projects live; the scripts would
    // otherwise look next to themselves, in the repo.
    env_vars.insert("RAG_MED_ROOT".into(), med_root(&state).to_string_lossy().into());
    env_vars.insert("RAG_PROJECT_TITLE".into(), project.clone());

    if let Some(year) = &meta.year {
        env_vars.insert("RAG_GUIDELINE_YEAR".into(), year.clone());
    }

    // Step 1: copy PDF into data dir and set RAG_PDF_NAME
    if step == 1 {
        if let Some(pdf_path) = &meta.pdf_path {
            let src = Path::new(pdf_path);
            if src.exists() {
                if let Some(fname) = src.file_name() {
                    let dest = data_dir.join(fname);
                    if !dest.exists() {
                        std::fs::copy(src, &dest).map_err(|e| e.to_string())?;
                    }
                    env_vars.insert(
                        "RAG_PDF_NAME".into(),
                        fname.to_string_lossy().into(),
                    );
                }
            } else {
                return Err(format!("PDF niet gevonden: {}", pdf_path));
            }
        } else {
            return Err("Geen PDF gekoppeld aan dit project.".into());
        }
    }

    if let Some(key) = openai_key {
        if !key.is_empty() {
            env_vars.insert("OPENAI_API_KEY".into(), key);
        }
    }
    if let Some(uri) = mongodb_uri {
        if !uri.is_empty() {
            env_vars.insert("MONGODB_URI".into(), uri);
        }
    }
    if let Some(db) = mongodb_db {
        if !db.is_empty() {
            env_vars.insert("MONGODB_DB".into(), db);
        }
    }
    if let Some(coll) = mongodb_coll {
        if !coll.is_empty() {
            env_vars.insert("MONGODB_COLL".into(), coll);
        }
    }

    // Spawn
    let mut child = tokio::process::Command::new(&python)
        .arg(&script_path)
        .envs(&env_vars)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("Kon Python niet starten: {}", e))?;

    let stdout = child.stdout.take().ok_or("Geen stdout")?;
    let stderr = child.stderr.take().ok_or("Geen stderr")?;

    // Every event carries the project it belongs to, so the frontend can keep
    // each guideline's pipeline state separate while steps run concurrently.

    // Stream stdout
    let app_out = app.clone();
    let project_out = project.clone();
    tokio::spawn(async move {
        let mut lines = tokio::io::BufReader::new(stdout).lines();
        while let Ok(Some(line)) = lines.next_line().await {
            app_out
                .emit(
                    "pipeline-log",
                    LogEvent {
                        project: project_out.clone(),
                        step,
                        line,
                        is_stderr: false,
                    },
                )
                .ok();
        }
    });

    // Stream stderr
    let app_err = app.clone();
    let project_err = project.clone();
    tokio::spawn(async move {
        let mut lines = tokio::io::BufReader::new(stderr).lines();
        while let Ok(Some(line)) = lines.next_line().await {
            app_err
                .emit(
                    "pipeline-log",
                    LogEvent {
                        project: project_err.clone(),
                        step,
                        line,
                        is_stderr: true,
                    },
                )
                .ok();
        }
    });

    // Wait for exit and emit done
    tokio::spawn(async move {
        match child.wait().await {
            Ok(status) => {
                let exit_code = status.code().unwrap_or(-1);
                // New recommendations need their pages before the phone can
                // link to them.
                if step == 2 && status.success() {
                    let p = project.clone();
                    std::thread::spawn(move || build_page_indexes(vec![p]));
                }
                app.emit(
                    "pipeline-done",
                    DoneEvent {
                        project,
                        step,
                        success: status.success(),
                        exit_code,
                    },
                )
                .ok();
            }
            Err(e) => {
                app.emit(
                    "pipeline-log",
                    LogEvent {
                        project: project.clone(),
                        step,
                        line: format!("FOUT: {}", e),
                        is_stderr: true,
                    },
                )
                .ok();
                app.emit(
                    "pipeline-done",
                    DoneEvent { project, step, success: false, exit_code: -1 },
                )
                .ok();
            }
        }
    });

    Ok(())
}

// ── References ───────────────────────────────────────────────────────────────
//
// Mirrors the parsing in scripts/2_extract_guideline_structure.py so manually
// typed reference numbers resolve the same way automated extraction does.

fn is_heading(line: &str) -> Option<(usize, &str)> {
    let trimmed = line.trim_start();
    let hashes = trimmed.chars().take_while(|&c| c == '#').count();
    if !(1..=4).contains(&hashes) {
        return None;
    }
    let rest = &trimmed[hashes..];
    if rest.is_empty() || !rest.starts_with(char::is_whitespace) {
        return None;
    }
    Some((hashes, rest.trim()))
}

fn is_references_heading(line: &str) -> bool {
    let Some((_, rest)) = is_heading(line) else {
        return false;
    };
    let rest = rest.trim_matches('*').trim();
    let digit_len = rest.chars().take_while(|c| c.is_ascii_digit()).count();
    let rest = rest[digit_len..].trim_start_matches('.').trim();
    let rest = rest.trim_matches('*').trim();
    matches!(rest.to_lowercase().as_str(), "references" | "reference")
}

fn parse_entry_start(line: &str) -> Option<(i64, &str)> {
    let trimmed = line.trim_start();
    let digit_len = trimmed.chars().take_while(|c| c.is_ascii_digit()).count();
    if digit_len == 0 {
        return None;
    }
    let rest = &trimmed[digit_len..];
    let after_dot = rest.strip_prefix('.')?;
    if !after_dot.starts_with(char::is_whitespace) {
        return None;
    }
    let num: i64 = trimmed[..digit_len].parse().ok()?;
    Some((num, after_dot.trim_start()))
}

fn clean_ref_text(text: &str) -> String {
    let stripped: String = text.chars().filter(|c| !matches!(c, '*' | '_' | '`')).collect();
    stripped.split_whitespace().collect::<Vec<_>>().join(" ")
}

/// Parse the "## References" section of a converted guideline.md into
/// {ref_number: reference_text}, handling multi-line entries.
fn parse_reference_section(markdown: &str) -> HashMap<i64, String> {
    let mut refs = HashMap::new();
    let lines: Vec<&str> = markdown.lines().collect();

    let Some(start) = lines.iter().position(|l| is_references_heading(l)) else {
        return refs;
    };

    let mut body: Vec<&str> = Vec::new();
    for line in &lines[start + 1..] {
        if is_heading(line).is_some() {
            break;
        }
        body.push(line);
    }

    let mut current: Option<(i64, String)> = None;
    for line in body {
        if let Some((num, rest)) = parse_entry_start(line) {
            if let Some((n, text)) = current.take() {
                let cleaned = clean_ref_text(&text);
                if !cleaned.is_empty() {
                    refs.insert(n, cleaned);
                }
            }
            current = Some((num, rest.to_string()));
        } else if let Some((_, text)) = current.as_mut() {
            text.push(' ');
            text.push_str(line.trim());
        }
    }
    if let Some((n, text)) = current {
        let cleaned = clean_ref_text(&text);
        if !cleaned.is_empty() {
            refs.insert(n, cleaned);
        }
    }

    refs
}

/// Look up reference text for a chunk's ref_ids against guideline.md.
/// Returns an empty list if there's no guideline.md or no matches.
#[cfg(desktop)]
fn resolve_references(state: &AppState, project: &str, ref_ids: &[i64]) -> Vec<ReferenceEntry> {
    if ref_ids.is_empty() {
        return vec![];
    }
    let md_path = project_file(state, project, "guideline.md");
    let Ok(markdown) = std::fs::read_to_string(&md_path) else {
        return vec![];
    };
    let ref_dict = parse_reference_section(&markdown);
    ref_ids
        .iter()
        .filter_map(|id| {
            ref_dict
                .get(id)
                .map(|text| ReferenceEntry { id: *id, text: text.clone() })
        })
        .collect()
}

// ── Commands: chunks ──────────────────────────────────────────────────────────

#[derive(Serialize)]
pub struct ChunksPage {
    pub items: Vec<Chunk>,
    pub total: usize,
}

#[tauri::command]
pub fn get_chunks(
    state: State<AppState>,
    project: String,
    page: usize,
    page_size: usize,
    approved_filter: Option<bool>,
) -> Result<ChunksPage, String> {
    let path = project_file(&state, &project, "rag_chunks.json");
    if !path.exists() {
        return Ok(ChunksPage { items: vec![], total: 0 });
    }
    let text = std::fs::read_to_string(&path).map_err(|e| e.to_string())?;
    let mut all: Vec<Chunk> = serde_json::from_str(&text).map_err(|e| e.to_string())?;
    if let Some(want) = approved_filter {
        all.retain(|c| c.metadata.approved == want);
    }
    let total = all.len();
    let items = all.into_iter().skip(page * page_size).take(page_size).collect();
    Ok(ChunksPage { items, total })
}


// ── Commands: QA pairs ────────────────────────────────────────────────────────

/// Metadata written by `3_generate_qa_pairs.py`. Every field is optional so an
/// older `qa_pairs.json` still loads instead of failing the whole tab.
#[derive(Serialize, Deserialize, Clone, Debug, Default)]
pub struct QaMetadata {
    #[serde(default)]
    pub chunk_id: Option<String>,
    #[serde(default)]
    pub disease: Option<String>,
    #[serde(default)]
    pub topic: Option<String>,
    #[serde(rename = "type", default)]
    pub qa_type: Option<String>,
    #[serde(default)]
    pub source: Option<String>,
    #[serde(default)]
    pub section: Option<String>,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct QaPair {
    #[serde(default)]
    pub question: String,
    #[serde(default)]
    pub answer: String,
    #[serde(default)]
    pub metadata: QaMetadata,
}

#[derive(Serialize)]
pub struct QaPage {
    pub items: Vec<QaPair>,
    /// Pairs in the file, before the query filter.
    pub total: usize,
    /// Pairs left after the query filter — what `page`/`page_size` index into.
    pub matched: usize,
}

#[tauri::command]
pub fn get_qa_pairs(
    state: State<AppState>,
    project: String,
    page: usize,
    page_size: usize,
    query: Option<String>,
) -> Result<QaPage, String> {
    let path = project_file(&state, &project, "qa_pairs.json");
    if !path.exists() {
        return Ok(QaPage { items: vec![], total: 0, matched: 0 });
    }
    let all = read_qa_pairs(&path)?;
    let total = all.len();

    let q = query.unwrap_or_default().trim().to_lowercase();
    let filtered: Vec<QaPair> = if q.is_empty() {
        all
    } else {
        all.into_iter()
            .filter(|p| {
                let m = &p.metadata;
                p.question.to_lowercase().contains(&q)
                    || p.answer.to_lowercase().contains(&q)
                    || field_matches(m.section.as_deref(), &q)
                    || field_matches(m.disease.as_deref(), &q)
                    || field_matches(m.topic.as_deref(), &q)
                    || field_matches(m.chunk_id.as_deref(), &q)
            })
            .collect()
    };

    let matched = filtered.len();
    let items = filtered
        .into_iter()
        .skip(page * page_size)
        .take(page_size)
        .collect();
    Ok(QaPage { items, total, matched })
}

/// Read and parse `qa_pairs.json`.
///
/// Split out from the command so a test can run it against a real project
/// folder: a pair the file has but the tab does not show is either a parse
/// failure here or a frontend problem, and this tells the two apart.
fn read_qa_pairs(path: &Path) -> Result<Vec<QaPair>, String> {
    let text = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
    serde_json::from_str(&text).map_err(|e| format!("{}: {}", path.display(), e))
}

fn field_matches(field: Option<&str>, needle: &str) -> bool {
    field.map(|v| v.to_lowercase().contains(needle)).unwrap_or(false)
}

#[tauri::command]
pub fn search_chunks(
    state: State<AppState>,
    project: String,
    query: String,
    class_filter: Option<String>,
    disease_filter: Option<String>,
    topic_filter: Option<String>,
) -> Result<Vec<Chunk>, String> {
    let path = project_file(&state, &project, "rag_chunks.json");
    if !path.exists() {
        return Ok(vec![]);
    }
    let text = std::fs::read_to_string(&path).map_err(|e| e.to_string())?;
    let all: Vec<Chunk> = serde_json::from_str(&text).map_err(|e| e.to_string())?;

    let q = query.to_lowercase();

    let results = all
        .into_iter()
        .filter(|c| {
            let text_ok = q.is_empty() || c.text.to_lowercase().contains(&q);
            let class_ok = class_filter
                .as_deref()
                .map(|f| {
                    c.metadata
                        .class
                        .as_deref()
                        .map(|v| v.to_lowercase().contains(&f.to_lowercase()))
                        .unwrap_or(false)
                })
                .unwrap_or(true);
            let disease_ok = disease_filter
                .as_deref()
                .map(|f| c.metadata.disease.as_deref() == Some(f))
                .unwrap_or(true);
            let topic_ok = topic_filter
                .as_deref()
                .map(|f| c.metadata.topic.as_deref() == Some(f))
                .unwrap_or(true);
            text_ok && class_ok && disease_ok && topic_ok
        })
        .take(200)
        .collect();

    Ok(results)
}

#[cfg(desktop)]
#[tauri::command]
pub fn save_chunk(
    state: State<AppState>,
    project: String,
    mut chunk: Chunk,
) -> Result<Chunk, String> {
    // Always resolve against guideline.md, so a manually typed reference
    // number gets its text looked up the same way extraction does.
    chunk.metadata.references = resolve_references(&state, &project, &chunk.metadata.ref_ids);

    let path = project_file(&state, &project, "rag_chunks.json");
    if storage::is_pending(&path) {
        return Err(pending_error(&path));
    }
    let mut all: Vec<Chunk> = if path.exists() {
        let text = std::fs::read_to_string(&path).map_err(|e| e.to_string())?;
        serde_json::from_str(&text).map_err(|e| e.to_string())?
    } else {
        vec![]
    };

    match all.iter_mut().find(|c| c.id == chunk.id) {
        Some(existing) => *existing = chunk.clone(),
        None => all.push(chunk.clone()),
    }

    let text = serde_json::to_string_pretty(&all).map_err(|e| e.to_string())?;
    std::fs::write(&path, text).map_err(|e| e.to_string())?;
    Ok(chunk)
}

#[cfg(desktop)]
#[tauri::command]
pub fn delete_chunk(
    state: State<AppState>,
    project: String,
    id: String,
) -> Result<(), String> {
    let path = project_file(&state, &project, "rag_chunks.json");
    if storage::is_pending(&path) {
        return Err(pending_error(&path));
    }
    if !path.exists() {
        return Ok(());
    }
    let text = std::fs::read_to_string(&path).map_err(|e| e.to_string())?;
    let mut all: Vec<Chunk> = serde_json::from_str(&text).map_err(|e| e.to_string())?;
    all.retain(|c| c.id != id);

    let text = serde_json::to_string_pretty(&all).map_err(|e| e.to_string())?;
    std::fs::write(&path, text).map_err(|e| e.to_string())
}

// ── Commands: guideline info ──────────────────────────────────────────────────
//
// Aggregates a project's rag_chunks.json into the counts shown on the
// "Richtlijn" tab: tables, recommendations and Level of Evidence A.

/// Order used in the UI so distributions read the same everywhere.
const CLASS_ORDER: [&str; 4] = ["Class I", "Class IIa", "Class IIb", "Class III"];
const EVIDENCE_ORDER: [&str; 6] = ["A", "B1", "B2", "B", "C", "NR"];

const UNKNOWN_LABEL: &str = "Onbekend";

#[derive(Serialize)]
pub struct CountEntry {
    pub label: String,
    pub count: usize,
}

#[derive(Serialize)]
pub struct TableInfo {
    pub title: String,
    pub recommendation_count: usize,
    pub evidence_a_count: usize,
    pub approved_count: usize,
}

/// A reference and how often the guideline's recommendations cite it.
#[derive(Serialize)]
pub struct ReferenceUsage {
    pub id: i64,
    pub text: String,
    pub count: usize,
}

#[derive(Serialize)]
pub struct GuidelineInfo {
    pub project: String,
    pub guideline: Option<String>,
    pub year: Option<String>,
    pub pdf_name: Option<String>,
    pub has_chunks: bool,
    /// Distinct `table_title` values — the recommendation tables in the guideline.
    pub table_count: usize,
    pub recommendation_count: usize,
    pub chunk_count: usize,
    pub evidence_a_count: usize,
    pub approved_count: usize,
    /// Distinct reference numbers cited by chunks.
    pub cited_reference_count: usize,
    /// Entries in the guideline's own reference list (0 without guideline.md).
    pub guideline_reference_count: usize,
    /// Cited numbers with no resolved reference text — extraction gaps to fix.
    pub unresolved_reference_count: usize,
    /// Recommendations that cite nothing; usually expert consensus, sometimes
    /// a citation the extraction missed.
    pub unreferenced_recommendation_count: usize,
    /// The most-cited references, as an entry point into the evidence base.
    pub top_references: Vec<ReferenceUsage>,
    pub class_counts: Vec<CountEntry>,
    pub evidence_counts: Vec<CountEntry>,
    /// Class distribution restricted to Level of Evidence A.
    pub evidence_a_class_counts: Vec<CountEntry>,
    pub tables: Vec<TableInfo>,
}

/// Counts in a fixed order first, any unexpected labels alphabetically after.
fn ordered_counts(counts: HashMap<String, usize>, order: &[&str]) -> Vec<CountEntry> {
    let mut extra: Vec<String> = counts
        .keys()
        .filter(|k| !order.contains(&k.as_str()))
        .cloned()
        .collect();
    extra.sort();

    order
        .iter()
        .map(|s| s.to_string())
        .chain(extra)
        .filter_map(|label| {
            counts
                .get(&label)
                .copied()
                .map(|count| CountEntry { label, count })
        })
        .collect()
}

/// Leading number of "Recommendation Table 7 — …", for sorting tables the way
/// the guideline numbers them instead of alphabetically.
fn table_sort_num(title: &str) -> Option<i64> {
    let idx = title.to_lowercase().find("table")?;
    let rest = title[idx + "table".len()..].trim_start();
    let digits: String = rest.chars().take_while(|c| c.is_ascii_digit()).collect();
    digits.parse().ok()
}

/// Pure aggregation, kept separate from the file I/O so it can be tested.
fn build_guideline_info(
    project: String,
    meta: &ProjectMeta,
    chunks: &[Chunk],
    has_chunks: bool,
    guideline_reference_count: usize,
) -> GuidelineInfo {
    let mut class_counts: HashMap<String, usize> = HashMap::new();
    let mut evidence_counts: HashMap<String, usize> = HashMap::new();
    let mut evidence_a_class: HashMap<String, usize> = HashMap::new();
    let mut table_acc: HashMap<String, TableInfo> = HashMap::new();
    let mut cited_refs: std::collections::HashSet<i64> = std::collections::HashSet::new();
    let mut ref_usage: HashMap<i64, usize> = HashMap::new();
    let mut ref_text: HashMap<i64, String> = HashMap::new();
    let mut unreferenced_recommendation_count = 0;

    let mut recommendation_count = 0;
    let mut evidence_a_count = 0;
    let mut approved_count = 0;

    for chunk in chunks {
        let m = &chunk.metadata;

        // Extraction only emits recommendations; older files left `type` unset.
        if m.chunk_type.as_deref().unwrap_or("recommendation") == "recommendation" {
            recommendation_count += 1;
        }
        if m.approved {
            approved_count += 1;
        }

        let class = m
            .class
            .as_deref()
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .unwrap_or(UNKNOWN_LABEL)
            .to_string();
        let evidence = m
            .evidence
            .as_deref()
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .unwrap_or(UNKNOWN_LABEL)
            .to_string();

        let is_level_a = evidence == "A";
        if is_level_a {
            evidence_a_count += 1;
            *evidence_a_class.entry(class.clone()).or_insert(0) += 1;
        }
        *class_counts.entry(class).or_insert(0) += 1;
        *evidence_counts.entry(evidence).or_insert(0) += 1;

        cited_refs.extend(m.ref_ids.iter().copied());
        if m.ref_ids.is_empty() {
            unreferenced_recommendation_count += 1;
        }
        for id in &m.ref_ids {
            *ref_usage.entry(*id).or_insert(0) += 1;
        }
        for r in &m.references {
            ref_text.entry(r.id).or_insert_with(|| r.text.clone());
        }

        let title = m.table_title.as_deref().unwrap_or("").trim();
        if !title.is_empty() {
            let entry = table_acc.entry(title.to_string()).or_insert_with(|| TableInfo {
                title: title.to_string(),
                recommendation_count: 0,
                evidence_a_count: 0,
                approved_count: 0,
            });
            entry.recommendation_count += 1;
            if is_level_a {
                entry.evidence_a_count += 1;
            }
            if m.approved {
                entry.approved_count += 1;
            }
        }
    }

    // A cited number without text means resolve_references found no entry for
    // it in guideline.md — the reference list parse dropped or renumbered it.
    let unresolved_reference_count = cited_refs
        .iter()
        .filter(|id| !ref_text.contains_key(id))
        .count();

    let mut top_references: Vec<ReferenceUsage> = ref_usage
        .iter()
        .filter_map(|(id, count)| {
            ref_text.get(id).map(|text| ReferenceUsage {
                id: *id,
                text: text.clone(),
                count: *count,
            })
        })
        .collect();
    // Most cited first; the number breaks ties so the list is stable between
    // runs instead of following HashMap order.
    top_references.sort_by(|a, b| b.count.cmp(&a.count).then_with(|| a.id.cmp(&b.id)));
    top_references.truncate(12);

    let mut tables: Vec<TableInfo> = table_acc.into_values().collect();
    tables.sort_by(|a, b| {
        match (table_sort_num(&a.title), table_sort_num(&b.title)) {
            (Some(x), Some(y)) => x.cmp(&y),
            (Some(_), None) => std::cmp::Ordering::Less,
            (None, Some(_)) => std::cmp::Ordering::Greater,
            (None, None) => std::cmp::Ordering::Equal,
        }
        .then_with(|| a.title.cmp(&b.title))
    });

    // Chunks carry the guideline name themselves; fall back to the project name.
    let guideline = chunks
        .iter()
        .find_map(|c| c.metadata.guideline.clone())
        .filter(|g| !g.trim().is_empty())
        .or_else(|| Some(project.clone()));
    let year = chunks
        .iter()
        .find_map(|c| c.metadata.year.clone())
        .filter(|y| !y.trim().is_empty())
        .or_else(|| meta.year.clone());

    GuidelineInfo {
        project,
        guideline,
        year,
        pdf_name: meta.pdf_name.clone(),
        has_chunks,
        table_count: tables.len(),
        recommendation_count,
        chunk_count: chunks.len(),
        evidence_a_count,
        approved_count,
        cited_reference_count: cited_refs.len(),
        guideline_reference_count,
        unresolved_reference_count,
        unreferenced_recommendation_count,
        top_references,
        class_counts: ordered_counts(class_counts, &CLASS_ORDER),
        evidence_counts: ordered_counts(evidence_counts, &EVIDENCE_ORDER),
        evidence_a_class_counts: ordered_counts(evidence_a_class, &CLASS_ORDER),
        tables,
    }
}

#[tauri::command]
pub fn get_guideline_info(
    state: State<AppState>,
    project: String,
) -> Result<GuidelineInfo, String> {
    let config = read_config(&state)?;
    let meta = config.project_meta.get(&project).cloned().unwrap_or_default();

    let chunks_path = project_file(&state, &project, "rag_chunks.json");
    let has_chunks = chunks_path.exists();
    let chunks: Vec<Chunk> = if has_chunks {
        let text = std::fs::read_to_string(&chunks_path).map_err(|e| e.to_string())?;
        serde_json::from_str(&text).map_err(|e| e.to_string())?
    } else {
        vec![]
    };

    let guideline_reference_count = std::fs::read_to_string(project_file(&state, &project, "guideline.md"))
        .map(|md| parse_reference_section(&md).len())
        .unwrap_or(0);

    Ok(build_guideline_info(
        project,
        &meta,
        &chunks,
        has_chunks,
        guideline_reference_count,
    ))
}

// ── Commands: external links & PDF source view ───────────────────────────────

/// Reference strings come out of a PDF, so any URL built from them is untrusted
/// input. Handing "file:", "javascript:" or a shell-quoted string to the OS
/// opener would turn a citation into arbitrary local action; only plain http(s)
/// gets through.
#[cfg(desktop)]
fn validate_web_url(url: &str) -> Result<(), String> {
    let trimmed = url.trim();
    let lower = trimmed.to_lowercase();
    if !(lower.starts_with("http://") || lower.starts_with("https://")) {
        return Err("Alleen http(s)-links kunnen geopend worden.".into());
    }
    if trimmed.chars().any(|c| c.is_control()) {
        return Err("Ongeldige link.".into());
    }
    Ok(())
}

#[cfg(desktop)]
fn os_open(target: &str) -> Result<(), String> {
    let mut cmd = if cfg!(target_os = "macos") {
        let mut c = std::process::Command::new("open");
        c.arg(target);
        c
    } else if cfg!(target_os = "windows") {
        let mut c = std::process::Command::new("cmd");
        // The empty argument is `start`'s window-title slot; without it a
        // quoted target is swallowed as the title and nothing opens.
        c.args(["/C", "start", "", target]);
        c
    } else {
        let mut c = std::process::Command::new("xdg-open");
        c.arg(target);
        c
    };
    cmd.spawn().map(|_| ()).map_err(|e| format!("Kon niet openen: {}", e))
}

/// Open a reference (PubMed, doi.org, Scholar) in the user's browser.
#[cfg(desktop)]
#[tauri::command]
pub fn open_external(url: String) -> Result<(), String> {
    validate_web_url(&url)?;
    os_open(&url)
}

/// The guideline PDF for a project.
///
/// Step 1 copies the source PDF into the project folder, so that copy is
/// preferred: it keeps working when the original lives on iCloud or an
/// external drive that is not currently mounted.
pub fn project_pdf_path(state: &AppState, project: &str) -> Option<PathBuf> {
    let dir = project_data_dir(state, project);
    if let Ok(entries) = std::fs::read_dir(&dir) {
        let mut pdfs: Vec<PathBuf> = entries
            .flatten()
            .map(|e| e.path())
            // A PDF iCloud has not downloaded shows up as ".name.pdf.icloud".
            .map(|p| storage::real_path_of(&p).unwrap_or(p))
            .filter(|p| {
                p.extension()
                    .and_then(|e| e.to_str())
                    .map(|e| e.eq_ignore_ascii_case("pdf"))
                    .unwrap_or(false)
            })
            .collect();
        pdfs.sort();
        if let Some(p) = pdfs.into_iter().next() {
            storage::ensure_local(&p);
            return Some(p);
        }
    }

    read_config(state)
        .ok()
        .and_then(|c| c.project_meta.get(project).and_then(|m| m.pdf_path.clone()))
        .map(PathBuf::from)
        .filter(|p| p.exists())
}

/// Open the guideline PDF itself in the system viewer.
#[cfg(desktop)]
#[tauri::command]
pub fn open_project_pdf(state: State<AppState>, project: String) -> Result<(), String> {
    let path = project_pdf_path(&state, &project)
        .ok_or("Geen PDF gevonden voor dit project.")?;
    os_open(&path.to_string_lossy())
}

/// chunk_id → 0-based page, so a recommendation is only searched for once.
fn page_cache_path(state: &AppState, project: &str) -> PathBuf {
    project_file(state, project, "pdf_pages.json")
}

fn read_page_cache(state: &AppState, project: &str) -> HashMap<String, i64> {
    std::fs::read_to_string(page_cache_path(state, project))
        .ok()
        .and_then(|t| serde_json::from_str(&t).ok())
        .unwrap_or_default()
}

#[cfg(desktop)]
fn write_page_cache(state: &AppState, project: &str, cache: &HashMap<String, i64>) {
    if let Ok(text) = serde_json::to_string_pretty(cache) {
        // A failed cache write only costs a re-search next time.
        std::fs::write(page_cache_path(state, project), text).ok();
    }
}

/// Find a recommendation in the source PDF and render that page.
///
/// The heavy lifting runs in `pdf_locate.py` because PyMuPDF is already a
/// pipeline dependency — no PDF library is needed on the Rust side. The
/// response is passed through untouched; see that script for its shape.
#[cfg(desktop)]
#[tauri::command]
pub async fn locate_in_pdf(
    state: State<'_, AppState>,
    project: String,
    chunk_id: Option<String>,
    text: String,
    table_title: Option<String>,
    page: Option<i64>,
    zoom: Option<f64>,
) -> Result<serde_json::Value, String> {
    let pdf = project_pdf_path(&state, &project).ok_or(
        "Geen PDF gevonden voor dit project. Koppel een PDF en voer stap 1 uit.",
    )?;
    let script = scripts_dir().join("pdf_locate.py");
    if !script.exists() {
        return Err(format!("Script niet gevonden: {}", script.display()));
    }
    let python = python_exec();

    // An explicit page wins (the viewer's prev/next), then the cached hit.
    let cached = chunk_id
        .as_ref()
        .and_then(|id| read_page_cache(&state, &project).get(id).copied());
    let target_page = page.or(cached);

    let mut request = serde_json::json!({
        "pdf": pdf.to_string_lossy(),
        "text": text,
        "table_title": table_title.unwrap_or_default(),
        "zoom": zoom.unwrap_or(2.0),
    });
    if let Some(p) = target_page {
        request["page"] = serde_json::json!(p);
    }

    let mut child = tokio::process::Command::new(&python)
        .arg(&script)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("Kon Python niet starten: {}", e))?;

    {
        use tokio::io::AsyncWriteExt;
        let mut stdin = child.stdin.take().ok_or("Geen stdin")?;
        stdin
            .write_all(request.to_string().as_bytes())
            .await
            .map_err(|e| e.to_string())?;
        // Dropping stdin here sends EOF; the script blocks on stdin otherwise.
    }

    let output = child.wait_with_output().await.map_err(|e| e.to_string())?;
    if !output.status.success() && output.stdout.is_empty() {
        return Err(format!(
            "PDF-zoekopdracht mislukt: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }

    let value: serde_json::Value = serde_json::from_slice(&output.stdout)
        .map_err(|e| format!("Onleesbaar antwoord van pdf_locate.py: {}", e))?;
    if let Some(err) = value.get("error").and_then(|v| v.as_str()) {
        return Err(err.to_string());
    }

    // Only remember a page the script actually searched out — caching the page
    // the viewer happened to be paging through would poison the next lookup.
    if page.is_none() {
        if let (Some(id), Some(found)) = (chunk_id, value.get("page").and_then(|v| v.as_i64())) {
            let mut cache = read_page_cache(&state, &project);
            if cache.get(&id) != Some(&found) {
                cache.insert(id, found);
                write_page_cache(&state, &project, &cache);
            }
        }
    }

    Ok(value)
}

// ── Page index for the phone ─────────────────────────────────────────────────
//
// The iOS app cannot run PyMuPDF, so it can only jump to a page that is already
// in pdf_pages.json. The desktop keeps that file complete in the background.

/// Whether a project's page index is older than its recommendations.
#[cfg(desktop)]
fn page_index_stale(dir: &Path) -> bool {
    let modified = |name: &str| std::fs::metadata(dir.join(name)).and_then(|m| m.modified()).ok();
    match (modified("rag_chunks.json"), modified("pdf_pages.json")) {
        (None, _) => false,
        (Some(_), None) => true,
        (Some(chunks), Some(pages)) => pages < chunks,
    }
}

/// Look up the PDF page of every recommendation in `projects` that lacks one.
///
/// Blocking and sequential; callers run it on a thread of its own. Failures
/// only cost the phone its page links, so they are logged and skipped.
#[cfg(desktop)]
fn build_page_indexes(projects: Vec<String>) {
    let state = AppState;
    let script = scripts_dir().join("build_pdf_pages.py");
    for project in projects {
        let dir = project_data_dir(&state, &project);
        if !page_index_stale(&dir) {
            continue;
        }
        let result = std::process::Command::new(python_exec())
            .arg(&script)
            .arg(&dir)
            .output();
        match result {
            Ok(out) if out.status.success() => {
                eprintln!("[pdf_pages] {}", String::from_utf8_lossy(&out.stdout).trim());
            }
            Ok(out) => eprintln!(
                "[pdf_pages] {}: {}",
                project,
                String::from_utf8_lossy(&out.stderr).trim()
            ),
            Err(e) => eprintln!("[pdf_pages] {}: {}", project, e),
        }
    }
}

/// Bring every project's page index up to date, once per launch.
#[cfg(desktop)]
fn refresh_page_indexes_once() {
    static STARTED: std::sync::Once = std::sync::Once::new();
    STARTED.call_once(|| {
        let Ok(config) = read_config(&AppState) else {
            return;
        };
        std::thread::spawn(move || build_page_indexes(config.projects));
    });
}

// ── Commands: export ─────────────────────────────────────────────────────────

#[cfg(desktop)]
fn csv_cell(value: &str) -> String {
    format!("\"{}\"", value.replace('"', "\"\""))
}

#[cfg(desktop)]
fn chunks_to_csv(chunks: &[Chunk]) -> String {
    let mut out = String::from(
        "id,tabel,klasse,evidence,ziekte,onderwerp,sectie,geaccordeerd,referenties,aanbeveling\n",
    );
    for c in chunks {
        let m = &c.metadata;
        let refs = m
            .ref_ids
            .iter()
            .map(|n| n.to_string())
            .collect::<Vec<_>>()
            .join(" ");
        let row = [
            c.id.as_str(),
            m.table_title.as_deref().unwrap_or(""),
            m.class.as_deref().unwrap_or(""),
            m.evidence.as_deref().unwrap_or(""),
            m.disease.as_deref().unwrap_or(""),
            m.topic.as_deref().unwrap_or(""),
            m.section.as_deref().unwrap_or(""),
            if m.approved { "ja" } else { "nee" },
            refs.as_str(),
            c.text.as_str(),
        ]
        .iter()
        .map(|v| csv_cell(v))
        .collect::<Vec<_>>()
        .join(",");
        out.push_str(&row);
        out.push('\n');
    }
    out
}

#[cfg(desktop)]
fn chunks_to_markdown(project: &str, chunks: &[Chunk]) -> String {
    let mut out = format!("# {}\n\n", project);

    // Grouped by recommendation table, in the guideline's own numbering, so the
    // export reads like the source document rather than like a database dump.
    let mut order: Vec<String> = Vec::new();
    let mut groups: HashMap<String, Vec<&Chunk>> = HashMap::new();
    for c in chunks {
        let key = c
            .metadata
            .table_title
            .as_deref()
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .unwrap_or("Overig")
            .to_string();
        if !groups.contains_key(&key) {
            order.push(key.clone());
        }
        groups.entry(key).or_default().push(c);
    }
    order.sort_by(|a, b| match (table_sort_num(a), table_sort_num(b)) {
        (Some(x), Some(y)) => x.cmp(&y),
        (Some(_), None) => std::cmp::Ordering::Less,
        (None, Some(_)) => std::cmp::Ordering::Greater,
        (None, None) => a.cmp(b),
    });

    for key in order {
        out.push_str(&format!("## {}\n\n", key));
        for c in groups.get(&key).into_iter().flatten() {
            let m = &c.metadata;
            out.push_str(&format!(
                "- **[{} / {}]** {}\n",
                m.class.as_deref().unwrap_or("—"),
                m.evidence.as_deref().unwrap_or("—"),
                c.text.trim()
            ));
            if !m.references.is_empty() {
                for r in &m.references {
                    out.push_str(&format!("  - _{}._ {}\n", r.id, r.text.trim()));
                }
            }
        }
        out.push('\n');
    }
    out
}

/// Write the (optionally approved-only) recommendations to a file the user picks.
/// Returns the chosen path, or None when the dialog was cancelled.
#[cfg(desktop)]
#[tauri::command]
pub async fn export_chunks(
    app: AppHandle,
    state: State<'_, AppState>,
    project: String,
    format: String,
    approved_only: bool,
) -> Result<Option<String>, String> {
    use tauri_plugin_dialog::DialogExt;

    let path = project_file(&state, &project, "rag_chunks.json");
    if !path.exists() {
        return Err("Geen chunks om te exporteren.".into());
    }
    let text = std::fs::read_to_string(&path).map_err(|e| e.to_string())?;
    let mut chunks: Vec<Chunk> = serde_json::from_str(&text).map_err(|e| e.to_string())?;
    if approved_only {
        chunks.retain(|c| c.metadata.approved);
    }
    if chunks.is_empty() {
        return Err("Niets te exporteren met deze selectie.".into());
    }

    let (ext, content) = match format.as_str() {
        "csv" => ("csv", chunks_to_csv(&chunks)),
        "md" => ("md", chunks_to_markdown(&project, &chunks)),
        "json" => (
            "json",
            serde_json::to_string_pretty(&chunks).map_err(|e| e.to_string())?,
        ),
        other => return Err(format!("Onbekend exportformaat: {}", other)),
    };

    let suffix = if approved_only { "-geaccordeerd" } else { "" };
    let default_name = format!("{}{}.{}", project.replace('/', "-"), suffix, ext);

    let target = app
        .dialog()
        .file()
        .set_file_name(&default_name)
        .add_filter(ext, &[ext])
        .blocking_save_file();

    let Some(target) = target else { return Ok(None) };
    let target = target
        .into_path()
        .map_err(|e| format!("Ongeldige bestemming: {}", e))?;

    std::fs::write(&target, content).map_err(|e| e.to_string())?;
    Ok(Some(target.to_string_lossy().to_string()))
}

// ── Commands: file dialog ─────────────────────────────────────────────────────

#[cfg(desktop)]
#[tauri::command]
pub async fn pick_pdf(app: AppHandle) -> Result<Option<String>, String> {
    use tauri_plugin_dialog::DialogExt;

    let result = app
        .dialog()
        .file()
        .add_filter("PDF bestanden", &["pdf"])
        .blocking_pick_file();

    Ok(result.map(|fp| fp.to_string()))
}

// ── Commands: env/API config ──────────────────────────────────────────────────

/// Trim whitespace and strip a matching pair of surrounding quotes.
/// Pasted API keys often carry quotes, which would otherwise be sent verbatim
/// and rejected as an invalid key.
#[cfg(desktop)]
fn clean_env_value(raw: &str) -> String {
    let v = raw.trim();
    let bytes = v.as_bytes();
    if v.len() >= 2
        && (bytes[0] == b'"' || bytes[0] == b'\'')
        && bytes[bytes.len() - 1] == bytes[0]
    {
        return v[1..v.len() - 1].trim().to_string();
    }
    v.to_string()
}

#[cfg(desktop)]
fn env_path() -> PathBuf {
    code_med_root().join(".env")
}

#[cfg(desktop)]
#[tauri::command]
pub fn get_env_config() -> Result<EnvConfig, String> {
    let path = env_path();
    if !path.exists() {
        return Ok(EnvConfig {
            mongodb_db: "rag_db".into(),
            mongodb_coll: "rag_chunks".into(),
            ..Default::default()
        });
    }
    let text = std::fs::read_to_string(&path).map_err(|e| e.to_string())?;
    let mut cfg = EnvConfig {
        mongodb_db: "rag_db".into(),
        mongodb_coll: "rag_chunks".into(),
        ..Default::default()
    };
    for line in text.lines() {
        if line.starts_with('#') || line.trim().is_empty() {
            continue;
        }
        if let Some((key, val)) = line.split_once('=') {
            let val = clean_env_value(val);
            match key.trim() {
                "OPENAI_API_KEY" => cfg.openai_key = val,
                "MONGODB_URI" => cfg.mongodb_uri = val,
                "MONGODB_DB" => cfg.mongodb_db = val,
                "MONGODB_COLL" => cfg.mongodb_coll = val,
                _ => {}
            }
        }
    }
    Ok(cfg)
}

#[cfg(desktop)]
/// Reject an OpenAI key that carries leftovers from a previous paste.
/// A well-formed key contains exactly one "sk-" prefix; a second one means the
/// input field was not cleared before pasting, and the concatenation is sent
/// verbatim to OpenAI and rejected as invalid.
fn validate_openai_key(key: &str) -> Result<(), String> {
    if key.is_empty() {
        return Ok(());
    }
    if !key.starts_with("sk-") {
        return Err("OpenAI-sleutel moet met \"sk-\" beginnen.".into());
    }
    if key.matches("sk-").count() > 1 {
        return Err(
            "OpenAI-sleutel bevat meerdere sleutels achter elkaar. Maak het veld \
             eerst leeg en plak daarna alleen de nieuwe sleutel."
                .into(),
        );
    }
    Ok(())
}

#[cfg(desktop)]
#[tauri::command]
pub fn save_env_config(
    config: EnvConfig,
) -> Result<(), String> {
    let path = env_path();
    let openai_key = clean_env_value(&config.openai_key);
    validate_openai_key(&openai_key)?;
    let content = format!(
        "OPENAI_API_KEY={}\nMONGODB_URI={}\nMONGODB_DB={}\nMONGODB_COLL={}\n",
        openai_key,
        clean_env_value(&config.mongodb_uri),
        clean_env_value(&config.mongodb_db),
        clean_env_value(&config.mongodb_coll),
    );
    std::fs::write(path, content).map_err(|e| e.to_string())
}

// ── Commands: storage & platform ─────────────────────────────────────────────

#[derive(Serialize)]
pub struct StorageInfo {
    /// "ios", "macos", "windows", "linux".
    pub platform: String,
    /// True on the read-only mobile build, which has no pipeline and no editing.
    pub read_only: bool,
    pub root: String,
    /// Whether the data lives in iCloud Drive or in the local fallback.
    pub using_icloud: bool,
    /// Why the data is not in iCloud, or what moving it there did.
    pub note: Option<String>,
    /// Files iCloud had not downloaded yet when the app started.
    pub pending_downloads: usize,
    /// Projects actually present on disk, so the mobile app can tell "iCloud has
    /// not synced yet" apart from "nothing was ever exported".
    pub available_projects: Vec<String>,
}

/// Resolve the data root and report what the frontend is working with.
///
/// Runs on a blocking thread: resolving the iCloud container asks Foundation to
/// provision it, which Apple documents as slow enough that it must stay off the
/// main thread. Every other command reuses the cached result, so this is the
/// only place that pays the cost. The frontend calls it before anything else.
#[tauri::command]
pub async fn init_storage() -> Result<StorageInfo, String> {
    tauri::async_runtime::spawn_blocking(|| {
        let root = storage::resolve_blocking();
        #[cfg(desktop)]
        refresh_page_indexes_once();
        // A phone only downloads iCloud files on request. Asking for all of
        // them here means the tabs find them on disk instead of each one
        // waiting on its own file.
        let pending_downloads =
            storage::ensure_tree(&root.join(MED_DIR), std::time::Duration::from_secs(15));
        let mut available_projects: Vec<String> =
            std::fs::read_dir(root.join(MED_DIR).join("projects"))
                .map(|entries| {
                    entries
                        .flatten()
                        .filter(|e| e.path().is_dir())
                        .map(|e| e.file_name().to_string_lossy().into_owned())
                        .collect()
                })
                .unwrap_or_default();
        available_projects.sort();

        StorageInfo {
            platform: std::env::consts::OS.to_string(),
            read_only: cfg!(mobile),
            root: root.to_string_lossy().into_owned(),
            using_icloud: storage::using_icloud(),
            note: storage::note(),
            pending_downloads,
            available_projects,
        }
    })
    .await
    .map_err(|e| format!("Kon de opslag niet initialiseren: {}", e))
}

// ── Commands: guideline text ─────────────────────────────────────────────────
//
// Reading the guideline on a phone. guideline.md runs to hundreds of kilobytes,
// far too much to hand a mobile webview in one piece, so it is served as an
// outline plus one section at a time.

/// Strip the bold/italic wrapping the PDF conversion leaves on every heading.
fn clean_heading(raw: &str) -> String {
    let mut t = raw.trim();
    loop {
        let stripped = t
            .strip_prefix("**")
            .and_then(|r| r.strip_suffix("**"))
            .or_else(|| t.strip_prefix('_').and_then(|r| r.strip_suffix('_')))
            .or_else(|| t.strip_prefix('*').and_then(|r| r.strip_suffix('*')));
        match stripped {
            Some(inner) => t = inner.trim(),
            None => break,
        }
    }
    t.to_string()
}

/// Nesting depth from a "4.1.3.2." style prefix.
///
/// The conversion flattens every heading to `##`, so the numbering the
/// guideline itself uses is the only structure left to indent by.
fn heading_depth(title: &str) -> usize {
    let prefix: String = title
        .chars()
        .take_while(|c| c.is_ascii_digit() || *c == '.')
        .collect();
    let depth = prefix.split('.').filter(|p| !p.is_empty()).count();
    depth.clamp(1, 4)
}

#[derive(Serialize)]
pub struct GuidelineSection {
    /// Position in the outline; also what `get_guideline_section` takes.
    pub index: usize,
    pub title: String,
    pub depth: usize,
    /// Characters of body text, so the UI can skip empty front-matter headings.
    pub length: usize,
}

/// Byte ranges of each section's body, in document order.
fn split_sections(markdown: &str) -> Vec<(String, usize, usize)> {
    let mut heads: Vec<(String, usize)> = vec![];
    let mut offset = 0usize;
    for line in markdown.split_inclusive('\n') {
        if let Some((_, title)) = is_heading(line) {
            heads.push((clean_heading(title), offset));
        }
        offset += line.len();
    }

    let mut out = vec![];
    for (i, (title, start)) in heads.iter().enumerate() {
        let end = heads.get(i + 1).map(|(_, s)| *s).unwrap_or(markdown.len());
        out.push((title.clone(), *start, end));
    }
    out
}

fn guideline_path(state: &AppState, project: &str) -> PathBuf {
    project_file(state, project, "guideline.md")
}

#[tauri::command]
pub fn get_guideline_outline(
    state: State<AppState>,
    project: String,
) -> Result<Vec<GuidelineSection>, String> {
    let path = guideline_path(&state, &project);
    if !path.exists() {
        return Ok(vec![]);
    }
    let md = std::fs::read_to_string(&path).map_err(|e| e.to_string())?;

    Ok(split_sections(&md)
        .into_iter()
        .enumerate()
        .map(|(index, (title, start, end))| GuidelineSection {
            index,
            depth: heading_depth(&title),
            length: end.saturating_sub(start),
            title,
        })
        .collect())
}

#[derive(Serialize)]
pub struct GuidelineSectionText {
    pub index: usize,
    pub title: String,
    pub markdown: String,
    pub has_prev: bool,
    pub has_next: bool,
}

#[tauri::command]
pub fn get_guideline_section(
    state: State<AppState>,
    project: String,
    index: usize,
) -> Result<GuidelineSectionText, String> {
    let path = guideline_path(&state, &project);
    let md = std::fs::read_to_string(&path)
        .map_err(|_| "Geen guideline.md voor dit project.".to_string())?;

    let sections = split_sections(&md);
    let (title, start, end) = sections
        .get(index)
        .cloned()
        .ok_or_else(|| format!("Sectie {} bestaat niet.", index))?;

    // The heading line itself is part of the range; the UI renders the title
    // separately, so drop it here rather than showing it twice.
    let body = md[start..end]
        .splitn(2, '\n')
        .nth(1)
        .unwrap_or("")
        .trim()
        .to_string();

    Ok(GuidelineSectionText {
        index,
        title,
        markdown: body,
        has_prev: index > 0,
        has_next: index + 1 < sections.len(),
    })
}

/// Full-text search across the guideline's sections.
///
/// Complements `search_chunks`: that one only sees extracted recommendations,
/// this one sees the prose around them.
#[derive(Serialize)]
pub struct GuidelineHit {
    pub index: usize,
    pub title: String,
    /// Text around the first match, for a result-list preview.
    pub snippet: String,
}

#[tauri::command]
pub fn search_guideline(
    state: State<AppState>,
    project: String,
    query: String,
) -> Result<Vec<GuidelineHit>, String> {
    let needle = query.trim().to_lowercase();
    if needle.is_empty() {
        return Ok(vec![]);
    }
    let path = guideline_path(&state, &project);
    if !path.exists() {
        return Ok(vec![]);
    }
    let md = std::fs::read_to_string(&path).map_err(|e| e.to_string())?;

    let mut hits = vec![];
    for (index, (title, start, end)) in split_sections(&md).into_iter().enumerate() {
        let body = &md[start..end];
        let Some(at) = body.to_lowercase().find(&needle) else {
            continue;
        };

        // Widen to char boundaries; slicing a UTF-8 string mid-character panics.
        let from = body[..at].char_indices().rev().nth(60).map(|(i, _)| i).unwrap_or(0);
        let to = body[at..]
            .char_indices()
            .nth(needle.chars().count() + 90)
            .map(|(i, _)| at + i)
            .unwrap_or(body.len());

        hits.push(GuidelineHit {
            index,
            title,
            snippet: body[from..to].split_whitespace().collect::<Vec<_>>().join(" "),
        });
        if hits.len() >= 60 {
            break;
        }
    }
    Ok(hits)
}

// ── Commands: PDF location (mobile) ──────────────────────────────────────────

/// Where a project's PDF sits and which page a recommendation is on.
///
/// iOS cannot run PyMuPDF, so it never searches the PDF itself — it reads the
/// `pdf_pages.json` cache the desktop app already built and synced, and hands
/// the page number to the Files app.
#[derive(Serialize)]
pub struct PdfLocation {
    pub file_name: String,
    /// Absolute path, shown so the file stays findable if opening fails.
    pub path: String,
    /// Files-app URL for the PDF.
    pub files_url: String,
    /// 1-based page for the requested chunk, when the desktop app cached one.
    pub page: Option<i64>,
}

#[tauri::command]
pub fn get_pdf_location(
    state: State<AppState>,
    project: String,
    chunk_id: Option<String>,
) -> Result<Option<PdfLocation>, String> {
    let Some(pdf) = project_pdf_path(&state, &project) else {
        return Ok(None);
    };
    // The cache is 0-based (it indexes PyMuPDF pages); readers count from 1.
    let page = chunk_id
        .and_then(|id| read_page_cache(&state, &project).get(&id).copied())
        .map(|p| p + 1);

    Ok(Some(PdfLocation {
        file_name: pdf
            .file_name()
            .map(|n| n.to_string_lossy().into_owned())
            .unwrap_or_default(),
        files_url: format!("shareddocuments://{}", pdf.to_string_lossy()),
        path: pdf.to_string_lossy().into_owned(),
        page,
    }))
}

/// The project's PDF as raw bytes, for the in-app viewer.
///
/// Sent as a binary IPC response rather than JSON: a guideline PDF runs to
/// ten-odd megabytes, and base64 or a number array would multiply that.
#[tauri::command]
pub fn read_project_pdf(
    state: State<AppState>,
    project: String,
) -> Result<tauri::ipc::Response, String> {
    let pdf = project_pdf_path(&state, &project).ok_or("Geen PDF gevonden voor dit project.")?;
    if storage::is_pending(&pdf) {
        return Err(pending_error(&pdf));
    }
    let bytes = std::fs::read(&pdf).map_err(|e| format!("{}: {}", pdf.display(), e))?;
    Ok(tauri::ipc::Response::new(bytes))
}

// ── Commands: external links (mobile) ────────────────────────────────────────

/// Mobile counterpart of the desktop `open_external`.
///
/// iOS has no child processes, so the opener plugin takes the place of `open`.
/// The same scheme check applies: reference strings come out of a PDF and are
/// untrusted input.
#[cfg(mobile)]
#[tauri::command]
pub fn open_external(app: tauri::AppHandle, url: String) -> Result<(), String> {
    use tauri_plugin_opener::OpenerExt;

    let trimmed = url.trim();
    let lower = trimmed.to_lowercase();
    let allowed = lower.starts_with("http://")
        || lower.starts_with("https://")
        || lower.starts_with("shareddocuments://");
    if !allowed || trimmed.chars().any(|c| c.is_control()) {
        return Err("Alleen http(s)-links kunnen geopend worden.".into());
    }

    app.opener()
        .open_url(trimmed, None::<&str>)
        .map_err(|e| format!("Kon niet openen: {}", e))
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    /// Every `qa_pairs.json` on this machine parses into the structs the Q&A
    /// tab renders.
    ///
    /// The project folders are gitignored, so this asserts nothing on a fresh
    /// clone — it exists to catch the case where the file is on disk but the
    /// tab shows nothing, which would otherwise look like a frontend bug.
    #[test]
    fn real_qa_pair_files_parse_into_what_the_tab_renders() {
        let projects = crate::storage::data_root().join(MED_DIR).join("projects");
        let Ok(entries) = std::fs::read_dir(&projects) else {
            return;
        };

        for entry in entries.flatten().filter(|e| e.path().is_dir()) {
            let path = entry.path().join("qa_pairs.json");
            if !path.exists() {
                continue;
            }
            let pairs = read_qa_pairs(&path).unwrap_or_else(|e| panic!("{}", e));
            assert!(
                pairs.iter().all(|p| !p.question.trim().is_empty()),
                "{} has a pair without a question",
                path.display()
            );
            println!("{}: {} pairs", path.display(), pairs.len());
        }
    }

    fn chunk(id: &str, class: &str, evidence: &str, table: &str, approved: bool) -> Chunk {
        Chunk {
            id: id.into(),
            text: "text".into(),
            metadata: ChunkMetadata {
                chunk_type: Some("recommendation".into()),
                class: Some(class.into()),
                evidence: Some(evidence.into()),
                disease: None,
                topic: None,
                section: None,
                table_title: Some(table.into()),
                guideline: Some("ESC HF".into()),
                year: Some("2026".into()),
                references: vec![],
                ref_ids: vec![1, 2],
                approved,
            },
        }
    }

    fn counts(entries: &[CountEntry]) -> Vec<(&str, usize)> {
        entries.iter().map(|e| (e.label.as_str(), e.count)).collect()
    }

    #[test]
    fn heading_titles_lose_their_markdown_wrapping() {
        assert_eq!(clean_heading("**4.1. Patients at risk**"), "4.1. Patients at risk");
        assert_eq!(clean_heading("_4.1.3.2. Smoking_"), "4.1.3.2. Smoking");
        assert_eq!(clean_heading("  Plain title  "), "Plain title");
    }

    #[test]
    fn heading_depth_follows_the_guideline_numbering() {
        // Every heading converts to "##", so the number prefix is the only
        // structure left to indent the outline by.
        assert_eq!(heading_depth("4. Prevention"), 1);
        assert_eq!(heading_depth("4.1. Patients at risk"), 2);
        assert_eq!(heading_depth("4.1.3.2. Smoking"), 4);
        assert_eq!(heading_depth("Abbreviations"), 1);
        // Deeper than the outline renders, clamped rather than dropped.
        assert_eq!(heading_depth("1.2.3.4.5. Deep"), 4);
    }

    #[test]
    fn sections_span_from_one_heading_to_the_next() {
        let md = "intro line\n## **1. First**\nbody one\n## **2. Second**\nbody two\n";
        let sections = split_sections(md);

        assert_eq!(sections.len(), 2);
        assert_eq!(sections[0].0, "1. First");
        assert_eq!(&md[sections[0].1..sections[0].2], "## **1. First**\nbody one\n");
        assert_eq!(sections[1].0, "2. Second");
        // The last section runs to the end of the document.
        assert_eq!(sections[1].2, md.len());
    }

    #[test]
    fn guideline_snippets_never_split_a_utf8_character() {
        // Accented text around the match would panic a byte-index slice.
        let body = "ééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééééé                     cardiomyopathie ééééééééééééééééééééééééééééééééééééé";
        let needle = "cardiomyopathie";
        let at = body.to_lowercase().find(needle).unwrap();

        let from = body[..at].char_indices().rev().nth(60).map(|(i, _)| i).unwrap_or(0);
        let to = body[at..]
            .char_indices()
            .nth(needle.chars().count() + 90)
            .map(|(i, _)| at + i)
            .unwrap_or(body.len());

        assert!(body[from..to].contains(needle));
    }

    #[test]
    fn counts_tables_recommendations_and_level_a() {
        let chunks = vec![
            chunk("r1", "Class I", "A", "Recommendation Table 2 — Later table", true),
            chunk("r2", "Class I", "A", "Recommendation Table 1 — First table", false),
            chunk("r3", "Class IIa", "C", "Recommendation Table 1 — First table", true),
            chunk("r4", "Class III", "B1", "", false),
        ];

        let info = build_guideline_info("HF".into(), &ProjectMeta::default(), &chunks, true, 1113);

        assert_eq!(info.table_count, 2); // the empty title is not a table
        assert_eq!(info.recommendation_count, 4);
        assert_eq!(info.evidence_a_count, 2);
        assert_eq!(info.approved_count, 2);
        assert_eq!(info.cited_reference_count, 2); // distinct ref ids
        assert_eq!(info.guideline_reference_count, 1113);
        assert_eq!(info.guideline.as_deref(), Some("ESC HF"));
        assert_eq!(info.year.as_deref(), Some("2026"));

        // Tables come back in guideline numbering order, not alphabetically.
        assert_eq!(info.tables[0].title, "Recommendation Table 1 — First table");
        assert_eq!(info.tables[0].recommendation_count, 2);
        assert_eq!(info.tables[0].evidence_a_count, 1);
        assert_eq!(info.tables[0].approved_count, 1);
        assert_eq!(info.tables[1].title, "Recommendation Table 2 — Later table");

        assert_eq!(
            counts(&info.class_counts),
            vec![("Class I", 2), ("Class IIa", 1), ("Class III", 1)]
        );
        assert_eq!(counts(&info.evidence_counts), vec![("A", 2), ("B1", 1), ("C", 1)]);
        assert_eq!(counts(&info.evidence_a_class_counts), vec![("Class I", 2)]);
    }

    #[test]
    fn missing_class_and_evidence_are_labelled_unknown() {
        let mut c = chunk("r1", "Class I", "A", "", false);
        c.metadata.class = None;
        c.metadata.evidence = Some("  ".into());

        let info = build_guideline_info("HF".into(), &ProjectMeta::default(), &[c], true, 0);

        assert_eq!(info.evidence_a_count, 0);
        assert_eq!(counts(&info.class_counts), vec![(UNKNOWN_LABEL, 1)]);
        assert_eq!(counts(&info.evidence_counts), vec![(UNKNOWN_LABEL, 1)]);
    }

    #[test]
    fn only_http_urls_reach_the_os_opener() {
        assert!(validate_web_url("https://pubmed.ncbi.nlm.nih.gov/?term=x").is_ok());
        assert!(validate_web_url("http://doi.org/10.1/x").is_ok());
        // A reference string is PDF-derived input; these must never be opened.
        assert!(validate_web_url("file:///etc/passwd").is_err());
        assert!(validate_web_url("javascript:alert(1)").is_err());
        assert!(validate_web_url("/Applications/Calculator.app").is_err());
        assert!(validate_web_url("https://ok.example\n-e /tmp/x").is_err());
    }

    #[test]
    fn csv_export_escapes_quotes_and_keeps_column_order() {
        let mut c = chunk("r1", "Class I", "A", "Recommendation Table 1 — X", true);
        c.text = "Use \"beta\"-blockers, always".into();
        c.metadata.ref_ids = vec![12, 34];

        let csv = chunks_to_csv(&[c]);
        let mut lines = csv.lines();
        assert!(lines.next().unwrap().starts_with("id,tabel,klasse,evidence"));
        let row = lines.next().unwrap();
        assert!(row.starts_with("\"r1\",\"Recommendation Table 1 — X\",\"Class I\",\"A\""));
        assert!(row.contains("\"12 34\""));
        assert!(row.ends_with("\"Use \"\"beta\"\"-blockers, always\""));
    }

    #[test]
    fn markdown_export_groups_by_table_in_guideline_order() {
        let chunks = vec![
            chunk("r1", "Class I", "A", "Recommendation Table 10 — Late", false),
            chunk("r2", "Class IIa", "B1", "Recommendation Table 2 — Early", false),
        ];

        let md = chunks_to_markdown("ESC Hartfalen", &chunks);

        let early = md.find("Table 2").expect("table 2 present");
        let late = md.find("Table 10").expect("table 10 present");
        // Numeric, not lexicographic: "10" must not sort before "2".
        assert!(early < late, "{}", md);
        assert!(md.contains("**[Class IIa / B1]**"));
    }

    #[test]
    fn reference_usage_is_ranked_and_gaps_are_reported() {
        let mut a = chunk("r1", "Class I", "A", "T1", false);
        a.metadata.ref_ids = vec![7, 9];
        a.metadata.references = vec![
            ReferenceEntry { id: 7, text: "Seven et al.".into() },
            ReferenceEntry { id: 9, text: "Nine et al.".into() },
        ];
        let mut b = chunk("r2", "Class I", "A", "T1", false);
        // 42 is cited but never resolved against guideline.md.
        b.metadata.ref_ids = vec![9, 42];
        b.metadata.references = vec![ReferenceEntry { id: 9, text: "Nine et al.".into() }];
        let mut c = chunk("r3", "Class I", "A", "T1", false);
        c.metadata.ref_ids.clear();

        let info = build_guideline_info("HF".into(), &ProjectMeta::default(), &[a, b, c], true, 0);

        assert_eq!(info.cited_reference_count, 3);
        assert_eq!(info.unresolved_reference_count, 1);
        assert_eq!(info.unreferenced_recommendation_count, 1);
        let top: Vec<_> = info.top_references.iter().map(|r| (r.id, r.count)).collect();
        assert_eq!(top, vec![(9, 2), (7, 1)]);
    }

    #[test]
    fn empty_project_reports_zeroes_and_falls_back_to_project_name() {
        let info = build_guideline_info("Valvular_2025".into(), &ProjectMeta::default(), &[], false, 0);

        assert!(!info.has_chunks);
        assert_eq!(info.table_count, 0);
        assert_eq!(info.recommendation_count, 0);
        assert_eq!(info.evidence_a_count, 0);
        assert_eq!(info.guideline.as_deref(), Some("Valvular_2025"));
    }
}
