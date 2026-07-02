use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::process::Stdio;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, State};
use tokio::io::AsyncBufReadExt;

// ── App state ────────────────────────────────────────────────────────────────

pub struct AppState {
    /// Absolute path to the RAGCreator repo root (contains medical_rag_project/).
    pub project_root: PathBuf,
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

#[derive(Serialize, Clone)]
pub struct LogEvent {
    pub step: u8,
    pub line: String,
    pub is_stderr: bool,
}

#[derive(Serialize, Clone)]
pub struct DoneEvent {
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
    pub references: Vec<String>,
    #[serde(default)]
    pub ref_ids: Vec<serde_json::Value>,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct Chunk {
    pub id: String,
    pub text: String,
    pub metadata: ChunkMetadata,
}

// ── Env/API config ────────────────────────────────────────────────────────────

#[derive(Serialize, Deserialize, Clone, Debug, Default)]
pub struct EnvConfig {
    pub openai_key: String,
    pub mongodb_uri: String,
    pub mongodb_db: String,
    pub mongodb_coll: String,
}

// ── Path helpers ──────────────────────────────────────────────────────────────

fn med_root(state: &AppState) -> PathBuf {
    state.project_root.join("medical_rag_project")
}

fn config_path(state: &AppState) -> PathBuf {
    med_root(state).join("rag_config.json")
}

fn project_data_dir(state: &AppState, project: &str) -> PathBuf {
    med_root(state).join("projects").join(project)
}

fn scripts_dir(state: &AppState) -> PathBuf {
    med_root(state).join("scripts")
}

fn python_exec(state: &AppState) -> PathBuf {
    let venv_py = med_root(state)
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

fn read_config(state: &AppState) -> Result<Config, String> {
    let path = config_path(state);
    if !path.exists() {
        return Ok(Config {
            active: String::new(),
            projects: vec![],
            project_meta: HashMap::new(),
        });
    }
    let text = std::fs::read_to_string(&path).map_err(|e| e.to_string())?;
    serde_json::from_str(&text).map_err(|e| e.to_string())
}

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

    let chunks_path = data_dir.join("rag_chunks.json");
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
        has_markdown: data_dir.join("guideline.md").exists(),
        has_chunks: chunks_path.exists(),
        has_qa: data_dir.join("qa_pairs.json").exists(),
        has_embeddings: data_dir.join("embeddings.json").exists(),
        chunk_count,
    })
}

// ── Commands: pipeline runner ─────────────────────────────────────────────────

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
    let script_path = scripts_dir(&state).join(script_name);
    let python = python_exec(&state);

    std::fs::create_dir_all(&data_dir).map_err(|e| e.to_string())?;

    if !script_path.exists() {
        return Err(format!("Script niet gevonden: {}", script_path.display()));
    }

    // Build environment
    let mut env_vars: HashMap<String, String> = HashMap::new();
    env_vars.insert("RAG_DATA_DIR".into(), data_dir.to_string_lossy().into());
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

    // Stream stdout
    let app_out = app.clone();
    tokio::spawn(async move {
        let mut lines = tokio::io::BufReader::new(stdout).lines();
        while let Ok(Some(line)) = lines.next_line().await {
            app_out
                .emit("pipeline-log", LogEvent { step, line, is_stderr: false })
                .ok();
        }
    });

    // Stream stderr
    let app_err = app.clone();
    tokio::spawn(async move {
        let mut lines = tokio::io::BufReader::new(stderr).lines();
        while let Ok(Some(line)) = lines.next_line().await {
            app_err
                .emit("pipeline-log", LogEvent { step, line, is_stderr: true })
                .ok();
        }
    });

    // Wait for exit and emit done
    tokio::spawn(async move {
        match child.wait().await {
            Ok(status) => {
                let exit_code = status.code().unwrap_or(-1);
                app.emit(
                    "pipeline-done",
                    DoneEvent {
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
                        step,
                        line: format!("FOUT: {}", e),
                        is_stderr: true,
                    },
                )
                .ok();
                app.emit(
                    "pipeline-done",
                    DoneEvent { step, success: false, exit_code: -1 },
                )
                .ok();
            }
        }
    });

    Ok(())
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
) -> Result<ChunksPage, String> {
    let path = project_data_dir(&state, &project).join("rag_chunks.json");
    if !path.exists() {
        return Ok(ChunksPage { items: vec![], total: 0 });
    }
    let text = std::fs::read_to_string(&path).map_err(|e| e.to_string())?;
    let all: Vec<Chunk> = serde_json::from_str(&text).map_err(|e| e.to_string())?;
    let total = all.len();
    let items = all.into_iter().skip(page * page_size).take(page_size).collect();
    Ok(ChunksPage { items, total })
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
    let path = project_data_dir(&state, &project).join("rag_chunks.json");
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

#[tauri::command]
pub fn save_chunk(
    state: State<AppState>,
    project: String,
    chunk: Chunk,
) -> Result<(), String> {
    let path = project_data_dir(&state, &project).join("rag_chunks.json");
    let mut all: Vec<Chunk> = if path.exists() {
        let text = std::fs::read_to_string(&path).map_err(|e| e.to_string())?;
        serde_json::from_str(&text).map_err(|e| e.to_string())?
    } else {
        vec![]
    };

    match all.iter_mut().find(|c| c.id == chunk.id) {
        Some(existing) => *existing = chunk,
        None => all.push(chunk),
    }

    let text = serde_json::to_string_pretty(&all).map_err(|e| e.to_string())?;
    std::fs::write(&path, text).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn delete_chunk(
    state: State<AppState>,
    project: String,
    id: String,
) -> Result<(), String> {
    let path = project_data_dir(&state, &project).join("rag_chunks.json");
    if !path.exists() {
        return Ok(());
    }
    let text = std::fs::read_to_string(&path).map_err(|e| e.to_string())?;
    let mut all: Vec<Chunk> = serde_json::from_str(&text).map_err(|e| e.to_string())?;
    all.retain(|c| c.id != id);

    let text = serde_json::to_string_pretty(&all).map_err(|e| e.to_string())?;
    std::fs::write(&path, text).map_err(|e| e.to_string())
}

// ── Commands: file dialog ─────────────────────────────────────────────────────

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

fn env_path(state: &AppState) -> PathBuf {
    med_root(state).join(".env")
}

#[tauri::command]
pub fn get_env_config(state: State<AppState>) -> Result<EnvConfig, String> {
    let path = env_path(&state);
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
            match key.trim() {
                "OPENAI_API_KEY" => cfg.openai_key = val.trim().to_string(),
                "MONGODB_URI" => cfg.mongodb_uri = val.trim().to_string(),
                "MONGODB_DB" => cfg.mongodb_db = val.trim().to_string(),
                "MONGODB_COLL" => cfg.mongodb_coll = val.trim().to_string(),
                _ => {}
            }
        }
    }
    Ok(cfg)
}

#[tauri::command]
pub fn save_env_config(
    state: State<AppState>,
    config: EnvConfig,
) -> Result<(), String> {
    let path = env_path(&state);
    let content = format!(
        "OPENAI_API_KEY={}\nMONGODB_URI={}\nMONGODB_DB={}\nMONGODB_COLL={}\n",
        config.openai_key,
        config.mongodb_uri,
        config.mongodb_db,
        config.mongodb_coll,
    );
    std::fs::write(path, content).map_err(|e| e.to_string())
}
