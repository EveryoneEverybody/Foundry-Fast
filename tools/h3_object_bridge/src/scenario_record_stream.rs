//! Bounded, lossless record storage for large scenario inventories.
use anyhow::{bail, Context, Result};
use flate2::{write::GzEncoder, Compression};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::fs::{self, File, OpenOptions};
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};

pub const CHUNK_BYTES: u64 = 8 * 1024 * 1024;
pub const TOTAL_BYTES: u64 = 8 * 1024 * 1024 * 1024;
pub const COMPRESSED_BYTES: u64 = 512 * 1024 * 1024;

struct Chunk {
    encoder: GzEncoder<BufWriter<File>>,
    temporary: PathBuf,
    relative: String,
    count: u64,
    bytes: u64,
}

pub struct RecordStream {
    directory: PathBuf,
    root_address: String,
    root_name: String,
    current: Option<Chunk>,
    pub chunks: Vec<Value>,
    pub count: u64,
    pub bytes: u64,
    pub compressed_bytes: u64,
    pub references: u64,
    pub diagnostics: BTreeMap<String, u64>,
}

impl RecordStream {
    pub fn new(directory: &Path) -> Result<Self> {
        fs::create_dir(directory.join("records"))?;
        Ok(Self { directory: directory.to_owned(), root_address: String::new(),
            root_name: String::new(), current: None, chunks: Vec::new(),
            count: 0, bytes: 0, compressed_bytes: 0, references: 0,
            diagnostics: BTreeMap::new() })
    }

    pub fn begin_root(&mut self, address: &str, name: &str) -> Result<()> {
        self.finish_chunk()?;
        self.root_address = address.to_owned();
        self.root_name = name.to_owned();
        Ok(())
    }

    pub fn push(&mut self, row: &Value) -> Result<()> {
        let address = row["address"].as_str().context("Missing record address")?;
        if self.root_address.is_empty() || !(address == self.root_address
            || address.starts_with(&format!("{}/", self.root_address))
            || address.starts_with(&format!("{}[", self.root_address))) {
            bail!("Record is outside its inventory section: {address}");
        }
        let content = serde_json::to_vec(row)?;
        let size = content.len() as u64 + 1;
        if size > CHUNK_BYTES || self.bytes.saturating_add(size) > TOTAL_BYTES {
            bail!("Scenario inventory byte budget exceeded at {address}; {} records written", self.count);
        }
        if self.current.as_ref().is_some_and(|c| c.bytes + size > CHUNK_BYTES) {
            self.finish_chunk()?;
        }
        if self.current.is_none() {
            if self.chunks.len() >= 65_536 { bail!("Scenario inventory chunk budget exceeded at {address}"); }
            let relative = format!("records/{:06}.jsonl.gz", self.chunks.len());
            let temporary = self.directory.join(format!("{relative}.part"));
            let file = OpenOptions::new().write(true).create_new(true).open(&temporary)?;
            self.current = Some(Chunk { encoder: GzEncoder::new(BufWriter::new(file), Compression::fast()),
                temporary, relative, count: 0, bytes: 0 });
        }
        let chunk = self.current.as_mut().unwrap();
        chunk.encoder.write_all(&content)?;
        chunk.encoder.write_all(b"\n")?;
        chunk.count += 1;
        chunk.bytes += size;
        self.count += 1;
        self.bytes += size;
        if row["kind"] == "value" && row["value"].get("group").is_some() {
            self.references += 1;
        }
        let code = if row["kind"] == "resource_header_only" {
            Some("resource_payload_not_decoded")
        } else if row["value"].get("representation").is_some() {
            Some("value_retained_as_decoder_debug")
        } else { None };
        if let Some(code) = code { *self.diagnostics.entry(code.to_owned()).or_default() += 1; }
        if self.count % 100_000 == 0 {
            println!("Scenario inventory: {} fields retained; section {}", self.count, self.root_name);
            std::io::stdout().flush()?;
        }
        Ok(())
    }

    pub fn finish_chunk(&mut self) -> Result<()> {
        if let Some(chunk) = self.current.take() {
            let mut writer = chunk.encoder.finish()?;
            writer.flush()?;
            let compressed = writer.get_ref().metadata()?.len();
            drop(writer);
            if self.compressed_bytes.saturating_add(compressed) > COMPRESSED_BYTES {
                bail!("Compressed scenario inventory budget exceeded in section {}", self.root_name);
            }
            fs::rename(&chunk.temporary, self.directory.join(&chunk.relative))?;
            self.compressed_bytes += compressed;
            self.chunks.push(json!({"file":chunk.relative, "bytes":compressed, "raw_bytes":chunk.bytes,
                "count":chunk.count, "root_address":self.root_address, "root_name":self.root_name}));
        }
        Ok(())
    }

    pub fn summary(&mut self) -> Result<Value> {
        self.finish_chunk()?;
        Ok(json!({"encoding":"gzip-jsonl", "record_count":self.count, "raw_bytes":self.bytes,
            "compressed_bytes":self.compressed_bytes, "reference_count":self.references,
            "chunks":self.chunks, "diagnostics":self.diagnostics.iter().map(|(code, count)|
                json!({"code":code,"count":count})).collect::<Vec<_>>()}))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{BufRead, BufReader};
    use std::sync::atomic::{AtomicUsize, Ordering};
    static NEXT: AtomicUsize = AtomicUsize::new(0);
    fn directory() -> PathBuf {
        let p = std::env::temp_dir().join(format!("h3_records_{}_{}", std::process::id(), NEXT.fetch_add(1, Ordering::Relaxed)));
        fs::create_dir(&p).unwrap();
        p
    }
    #[test]
    fn chunk_boundary_and_root_identity() {
        let p = directory();
        let mut out = RecordStream::new(&p).unwrap();
        out.begin_root("one#0", "one").unwrap();
        for i in 0..12 {
            out.push(&json!({"address":format!("one#0[{i}]/value#0"), "kind":"value", "value":"x".repeat(1_000_000)})).unwrap();
        }
        out.begin_root("two#1", "two").unwrap();
        out.push(&json!({"address":"two#1","kind":"resource_header_only"})).unwrap();
        let summary = out.summary().unwrap();
        assert_eq!(summary["record_count"], 13);
        assert_eq!(summary["chunks"].as_array().unwrap().len(), 3);
        assert!(out.chunks.iter().all(|c| c["raw_bytes"].as_u64().unwrap() <= CHUNK_BYTES));
        assert!(out.current.is_none());
        assert_eq!(summary["diagnostics"][0]["count"], 1);
        fs::remove_dir_all(p).unwrap();
    }
    #[test]
    fn bad_address_and_oversized_row_are_errors() {
        let p = directory();
        let mut out = RecordStream::new(&p).unwrap();
        out.begin_root("one#0", "one").unwrap();
        assert!(out.push(&json!({"address":"two#1"})).is_err());
        assert!(out.push(&json!({"address":"one#0","value":"x".repeat(CHUNK_BYTES as usize)})).is_err());
        assert_eq!(out.count, 0);
        fs::remove_dir_all(p).unwrap();
    }
    #[test]
    fn more_than_two_million_records_are_retained() {
        let p = directory();
        let mut out = RecordStream::new(&p).unwrap();
        out.begin_root("bulk#0", "bulk").unwrap();
        for i in 0..2_000_001u64 {
            out.push(&json!({"address":format!("bulk#0[{i}]/v#0"),"name":"v","raw_name":"v",
                "ordinal":0,"type":"long integer","kind":"value","value":i})).unwrap();
        }
        let summary = out.summary().unwrap();
        assert_eq!(summary["record_count"], 2_000_001u64);
        let mut count = 0u64;
        for chunk in &out.chunks {
            let decoder = flate2::read::GzDecoder::new(File::open(p.join(chunk["file"].as_str().unwrap())).unwrap());
            for line in BufReader::new(decoder).lines() {
                let value: Value = serde_json::from_str(&line.unwrap()).unwrap();
                assert_eq!(value["value"], count);
                count += 1;
            }
        }
        assert_eq!(count, 2_000_001);
        assert!(out.current.is_none());
        if let Ok(dest) = std::env::var("H3_LARGE_INVENTORY_OUTPUT") {
            let dest = PathBuf::from(dest);
            fs::create_dir_all(&dest).unwrap();
            fs::rename(p.join("records"), dest.join("records")).unwrap();
            let mut manifest = json!({"format":"foundry.h3-scenario-inspection","version":2,
                "source_group":"scnr","source_tag":"levels/test/test.scenario",
                "coordinate_encoding":"source_world_units_unmodified","destination_tags_written":false,
                "blob_count":0,"blob_bytes":0,
                "scope":{"named_scenario_fields":true,"opaque_data_blobs":true,
                    "bsp_dependencies_loaded":false,"resource_payloads_decoded":false,
                    "scripts_executed":false,"lossless_tag_roundtrip":false}});
            manifest.as_object_mut().unwrap().extend(summary.as_object().unwrap().clone());
            fs::write(dest.join("scenario.h3inspect.json"), serde_json::to_vec(&manifest).unwrap()).unwrap();
        }
        fs::remove_dir_all(p).unwrap();
    }
}
