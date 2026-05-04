# AI Video Clipping Platform Blueprint

## 1) System architecture (text diagram)

```text
[Web App (Next.js)]
   |-- upload video / url
   |-- job progress / clip review / editor / export
   v
[API Gateway (FastAPI)] --auth--> [PostgreSQL]
   |                             [Redis]
   |-- signed upload URLs --------^ 
   |-- enqueue jobs --------------> [Queue: Celery]
   v
[S3 Object Storage]
   |-- originals
   |-- intermediates (audio, waveforms, frame tracks)
   |-- outputs (clips, subtitles)

[Workers]
  A. ingest_worker: probe media, extract audio, create metadata
  B. asr_worker: transcription + timestamps + diarization
  C. nlp_worker: topic split + highlight scoring + clip proposals
  D. framing_worker: face detection + active speaker + crop path
  E. caption_worker: subtitle lines + style + ASS events
  F. render_worker: ffmpeg cut/reframe/caption/brand/export
  G. publish_worker (later): social API pushes

[Observability]
  OpenTelemetry + Prometheus + Grafana + Sentry
```

## 2) MVP tech stack
- Frontend: Next.js + TypeScript + Tailwind + Zustand.
- Backend: FastAPI + Pydantic + SQLAlchemy.
- Queue: Celery + Redis.
- DB: PostgreSQL.
- Storage: S3-compatible (AWS S3 / MinIO for local).
- Media: FFmpeg + ffprobe.
- ASR: faster-whisper (GPU preferred).
- LLM scoring/titles: hosted LLM API (hybrid).
- Deployment: Docker Compose (local), Kubernetes/ECS (prod).

## 3) Product architecture and workflow
1. Upload or paste YouTube URL.
2. Store original video in private bucket.
3. Run ffprobe, save metadata.
4. Extract mono 16k wav.
5. Transcribe and optionally diarize.
6. Segment transcript into clauses/sentences.
7. LLM scores candidate windows (15–90s) with rubric.
8. Select top-N clips with diversity constraints.
9. For each clip: detect faces + compute crop path.
10. Build subtitles (SRT+ASS), generate title/hook/hashtags.
11. FFmpeg render 1080x1920 clip with burned captions.
12. Save outputs, expose preview/download URLs.

## 4) Model strategy

### Open-source only
- STT: faster-whisper large-v3.
- Diarization: pyannote.
- Highlight detection: local LLM (Qwen/Llama instruct) + rules.
- Face detection: RetinaFace/YOLOv8-face.
- Active speaker proxy: mouth motion + diarization alignment.
- Pros: low marginal cost, privacy.
- Cons: ops complexity, weaker quality/latency variability.

### Cloud API only
- STT + diarization via cloud speech service.
- Ranking/titles via frontier LLM API.
- Vision via cloud video intelligence.
- Pros: fastest build, strong quality.
- Cons: highest variable cost, vendor lock-in.

### Hybrid (recommended)
- Open-source ASR + FFmpeg pipeline.
- Cloud LLM for ranking/title generation only.
- Optional cloud fallback for low-confidence ASR.
- Best balance of cost, quality, build speed.

## 5) MVP scope (small team)
Include:
- MP4 upload
- Metadata extraction
- Audio extraction
- faster-whisper transcript
- LLM top-5 clip candidates
- FFmpeg cutting + 9:16 center/speaker crop fallback
- Burned captions (simple style)
- Download final clips

Exclude initially:
- Multi-user workspaces
- Billing
- Social publishing
- Fancy animated caption templates
- Real-time collaborative editing

## 6) Database design (core tables)
- users(id, email, password_hash, plan, created_at)
- videos(id, user_id, source_type, source_url, storage_key, duration_s, width, height, fps, size_bytes, status)
- transcripts(id, video_id, language, model_name, full_text, confidence_avg)
- transcript_segments(id, transcript_id, idx, start_s, end_s, speaker, text, confidence)
- processing_jobs(id, video_id, type, status, priority, retries, error_msg, started_at, finished_at)
- generated_clips(id, video_id, rank, start_s, end_s, score, title, summary, reason, layout_mode, status, output_key)
- captions(id, clip_id, format, storage_key, style_json)
- exports(id, clip_id, platform, codec, resolution, bitrate_kbps, storage_key, created_at)
- usage_billing(id, user_id, month, input_minutes, output_minutes, exports_count, storage_gb, amount_usd)

## 7) REST API design
- `POST /v1/videos/upload-url` -> signed URL + video_id
- `POST /v1/videos` -> finalize upload metadata
- `POST /v1/videos/{video_id}/process` -> start pipeline
- `GET /v1/videos/{video_id}/status`
- `GET /v1/videos/{video_id}/transcript`
- `GET /v1/videos/{video_id}/clips`
- `PATCH /v1/clips/{clip_id}` (start/end/title/layout)
- `POST /v1/clips/{clip_id}/captions/regenerate`
- `POST /v1/clips/{clip_id}/render`
- `GET /v1/clips/{clip_id}/download`

## 8) Worker pseudocode

### ingest_worker
```python
probe = ffprobe(video)
save_video_metadata(probe)
audio = ffmpeg_extract_wav(video, sr=16000, mono=True)
enqueue('asr', video_id, audio_key)
```

### asr_worker
```python
segments = faster_whisper_transcribe(audio)
if diarization_enabled:
    speakers = pyannote_diarize(audio)
    segments = align_speakers(segments, speakers)
save_segments(segments)
enqueue('analysis', video_id)
```

### analysis_worker
```python
windows = build_candidate_windows(segments, min_len=15, max_len=90)
scored = llm_score_windows(windows, rubric)
selected = diversify_and_select(scored, top_n=5)
save_clip_candidates(selected)
enqueue_batch('framing', selected_clip_ids)
```

### framing_worker
```python
for clip in clips:
    tracks = detect_faces_over_time(clip)
    crop_path = smooth_track_to_9x16(tracks)
    save_crop_path(clip, crop_path)
enqueue_batch('caption', clip_ids)
```

### caption_worker
```python
words = get_word_timestamps(clip)
lines = compose_mobile_readable_lines(words)
ass = render_ass_template(lines, style)
save_caption_assets(clip, srt, vtt, ass)
enqueue('render', clip_id)
```

### render_worker
```python
cmd = build_ffmpeg_filtergraph(clip, crop_path, ass, branding)
run(cmd)
validate_output()
upload_output()
mark_clip_ready()
```

## 9) Sample FFmpeg commands

### metadata
```bash
ffprobe -v quiet -print_format json -show_format -show_streams input.mp4
```

### extract audio
```bash
ffmpeg -y -i input.mp4 -vn -ac 1 -ar 16000 -c:a pcm_s16le audio.wav
```

### cut + 9:16 center crop
```bash
ffmpeg -y -ss 120 -to 165 -i input.mp4 \
  -vf "scale=1920:-2,crop=1080:1920:(in_w-1080)/2:(in_h-1920)/2" \
  -c:v libx264 -preset medium -crf 20 -c:a aac -b:a 128k clip.mp4
```

### burn ASS captions
```bash
ffmpeg -y -i clip.mp4 -vf "ass=clip.ass" -c:v libx264 -crf 20 -c:a copy clip_captioned.mp4
```

## 10) Sample LLM prompt (clip selection)
```text
You are selecting viral short clips from transcript segments.
Goal: choose 5 clips, each 15-90 seconds, standalone and coherent.
Score each candidate on hook_strength, clarity, emotional_intensity,
standalone_value, viral_potential, pacing, completeness (0-10).
Prefer clips with first 3 seconds containing a strong hook.
Avoid starting/ending mid-sentence unless needed.
Return strict JSON schema only.
Input segments: [...]
```

## 11) Sample JSON output schema
```json
{
  "video_id": "uuid",
  "clips": [
    {
      "rank": 1,
      "start_s": 120.4,
      "end_s": 163.8,
      "duration_s": 43.4,
      "title_suggestions": ["X", "Y", "Z"],
      "hook_text": "...",
      "summary": "...",
      "hashtags": ["#podcast", "#ai"],
      "scores": {
        "hook_strength": 9.1,
        "clarity": 8.8,
        "emotional_intensity": 7.0,
        "standalone_value": 8.9,
        "viral_potential": 8.7,
        "topic_relevance": 9.0,
        "pacing": 8.0,
        "completeness": 8.6,
        "length_suitability": 9.4
      },
      "virality_score": 8.8,
      "reason": "Strong opening claim and complete argument in <45s"
    }
  ]
}
```

## 12) Frontend pages and UX
- Upload page: file picker + URL ingest + size checks.
- Status page: per-stage progress bar + ETA + logs.
- Clip dashboard: ranked cards with score breakdown.
- Preview player: vertical preview + waveform + transcript sync.
- Timeline editor: drag start/end + snap to sentence boundaries.
- Caption editor: style presets, position, emphasis mode.
- Export page: platform presets (Shorts/Reels/TikTok/LinkedIn).

## 13) Engineering considerations
- Long videos: chunk audio and stream transcription updates.
- GPU scheduling: dedicate ASR workers, CPU workers for FFmpeg.
- Retries: exponential backoff + dead-letter queue.
- Failed jobs: partial state + resumable stages.
- Cleanup: lifecycle rules for intermediates.
- Limits: enforce max file size/duration by plan.
- Cost control: cache transcripts; render on demand; spot GPUs.
- Observability: trace per video_id/job_id across services.

## 14) Monetization tiers (example)
- Free: 60 input min/mo, 720p, watermark, 5 exports.
- Creator ($19): 600 min/mo, 1080p, no watermark, 100 exports.
- Pro ($59): 2,000 min/mo, priority queue, brand kit, 400 exports.
- Agency ($199): 10,000 min/mo, multi-seat, API access.
- Enterprise: custom minutes/SLA, SSO, VPC deployment.

## 15) Legal/ethical checklist
- Require user attestation of rights to upload content.
- DMCA takedown workflow + repeat infringer policy.
- Configurable retention + deletion guarantees.
- Encrypt at rest/in transit for media and transcripts.
- Consent guidance for interviews/podcasts and regional laws.
- Moderation for harmful/deceptive edited content.
- Deepfake/impersonation policy and abuse reporting.

## 16) Production roadmap
- Phase 1 (2-3 weeks): local CLI prototype.
- Phase 2 (4-6 weeks): MVP web app + async pipeline.
- Phase 3 (3-4 weeks): better ranking (ensembles + feedback loop).
- Phase 4 (4-5 weeks): dynamic face tracking + active speaker.
- Phase 5 (3-4 weeks): advanced caption templates.
- Phase 6 (4-6 weeks): SaaS hardening, autoscaling, observability.
- Phase 7 (4-8 weeks): teams, billing, social publish integrations.

## 17) Suggested repo folder structure
```text
clipassist/
  apps/
    api/                  # FastAPI
    web/                  # Next.js
    worker/               # Celery tasks
  packages/
    media/                # ffmpeg wrappers, probe utils
    ml/                   # ASR, diarization, scoring
    schemas/              # pydantic/shared contracts
  infra/
    docker/
    terraform/
    k8s/
  scripts/
    local_pipeline.py
  tests/
  docs/
```

## 18) Major risks and mitigations
- ASR accuracy on noisy audio -> denoise + confidence-based fallback.
- Bad clip relevance -> combine LLM scoring with heuristic filters.
- Slow rendering -> parallel clip renders + tuned FFmpeg presets.
- GPU cost spikes -> queue throttles + hybrid model routing.
- Copyright abuse -> detection, policies, rapid takedown process.
