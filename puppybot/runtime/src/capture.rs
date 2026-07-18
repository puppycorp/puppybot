use std::{
    collections::VecDeque,
    path::PathBuf,
    sync::{
        Arc, Mutex,
        atomic::{AtomicU64, Ordering},
        mpsc::{SyncSender, TrySendError, sync_channel},
    },
    time::{SystemTime, UNIX_EPOCH},
};

use crate::sim::{
    CaptureCameraView, CaptureStateV1, CaptureTraceV1, capture_trace_from_states,
    render_capture_state_png, render_capture_trace_mp4,
};

pub(crate) const MAX_SCREENSHOT_QUEUE: usize = 4;
pub(crate) const MAX_TERMINAL_JOBS: usize = 8;
pub(crate) const MAX_ARTIFACT_BYTES: usize = 16 * 1024 * 1024;
pub(crate) const MAX_RECORDING_ARTIFACT_BYTES: usize = 64 * 1024 * 1024;
pub(crate) const MAX_RETAINED_ARTIFACT_BYTES: usize = 128 * 1024 * 1024;
pub(crate) const MAX_TRACE_JSON_BYTES: usize = 96 * 1024 * 1024;
pub(crate) const MAX_RECORDING_FRAMES: u32 = 500;
pub(crate) const RECORDING_FPS: u32 = 50;
pub(crate) const MAX_CONCURRENT_RECORDINGS: usize = 2;

#[derive(Clone)]
pub(crate) struct CaptureManager {
    inner: Arc<Mutex<CaptureStore>>,
    worker: SyncSender<CaptureWork>,
    next_id: Arc<AtomicU64>,
}

struct CaptureStore {
    jobs: VecDeque<CaptureJob>,
    active_recordings: Vec<ActiveRecording>,
}

struct ActiveRecording {
    id: String,
    project_path: PathBuf,
    view: CaptureCameraView,
    target_frames: u32,
    sample_every_ticks: u32,
    sampled_ticks: u32,
    fps: u32,
    samples: Vec<Arc<CaptureStateV1>>,
}

struct CaptureJob {
    id: String,
    kind: &'static str,
    camera_source: String,
    status: &'static str,
    created_at_ms: u64,
    updated_at_ms: u64,
    state_json: Option<Arc<[u8]>>,
    artifact: Option<Arc<[u8]>>,
    artifact_content_type: &'static str,
    error: Option<String>,
}

enum CaptureWork {
    Screenshot {
        id: String,
        project_path: PathBuf,
        state: Arc<CaptureStateV1>,
    },
    Record {
        id: String,
        project_path: PathBuf,
        trace: CaptureTraceV1,
    },
}

pub(crate) struct CaptureFailure {
    pub(crate) status: &'static str,
    pub(crate) message: String,
}

impl CaptureManager {
    pub(crate) fn new() -> Self {
        let inner = Arc::new(Mutex::new(CaptureStore {
            jobs: VecDeque::new(),
            active_recordings: Vec::new(),
        }));
        let (worker, receiver) = sync_channel::<CaptureWork>(MAX_SCREENSHOT_QUEUE);
        let worker_store = Arc::clone(&inner);
        std::thread::Builder::new()
            .name("puppybot-capture-renderer".to_string())
            .spawn(move || {
                while let Ok(work) = receiver.recv() {
                    let (id, result) = match work {
                        CaptureWork::Screenshot { id, project_path, state } => {
                            update_job(&worker_store, &id, "rendering", None, None, None);
                            let state_json = serde_json::to_vec_pretty(state.as_ref())
                                .map(Vec::into)
                                .map_err(|err| format!("encode capture state: {err}"));
                            let result = state_json.and_then(|state_json: Arc<[u8]>| {
                                let png = render_capture_state_png(&project_path, &state, 0)?;
                                if png.len() > MAX_ARTIFACT_BYTES {
                                    return Err(format!(
                                        "screenshot artifact is {} bytes; limit is {MAX_ARTIFACT_BYTES}",
                                        png.len()
                                    ));
                                }
                                Ok((state_json, Arc::<[u8]>::from(png)))
                            });
                            (id, result)
                        }
                        CaptureWork::Record { id, project_path, trace } => {
                            update_job(&worker_store, &id, "rendering", None, None, None);
                            let state_json = serde_json::to_vec_pretty(&trace)
                                .map(Vec::into)
                                .map_err(|err| format!("encode capture trace: {err}"));
                            let result = state_json.and_then(|state_json: Arc<[u8]>| {
                                if state_json.len() > MAX_TRACE_JSON_BYTES {
                                    return Err(format!(
                                        "capture trace is {} bytes; limit is {MAX_TRACE_JSON_BYTES}",
                                        state_json.len()
                                    ));
                                }
                                let output = std::env::temp_dir().join(format!(
                                    "puppybot-{}-{id}.mp4",
                                    std::process::id()
                                ));
                                render_capture_trace_mp4(&project_path, &trace, &output)?;
                                let bytes = std::fs::read(&output)
                                    .map_err(|err| format!("read encoded recording: {err}"));
                                let _ = std::fs::remove_file(&output);
                                let bytes = bytes?;
                                if bytes.len() > MAX_RECORDING_ARTIFACT_BYTES {
                                    return Err(format!(
                                        "recording artifact is {} bytes; limit is {MAX_RECORDING_ARTIFACT_BYTES}",
                                        bytes.len()
                                    ));
                                }
                                Ok((state_json, Arc::<[u8]>::from(bytes)))
                            });
                            (id, result)
                        }
                    };
                    match result {
                        Ok((state_json, artifact)) => update_job(
                            &worker_store,
                            &id,
                            "complete",
                            Some(state_json),
                            Some(artifact),
                            None,
                        ),
                        Err(error) => update_job(
                            &worker_store,
                            &id,
                            "failed",
                            None,
                            None,
                            Some(error),
                        ),
                    }
                }
            })
            .expect("spawn PuppyBot capture renderer");
        Self {
            inner,
            worker,
            next_id: Arc::new(AtomicU64::new(1)),
        }
    }

    pub(crate) fn enqueue_screenshot(
        &self,
        project_path: PathBuf,
        state: Arc<CaptureStateV1>,
    ) -> Result<serde_json::Value, CaptureFailure> {
        let id = format!("c{:016x}", self.next_id.fetch_add(1, Ordering::Relaxed));
        let now = now_ms();
        {
            let mut store = self.inner.lock().map_err(|_| CaptureFailure {
                status: "500 Internal Server Error",
                message: "capture store lock poisoned".to_string(),
            })?;
            let active_screenshots = store
                .jobs
                .iter()
                .filter(|job| job.kind == "screenshot" && !terminal(job.status))
                .count();
            if active_screenshots >= MAX_SCREENSHOT_QUEUE {
                return Err(CaptureFailure {
                    status: "429 Too Many Requests",
                    message: format!("screenshot queue limit is {MAX_SCREENSHOT_QUEUE}"),
                });
            }
            evict_terminal_jobs(&mut store);
            store.jobs.push_back(CaptureJob {
                id: id.clone(),
                kind: "screenshot",
                camera_source: state.camera.source.clone(),
                status: "queued",
                created_at_ms: now,
                updated_at_ms: now,
                state_json: None,
                artifact: None,
                artifact_content_type: "image/png",
                error: None,
            });
        }
        match self.worker.try_send(CaptureWork::Screenshot {
            id: id.clone(),
            project_path,
            state,
        }) {
            Ok(()) => Ok(job_urls(&id)),
            Err(TrySendError::Full(_)) => {
                self.remove_job(&id);
                Err(CaptureFailure {
                    status: "429 Too Many Requests",
                    message: "capture renderer queue is full".to_string(),
                })
            }
            Err(TrySendError::Disconnected(_)) => {
                self.remove_job(&id);
                Err(CaptureFailure {
                    status: "500 Internal Server Error",
                    message: "capture renderer is unavailable".to_string(),
                })
            }
        }
    }

    pub(crate) fn begin_recording(
        &self,
        project_path: PathBuf,
        frames: u32,
        view: CaptureCameraView,
        sample_every_ticks: u32,
    ) -> Result<serde_json::Value, CaptureFailure> {
        if frames == 0 || frames > MAX_RECORDING_FRAMES {
            return Err(CaptureFailure {
                status: "400 Bad Request",
                message: format!("frames must be between 1 and {MAX_RECORDING_FRAMES}"),
            });
        }
        if sample_every_ticks == 0 || sample_every_ticks > RECORDING_FPS {
            return Err(CaptureFailure {
                status: "400 Bad Request",
                message: format!(
                    "sampleEveryTicks must be between 1 and {RECORDING_FPS}"
                ),
            });
        }
        let fps = RECORDING_FPS / sample_every_ticks;
        let id = format!("c{:016x}", self.next_id.fetch_add(1, Ordering::Relaxed));
        let now = now_ms();
        let mut store = self.inner.lock().map_err(store_error)?;
        if store.active_recordings.len() >= MAX_CONCURRENT_RECORDINGS {
            return Err(CaptureFailure {
                status: "429 Too Many Requests",
                message: format!(
                    "at most {MAX_CONCURRENT_RECORDINGS} recordings may be active"
                ),
            });
        }
        if store.active_recordings.iter().any(|active| active.view == view) {
            return Err(CaptureFailure {
                status: "409 Conflict",
                message: format!("a {} recording is already active", view.source()),
            });
        }
        evict_terminal_jobs(&mut store);
        store.jobs.push_back(CaptureJob {
            id: id.clone(),
            kind: "record",
            camera_source: view.source().to_string(),
            status: "capturing",
            created_at_ms: now,
            updated_at_ms: now,
            state_json: None,
            artifact: None,
            artifact_content_type: "video/mp4",
            error: None,
        });
        store.active_recordings.push(ActiveRecording {
            id: id.clone(),
            project_path,
            view,
            target_frames: frames,
            sample_every_ticks,
            sampled_ticks: 0,
            fps,
            samples: Vec::with_capacity(frames as usize),
        });
        Ok(job_urls(&id))
    }

    pub(crate) fn active_recording_views(&self) -> Vec<CaptureCameraView> {
        self.inner
            .lock()
            .ok()
            .map(|store| store.active_recordings.iter().map(|active| active.view).collect())
            .unwrap_or_default()
    }

    pub(crate) fn sample_recording(&self, view: CaptureCameraView, state: Arc<CaptureStateV1>) {
        let completed = {
            let Ok(mut store) = self.inner.lock() else {
                return;
            };
            let Some(index) = store.active_recordings.iter().position(|active| active.view == view) else {
                return;
            };
            let active = &mut store.active_recordings[index];
            active.sampled_ticks = active.sampled_ticks.saturating_add(1);
            if active.sampled_ticks % active.sample_every_ticks != 0 {
                return;
            }
            active.samples.push(state);
            if active.samples.len() < active.target_frames as usize {
                return;
            }
            Some(store.active_recordings.remove(index))
        };
        if let Some(completed) = completed {
            self.queue_recording(completed);
        }
    }

    pub(crate) fn stop_recording(&self, id: &str) -> Result<serde_json::Value, CaptureFailure> {
        validate_id(id)?;
        let completed = {
            let mut store = self.inner.lock().map_err(store_error)?;
            let index = store
                .active_recordings
                .iter()
                .position(|active| active.id == id)
                .ok_or_else(|| CaptureFailure {
                    status: "409 Conflict",
                    message: "recording is not active".to_string(),
                })?;
            if store.active_recordings[index].samples.is_empty() {
                return Err(CaptureFailure {
                    status: "409 Conflict",
                    message: "recording has no samples yet".to_string(),
                });
            }
            store.active_recordings.remove(index)
        };
        self.queue_recording(completed);
        Ok(job_urls(id))
    }

    fn queue_recording(&self, completed: ActiveRecording) {
        let id = completed.id.clone();
        let work = capture_trace_from_states(&completed.samples, completed.fps).map(|trace| {
            CaptureWork::Record {
                id: id.clone(),
                project_path: completed.project_path,
                trace,
            }
        });
        match work {
            Ok(work) => {
                update_job(&self.inner, &id, "queued", None, None, None);
                match self.worker.try_send(work) {
                    Ok(()) => {}
                    Err(_) => update_job(
                        &self.inner,
                        &id,
                        "failed",
                        None,
                        None,
                        Some("capture renderer queue is full".to_string()),
                    ),
                }
            }
            Err(error) => update_job(
                &self.inner,
                &id,
                "failed",
                None,
                None,
                Some(error),
            ),
        }
    }

    pub(crate) fn status(&self, id: &str) -> Result<serde_json::Value, CaptureFailure> {
        validate_id(id)?;
        let store = self.inner.lock().map_err(store_error)?;
        let job = store
            .jobs
            .iter()
            .find(|job| job.id == id)
            .ok_or_else(|| CaptureFailure {
                status: "404 Not Found",
                message: "unknown capture id".to_string(),
            })?;
        Ok(serde_json::json!({
            "id": job.id,
            "kind": job.kind,
            "camera": job.camera_source,
            "status": job.status,
            "createdAtMs": job.created_at_ms,
            "updatedAtMs": job.updated_at_ms,
            "error": job.error,
            "urls": job_urls(&job.id),
        }))
    }

    pub(crate) fn state(&self, id: &str) -> Result<Arc<[u8]>, CaptureFailure> {
        validate_id(id)?;
        let store = self.inner.lock().map_err(store_error)?;
        let job = store
            .jobs
            .iter()
            .find(|job| job.id == id)
            .ok_or_else(|| CaptureFailure {
                status: "404 Not Found",
                message: "unknown capture id".to_string(),
            })?;
        job.state_json.clone().ok_or_else(|| CaptureFailure {
            status: "409 Conflict",
            message: format!("capture state is not ready; job status is {}", job.status),
        })
    }

    pub(crate) fn artifact(&self, id: &str) -> Result<(&'static str, Arc<[u8]>), CaptureFailure> {
        validate_id(id)?;
        let store = self.inner.lock().map_err(store_error)?;
        let job = store
            .jobs
            .iter()
            .find(|job| job.id == id)
            .ok_or_else(|| CaptureFailure {
                status: "404 Not Found",
                message: "unknown capture id".to_string(),
            })?;
        job.artifact
            .clone()
            .map(|artifact| (job.artifact_content_type, artifact))
            .ok_or_else(|| CaptureFailure {
                status: "409 Conflict",
                message: format!(
                    "capture artifact is not ready; job status is {}",
                    job.status
                ),
            })
    }

    fn remove_job(&self, id: &str) {
        if let Ok(mut store) = self.inner.lock()
            && let Some(index) = store.jobs.iter().position(|job| job.id == id)
        {
            store.jobs.remove(index);
        }
    }
}

fn update_job(
    store: &Arc<Mutex<CaptureStore>>,
    id: &str,
    status: &'static str,
    state_json: Option<Arc<[u8]>>,
    artifact: Option<Arc<[u8]>>,
    error: Option<String>,
) {
    if let Ok(mut store) = store.lock()
        && let Some(job) = store.jobs.iter_mut().find(|job| job.id == id)
    {
        if terminal(job.status)
            || (status != "failed" && status_rank(status) < status_rank(job.status))
        {
            return;
        }
        job.status = status;
        job.updated_at_ms = now_ms();
        if state_json.is_some() {
            job.state_json = state_json;
        }
        if artifact.is_some() {
            job.artifact = artifact;
        }
        job.error = error;
        evict_terminal_jobs(&mut store);
    }
}

fn status_rank(status: &str) -> u8 {
    match status {
        "capturing" => 0,
        "queued" => 1,
        "rendering" => 2,
        "encoding" => 3,
        "complete" | "failed" => 4,
        _ => 0,
    }
}

fn terminal(status: &str) -> bool {
    matches!(status, "complete" | "failed")
}

fn evict_terminal_jobs(store: &mut CaptureStore) {
    while store.jobs.iter().filter(|job| terminal(job.status)).count() > MAX_TERMINAL_JOBS
        || retained_artifact_bytes(store) > MAX_RETAINED_ARTIFACT_BYTES
    {
        if let Some(index) = store.jobs.iter().position(|job| terminal(job.status)) {
            store.jobs.remove(index);
        } else {
            break;
        }
    }
}

fn retained_artifact_bytes(store: &CaptureStore) -> usize {
    store
        .jobs
        .iter()
        .filter_map(|job| job.artifact.as_ref())
        .fold(0usize, |total, artifact| {
            total.saturating_add(artifact.len())
        })
}

fn validate_id(id: &str) -> Result<(), CaptureFailure> {
    if id.len() == 17 && id.starts_with('c') && id[1..].bytes().all(|byte| byte.is_ascii_hexdigit())
    {
        Ok(())
    } else {
        Err(CaptureFailure {
            status: "404 Not Found",
            message: "unknown capture id".to_string(),
        })
    }
}

fn job_urls(id: &str) -> serde_json::Value {
    serde_json::json!({
        "status": format!("/api/sim/captures/{id}"),
        "state": format!("/api/sim/captures/{id}/state"),
        "artifact": format!("/api/sim/captures/{id}/artifact"),
    })
}

fn store_error(
    _: std::sync::PoisonError<std::sync::MutexGuard<'_, CaptureStore>>,
) -> CaptureFailure {
    CaptureFailure {
        status: "500 Internal Server Error",
        message: "capture store lock poisoned".to_string(),
    }
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .try_into()
        .unwrap_or(u64::MAX)
}
