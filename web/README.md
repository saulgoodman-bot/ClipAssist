# Frontend Preview (Next.js)

Implement these pages/components:
- Upload Zone: drag-and-drop file input posting to `POST /upload`.
- Progress Stepper: poll `GET /status/{video_id}` and render stages: `transcribing`, `analyzing`, `rendering`.
- Clip Gallery: render 9:16 players and download links from `clip.s3_path`.

Suggested minimal structure:
- `app/page.tsx` (upload + status polling)
- `components/UploadZone.tsx`
- `components/ProgressStepper.tsx`
- `components/ClipGallery.tsx`
