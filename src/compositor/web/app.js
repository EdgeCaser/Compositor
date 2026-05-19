const state = {
  projects: [],
  actions: [],
  project: null,
  activeTab: "import",
  activeChapterId: null,
  activePacketId: null,
  reviewMode: "source",
  activeReviewFileId: null,
  reviewText: "",
  reviewLoadedText: "",
  reviewSha: "",
  reviewPreview: null,
  reviewParseError: null,
  reviewDirty: false,
  performancePacket: null,
  settings: {
    providers: {
      elevenlabs: {
        configured: false,
        storage_backend: "unsupported",
        storage_mode: "unset",
        voice_library_url: "https://elevenlabs.io/app/voice-library",
        cached_voices: [],
      },
    },
  },
  integrations: {
    claude_cli: { available: false, version: null, error: null },
    ffmpeg: { available: false, version: null, error: null },
  },
  renderedChapter: null,
  providerDialogOpen: false,
  providerForm: {
    api_key: "",
    validate: false,
  },
  importForm: {
    name: "",
    source_path: "",
    review_source_path: "",
    packet_source_path: "",
  },
  castForm: {
    slot: "",
    display_name: "",
    voice_id: "",
    gain_db: "0.0",
    role: "custom",
    provider_url: "https://elevenlabs.io/app/voice-library",
    notes: "",
  },
  error: "",
  busy: false,
};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]
  ));
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || response.statusText);
  }
  return payload;
}

function syncProjectState(project) {
  state.project = project;
  if (!state.project) {
    state.activeChapterId = null;
    state.activePacketId = null;
    state.activeReviewFileId = null;
    state.reviewMode = "source";
    state.performancePacket = null;
    return;
  }
  const chapters = state.project.chapters || [];
  const reviewFiles = state.project.review_files || [];
  const packets = state.project.performance_packets || [];
  if (!chapters.find((item) => item.id === state.activeChapterId)) {
    state.activeChapterId = chapters[0]?.id || null;
  }
  if (!reviewFiles.find((item) => item.id === state.activeReviewFileId)) {
    state.activeReviewFileId = null;
    state.reviewText = "";
    state.reviewLoadedText = "";
    state.reviewSha = "";
    state.reviewPreview = null;
    state.reviewParseError = null;
    state.reviewDirty = false;
    if (state.reviewMode === "yaml" && reviewFiles.length === 0) {
      state.reviewMode = "source";
    }
  }
  if (!packets.find((item) => item.id === state.activePacketId)) {
    state.activePacketId = packets[0]?.id || null;
    state.performancePacket = null;
  }
}

async function boot() {
  try {
    const [projectsPayload, actionsPayload, settingsPayload, integrationsPayload] = await Promise.all([
      api("/api/projects"),
      api("/api/actions"),
      api("/api/settings"),
      api("/api/integrations"),
    ]);
    state.projects = projectsPayload.projects;
    state.actions = actionsPayload.actions;
    state.settings = settingsPayload;
    state.integrations = integrationsPayload;
    if (state.projects.length && !state.project) {
      await loadProject(state.projects[0].id);
    } else {
      render();
    }
  } catch (error) {
    state.error = error.message;
    render();
  }
}

async function refreshProjects() {
  const payload = await api("/api/projects");
  state.projects = payload.projects;
}

async function browsePath(kind, field) {
  state.busy = true;
  render();
  try {
    const payload = await api("/api/picker", {
      method: "POST",
      body: JSON.stringify({ kind }),
    });
    if (payload.path) {
      state.importForm[field] = payload.path;
      state.error = "";
    }
  } catch (error) {
    state.error = error.message;
  } finally {
    state.busy = false;
    render();
  }
}

async function refreshSettings() {
  const payload = await api("/api/settings");
  state.settings = payload;
}

async function loadProject(projectId) {
  if (!projectId) {
    syncProjectState(null);
    render();
    return;
  }
  state.busy = true;
  render();
  try {
    const payload = await api(`/api/projects/${encodeURIComponent(projectId)}`);
    syncProjectState(payload.project);
    state.error = "";
  } catch (error) {
    state.error = error.message;
  } finally {
    state.busy = false;
    await refreshProjects();
    render();
  }
}

async function createProject(event) {
  event.preventDefault();
  const name = state.importForm.name.trim();
  if (!name) {
    state.error = "Project name is required.";
    render();
    return;
  }
  state.busy = true;
  render();
  try {
    const payload = await api("/api/projects", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    state.importForm.name = "";
    await refreshProjects();
    await loadProject(payload.project.id);
    state.activeTab = "import";
  } catch (error) {
    state.error = error.message;
  } finally {
    state.busy = false;
    render();
  }
}

async function importDocx(event) {
  event.preventDefault();
  const sourcePath = state.importForm.source_path.trim();
  const name = state.importForm.name.trim();
  if (!sourcePath) {
    state.error = "DOCX path is required.";
    render();
    return;
  }
  state.busy = true;
  render();
  try {
    const payload = await api("/api/projects/import-docx", {
      method: "POST",
      body: JSON.stringify({
        project_id: state.project?.id || null,
        name: state.project ? null : name,
        source_path: sourcePath,
      }),
    });
    state.importForm.source_path = "";
    syncProjectState(payload.project);
    await refreshProjects();
    state.activeTab = "review";
    state.reviewMode = "source";
    state.error = "";
  } catch (error) {
    state.error = error.message;
  } finally {
    state.busy = false;
    render();
  }
}

async function importReviewYaml(event) {
  event.preventDefault();
  const sourcePath = state.importForm.review_source_path.trim();
  const name = state.importForm.name.trim();
  if (!sourcePath) {
    state.error = "Review YAML path is required.";
    render();
    return;
  }
  state.busy = true;
  render();
  try {
    const payload = await api("/api/projects/import-review", {
      method: "POST",
      body: JSON.stringify({
        project_id: state.project?.id || null,
        name: state.project ? null : name,
        source_path: sourcePath,
      }),
    });
    state.importForm.review_source_path = "";
    syncProjectState(payload.project);
    await refreshProjects();
    state.activeTab = "review";
    state.reviewMode = "yaml";
    const newest = state.project.review_files.at(-1);
    if (newest) {
      await loadReviewFile(newest.id);
    } else {
      render();
    }
    state.error = "";
  } catch (error) {
    state.error = error.message;
    state.busy = false;
    render();
  }
}

async function importPerformancePacket(event) {
  event.preventDefault();
  const sourcePath = state.importForm.packet_source_path.trim();
  const name = state.importForm.name.trim();
  if (!sourcePath) {
    state.error = "Recording packet path is required.";
    render();
    return;
  }
  state.busy = true;
  render();
  try {
    const payload = await api("/api/projects/import-packet", {
      method: "POST",
      body: JSON.stringify({
        project_id: state.project?.id || null,
        name: state.project ? null : name,
        source_path: sourcePath,
      }),
    });
    state.importForm.packet_source_path = "";
    syncProjectState(payload.project);
    await refreshProjects();
    state.activeTab = "performance";
    const newest = state.project.performance_packets.at(-1);
    if (newest) {
      await loadPerformancePacket(newest.id);
    } else {
      render();
    }
    state.error = "";
  } catch (error) {
    state.error = error.message;
    state.busy = false;
    render();
  }
}

function elevenlabsSettings() {
  return state.settings?.providers?.elevenlabs || {
    configured: false,
    storage_backend: "unsupported",
    storage_mode: "unset",
    voice_library_url: "https://elevenlabs.io/app/voice-library",
    cached_voices: [],
  };
}

function openProviderDialog() {
  state.providerDialogOpen = true;
  state.providerForm.api_key = "";
  state.providerForm.validate = false;
  render();
}

function closeProviderDialog() {
  state.providerDialogOpen = false;
  state.providerForm.api_key = "";
  state.providerForm.validate = false;
  render();
}

async function saveProviderDialog(event) {
  event.preventDefault();
  const apiKey = state.providerForm.api_key.trim();
  if (!apiKey) {
    state.error = "An ElevenLabs API key is required.";
    render();
    return;
  }
  state.busy = true;
  render();
  try {
    state.settings = await api("/api/settings/elevenlabs", {
      method: "POST",
      body: JSON.stringify({
        api_key: apiKey,
        validate: Boolean(state.providerForm.validate),
      }),
    });
    state.providerDialogOpen = false;
    state.providerForm.api_key = "";
    state.providerForm.validate = false;
    state.error = "";
  } catch (error) {
    state.error = error.message;
  } finally {
    state.busy = false;
    render();
  }
}

async function clearProviderConfiguration() {
  if (!confirm("Clear the stored ElevenLabs API key from this workstation?")) {
    return;
  }
  state.busy = true;
  render();
  try {
    state.settings = await api("/api/settings/elevenlabs/clear", {
      method: "POST",
      body: JSON.stringify({}),
    });
    state.error = "";
  } catch (error) {
    state.error = error.message;
  } finally {
    state.busy = false;
    render();
  }
}

async function refreshElevenLabsVoices() {
  state.busy = true;
  render();
  try {
    const payload = await api("/api/providers/elevenlabs/voices?refresh=1");
    state.settings.providers.elevenlabs = {
      ...elevenlabsSettings(),
      configured: payload.configured,
      cached_voices: payload.voices || [],
      cached_voice_count: (payload.voices || []).length,
      account: payload.account || null,
      last_validated_at: payload.last_validated_at || null,
      last_error: payload.last_error || null,
    };
    state.error = "";
  } catch (error) {
    state.error = error.message;
  } finally {
    state.busy = false;
    render();
  }
}

function useAccountVoice(voiceId, displayName) {
  state.castForm.voice_id = voiceId || "";
  if (!state.castForm.display_name && displayName) {
    state.castForm.display_name = displayName;
  }
  state.activeTab = "cast";
  render();
}

function providerBackendLabel(provider) {
  const backend = provider?.storage_backend || provider?.storage_mode || "unsupported";
  if (backend === "windows_dpapi") {
    return "Windows DPAPI";
  }
  if (backend === "macos_keychain") {
    return "macOS Keychain";
  }
  if (backend === "unsupported") {
    return "Unsupported";
  }
  return backend;
}

async function saveCastVoice(event) {
  event.preventDefault();
  if (!state.project) {
    return;
  }
  state.busy = true;
  render();
  try {
    const payload = await api(`/api/projects/${encodeURIComponent(state.project.id)}/cast`, {
      method: "POST",
      body: JSON.stringify({
        ...state.castForm,
        gain_db: parseFloat(state.castForm.gain_db || "0"),
      }),
    });
    syncProjectState(payload.project);
    state.castForm = {
      slot: "",
      display_name: "",
      voice_id: "",
      gain_db: "0.0",
      role: "custom",
      provider_url: state.project.voice_library_url,
      notes: "",
    };
    state.activeTab = "cast";
    state.error = "";
  } catch (error) {
    state.error = error.message;
  } finally {
    state.busy = false;
    render();
  }
}

function editVoice(slot) {
  const voice = state.project?.cast?.find((item) => item.slot === slot);
  if (!voice) {
    return;
  }
  state.castForm = {
    slot: voice.slot || "",
    display_name: voice.display_name || "",
    voice_id: voice.voice_id || "",
    gain_db: String(voice.gain_db ?? 0),
    role: voice.role || "custom",
    provider_url: voice.provider_url || state.project.voice_library_url,
    notes: voice.notes || "",
  };
  state.activeTab = "cast";
  render();
}

async function runAction(actionId) {
  if (!state.project || !state.activeChapterId) {
    return;
  }
  state.busy = true;
  render();
  try {
    const payload = await api(`/api/projects/${encodeURIComponent(state.project.id)}/actions/run`, {
      method: "POST",
      body: JSON.stringify({ action_id: actionId, chapter_id: state.activeChapterId }),
    });
    syncProjectState(payload.project);
    state.activeTab = "performance";
    state.error = "";
  } catch (error) {
    state.error = error.message;
  } finally {
    state.busy = false;
    render();
  }
}

async function exportChapterReview(chapterId) {
  if (!state.project || !chapterId) {
    return;
  }
  state.busy = true;
  render();
  try {
    const payload = await api(
      `/api/projects/${encodeURIComponent(state.project.id)}/chapters/${encodeURIComponent(chapterId)}/export-review`,
      { method: "POST", body: JSON.stringify({}) },
    );
    syncProjectState(payload.project);
    await refreshProjects();
    state.activeTab = "review";
    state.reviewMode = "yaml";
    if (payload.review_file_id) {
      await loadReviewFile(payload.review_file_id);
      return;
    }
    state.error = "";
  } catch (error) {
    state.error = error.message;
  } finally {
    state.busy = false;
    render();
  }
}

async function saveProgress(chapterId) {
  if (!state.project) {
    return;
  }
  const field = document.querySelector(`[data-progress-input="${chapterId}"]`);
  const linesRead = parseInt(field?.value || "0", 10);
  state.busy = true;
  render();
  try {
    const payload = await api(`/api/projects/${encodeURIComponent(state.project.id)}/chapters/${encodeURIComponent(chapterId)}/progress`, {
      method: "POST",
      body: JSON.stringify({ lines_read: linesRead }),
    });
    syncProjectState(payload.project);
    state.error = "";
  } catch (error) {
    state.error = error.message;
  } finally {
    state.busy = false;
    render();
  }
}

async function loadReviewFile(fileId) {
  if (!state.project || !fileId) {
    return;
  }
  state.busy = true;
  state.reviewMode = "yaml";
  render();
  try {
    const payload = await api(`/api/projects/${encodeURIComponent(state.project.id)}/review-files/${encodeURIComponent(fileId)}`);
    state.activeReviewFileId = fileId;
    state.reviewText = payload.text;
    state.reviewLoadedText = payload.text;
    state.reviewSha = payload.sha256;
    state.reviewPreview = payload.preview;
    state.reviewParseError = payload.parse_error;
    state.reviewDirty = false;
    state.error = "";
  } catch (error) {
    state.error = error.message;
  } finally {
    state.busy = false;
    render();
  }
}

function updateReviewText(value) {
  state.reviewText = value;
  state.reviewDirty = state.reviewText !== state.reviewLoadedText;
  const badge = document.querySelector("[data-review-status]");
  if (badge) {
    badge.textContent = state.reviewDirty ? "Unsaved changes" : "Saved";
  }
}

async function previewReviewFile() {
  if (!state.project || !state.activeReviewFileId) {
    return;
  }
  state.busy = true;
  render();
  try {
    const payload = await api(`/api/projects/${encodeURIComponent(state.project.id)}/review-files/preview`, {
      method: "POST",
      body: JSON.stringify({ text: state.reviewText }),
    });
    state.reviewPreview = payload.preview;
    state.reviewParseError = payload.parse_error;
    state.error = "";
  } catch (error) {
    state.error = error.message;
  } finally {
    state.busy = false;
    render();
  }
}

async function changeReviewSegmentVoice(segmentId, voice) {
  if (!state.project || !state.activeReviewFileId) {
    return;
  }
  state.busy = true;
  render();
  try {
    const payload = await api(
      `/api/projects/${encodeURIComponent(state.project.id)}/review-files/${encodeURIComponent(state.activeReviewFileId)}/segment-voice`,
      {
        method: "POST",
        body: JSON.stringify({
          text: state.reviewText,
          segment_id: segmentId,
          voice,
        }),
      },
    );
    state.reviewText = payload.text;
    state.reviewPreview = payload.preview;
    state.reviewParseError = null;
    state.reviewDirty = state.reviewText !== state.reviewLoadedText;
    state.error = payload.cleared_performance
      ? "Voice updated. Existing performance link was cleared for that segment."
      : "";
  } catch (error) {
    state.error = error.message;
  } finally {
    state.busy = false;
    render();
  }
}

async function attributeReviewDialogue() {
  if (!state.project || !state.activeReviewFileId) {
    return;
  }
  if (state.reviewDirty) {
    state.error = "Save your edits before running AI attribution -- it rewrites the saved file.";
    render();
    return;
  }
  state.busy = true;
  render();
  try {
    const payload = await api(
      `/api/projects/${encodeURIComponent(state.project.id)}/review-files/${encodeURIComponent(state.activeReviewFileId)}/attribute`,
      { method: "POST", body: JSON.stringify({}) },
    );
    state.reviewText = payload.text;
    state.reviewLoadedText = payload.text;
    state.reviewSha = payload.sha256;
    state.reviewPreview = payload.preview;
    state.reviewParseError = null;
    state.reviewDirty = false;
    const projectPayload = await api(`/api/projects/${encodeURIComponent(state.project.id)}`);
    syncProjectState(projectPayload.project);
    await refreshProjects();
    state.error = payload.updated
      ? `AI attribution updated ${payload.updated} segment(s)${payload.skipped ? `; ${payload.skipped} left unresolved` : ""}.`
      : "AI attribution ran but did not change any segments.";
  } catch (error) {
    state.error = error.message;
  } finally {
    state.busy = false;
    render();
  }
}

async function synthesizeReviewFile(segmentIds = null) {
  if (!state.project || !state.activeReviewFileId) {
    return;
  }
  if (state.reviewDirty) {
    state.error = "Save your edits before synthesizing -- it rewrites the saved file.";
    render();
    return;
  }
  const provider = elevenlabsSettings();
  if (!provider.configured) {
    state.error = "Configure your ElevenLabs API key in the Cast tab first.";
    state.activeTab = "cast";
    render();
    return;
  }
  if (!segmentIds) {
    const pending = (state.reviewPreview?.segments || []).filter(
      (s) => s.kind !== "pause" && !s.performance,
    ).length;
    if (pending === 0) {
      state.error = "All non-pause segments already have a performance linked. Use Re-render on individual segments.";
      render();
      return;
    }
    if (!confirm(`Synthesize ${pending} segment(s) via ElevenLabs? This will draw against your account credits.`)) {
      return;
    }
  }
  state.busy = true;
  state.error = "Synthesizing -- this can take a few seconds per segment...";
  render();
  try {
    const payload = await api(
      `/api/projects/${encodeURIComponent(state.project.id)}/review-files/${encodeURIComponent(state.activeReviewFileId)}/synthesize`,
      {
        method: "POST",
        body: JSON.stringify(segmentIds ? { segment_ids: segmentIds } : {}),
      },
    );
    state.reviewText = payload.text;
    state.reviewLoadedText = payload.text;
    state.reviewSha = payload.sha256;
    state.reviewPreview = payload.preview;
    state.reviewParseError = null;
    state.reviewDirty = false;
    const projectPayload = await api(`/api/projects/${encodeURIComponent(state.project.id)}`);
    syncProjectState(projectPayload.project);
    await refreshProjects();
    const parts = [];
    parts.push(`Synthesized ${payload.synthesized.length} segment(s)`);
    if (payload.skipped.length) parts.push(`skipped ${payload.skipped.length}`);
    if (payload.errors.length) parts.push(`errors ${payload.errors.length}`);
    state.error = parts.join("; ") + ".";
    if (payload.errors.length) {
      console.warn("synthesis errors:", payload.errors);
    }
    if (payload.skipped.length) {
      console.warn("synthesis skipped:", payload.skipped);
    }
  } catch (error) {
    state.error = error.message;
  } finally {
    state.busy = false;
    render();
  }
}

async function renderReviewChapter() {
  if (!state.project || !state.activeReviewFileId) {
    return;
  }
  if (state.reviewDirty) {
    state.error = "Save your edits before rendering.";
    render();
    return;
  }
  if (!state.integrations?.ffmpeg?.available) {
    state.error = "ffmpeg not detected. Install it and restart the server.";
    render();
    return;
  }
  state.busy = true;
  state.error = "Rendering chapter via ffmpeg...";
  render();
  try {
    const payload = await api(
      `/api/projects/${encodeURIComponent(state.project.id)}/review-files/${encodeURIComponent(state.activeReviewFileId)}/render`,
      { method: "POST", body: JSON.stringify({}) },
    );
    state.renderedChapter = {
      reviewFileId: state.activeReviewFileId,
      name: payload.name,
      path: payload.path,
      bytes: payload.bytes,
      segmentsRendered: payload.segments_rendered,
      clipsTotal: payload.clips_total,
      url: `/api/projects/${encodeURIComponent(state.project.id)}/rendered/${payload.path.split("/").map(encodeURIComponent).join("/")}?t=${Date.now()}`,
    };
    state.error = `Rendered ${payload.name} (${(payload.bytes / (1024 * 1024)).toFixed(2)} MB, ${payload.segments_rendered} segments).`;
  } catch (error) {
    state.error = error.message;
  } finally {
    state.busy = false;
    render();
  }
}

async function rerenderReviewSegment(segmentId) {
  if (!state.project || !state.activeReviewFileId) {
    return;
  }
  if (state.reviewDirty) {
    state.error = "Save your edits before re-rendering.";
    render();
    return;
  }
  state.busy = true;
  render();
  try {
    await api(
      `/api/projects/${encodeURIComponent(state.project.id)}/review-files/${encodeURIComponent(state.activeReviewFileId)}/clear-performance`,
      { method: "POST", body: JSON.stringify({ segment_id: segmentId }) },
    );
    await synthesizeReviewFile([segmentId]);
  } catch (error) {
    state.error = error.message;
    state.busy = false;
    render();
  }
}

async function saveReviewFile() {
  if (!state.project || !state.activeReviewFileId) {
    return;
  }
  state.busy = true;
  render();
  try {
    const payload = await api(
      `/api/projects/${encodeURIComponent(state.project.id)}/review-files/${encodeURIComponent(state.activeReviewFileId)}/save`,
      {
        method: "POST",
        body: JSON.stringify({
          text: state.reviewText,
          expected_sha256: state.reviewSha,
        }),
      },
    );
    state.reviewLoadedText = state.reviewText;
    state.reviewSha = payload.sha256;
    state.reviewPreview = payload.preview;
    state.reviewParseError = null;
    state.reviewDirty = false;
    const projectPayload = await api(`/api/projects/${encodeURIComponent(state.project.id)}`);
    syncProjectState(projectPayload.project);
    await refreshProjects();
    state.error = "";
  } catch (error) {
    state.error = error.message;
  } finally {
    state.busy = false;
    render();
  }
}

async function undoProject() {
  if (!state.project) {
    return;
  }
  state.busy = true;
  render();
  try {
    const payload = await api(`/api/projects/${encodeURIComponent(state.project.id)}/undo`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    const previousReviewFileId = state.activeReviewFileId;
    const previousPacketId = state.activePacketId;
    syncProjectState(payload.project);
    await refreshProjects();
    state.error = "";
    if (previousReviewFileId && state.project.review_files.find((item) => item.id === previousReviewFileId)) {
      await loadReviewFile(previousReviewFileId);
      return;
    }
    if (previousPacketId && state.project.performance_packets.find((item) => item.id === previousPacketId)) {
      await loadPerformancePacket(previousPacketId);
      return;
    }
  } catch (error) {
    state.error = error.message;
  } finally {
    state.busy = false;
    render();
  }
}

function selectTab(tab) {
  state.activeTab = tab;
  if (tab === "performance" && state.activePacketId && !state.performancePacket) {
    loadPerformancePacket(state.activePacketId);
    return;
  }
  render();
}

function selectChapter(chapterId) {
  state.activeChapterId = chapterId;
  state.reviewMode = "source";
  render();
}

function selectPacket(packetId) {
  loadPerformancePacket(packetId);
}

function selectReviewMode(mode) {
  state.reviewMode = mode;
  render();
}

function currentChapter() {
  return state.project?.chapters?.find((item) => item.id === state.activeChapterId) || state.project?.chapters?.[0] || null;
}

function currentReviewFileMeta() {
  return state.project?.review_files?.find((item) => item.id === state.activeReviewFileId) || null;
}

function currentPacketMeta() {
  return state.project?.performance_packets?.find((item) => item.id === state.activePacketId) || null;
}

function topButton(label) {
  return `<button class="ghost" onclick="window.scrollTo({ top: 0, behavior: 'smooth' })">${escapeHtml(label)}</button>`;
}

function reviewVoiceChoices(segment) {
  const projectSlots = (state.project?.cast || []).map((voice) => voice.slot);
  const previewSlots = Array.isArray(state.reviewPreview?.voice_slots_available)
    ? state.reviewPreview.voice_slots_available
    : [];
  return [...new Set([...projectSlots, ...previewSlots, segment.voice].filter(Boolean))];
}

function reviewVoiceOptions(segment) {
  return reviewVoiceChoices(segment).map((slot) => `
    <option value="${escapeHtml(slot)}" ${slot === segment.voice ? "selected" : ""}>${escapeHtml(slot)}</option>
  `).join("");
}

async function loadPerformancePacket(packetId) {
  if (!state.project || !packetId) {
    return;
  }
  state.busy = true;
  state.activePacketId = packetId;
  render();
  try {
    const payload = await api(`/api/projects/${encodeURIComponent(state.project.id)}/packets/${encodeURIComponent(packetId)}`);
    state.performancePacket = payload;
    state.error = "";
  } catch (error) {
    state.performancePacket = null;
    state.error = error.message;
  } finally {
    state.busy = false;
    render();
  }
}

function packetVoiceChoices(segment) {
  const projectSlots = (state.project?.cast || []).map((voice) => voice.slot);
  return [...new Set([...projectSlots, segment.voice_slot, segment.review_voice, segment.shotlist_voice].filter(Boolean))];
}

async function changePacketSegmentVoice(segmentId, voice) {
  if (!state.project || !state.activePacketId) {
    return;
  }
  state.busy = true;
  render();
  try {
    const payload = await api(`/api/projects/${encodeURIComponent(state.project.id)}/packets/${encodeURIComponent(state.activePacketId)}/segment-voice`, {
      method: "POST",
      body: JSON.stringify({ segment_id: segmentId, voice }),
    });
    syncProjectState(payload.project);
    state.performancePacket = payload.packet;
    state.error = "";
  } catch (error) {
    state.error = error.message;
  } finally {
    state.busy = false;
    render();
  }
}

async function togglePacketSegmentPerformance(segmentId, approved) {
  if (!state.project || !state.activePacketId) {
    return;
  }
  state.busy = true;
  render();
  try {
    const payload = await api(`/api/projects/${encodeURIComponent(state.project.id)}/packets/${encodeURIComponent(state.activePacketId)}/performance`, {
      method: "POST",
      body: JSON.stringify({ segment_id: segmentId, approved }),
    });
    syncProjectState(payload.project);
    state.performancePacket = payload.packet;
    state.error = "";
  } catch (error) {
    state.error = error.message;
  } finally {
    state.busy = false;
    render();
  }
}

function renderProjectSidebar() {
  const items = state.projects.map((project) => `
    <button class="project-link ${state.project?.id === project.id ? "active" : ""}" onclick="loadProject('${escapeHtml(project.id)}')">
      <strong>${escapeHtml(project.name)}</strong>
      <span>${project.chapters} chapters · ${project.review_files || 0} review files · ${project.performance_packets || 0} packets</span>
    </button>
  `).join("");

  return `
    <section class="panel sidebar-panel">
      <div class="sidebar-header">
        <h1>Compositor</h1>
        <p>Review + performance in one shell.</p>
      </div>
      <div class="project-list">${items || "<p class='empty'>No projects yet.</p>"}</div>
    </section>
  `;
}

function renderImportTab() {
  return `
    <section class="panel">
      <h2>Import</h2>
      <p class="muted">Use local paths to bring source docs or existing review YAMLs into a project.</p>
      <div class="import-grid">
        <form class="stack" onsubmit="createProject(event)">
          <label>New project name
            <input value="${escapeHtml(state.importForm.name)}" oninput="state.importForm.name = this.value">
          </label>
          <button type="submit">Create Empty Project</button>
        </form>
        <form class="stack" onsubmit="importDocx(event)">
          <label>Project name
            <input value="${escapeHtml(state.importForm.name)}" oninput="state.importForm.name = this.value" placeholder="${state.project ? "Ignored while a project is selected" : "Cold Storage"}">
          </label>
          <label>Word doc path
            <div class="path-picker">
              <input value="${escapeHtml(state.importForm.source_path)}" oninput="state.importForm.source_path = this.value" placeholder="C:\\path\\to\\Chapter 1.docx">
              <button type="button" class="ghost" onclick="browsePath('docx', 'source_path')">Browse...</button>
            </div>
          </label>
          <button type="submit">${state.project ? "Import DOCX Into Current Project" : "Create Project From DOCX"}</button>
        </form>
      </div>
      <div class="import-grid">
        <div class="stack">
          <h3>Review YAML Import</h3>
          <p class="muted">Bring in existing .review.yaml files so the real review workflow lives inside Compositor.</p>
        </div>
        <form class="stack" onsubmit="importReviewYaml(event)">
          <label>Project name
            <input value="${escapeHtml(state.importForm.name)}" oninput="state.importForm.name = this.value" placeholder="${state.project ? "Ignored while a project is selected" : "Cold Storage"}">
          </label>
          <label>Review YAML path
            <div class="path-picker">
              <input value="${escapeHtml(state.importForm.review_source_path)}" oninput="state.importForm.review_source_path = this.value" placeholder="C:\\path\\to\\06_Chapter 3.review.yaml">
              <button type="button" class="ghost" onclick="browsePath('yaml', 'review_source_path')">Browse...</button>
            </div>
          </label>
          <button type="submit">${state.project ? "Import Review YAML" : "Create Project From Review YAML"}</button>
        </form>
      </div>
      <div class="import-grid">
        <div class="stack">
          <h3>Recording Packet Import</h3>
          <p class="muted">Bring in a legacy STS packet with its shotlist, staging takes, and approved performances.</p>
        </div>
        <form class="stack" onsubmit="importPerformancePacket(event)">
          <label>Project name
            <input value="${escapeHtml(state.importForm.name)}" oninput="state.importForm.name = this.value" placeholder="${state.project ? "Ignored while a project is selected" : "Cold Storage"}">
          </label>
          <label>Recording packet path
            <div class="path-picker">
              <input value="${escapeHtml(state.importForm.packet_source_path)}" oninput="state.importForm.packet_source_path = this.value" placeholder="C:\\path\\to\\06_Chapter 3">
              <button type="button" class="ghost" onclick="browsePath('packet', 'packet_source_path')">Browse...</button>
            </div>
          </label>
          <button type="submit">${state.project ? "Import Recording Packet" : "Create Project From Packet"}</button>
        </form>
      </div>
      ${state.project ? `
        <div class="summary-row">
          <div><strong>Current project:</strong> ${escapeHtml(state.project.name)}</div>
          <div><strong>Chapters:</strong> ${state.project.chapters.length}</div>
          <div><strong>Review files:</strong> ${state.project.review_files.length}</div>
          <div><strong>Packets:</strong> ${state.project.performance_packets.length}</div>
          <div><strong>History snapshots:</strong> ${state.project.history.length}</div>
        </div>
      ` : ""}
    </section>
  `;
}

function renderSourceReviewPanel(chapter) {
  if (!chapter) {
    return "<p class='empty'>Import a chapter to start reviewing.</p>";
  }
  const paragraphs = chapter.paragraphs.slice(0, 24).map((para) => `
    <article class="paragraph-card ${escapeHtml(para.kind)}">
      <header>
        <span>#${para.index + 1}</span>
        <span>${escapeHtml(para.kind)}</span>
        <span>${escapeHtml(para.guidance || "flat")}</span>
        <span>${escapeHtml(para.voice_slot || "narrator")}</span>
      </header>
      <p>${escapeHtml(para.text)}</p>
    </article>
  `).join("");
  return `
    <div class="stack">
      <div class="panel-actions">
        <button type="button" onclick="exportChapterReview('${escapeHtml(chapter.id)}')">Generate Review YAML</button>
        <span class="muted">Writes a .review.yaml from these heuristic-tagged paragraphs and opens it in the editor.</span>
      </div>
      <div class="stats-grid">
        <div><strong>${chapter.stats.dialogue_paragraphs}</strong><span>Dialogue</span></div>
        <div><strong>${chapter.stats.mixed_paragraphs}</strong><span>Mixed</span></div>
        <div><strong>${chapter.stats.narration_paragraphs}</strong><span>Narration</span></div>
        <div><strong>${chapter.stats.estimated_lines}</strong><span>Estimated lines</span></div>
      </div>
      <div class="paragraph-list">${paragraphs || "<p class='empty'>No paragraphs extracted.</p>"}</div>
    </div>
  `;
}

function renderReviewValidation(validation) {
  const issues = Object.entries(validation || {}).filter(([, ids]) => Array.isArray(ids) && ids.length);
  if (!issues.length) {
    return `<div class="message-strip ok">Structural validation is clean.</div>`;
  }
  return `
    <div class="message-strip">
      ${issues.map(([name, ids]) => `<div><strong>${escapeHtml(name)}</strong>: ${escapeHtml(ids.join(", "))}</div>`).join("")}
    </div>
  `;
}

function renderReviewYamlPanel() {
  const meta = currentReviewFileMeta();
  if (!meta) {
    return "<p class='empty'>Import or select a review YAML to start editing.</p>";
  }
  const preview = state.reviewPreview;
  const parseError = state.reviewParseError;
  const tts = elevenlabsSettings().configured;
  const segments = preview?.segments?.map((segment) => `
    <article class="review-segment ${escapeHtml(segment.kind)}">
      <header>
        <span>#${segment.id}</span>
        <span>${escapeHtml(segment.kind)}</span>
        <span>${escapeHtml(segment.mood || "-")}</span>
        ${segment.performance ? `<span>performance linked</span>` : ""}
      </header>
      <p>${escapeHtml(segment.text)}</p>
      ${segment.kind === "pause" ? `
        <div class="segment-controls"><span class="muted">Pause ${segment.pause_ms || 0} ms</span></div>
      ` : `
        <div class="segment-controls">
          <label>Voice
            <select onchange="changeReviewSegmentVoice(${segment.id}, this.value)">
              ${reviewVoiceOptions(segment)}
            </select>
          </label>
          <span class="muted">Attribution: ${escapeHtml(segment.attribution || "-")}</span>
          ${tts && segment.performance
            ? `<button type="button" class="ghost" onclick="rerenderReviewSegment(${segment.id})">Re-render</button>`
            : ""}
          ${tts && !segment.performance
            ? `<button type="button" class="ghost" onclick="synthesizeReviewFile([${segment.id}])">Render</button>`
            : ""}
        </div>
      `}
    </article>
  `).join("") || "<p class='empty'>No preview available yet.</p>";

  return `
    <div class="stack">
      <div class="panel-header">
        <div>
          <h3>${escapeHtml(meta.name)}</h3>
          <p class="muted">${escapeHtml(meta.source_path || "")}</p>
        </div>
        <div class="topbar-actions">
          <span class="review-status" data-review-status>${state.reviewDirty ? "Unsaved changes" : "Saved"}</span>
          <button class="ghost" onclick="previewReviewFile()">Validate</button>
          ${state.integrations?.claude_cli?.available
            ? `<button class="ghost" onclick="attributeReviewDialogue()" title="Uses your local Claude CLI session">AI Attribution</button>`
            : `<button class="ghost" disabled title="${escapeHtml(state.integrations?.claude_cli?.error || "claude CLI not detected")}">AI Attribution</button>`}
          ${elevenlabsSettings().configured
            ? `<button class="ghost" onclick="synthesizeReviewFile()" title="Renders pending segments via ElevenLabs">Synthesize</button>`
            : `<button class="ghost" disabled title="Configure ElevenLabs in the Cast tab to enable">Synthesize</button>`}
          ${state.integrations?.ffmpeg?.available
            ? `<button onclick="renderReviewChapter()" title="Stitch all segments + pauses into one mp3 via ffmpeg">Render Chapter</button>`
            : `<button disabled title="${escapeHtml(state.integrations?.ffmpeg?.error || "ffmpeg not detected")}">Render Chapter</button>`}
          <button onclick="saveReviewFile()">Save YAML</button>
        </div>
      </div>
      <div class="summary-row">
        <div><strong>Source:</strong> ${escapeHtml(preview?.source || "—")}</div>
        <div><strong>Output:</strong> ${escapeHtml(preview?.output || "—")}</div>
        <div><strong>Narrator:</strong> ${escapeHtml(preview?.narrator || "—")}</div>
        <div><strong>Segments:</strong> ${preview?.stats?.segments ?? "—"}</div>
      </div>
      ${state.renderedChapter && state.renderedChapter.reviewFileId === state.activeReviewFileId ? `
        <div class="message-strip ok">
          <div><strong>Rendered:</strong> ${escapeHtml(state.renderedChapter.name)} (${(state.renderedChapter.bytes / (1024 * 1024)).toFixed(2)} MB)</div>
          <audio controls src="${escapeHtml(state.renderedChapter.url)}" style="width:100%;margin-top:0.5rem"></audio>
          <div><a class="button-link ghost" href="${escapeHtml(state.renderedChapter.url)}" download="${escapeHtml(state.renderedChapter.name)}">Download mp3</a></div>
        </div>
      ` : ""}
      ${parseError ? `
        <div class="message-strip error">
          Parse error: ${escapeHtml(parseError.message || "Invalid YAML")}
          ${parseError.line ? `<div>Line ${parseError.line}, column ${parseError.column || 1}</div>` : ""}
        </div>
      ` : ""}
      ${preview ? renderReviewValidation(preview.validation) : ""}
      <div class="review-editor-layout">
        <div class="stack">
          <h4>Raw YAML</h4>
          <textarea class="yaml-editor" oninput="updateReviewText(this.value)">${escapeHtml(state.reviewText)}</textarea>
        </div>
        <div class="stack">
          <h4>Rendered Segments</h4>
          <div class="review-preview-list">${segments}</div>
        </div>
      </div>
    </div>
  `;
}

function renderReviewTab() {
  if (!state.project) {
    return `<section class="panel"><h2>Review</h2><p class="empty">Import a chapter or review YAML to start.</p></section>`;
  }
  const chapter = currentChapter();
  const chapterList = (state.project.chapters || []).map((item) => `
    <button class="chapter-link ${chapter?.id === item.id && state.reviewMode === "source" ? "active" : ""}" onclick="selectChapter('${escapeHtml(item.id)}')">
      <strong>${escapeHtml(item.title)}</strong>
      <span>${item.stats.paragraphs} paragraphs</span>
    </button>
  `).join("");
  const reviewList = (state.project.review_files || []).map((item) => `
    <button class="chapter-link ${state.activeReviewFileId === item.id && state.reviewMode === "yaml" ? "active" : ""}" onclick="loadReviewFile('${escapeHtml(item.id)}')">
      <strong>${escapeHtml(item.name)}</strong>
      <span>Imported ${escapeHtml(item.imported_at || "")}</span>
    </button>
  `).join("");
  return `
    <section class="panel">
      <div class="panel-header">
        <div>
          <h2>Review</h2>
          <p class="muted">Source heuristics and real review-YAML editing now live together.</p>
        </div>
        ${topButton("Back To Top")}
      </div>
      <div class="review-layout">
        <aside class="chapter-column">
          <div class="section-label">Source Chapters</div>
          ${chapterList || "<p class='empty'>No source chapters.</p>"}
          <div class="section-label">Review YAMLs</div>
          ${reviewList || "<p class='empty'>No imported review YAMLs yet.</p>"}
        </aside>
        <div class="chapter-detail">
          <div class="mode-toggle">
            <button class="${state.reviewMode === "source" ? "active" : ""}" onclick="selectReviewMode('source')">Source Review</button>
            <button class="${state.reviewMode === "yaml" ? "active" : ""}" onclick="selectReviewMode('yaml')">YAML Review</button>
          </div>
          ${state.reviewMode === "yaml" ? renderReviewYamlPanel() : renderSourceReviewPanel(chapter)}
        </div>
      </div>
    </section>
  `;
}

function renderPerformanceTab() {
  if (!state.project) {
    return `<section class="panel"><h2>Performance</h2><p class="empty">Create or load a project first.</p></section>`;
  }
  const packetMeta = currentPacketMeta();
  const packetPayload = state.performancePacket;
  const packetList = (state.project.performance_packets || []).map((item) => `
    <button class="chapter-link ${state.activePacketId === item.id ? "active" : ""}" onclick="selectPacket('${escapeHtml(item.id)}')">
      <strong>${escapeHtml(item.name)}</strong>
      <span>${escapeHtml(item.review_name || "Unlinked review")}</span>
    </button>
  `).join("");
  const tracker = state.project.chapters.map((item) => {
    const estimated = Math.max(item.stats.estimated_lines || 0, 1);
    const linesRead = item.stats.lines_read || 0;
    const percent = Math.min(100, Math.round((linesRead / estimated) * 100));
    return `
      <article class="progress-card">
        <header>
          <strong>${escapeHtml(item.title)}</strong>
          <span>${linesRead}/${estimated}</span>
        </header>
        <div class="progress-bar"><span style="width:${percent}%"></span></div>
        <div class="progress-controls">
          <input data-progress-input="${escapeHtml(item.id)}" type="number" min="0" value="${linesRead}">
          <button onclick="saveProgress('${escapeHtml(item.id)}')">Save</button>
        </div>
      </article>
    `;
  }).join("");
  const actions = state.actions.map((action) => `
    <button onclick="runAction('${escapeHtml(action.id)}')">
      <strong>${escapeHtml(action.label)}</strong>
      <span>${escapeHtml(action.description)}</span>
    </button>
  `).join("");
  const summary = packetPayload ? `
    <div class="stats-grid performance-stats">
      <div><strong>${packetPayload.counts.approved}</strong><span>Approved</span></div>
      <div><strong>${packetPayload.counts.ready}</strong><span>Generated</span></div>
      <div><strong>${packetPayload.counts.recorded}</strong><span>Recorded</span></div>
      <div><strong>${packetPayload.counts.pending}</strong><span>Pending</span></div>
    </div>
  ` : `<p class="empty">Select an imported packet to inspect its review linkage and segment states.</p>`;
  const segments = packetPayload?.segments?.map((segment) => `
    <article class="review-segment dialogue ${segment.issues?.length ? "flagged" : ""}">
      <header>
        <span>#${segment.segment_id}</span>
        <span>${escapeHtml(segment.status)}</span>
        <span>${escapeHtml(segment.voice_slot || "—")}</span>
        <span>${segment.performance_exists ? "performance linked" : `${segment.takes_count || 0} take(s)`}</span>
      </header>
      <p>${escapeHtml(segment.text)}</p>
      ${segment.rationale ? `<p class="muted"><strong>Why:</strong> ${escapeHtml(segment.rationale)}</p>` : ""}
      <div class="segment-context">
        ${segment.context_before ? `<div><strong>Before:</strong> ${escapeHtml(segment.context_before)}</div>` : ""}
        ${segment.context_after ? `<div><strong>After:</strong> ${escapeHtml(segment.context_after)}</div>` : ""}
      </div>
      <div class="segment-controls">
        <label>Voice
          <select onchange="changePacketSegmentVoice(${segment.segment_id}, this.value)">
            ${packetVoiceChoices(segment).map((slot) => `
              <option value="${escapeHtml(slot)}" ${slot === segment.voice_slot ? "selected" : ""}>${escapeHtml(slot)}</option>
            `).join("")}
          </select>
        </label>
        <button class="ghost" onclick="togglePacketSegmentPerformance(${segment.segment_id}, ${segment.performance_exists ? "false" : "true"})">
          ${segment.performance_exists ? "Clear Performance" : "Approve Performance"}
        </button>
      </div>
      <div class="segment-metadata">
        <span>Shotlist voice: ${escapeHtml(segment.shotlist_voice || "—")}</span>
        <span>Review voice: ${escapeHtml(segment.review_voice || "—")}</span>
        <span>Mood: ${escapeHtml(segment.mood || "—")}</span>
        ${segment.performance_path ? `<span>Path: ${escapeHtml(segment.performance_path)}</span>` : ""}
      </div>
      ${segment.issues?.length ? `<div class="message-strip error">${segment.issues.map((issue) => escapeHtml(issue)).join(", ")}</div>` : ""}
    </article>
  `).join("") || "<p class='empty'>No packet segments loaded.</p>";
  return `
    <section class="panel">
      <div class="panel-header">
        <div>
          <h2>Performance</h2>
          <p class="muted">${packetMeta ? `Active packet: ${packetMeta.name}` : "Import or select a packet to manage approvals and voice drift."}</p>
        </div>
        ${topButton("Back To Top")}
      </div>
      <div class="review-layout performance-shell">
        <aside class="chapter-column">
          <div class="section-label">Packets</div>
          ${packetList || "<p class='empty'>No imported packets yet.</p>"}
          <div class="section-label">Project Progress</div>
          <div class="progress-grid">${tracker}</div>
        </aside>
        <div class="chapter-detail">
          <div class="stack">
            <div class="summary-row">
              <div><strong>Review:</strong> ${escapeHtml(packetPayload?.review_file?.name || packetMeta?.review_name || "Unlinked")}</div>
              <div><strong>Chapter refs:</strong> ${packetPayload?.chapter_reference_files?.length || 0}</div>
              <div><strong>Issues:</strong> ${packetPayload?.counts?.issues ?? 0}</div>
              <div><strong>Snapshots:</strong> ${state.project.history.length}</div>
            </div>
            ${packetPayload?.review_parse_error ? `
              <div class="message-strip error">
                Review parse error: ${escapeHtml(packetPayload.review_parse_error.message || "Invalid YAML")}
              </div>
            ` : ""}
            ${summary}
            <div class="stack">
              <h3>Segment Queue</h3>
              <div class="review-preview-list">${segments}</div>
            </div>
            <div class="stack">
              <h3>Action Runner</h3>
              <div class="action-grid">${actions}</div>
            </div>
          </div>
        </div>
      </div>
    </section>
  `;
}

function renderProviderDialog() {
  if (!state.providerDialogOpen) {
    return "";
  }
  const provider = elevenlabsSettings();
  return `
    <div class="modal-backdrop" onclick="closeProviderDialog()">
      <div class="modal-card" onclick="event.stopPropagation()">
        <div class="panel-header">
          <div>
            <h3>Configure ElevenLabs</h3>
            <p class="muted">The API key is stored outside the repo using ${escapeHtml(providerBackendLabel(provider))}.</p>
          </div>
          <button class="ghost" type="button" onclick="closeProviderDialog()">Close</button>
        </div>
        <form class="stack" onsubmit="saveProviderDialog(event)">
          <label>API key
            <input type="password" value="${escapeHtml(state.providerForm.api_key)}" oninput="state.providerForm.api_key = this.value" placeholder="sk_...">
          </label>
          <label class="inline-check">
            <input type="checkbox" ${state.providerForm.validate ? "checked" : ""} onchange="state.providerForm.validate = this.checked">
            <span>Validate now by calling ElevenLabs and caching account voices.</span>
          </label>
          <div class="panel-actions">
            <button type="submit">Save Securely</button>
            <a class="ghost button-link" href="${escapeHtml(provider.voice_library_url || state.project?.voice_library_url || "https://elevenlabs.io/app/voice-library")}" target="_blank" rel="noreferrer">Open Voice Library</a>
          </div>
        </form>
      </div>
    </div>
  `;
}

function renderCastTab() {
  if (!state.project) {
    return `<section class="panel"><h2>Cast</h2><p class="empty">Load a project to manage voices.</p></section>`;
  }
  const provider = elevenlabsSettings();
  const rows = state.project.cast.map((voice) => `
    <tr>
      <td>${escapeHtml(voice.slot)}</td>
      <td>${escapeHtml(voice.display_name)}</td>
      <td>${escapeHtml(voice.voice_id || "—")}</td>
      <td>${escapeHtml(String(voice.gain_db ?? 0))}</td>
      <td>${escapeHtml(voice.role || "custom")}</td>
      <td><button class="ghost" onclick="editVoice('${escapeHtml(voice.slot)}')">Edit</button></td>
    </tr>
  `).join("");
  return `
    <section class="panel">
      <div class="panel-header">
        <div>
          <h2>Cast</h2>
          <p class="muted">Add voices on the fly and keep the slot list attached to the project.</p>
        </div>
        <div class="panel-actions">
          <button class="ghost" type="button" onclick="openProviderDialog()">${provider.configured ? "Replace API Key" : "Configure ElevenLabs"}</button>
          <a class="ghost button-link" href="${escapeHtml(provider.voice_library_url || state.project.voice_library_url)}" target="_blank" rel="noreferrer">Open ElevenLabs Voice Library</a>
        </div>
      </div>
      <div class="stack provider-card">
        <div class="summary-row">
          <div><strong>Status:</strong> ${provider.configured ? "Configured" : "Not configured"}</div>
          <div><strong>Backend:</strong> ${escapeHtml(providerBackendLabel(provider))}</div>
          <div><strong>Mode:</strong> ${escapeHtml(provider.storage_mode || "unset")}</div>
          <div><strong>Cached voices:</strong> ${provider.cached_voice_count || (provider.cached_voices || []).length || 0}</div>
          <div><strong>Last validated:</strong> ${escapeHtml(provider.last_validated_at || "—")}</div>
        </div>
        ${provider.account ? `
          <div class="summary-row">
            <div><strong>Tier:</strong> ${escapeHtml(provider.account.tier || "—")}</div>
            <div><strong>Usage:</strong> ${escapeHtml(provider.account.character_count ?? "—")} / ${escapeHtml(provider.account.character_limit ?? "—")}</div>
          </div>
        ` : ""}
        ${provider.last_error ? `<div class="message-strip error">${escapeHtml(provider.last_error)}</div>` : ""}
        <div class="panel-actions">
          <button type="button" onclick="refreshElevenLabsVoices()" ${provider.configured ? "" : "disabled"}>Refresh Account Voices</button>
          <button class="ghost" type="button" onclick="clearProviderConfiguration()" ${provider.configured ? "" : "disabled"}>Clear Stored Key</button>
        </div>
        <div class="voice-browser">
          ${(provider.cached_voices || []).slice(0, 24).map((voice) => `
            <article class="voice-browser-card">
              <header>
                <strong>${escapeHtml(voice.name || "Unnamed Voice")}</strong>
                <span>${escapeHtml(voice.category || "custom")}</span>
              </header>
              <p>${escapeHtml(voice.description || "")}</p>
              <div class="segment-metadata">
                <span>${escapeHtml(voice.voice_id || "")}</span>
              </div>
              <div class="panel-actions">
                <button class="ghost" type="button" onclick='useAccountVoice(${JSON.stringify(voice.voice_id || "")}, ${JSON.stringify(voice.name || "")})'>Use In Cast Form</button>
                ${voice.preview_url ? `<a class="ghost button-link" href="${escapeHtml(voice.preview_url)}" target="_blank" rel="noreferrer">Preview</a>` : ""}
              </div>
            </article>
          `).join("") || "<p class='empty'>No cached account voices yet. Configure the provider and refresh to pull them in.</p>"}
        </div>
      </div>
      <div class="cast-layout">
        <div class="stack">
          <table>
            <thead>
              <tr><th>Slot</th><th>Name</th><th>Voice ID</th><th>Gain</th><th>Role</th><th></th></tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
        <div class="stack">
          <form class="stack" onsubmit="saveCastVoice(event)">
            <label>Slot
              <input value="${escapeHtml(state.castForm.slot)}" oninput="state.castForm.slot = this.value" placeholder="generic_female_3">
            </label>
            <label>Display name
              <input value="${escapeHtml(state.castForm.display_name)}" oninput="state.castForm.display_name = this.value" placeholder="Generic Female 3">
            </label>
            <label>ElevenLabs voice ID
              <input value="${escapeHtml(state.castForm.voice_id)}" oninput="state.castForm.voice_id = this.value" placeholder="lSmT8ZuVqRPz7bAz1xrJ">
            </label>
            <label>Gain dB
              <input value="${escapeHtml(state.castForm.gain_db)}" oninput="state.castForm.gain_db = this.value" placeholder="2.23">
            </label>
            <label>Role
              <select onchange="state.castForm.role = this.value">
                ${["custom", "narrator", "dialogue_default", "dialogue_female", "dialogue_male"].map((role) => `
                  <option value="${role}" ${state.castForm.role === role ? "selected" : ""}>${role}</option>
                `).join("")}
              </select>
            </label>
            <label>Provider URL
              <input value="${escapeHtml(state.castForm.provider_url)}" oninput="state.castForm.provider_url = this.value">
            </label>
            <label>Notes
              <textarea oninput="state.castForm.notes = this.value">${escapeHtml(state.castForm.notes)}</textarea>
            </label>
            <button type="submit">Save Voice</button>
          </form>
          <div class="voice-lab">
            <h3>Voice Creation Prompt Draft</h3>
            <textarea placeholder="Write the voice brief you want to use before creating or remixing a voice in ElevenLabs."></textarea>
            <p class="muted">Use this as a staging area, then jump out to clones, remixes, or the voice library.</p>
          </div>
        </div>
      </div>
      ${renderProviderDialog()}
    </section>
  `;
}

function renderJobsTab() {
  if (!state.project) {
    return `<section class="panel"><h2>Jobs</h2><p class="empty">No project loaded.</p></section>`;
  }
  const jobs = state.project.jobs.map((job) => `
    <article class="job-card">
      <header>
        <strong>${escapeHtml(job.action_id)}</strong>
        <span>${escapeHtml(job.chapter_title || job.chapter_id)}</span>
        <span>${escapeHtml(job.ran_at || "")}</span>
      </header>
      <pre>${escapeHtml(JSON.stringify(job.summary, null, 2))}</pre>
    </article>
  `).join("");
  const history = state.project.history.slice().reverse().slice(0, 12).map((item) => `
    <li><strong>${escapeHtml(item.label)}</strong><span>${escapeHtml(item.timestamp)}</span></li>
  `).join("");
  return `
    <section class="panel">
      <div class="panel-header">
        <div>
          <h2>Jobs</h2>
          <p class="muted">Action runs and project snapshot history.</p>
        </div>
        <button class="ghost" onclick="undoProject()">Undo</button>
      </div>
      <div class="jobs-layout">
        <div class="stack">
          <h3>Recent Jobs</h3>
          <div class="job-list">${jobs || "<p class='empty'>No jobs run yet.</p>"}</div>
        </div>
        <div class="stack">
          <h3>History</h3>
          <ol class="history-list">${history || "<li>No snapshots yet.</li>"}</ol>
        </div>
      </div>
    </section>
  `;
}

function renderTabs() {
  const tabs = [
    ["import", "Import"],
    ["review", "Review"],
    ["performance", "Performance"],
    ["cast", "Cast"],
    ["jobs", "Jobs"],
  ];
  return `
    <nav class="tabs">
      ${tabs.map(([id, label]) => `
        <button class="${state.activeTab === id ? "active" : ""}" onclick="selectTab('${id}')">${label}</button>
      `).join("")}
    </nav>
  `;
}

function renderMain() {
  const tabMap = {
    import: renderImportTab,
    review: renderReviewTab,
    performance: renderPerformanceTab,
    cast: renderCastTab,
    jobs: renderJobsTab,
  };
  const body = (tabMap[state.activeTab] || renderImportTab)();
  return `
    <main class="main">
      <header class="topbar">
        <div>
          <h1>${escapeHtml(state.project?.name || "Standalone Compositor")}</h1>
          <p>${state.project ? `${state.project.chapters.length} chapters, ${state.project.review_files.length} review files, ${state.project.performance_packets.length} packets, ${state.project.cast.length} cast voices` : "Create a project to start."}</p>
        </div>
        <div class="topbar-actions">
          ${state.project ? `<button class="ghost" onclick="undoProject()">Undo</button>` : ""}
        </div>
      </header>
      ${state.error ? `<div class="error-banner">${escapeHtml(state.error)}</div>` : ""}
      ${state.busy ? `<div class="busy-banner">Working...</div>` : ""}
      ${renderTabs()}
      ${body}
    </main>
  `;
}

function render() {
  document.getElementById("app").innerHTML = `
    <div class="layout">
      ${renderProjectSidebar()}
      ${renderMain()}
    </div>
  `;
}

window.loadProject = loadProject;
window.browsePath = browsePath;
window.createProject = createProject;
window.importDocx = importDocx;
window.importReviewYaml = importReviewYaml;
window.importPerformancePacket = importPerformancePacket;
window.openProviderDialog = openProviderDialog;
window.closeProviderDialog = closeProviderDialog;
window.saveProviderDialog = saveProviderDialog;
window.clearProviderConfiguration = clearProviderConfiguration;
window.refreshElevenLabsVoices = refreshElevenLabsVoices;
window.useAccountVoice = useAccountVoice;
window.saveCastVoice = saveCastVoice;
window.editVoice = editVoice;
window.runAction = runAction;
window.exportChapterReview = exportChapterReview;
window.saveProgress = saveProgress;
window.loadReviewFile = loadReviewFile;
window.loadPerformancePacket = loadPerformancePacket;
window.updateReviewText = updateReviewText;
window.previewReviewFile = previewReviewFile;
window.changeReviewSegmentVoice = changeReviewSegmentVoice;
window.changePacketSegmentVoice = changePacketSegmentVoice;
window.togglePacketSegmentPerformance = togglePacketSegmentPerformance;
window.saveReviewFile = saveReviewFile;
window.attributeReviewDialogue = attributeReviewDialogue;
window.synthesizeReviewFile = synthesizeReviewFile;
window.rerenderReviewSegment = rerenderReviewSegment;
window.renderReviewChapter = renderReviewChapter;
window.undoProject = undoProject;
window.selectTab = selectTab;
window.selectChapter = selectChapter;
window.selectPacket = selectPacket;
window.selectReviewMode = selectReviewMode;

boot();
