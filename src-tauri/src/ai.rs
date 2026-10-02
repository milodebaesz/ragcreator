//! Apple Intelligence, reached through a C bridge the iOS app installs.
//!
//! The model itself is Apple's on-device FoundationModels framework, which only
//! Swift can call. `AppleIntelligence.swift` wraps it in three C functions and
//! `main.mm` passes their addresses to `rc_register_ai` before the app starts.
//! Taking them as pointers rather than linking to them keeps this crate
//! buildable as a cdylib and on desktop, where nothing registers and every
//! call reports the model as unavailable.

use std::ffi::{c_char, CStr, CString};
use std::sync::OnceLock;

use serde::{Deserialize, Serialize};

type StatusFn = extern "C" fn() -> *mut c_char;
type GenerateFn = extern "C" fn(*const c_char, *const c_char, f64) -> *mut c_char;
type FreeFn = extern "C" fn(*mut c_char);

struct Bridge {
    status: StatusFn,
    generate: GenerateFn,
    free: FreeFn,
}

static BRIDGE: OnceLock<Bridge> = OnceLock::new();

/// Called once from `main.mm`, before `start_app`.
#[no_mangle]
pub extern "C" fn rc_register_ai(status: StatusFn, generate: GenerateFn, free: FreeFn) {
    BRIDGE.set(Bridge { status, generate, free }).ok();
}

impl Bridge {
    /// Take ownership of a string the Swift side allocated.
    fn take(&self, raw: *mut c_char) -> String {
        if raw.is_null() {
            return "{}".into();
        }
        // SAFETY: the Swift side returns a NUL-terminated strdup'd string,
        // which stays valid until handed back to its own free function.
        let text = unsafe { CStr::from_ptr(raw) }.to_string_lossy().into_owned();
        (self.free)(raw);
        text
    }
}

#[derive(Serialize, Deserialize, Debug)]
pub struct AiStatus {
    pub available: bool,
    #[serde(default)]
    pub reason: Option<String>,
}

#[tauri::command]
pub fn ai_status() -> AiStatus {
    let Some(bridge) = BRIDGE.get() else {
        return AiStatus {
            available: false,
            reason: Some("Apple Intelligence is alleen beschikbaar in de iOS-app.".into()),
        };
    };
    let raw = (bridge.status)();
    serde_json::from_str(&bridge.take(raw)).unwrap_or(AiStatus {
        available: false,
        reason: Some("Onleesbaar antwoord van Apple Intelligence.".into()),
    })
}

#[derive(Deserialize)]
struct GenerateReply {
    text: Option<String>,
    error: Option<String>,
}

/// One prompt, one answer, in a fresh session: nothing carries over between
/// questions, so an earlier answer can never colour the next one.
#[tauri::command]
pub async fn ai_generate(
    instructions: String,
    prompt: String,
    temperature: Option<f64>,
) -> Result<String, String> {
    let bridge = BRIDGE
        .get()
        .ok_or("Apple Intelligence is alleen beschikbaar in de iOS-app.")?;
    let instructions = CString::new(instructions).map_err(|e| e.to_string())?;
    let prompt = CString::new(prompt).map_err(|e| e.to_string())?;
    let temperature = temperature.unwrap_or(0.2).clamp(0.0, 1.0);

    // The Swift side blocks until the model is done — seconds, not millis —
    // so it must not run on the async runtime's worker threads.
    let raw = tauri::async_runtime::spawn_blocking(move || {
        bridge.take((bridge.generate)(instructions.as_ptr(), prompt.as_ptr(), temperature))
    })
    .await
    .map_err(|e| e.to_string())?;

    let reply: GenerateReply =
        serde_json::from_str(&raw).map_err(|_| "Onleesbaar antwoord van Apple Intelligence.".to_string())?;
    match (reply.text, reply.error) {
        (Some(text), _) => Ok(text),
        (None, Some(err)) => Err(err),
        (None, None) => Err("Apple Intelligence gaf geen antwoord.".into()),
    }
}
