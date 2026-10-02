#include "bindings/bindings.h"

int main(int argc, char * argv[]) {
	// Before start_app: the Rust commands look the bridge up on first use.
	ffi::rc_register_ai(ffi::rc_ai_status, ffi::rc_ai_generate, ffi::rc_ai_free);
	ffi::start_app();
	return 0;
}
