# Temporary Rendering/Overlay Cleanup Checklist

Second-pass reviewed:

- `PageLoaderMixin._uses_overlay_pdf_tiles`
- `PageLoaderMixin._primary_tiles_use_overlay_pdf`
- `PageLoaderMixin._uses_both_overlay_pdf_tiles`
- `PageLoaderMixin._active_page_raster_rotation`
- `PageLoaderMixin._tile_raster_dimensions`
- `PageLoaderMixin._overlay_tile_raster_dimensions`
- `PageLoaderMixin._overlay_graphics_transform`
- `PageLoaderMixin._compute_visible_tile_keys`
- `PageLoaderMixin._get_tile_px_rect`
- `PageLoaderMixin._get_tile_render_px_rect`
- `PageLoaderMixin._tile_item_rects`
- `PageLoaderMixin._evict_overlay_tile_keys`
- `PageLoaderMixin._request_tile`
- `PageLoaderMixin._request_overlay_tile`
- `PageLoaderMixin._on_tile_loaded`
- `PageLoaderMixin._on_overlay_tile_loaded`
- `PageLoaderMixin._update_tile_coverage`
- `TakeoffPlanView.can_move_overlay_image`
- `TakeoffPlanView.show_overlay_move_handle`
- `TakeoffPlanView.cancel_overlay_move_mode`
- `TakeoffPlanView._preview_overlay_move`
- `TakeoffPlanView._apply_overlay_rect_to_visuals`
- `TakeoffPlanView._commit_overlay_move`
- `CompositeRenderer.render_composite_region`
- `CompositeRenderer._is_unrotated_full_scale_overlay`
- `CompositeRenderer._source_crop_to_tile_transform`
- `PDFRenderingService._snapshot_page_for_render`
- `PDFRenderingService.render_page_async`
- `PDFRenderingService.render_region_async`
- `PDFRenderingService.render_composite_async`
- `PDFRenderingService.render_composite_region_async`
- `PDFExporter._try_overlay_background`
- `PDFExporter._overlay_rect_matches_page`
- `PDFExporter._render_positioned_overlay_background`
- `PDFExporter._is_annotation_exportable`
- `PDFExporter._text_align_to_pdf_value`
- `ProjectWriteService.save_page_overlay_rect_result`
- `SavePageOverlayRectUseCase.execute`
- `PageOperationsMixin.save_page_overlay_rect`
- `InputHandlerMixin` move-overlay mouse/key/cursor paths
- `ToolbarStateCoordinator.refresh`
- `PlanViewActionHandler.save_current_page_overlay_rect`

Third-pass checklist:

- [x] Confirm no temporary live logging or diagnostic helpers remain.
- [x] Re-check overlay tile and base tile visibility sync for dead branches.
- [x] Re-check composite full-scale branch for overly broad matching.
- [x] Re-check move-overlay cancel/commit paths for duplicated rollback.
- [x] Re-check overlay rect save path for one-off patterns.
- [x] Re-check tests for duplicated fake objects or implementation-only assertions.
- [x] Run focused py_compile, unit tests, architecture check, and diff check.

Third-pass cleanup:

- `TakeoffPlanView._commit_overlay_move`: collapsed duplicated failed-save
  rollback and warning handling into one local helper.
- `OptionsPreferencesTests.test_visible_tile_keys_carry_quantized_scale_identity`:
  updated the private test stub to `_tile_raster_dimensions`, matching the
  current tile helper path under review.
- Run focused py_compile, unit tests, architecture check, and diff check.
