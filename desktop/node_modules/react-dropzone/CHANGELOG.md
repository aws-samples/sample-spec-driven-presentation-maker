# [15.0.0](https://github.com/react-dropzone/react-dropzone/compare/v14.4.1...v15.0.0) (2026-02-10)


* fix!: reset isDragReject after drop ([c9d1c31](https://github.com/react-dropzone/react-dropzone/commit/c9d1c3197fcef7ebff8b50f933720f48b982c895))


### BREAKING CHANGES

* isDragReject only reflects active drag state and is cleared after drop. Use fileRejections or onDropRejected/onDrop for post-drop rejection UI.
