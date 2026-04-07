# Docs Changelog.Rst

## Overview
This document tracks **new pages added** to the Godot documentation since version 3.0. It is **not** a comprehensive changelog—substantial updates to existing pages are not reflected. Use this as an index to discover when major documentation topics were introduced.

## Key Patterns

- **Pattern 1: Version-gated content discovery.** New docs are grouped by engine version, then by topic category (2D, 3D, Physics, Shaders, XR, etc.). Use this to determine minimum engine version for a documented feature.
- **Pattern 2: Series-based learning paths.** Many new pages are introduced as multi-part series:
  - *Your First Shader Series* (v3.1): [[Introduction to Shaders]] → [[Your First CanvasItem Shader]] → [[Your First Spatial Shader]] → [[Your Second Spatial Shader]]
  - *Procedural Geometry Series* (v3.1): [[ArrayMesh]] → [[SurfaceTool]] → [[MeshDataTool]] → [[ImmediateMesh]]
  - *Physics Interpolation Series* (v3.3+): Six pages covering intro through advanced topics
- **Pattern 3: Migration docs per minor release.** Every minor release (4.1, 4.2, 4.3, 4.4, 4.5) gets a dedicated upgrading page: `doc_upgrading_to_godot_4.X`.

## API Reference
*This is a meta-document (page index). No API signatures are present. Key cross-referenced page groups are listed below by version.*

### Notable Additions by Version

| Version | Highlights |
|---------|-----------|
| **4.4** | Engine compilation config (editor), [[GDExtension C Example]], [[Logging]] |
| **4.3** | [[SpringArm]], [[Physics Interpolation]] (6-page series), [[Renderers]], [[Shader Functions]], [[Output Panel]] |
| **4.2** | [[2D Parallax]], [[Compositor]], [[SDFGI]] usage, OpenXR body tracking/passthrough/composition layers |
| **4.1** | C# diagnostics, [[2D Coordinate Systems]], runtime loading/saving, Android library plugins |
| **4.0** | Internal rendering architecture, sanitizers, physics troubleshooting |
| **3.6** | Anti-aliasing (2D/3D), [[SDFGI]], [[Mesh LOD]], [[Occlusion Culling]], [[Volumetric Fog]], [[Compute Shaders]], large world coordinates, [[Variable Rate Shading]], retargeting 3D skeletons |
| **3.2** | [[GDScript Documentation Comments]], 3D rendering limitations, version control best practices, exporting for dedicated servers, [[Debugger Panel]], [[GDExtension]] intro |
| **3.1** | Sprite animation, shader series, procedural geometry series, [[MultiMesh]], [[Using Servers]], [[WebRTC]], [[Localization Using Gettext]], [[Signals]] (step by step) |
| **3.0** | Best practices series (10 pages), [[2D Lights and Shadows]], [[CSG Tools]], [[Ragdoll System]], [[Soft Body]], [[Animation Tree]], [[GUI Containers]], [[Viewport as Texture]] |

## Gotchas

- **This list is incomplete by design.** It only tracks *new* pages, not updates or rewrites. Many critical pages (e.g., [[GDScript]] basics, [[Node2D]] reference) pre-date 3.0 or were updated without being listed here.
- **Version 3.5 had zero new pages listed.** Don't assume the engine stalled—changes were reflected in existing page updates.
- **Some pages were split, not created fresh.** For example, `doc_gdscript_warning_system` was split from `doc_gdscript_static_typing` in v3.2.
- **Truncation warning.** The raw source is truncated at 8714 characters. The v3.0 Shading Reference section and anything after is incomplete.

## Cross-References

- [[Physics Interpolation]] — Introduced in v4.3 as a 6-page series; critical for smooth physics rendering
- [[Upgrading to Godot 4]] — Migration page from v3.6; entry point for 3.x→4.x breaking changes
- [[GDExtension]] — Multiple pages added across versions (file format, C example, godot-cpp docs system)
- [[Compute Shaders]] — Added v3.6; enables GPU compute workflows
- [[SDFGI]] — Added v3.6; real-time global illumination technique
- [[Compositor]] — Added v4.2; rendering post-processing pipeline
- [[Large World Coordinates]] — Added v3.6; doubles-precision for large-scale worlds
- [[OpenXR]] — Multiple pages (passthrough, body tracking, composition layers, settings) added in v4.2
- [[Best Practices]] — 10-page series added in v3.0 covering scene organization, autoloads, data/logic preferences
- [[Signals]] — Core concept page introduced in v3.0 step-by-step series

---
### Jinn Heuristics

- **HEURISTIC: When checking if a feature is documented, verify the minimum engine version in this changelog first, then confirm against the actual page—features may have been significantly rewritten since their initial page was added.** — source: Godot Docs Changelog
- **HEURISTIC: Migration guides exist for every minor release (4.1+). Always read the upgrading guide for your target version before updating engine versions.** — source: Godot Docs Changelog
- **HEURISTIC: If you can't find a feature's documentation, it may pre-date v3.0 or exist as an update to an older page rather than a new page. Search the full docs, not just the changelog.** — source: Godot Docs Changelog