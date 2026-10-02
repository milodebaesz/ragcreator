#pragma once

namespace ffi {
    extern "C" {
        void start_app();

        // Apple Intelligence bridge: implemented in AppleIntelligence.swift,
        // handed to Rust by address (see src-tauri/src/ai.rs).
        typedef char *(*rc_ai_status_fn)(void);
        typedef char *(*rc_ai_generate_fn)(const char *instructions, const char *prompt, double temperature);
        typedef void (*rc_ai_free_fn)(char *);

        void rc_register_ai(rc_ai_status_fn status, rc_ai_generate_fn generate, rc_ai_free_fn free_fn);

        char *rc_ai_status(void);
        char *rc_ai_generate(const char *instructions, const char *prompt, double temperature);
        void rc_ai_free(char *);
    }
}
