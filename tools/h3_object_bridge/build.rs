use std::{env, process::Command};
fn main() {
    let root = std::path::PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap()).join("../..");
    println!("cargo:rerun-if-env-changed=FOUNDRY_FAST_REVISION");
    println!(
        "cargo:rerun-if-changed={}",
        root.join(".git/HEAD").display()
    );
    println!(
        "cargo:rerun-if-changed={}",
        root.join(".git/refs/heads/feature/h3-scenario-inspection")
            .display()
    );
    let revision = env::var("FOUNDRY_FAST_REVISION")
        .ok()
        .or_else(|| {
            Command::new("git")
                .arg("-c")
                .arg(format!(
                    "safe.directory={}",
                    root.canonicalize().ok()?.display()
                ))
                .arg("-C")
                .arg(&root)
                .args(["rev-parse", "HEAD"])
                .output()
                .ok()
                .filter(|r| r.status.success())
                .map(|r| String::from_utf8_lossy(&r.stdout).trim().to_owned())
        })
        .unwrap_or_else(|| "unknown".into());
    println!("cargo:rustc-env=FOUNDRY_FAST_REVISION={revision}");
}
