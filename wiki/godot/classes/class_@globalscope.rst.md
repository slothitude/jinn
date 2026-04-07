# Class @GlobalScope

## Overview
Global scope containing enumerated constants, built-in functions, and singleton access. This is the root namespace for error codes, keycodes, property hints, and all auto-loaded singletons. Functions documented here are available across all languages; GDScript-specific utilities live in [[@GDScript]].

## Key Patterns
- **Singleton Access:** All singletons are accessible as global properties without requiring `get_node()` or references
  ```gdscript
  # Direct access anywhere
  Input.is_action_pressed("jump")
  AudioServer.set_bus_volume_db(0, -6.0)
  ```
- **Error Handling:** Use `@GlobalScope` error constants for return value checking
  ```gdscript
  var err = file.open("data.txt", File.READ)
  if err != OK:
      push_error("Failed to open: %s" % error_string(err))
  ```

## API Reference

### Core Singletons
| Singleton | Purpose |
|-----------|---------|
| `AudioServer` | Audio bus management |
| `CameraServer` | Camera feed handling |
| `ClassDB` | Runtime class introspection |
| `DisplayServer` | Window/display management |
| `Input` | Input event polling |
| `InputMap` | Action mapping configuration |
| `NavigationServer2D/3D` | Nav mesh pathfinding |
| `PhysicsServer2D/3D` | Low-level physics queries |
| `RenderingServer` | Direct rendering API |
| `Time` | High-precision timing |

### Key Constants (Categories)
- **Error Codes:** `OK`, `FAILED`, `ERR_*` variants
- **Keycodes:** `KEY_*` (e.g., `KEY_A`, `KEY_ESCAPE`)
- **Property Hints:** `PROPERTY_HINT_*`
- **Type Constants:** `TYPE_*` for Variant types

## Gotchas
- **C# Differences:** Many constants/functions have different names or signatures in C#—consult C# differences docs
- **Not Everything is Here:** GDScript-only functions (like `range()`, `lerp()` overloads) are in [[@GDScript]], not here
- **Singleton Availability:** Some singletons like `EditorInterface` only exist in editor builds

## Cross-References
- [[@GDScript]] — GDScript-specific global functions
- [[Input]] — Input event handling singleton
- [[RenderingServer]] — Low-level rendering access
- [[ClassDB]] — Runtime class introspection

---
### Jinn Heuristics
- HEURISTIC: Always use `OK` constant for error comparison, never assume `0` — source: Godot
- HEURISTIC: Check `Engine.is_editor_hint()` before accessing `EditorInterface` — source: Godot
- HEURISTIC: Prefer `Time.get_ticks_msec()` over `OS.get_ticks_msec()` in Godot 4+ — source: Godot