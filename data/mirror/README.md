# Original-post mirror data

**Provenance: manual only.** Every file in this directory is entered by the
site owner by hand — pasted text and saved photos from their own Facebook
session — never collected by an automated tool. No script in this repo
fetches, scrapes, or renders Facebook content on its own; `build-index.mjs`
never touches this directory.

This is a deliberate exception to the rest of the public build (spec
§17/§26/§38: no raw post body, no commenter identities/comments are published
by default). The site owner has explicitly chosen, for this file only, to
mirror a post's full text, photo(s), and comment thread (including commenter
names) publicly. Treat every addition here as a conscious, individually
reviewed publishing decision, not a bulk import.

## manifest.json

A flat JSON array of Facebook post ids (matching `discussions-index.json`
record `id`s) that have a mirror file. The frontend fetches this once at
boot and only requests `<id>.json` for ids listed here.

## `<id>.json` schema

```json
{
  "id": "28973864082215945",
  "capturedAt": "2026-09-11",
  "capturedMethod": "manual_user_provided_screenshot",
  "postText": "Full text of the post, transcribed as-is.",
  "photos": ["media/mirror/28973864082215945/photo_1.jpg"],
  "comments": [
    { "author": "Full Name", "text": "Comment text.", "timestampLabel": "1 day ago" }
  ]
}
```

`photos` paths are relative to `portal/public-discussions/`. Add the actual
image file under `media/mirror/<id>/` alongside the JSON.

To add a post by hand: create `<id>.json` following the schema above, drop
any photo files in `media/mirror/<id>/`, and append the id to
`manifest.json`.

## Batch intake (many posts at once)

`build-discussions/tools/import-mirror-batch.mjs` does the same thing as
"add a post by hand" above, just for many posts in one pass, so a human
doesn't have to hand-write JSON per post. It is still entirely manual —
this tool reads files a human has already saved from looking at the real
post themselves; it never fetches anything itself.

1. Run `node build-discussions/tools/coverage-gap-report.mjs --staging-dir
   <dir>` to pre-create `<dir>/<postId>/` for the highest-priority posts
   with nothing captured, each with a `SOURCE.txt` naming the post and its
   Facebook URL.
2. For each folder you want to fill in: open the URL from its `SOURCE.txt`,
   save the post's text into that folder's `text.txt` and/or drop photo
   files into the same folder. Leave a folder as-is (empty) to skip it —
   it's picked up again next time `--staging-dir` runs.
3. Run `node build-discussions/tools/import-mirror-batch.mjs <dir>` to turn
   every filled-in folder into a `<id>.json` + manifest entry in one pass.
   An id already in `manifest.json` is skipped, never overwritten. Entries
   made this way are tagged `capturedMethod: "manual_batch_import"` rather
   than `"manual_user_provided_screenshot"`, so it's always clear which
   path produced which entry.
4. Rebuild the index (`build-index.mjs`) to see the new entries live.

Comments are out of scope for this fast path (`comments: []` always) —
`build-discussions/tools/promote-to-mirror.mjs` remains the route for a
specific post whose comments are also worth publishing individually.
